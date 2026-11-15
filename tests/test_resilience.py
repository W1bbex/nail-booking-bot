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
    from handlers.master import cb_master_claim

    call = MagicMock()
    call.from_user.id = 12345
    call.data = "master_claim:99"
    call.answer = AsyncMock()
    call.message.edit_text = AsyncMock()

    with patch("core.booking_service.claim_booking_by_master", new_callable=AsyncMock) as mock_claim:
        mock_claim.return_value = (False, "Вы не зарегистрированы как мастер студии", None)
        with patch("handlers.master.get_session") as mock_maker:
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


@pytest.mark.asyncio
async def test_pending_reservation_blocks_slot_in_free_masters_search(db_session):
    """Verify that a pending any-master reservation blocks its assigned slot from other queries."""
    from core.catalog_service import get_free_active_masters

    target_date = get_moscow_now().date() + timedelta(days=4)
    # Master 1 is assigned an any-master booking on this slot
    b = await create_booking(
        session=db_session,
        client_telegram_id=888111,
        client_name="Клиент 1",
        client_phone="+79991112233",
        master_id=0,
        service_id=1,
        booking_date=target_date,
        start_time=dtime(14, 0),
    )
    assert b.master_id == 1
    assert b.status == "pending"

    # Search free masters on the same slot without excluding this booking
    free = await get_free_active_masters(
        db_session, target_date, dtime(14, 0), dtime(15, 0)
    )
    free_ids = [m.id for m in free]
    assert 1 not in free_ids, "Master 1 must be occupied by pending reservation"

    # Search free masters excluding this booking (self-check during re-evaluation)
    free_self = await get_free_active_masters(
        db_session, target_date, dtime(14, 0), dtime(15, 0), exclude_booking_id=b.id
    )
    assert any(m.id == 1 for m in free_self)


@pytest.mark.asyncio
async def test_cannot_decline_cancelled_or_completed_booking(db_session):
    """Verify masters cannot decline already cancelled or completed orders."""
    from core.booking_service import cancel_booking, decline_booking_by_master

    target_date = get_moscow_now().date() + timedelta(days=4)
    b = await create_booking(
        session=db_session,
        client_telegram_id=888112,
        client_name="Клиент 2",
        client_phone="+79991112233",
        master_id=1,
        service_id=1,
        booking_date=target_date,
        start_time=dtime(11, 0),
    )
    await cancel_booking(db_session, b.id, actor_telegram_id=5568814893, is_admin_action=True)
    await db_session.refresh(b)
    assert b.status == "cancelled_by_admin"

    # Master attempts to decline cancelled booking
    m1 = await db_session.get(Master, 1)
    m1.telegram_id = 777001
    await db_session.commit()

    ok, msg, updated_b = await decline_booking_by_master(db_session, b.id, 777001)
    assert ok is False
    assert "Нельзя отклонить заказ в статусе" in msg
    assert updated_b.declined_master_ids is None


@pytest.mark.asyncio
async def test_admin_reassign_booking_rejects_cancelled_or_completed(db_session):
    """Verify administrator cannot reassign already cancelled or completed orders."""
    from core.booking_service import cancel_booking, admin_reassign_booking

    target_date = get_moscow_now().date() + timedelta(days=4)
    b = await create_booking(
        session=db_session,
        client_telegram_id=888113,
        client_name="Клиент 3",
        client_phone="+79991112233",
        master_id=1,
        service_id=1,
        booking_date=target_date,
        start_time=dtime(12, 0),
    )
    await cancel_booking(db_session, b.id, actor_telegram_id=5568814893, is_admin_action=True)

    with pytest.raises(ValueError, match="Невозможно переназначить запись в статусе"):
        await admin_reassign_booking(db_session, b.id, new_master_id=2, admin_telegram_id=5568814893)


