import hashlib
import hmac
import json
import time
from datetime import date, timedelta
from typing import Dict
from httpx import AsyncClient
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.booking_service import cancel_booking, create_booking
from core.security import validate_telegram_init_data


def generate_valid_telegram_init_data(
    bot_token: str,
    user_id: int = 12345678,
    first_name: str = "TestUser",
    auth_date: int = None,
) -> str:
    if auth_date is None:
        auth_date = int(time.time())

    user_dict = {"id": user_id, "first_name": first_name}
    params = {
        "auth_date": str(auth_date),
        "query_id": "AAHdF6IQAAAAAN0XohDhrP2F",
        "user": json.dumps(user_dict, separators=(",", ":")),
    }

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    data_hash = hmac.new(secret_key, check_string.encode("utf-8"), hashlib.sha256).hexdigest()

    params["hash"] = data_hash
    return "&".join(f"{k}={v}" for k, v in params.items())


def test_telegram_init_data_cryptographic_verification():
    token = "987654321:AAFakeTestTokenSecret123"

    # 1. Valid data
    valid_data = generate_valid_telegram_init_data(token, user_id=424242, first_name="Daria")
    parsed = validate_telegram_init_data(valid_data, token)
    assert parsed["user"]["id"] == 424242
    assert parsed["user"]["first_name"] == "Daria"

    # 2. Tampered data
    tampered_data = valid_data.replace("Daria", "Hacker")
    with pytest.raises(ValueError, match="не прошла проверку"):
        validate_telegram_init_data(tampered_data, token)

    # 3. Expired data (older than 24h)
    old_time = int(time.time()) - 90000
    expired_data = generate_valid_telegram_init_data(token, user_id=424242, auth_date=old_time)
    with pytest.raises(ValueError, match="Срок действия сессии"):
        validate_telegram_init_data(expired_data, token)


@pytest.mark.asyncio
async def test_production_rejects_signed_data_without_bot_token(client, monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "dev_mode", False)
    monkeypatch.setattr(settings, "bot_token", "")
    forged = generate_valid_telegram_init_data("", user_id=999000199)
    response = await client.get("/api/me", headers={"X-Telegram-Init-Data": forged})
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_admin_api_rbac_enforcement(client: AsyncClient):
    # 1. Client user (999000101) tries to access admin schedule
    res_client = await client.get(
        "/api/admin/schedule",
        headers={"X-Dev-User-Id": "999000101"},
    )
    assert res_client.status_code == 403
    assert "Недостаточно прав" in res_client.json()["detail"]

    # 2. Admin user (999000199) accesses admin schedule
    res_admin = await client.get(
        "/api/admin/schedule",
        headers={"X-Dev-User-Id": "999000199"},
    )
    assert res_admin.status_code == 200
    data = res_admin.json()
    assert "bookings" in data
    assert "blocked_intervals" in data


@pytest.mark.asyncio
async def test_client_cannot_cancel_foreign_booking(db_session: AsyncSession):
    target_date = date.today() + timedelta(days=2)
    from datetime import time as time_val

    # Booking belongs to client 1 (999000101)
    booking = await create_booking(
        session=db_session,
        client_telegram_id=999000101,
        client_name="Дарья",
        client_phone="+79991112233",
        master_id=1,
        service_id=2,
        booking_date=target_date,
        start_time=time_val(11, 0),
    )

    # Client 2 (999000102) attempts to cancel
    with pytest.raises(PermissionError, match="только свои собственные записи"):
        await cancel_booking(
            session=db_session,
            booking_id=booking.id,
            actor_telegram_id=999000102,
            is_admin_action=False,
        )
