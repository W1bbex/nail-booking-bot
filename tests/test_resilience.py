"""
Resilience, edge cases and security integrity regression tests for nail-booking-bot.
Covers:
- Telegram ID determinism and database column typing
- Production HMAC validation and expiration safeguards
- Non-slot IntegrityError propagation
- Concurrent registration conflict resolution
- Unregistered claim authorization boundary
- Terminal console input fallback across unsupported environments
"""
import time
import hmac
import hashlib
import json
from urllib.parse import urlencode
from datetime import date, time as dtime, datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy import BigInteger, select

from core.config import settings
from core.security import (
    deterministic_virtual_telegram_id,
    validate_telegram_init_data,
    get_current_user,
)
from core.models import Booking, Master, Service, User, BookingMessage
from core.booking_service import create_booking, get_moscow_now


def generate_valid_init_data(bot_token: str, user_dict: dict, auth_date: int = None) -> str:
    if auth_date is None:
        auth_date = int(time.time())
    params = {
        "auth_date": str(auth_date),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": json.dumps(user_dict, separators=(",", ":")),
    }
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    params["hash"] = calc_hash
    return urlencode(params)


def test_deterministic_virtual_telegram_id_stability():
    """Verify virtual telegram ID generation is stable, deterministic and negative."""
    phone1 = "+7 (999) 111-22-33"
    phone2 = "+79991112233"
    phone3 = "+7 (999) 444-55-66"

    id1 = deterministic_virtual_telegram_id(phone1)
    id2 = deterministic_virtual_telegram_id(phone2)
    id3 = deterministic_virtual_telegram_id(phone3)

    assert id1 < 0
    assert id1 == id2  # Formatting differences normalize to same digits
    assert id1 != id3


def test_models_use_biginteger_for_telegram_ids():
    """Verify telegram_id columns use BigInteger for 64-bit Telegram IDs."""
    assert isinstance(User.__table__.c.telegram_id.type, BigInteger)
    assert isinstance(Master.__table__.c.telegram_id.type, BigInteger)
    assert isinstance(BookingMessage.__table__.c.chat_id.type, BigInteger)


def test_production_auth_valid_and_tampered():
    """Verify production HMAC validation works with valid data and rejects forged/expired sessions."""
    token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    user_payload = {"id": 987654321, "first_name": "Anna", "username": "anna_nail"}

    # 1. Valid initData
    valid_data = generate_valid_init_data(token, user_payload)
    parsed = validate_telegram_init_data(valid_data, token)
    assert parsed["user"]["id"] == 987654321
    assert parsed["user"]["first_name"] == "Anna"

    # 2. Forged signature / tampered user
    tampered_data = valid_data.replace("987654321", "111111111")
    with pytest.raises(ValueError, match="не прошла проверку подлинности"):
        validate_telegram_init_data(tampered_data, token)

    # 3. Expired auth_date (older than 24h)
    expired_date = int(time.time()) - 100000
    expired_data = generate_valid_init_data(token, user_payload, auth_date=expired_date)
    with pytest.raises(ValueError, match="Срок действия сессии Telegram истёк"):
        validate_telegram_init_data(expired_data, token)


@pytest.mark.asyncio
async def test_integrity_error_re_raised_for_non_slot_failures(db_session, monkeypatch):
    """Verify that IntegrityError not related to slot uniqueness is re-raised and NOT masked as slot conflict."""
    master = Master(telegram_id=9998881, full_name="Master Lena", is_active=True)
    service = Service(name="Manicure", price=2500.0, duration_minutes=60, is_active=True)
    db_session.add_all([master, service])
    await db_session.commit()
    await db_session.refresh(master)
    await db_session.refresh(service)

    orig_commit = db_session.commit
    async def mock_failing_commit():
        raise IntegrityError("INSERT INTO bookings ...", {}, Exception("FOREIGN KEY constraint failed: client_user_id"))

    monkeypatch.setattr(db_session, "commit", mock_failing_commit)

    target_date = get_moscow_now().date() + timedelta(days=2)
    with pytest.raises(IntegrityError):
        await create_booking(
            session=db_session,
            client_telegram_id=1234567,
            client_name="Test Client",
            client_phone="+79991234567",
            master_id=master.id,
            service_id=service.id,
            booking_date=target_date,
            start_time=dtime(12, 0),
        )


@pytest.mark.asyncio
async def test_security_auto_register_handles_integrity_error():
    """Verify concurrent user registrations gracefully resolve UNIQUE constraint conflicts."""
    db = AsyncMock()
    db.add = MagicMock()
    existing_user = User(id=10, telegram_id=999999, full_name="Concurrent User", role="client", is_active=True)

    first_result = MagicMock()
    first_result.scalar_one_or_none.return_value = None

    second_result = MagicMock()
    second_result.scalar_one.return_value = existing_user

    db.execute.side_effect = [first_result, second_result]
    db.commit.side_effect = [IntegrityError("statement", "params", "orig")]

    with patch("core.security.validate_telegram_init_data", return_value={"user": {"id": 999999, "first_name": "Concurrent"}}):
        with patch.object(settings, "bot_token", "real_bot_token"):
            user = await get_current_user(x_telegram_init_data="fake_init_data", db=db)
            assert user.id == 10
            assert user.telegram_id == 999999
            assert db.rollback.called


@pytest.mark.asyncio
async def test_admin_claim_not_registered_does_not_edit_message():
    """Verify unauthorized master claims do not overwrite or erase public broadcast cards."""
    from handlers.admin import cb_master_claim

    call = MagicMock()
    call.from_user.id = 12345
    call.data = "master_claim:99"
    call.answer = AsyncMock()
    call.message.edit_text = AsyncMock()

    with patch("core.booking_service.claim_booking_by_master", new_callable=AsyncMock) as mock_claim:
        mock_claim.return_value = (False, "Вы не зарегистрированы как мастер студии", None)
        with patch("handlers.admin.get_session") as mock_maker:
            mock_session = AsyncMock()
            mock_maker.return_value.__aenter__.return_value = mock_session

            await cb_master_claim(call)

            call.answer.assert_called_once_with("Вы не зарегистрированы как мастер студии", show_alert=True)
            call.message.edit_text.assert_not_called()


def test_launcher_and_wizard_console_input_oserror_fallback():
    """Verify interactive menus gracefully fall back to text prompts when console mode is unavailable."""
    import launcher
    import wizard_ui

    with patch("console_mouse.ConsoleInput.__enter__", side_effect=OSError("Console mode not supported")):
        with patch("launcher.show_menu"), patch("builtins.input", return_value="1"):
            choice = launcher.choose_action()
            assert choice == "1"

        with patch("builtins.input", return_value="2"):
            res = wizard_ui.choose("Title", [("1", "First"), ("2", "Second")], ["Desc"])
            assert res == "2"