@pytest.mark.asyncio
async def test_client_accept_any_master_when_no_other_masters_free(db_session):
    """Verify accepting any master fails gracefully without locking previous master when none are free."""
    from core.booking_service import client_accept_any_master

    # Deactivate all masters except Master 1
    all_masters = (await db_session.execute(select(Master))).scalars().all()
    for m in all_masters:
        if m.id != 1:
            m.is_active = False
    await db_session.commit()

    target_date = get_moscow_now().date() + timedelta(days=4)
    b = await create_booking(
        session=db_session,
        client_telegram_id=888114,
        client_name="Клиент 4",
        client_phone="+79991112233",
        master_id=1,
        service_id=1,
        booking_date=target_date,
        start_time=dtime(13, 0),
    )
    # Master 1 declines specific booking -> awaiting_client_choice
    b.status = "awaiting_client_choice"
    b.declined_master_ids = "1"
    await db_session.commit()

    # Client tries to switch to any master, but no other master is free
    ok, msg, updated = await client_accept_any_master(db_session, b.id, client_telegram_id=888114)
    assert ok is False
    assert "нет других свободных мастеров" in msg
    await db_session.refresh(b)
    assert b.status == "awaiting_client_choice"


@pytest.mark.asyncio
async def test_all_masters_declined_releases_slot(db_session):
    """Verify that when all masters decline an any-master booking, the order is cancelled and slot freed."""
    from core.booking_service import decline_booking_by_master
    from core.catalog_service import get_free_active_masters

    all_masters = (await db_session.execute(select(Master))).scalars().all()
    for m in all_masters:
        if m.id != 1:
            m.is_active = False
    m1 = await db_session.get(Master, 1)
    m1.telegram_id = 777005
    await db_session.commit()

    target_date = get_moscow_now().date() + timedelta(days=4)
    b = await create_booking(
        session=db_session,
        client_telegram_id=888115,
        client_name="Клиент 5",
        client_phone="+79991112233",
        master_id=0,
        service_id=1,
        booking_date=target_date,
        start_time=dtime(15, 0),
    )
    assert b.master_id == 1

    ok, flow_status, updated = await decline_booking_by_master(db_session, b.id, 777005)
    assert ok is True
    assert flow_status == "all_declined"
    assert updated.status == "cancelled_by_admin"
    assert updated.assignment_deadline is None

    # Slot should be completely free again
    free = await get_free_active_masters(db_session, target_date, dtime(15, 0), dtime(16, 0))
    assert any(m.id == 1 for m in free)


@pytest.mark.asyncio
async def test_expired_pending_booking_cancels_when_no_masters_free(db_session, monkeypatch):
    """Verify expired bookings without auto-assignment are cancelled rather than hanging indefinitely."""
    from core.booking_service import process_expired_bookings
    from core.config import settings

    monkeypatch.setattr(settings, "salon", {**settings.salon, "auto_assign_on_timeout": False})

    target_date = get_moscow_now().date() + timedelta(days=4)
    b_pending = await create_booking(
        session=db_session,
        client_telegram_id=888116,
        client_name="Клиент 6",
        client_phone="+79991112233",
        master_id=1,
        service_id=1,
        booking_date=target_date,
        start_time=dtime(16, 0),
    )
    b_pending.assignment_deadline = datetime.now() - timedelta(minutes=15)
    await db_session.commit()

    processed = await process_expired_bookings(db_session, bot=None)
    assert processed >= 1
    await db_session.refresh(b_pending)
    assert b_pending.status == "cancelled_by_admin"
    assert b_pending.assignment_deadline is None


@pytest.mark.asyncio
async def test_block_time_interval_raises_value_error_for_nonexistent_master(db_session):
    """Verify that blocking an interval for an invalid master raises a clear ValueError instead of DB error."""
    from core.catalog_service import block_time_interval

    target_date = get_moscow_now().date() + timedelta(days=4)
    with pytest.raises(ValueError, match="не найден или деактивирован"):
        await block_time_interval(
            session=db_session,
            master_id=999999,
            block_date=target_date,
            start_time=dtime(17, 0),
            end_time=dtime(18, 0),
            admin_telegram_id=5568814893,
        )


@pytest.mark.asyncio
async def test_batch_block_all_masters_atomic_rollback_on_conflict(db_session):
    """Verify salon-wide interval blocking is atomic: if any master has a conflict, no intervals are committed."""
    from core.catalog_service import block_all_masters_time_interval
    from core.models import BlockedInterval

    # Ensure Master 1 and Master 2 are active
    m1 = await db_session.get(Master, 1)
    m2 = await db_session.get(Master, 2)
    m1.is_active = True
    m2.is_active = True
    await db_session.commit()

    target_date = get_moscow_now().date() + timedelta(days=4)
    # Master 2 has an active confirmed booking at 17:00
    b2 = await create_booking(
        session=db_session,
        client_telegram_id=888117,
        client_name="Клиент 7",
        client_phone="+79991112233",
        master_id=2,
        service_id=1,
        booking_date=target_date,
        start_time=dtime(17, 0),
    )
    b2.status = "confirmed"
    await db_session.commit()

    # Attempt to block all masters at 17:00
    with pytest.raises(ValueError, match="уже есть активная запись"):
        await block_all_masters_time_interval(
            session=db_session,
            block_date=target_date,
            start_time=dtime(17, 0),
            end_time=dtime(18, 0),
            reason="Санитарный час",
            admin_telegram_id=5568814893,
        )

    # Verify Master 1 was NOT blocked either
    res = await db_session.execute(
        select(BlockedInterval).where(
            BlockedInterval.booking_date == target_date,
            BlockedInterval.start_time == dtime(17, 0),
        )
    )
    assert len(res.scalars().all()) == 0, "No partial intervals should be persisted on conflict"


def test_proxy_ip_spoofing_rejected_as_external():
    from core.security import _is_proxied_external

    # Prepending 127.0.0.1 to spoof trust in X-Forwarded-For must be detected as external
    assert _is_proxied_external(x_forwarded_for="127.0.0.1, 198.51.100.2") is True
    assert _is_proxied_external(x_forwarded_for="198.51.100.2, 127.0.0.1") is True
    assert _is_proxied_external(x_real_ip="198.51.100.2") is True

    # Trusted local hosts only
    assert _is_proxied_external(x_forwarded_for="127.0.0.1", x_real_ip="127.0.0.1") is False
    assert _is_proxied_external(x_forwarded_for="localhost", x_real_ip="::1") is False


@pytest.mark.asyncio
async def test_proxy_ip_spoofing_prevented_against_dev_mode(db_session, monkeypatch):
    from core.security import get_current_user
    from fastapi import HTTPException

    monkeypatch.setattr(settings, "dev_mode", True)
    monkeypatch.setattr(settings, "bot_token", "987654321:ValidLookingBotTokenSecret")

    # Attacker tries prepending 127.0.0.1 to spoof trust in X-Forwarded-For to access dev mode
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(
            x_forwarded_for="127.0.0.1, 198.51.100.2",
            x_dev_user_id="5568814893",
            db=db_session,
        )
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_api_me_exposes_master_details_for_owner_master(client, db_session):
    master_tg_id = 888777666
    master = Master(
        full_name="Тестовый Владелец-Мастер",
        specialization="Универсал",
        experience_years=7,
        is_active=True,
        telegram_id=master_tg_id,
    )
    db_session.add(master)
    await db_session.commit()
    await db_session.refresh(master)

    res = await client.get("/api/me", headers={"X-Dev-User-Id": str(master_tg_id)})
    assert res.status_code == 200
    data = res.json()
    assert data["telegram_id"] == master_tg_id
    assert data["is_master"] is True
    assert data["master_id"] == master.id


@pytest.mark.asyncio
async def test_bind_master_by_telegram_duplicate_protection(db_session):
    from core.catalog_service import bind_master_by_telegram

    m1 = Master(full_name="Мастер А", specialization="Маникюр", experience_years=2, telegram_username="duplicate_user", is_active=True)
    m2 = Master(full_name="Мастер Б", specialization="Педикюр", experience_years=4, telegram_username="duplicate_user", is_active=True)
    db_session.add_all([m1, m2])
    await db_session.commit()

    # Must return latest without MultipleResultsFound
    claimed = await bind_master_by_telegram(db_session, 777666555, "duplicate_user")
    assert claimed is not None
    assert claimed.telegram_id == 777666555


def test_single_instance_lock_windows_process_alive_check():
    import os
    from core.lock import SingleInstanceLock

    assert SingleInstanceLock._is_pid_running(os.getpid()) is True
    assert SingleInstanceLock._is_pid_running(99999999) is False
    assert SingleInstanceLock._is_pid_running(0) is False
    assert SingleInstanceLock._is_pid_running(-5) is False


def test_launcher_preview_handles_missing_config_cleanly(monkeypatch):
    import tempfile
    from pathlib import Path
    import launcher

    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setattr(launcher, "ROOT", Path(td))
        # config.json does not exist in tmp_path, must not raise FileNotFoundError
        launcher.preview()


@pytest.mark.asyncio
async def test_cmd_start_resolves_master_by_telegram_id_without_username(db_session, monkeypatch):
    from contextlib import asynccontextmanager
    from handlers.client import handle_start

    master = Master(
        full_name="Светлана Мастер",
        specialization="Дизайн",
        experience_years=4,
        telegram_id=987654321,
        telegram_username=None,
        is_active=True,
    )
    db_session.add(master)
    await db_session.commit()

    @asynccontextmanager
    async def mock_get_session():
        yield db_session

    monkeypatch.setattr("handlers.client.get_session", mock_get_session)

    msg = MagicMock()
    msg.from_user.id = 987654321
    msg.from_user.username = None
    msg.answer = AsyncMock()

    await handle_start(msg)
    msg.answer.assert_called_once()
    assert "СВЕТЛАНА МАСТЕР" in msg.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_client_cancellation_debounce_handles_already_cancelled_gracefully(db_session, monkeypatch):
    from contextlib import asynccontextmanager
    from handlers.client import cb_client_cancel_confirm
    from core.booking_service import cancel_booking

    target_date = get_moscow_now().date() + timedelta(days=2)
    booking = await create_booking(
        session=db_session,
        client_telegram_id=999000101,
        client_name="Тестовая Дарья",
        client_phone="+79991112233",
        master_id=1,
        service_id=1,
        booking_date=target_date,
        start_time=dtime(12, 0),
    )
    await cancel_booking(db_session, booking.id, 999000101)

    @asynccontextmanager
    async def mock_get_session():
        yield db_session

    monkeypatch.setattr("handlers.client.get_session", mock_get_session)

    call = MagicMock()
    call.data = f"client_cancel:{booking.id}:confirm"
    call.from_user.id = 999000101
    call.message.edit_text = AsyncMock()
    call.answer = AsyncMock()
    call.bot = None

    await cb_client_cancel_confirm(call)

    call.answer.assert_called_with("Запись уже отменена")
    call.message.edit_text.assert_called_once()
    assert "уже была отменена ранее" in call.message.edit_text.call_args[0][0]


@pytest.mark.asyncio
async def test_admin_unblock_cmd_with_botname_suffix(db_session, monkeypatch):
    from contextlib import asynccontextmanager
    from handlers.admin_catalog import handle_unblock_id_cmd
    from core.catalog_service import block_time_interval

    target_date = get_moscow_now().date() + timedelta(days=3)
    block = await block_time_interval(
        session=db_session,
        master_id=1,
        block_date=target_date,
        start_time=dtime(10, 0),
        end_time=dtime(11, 0),
        reason="Перерыв",
        admin_telegram_id=5568814893,
    )

    @asynccontextmanager
    async def mock_get_session():
        yield db_session

    monkeypatch.setattr("handlers.admin_catalog.get_session", mock_get_session)

    msg = MagicMock()
    msg.text = f"/unblock_{block.id}@my_salon_bot"
    msg.from_user.id = 5568814893
    msg.answer = AsyncMock()

    await handle_unblock_id_cmd(msg)
    msg.answer.assert_called_once()
    assert f"#{block.id} успешно разблокирован" in msg.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_admin_bookings_pagination(client, db_session):
    target_date = get_moscow_now().date() + timedelta(days=5)
    for i in range(5):
        await create_booking(
            session=db_session,
            client_telegram_id=777000 + i,
            client_name=f"Клиент {i}",
            client_phone=f"+7999000110{i}",
            master_id=1,
            service_id=2,
            booking_date=target_date,
            start_time=dtime(10 + i, 0),
        )

    res1 = await client.get("/api/admin/bookings?limit=2&offset=0", headers={"X-Dev-User-Id": "5568814893"})
    assert res1.status_code == 200
    data1 = res1.json()
    assert len(data1) == 2

    res2 = await client.get("/api/admin/bookings?limit=2&offset=2", headers={"X-Dev-User-Id": "5568814893"})
    assert res2.status_code == 200
    data2 = res2.json()
    assert len(data2) == 2

    ids1 = {b["id"] for b in data1}
    ids2 = {b["id"] for b in data2}
    assert ids1.isdisjoint(ids2)


@pytest.mark.asyncio
async def test_manual_booking_phone_normalization_and_master_notification(client, db_session, monkeypatch):
    import api.routes_client as routes_client

    m1 = await db_session.get(Master, 1)
    m1.telegram_id = 99912345
    await db_session.commit()

    mock_sent_msg = MagicMock()
    mock_sent_msg.message_id = 12345
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock(return_value=mock_sent_msg)
    monkeypatch.setattr(routes_client, "telegram_bot_instance", mock_bot)

    target_date = (get_moscow_now().date() + timedelta(days=6)).strftime("%Y-%m-%d")

    res = await client.post(
        "/api/admin/manual-booking",
        json={
            "master_id": 1,
            "service_id": 1,
            "date": target_date,
            "start_time": "15:00",
            "client_name": "Тестовая Дарья",
            "client_phone": "+7 (999) 111-22-33",
            "comment": "Запись по звонку",
        },
        headers={"X-Dev-User-Id": "5568814893"},
    )
    assert res.status_code == 200
    b_id = res.json()["booking_id"]

    b = await db_session.get(Booking, b_id)
    assert b is not None
    assert b.client_user_id == 1

    sent_chats = [call.kwargs.get("chat_id") or (call.args[0] if call.args else None) for call in mock_bot.send_message.call_args_list]
    assert 99912345 in sent_chats


@pytest.mark.asyncio
async def test_catalog_admin_permission_enforcement(db_session):
    from core.catalog_service import create_master, update_master, create_service, update_service

    non_admin_id = 123456789

    with pytest.raises(PermissionError, match="Недостаточно прав администратора"):
        await create_master(db_session, "Тест Мастер", "Маникюр", admin_telegram_id=non_admin_id)

    with pytest.raises(PermissionError, match="Недостаточно прав администратора"):
        await update_master(db_session, master_id=1, full_name="Новое имя", admin_telegram_id=non_admin_id)

    with pytest.raises(PermissionError, match="Недостаточно прав администратора"):
        await create_service(db_session, "Категория", "Услуга", admin_telegram_id=non_admin_id)

    with pytest.raises(PermissionError, match="Недостаточно прав администратора"):
        await update_service(db_session, service_id=1, name="Новая услуга", admin_telegram_id=non_admin_id)
