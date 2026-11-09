import json
from datetime import date, time, timedelta

from fastapi import HTTPException
import pytest
import pytest_asyncio

from core import booking_service
from core.config import settings
from core.models import Master, User
from core.security import require_admin


MASTER_ID = 777001
ADMIN_ID = 999000199

ADMIN_OPERATIONS = [
    ("GET", "/schedule", None),
    ("GET", "/bookings", None),
    ("POST", "/bookings/1/confirm", None),
    ("POST", "/bookings/1/cancel", None),
    ("POST", "/bookings/1/complete", None),
    ("DELETE", "/block/1", None),
    ("POST", "/block", {"master_id": 1, "date": "<date>", "start_time": "14:00", "end_time": "15:00"}),
    ("GET", "/services", None),
    ("POST", "/services/1/toggle", None),
    ("POST", "/services", {"category": "Test", "name": "New service", "price": 1000}),
    ("PUT", "/services/1", {"name": "Changed service"}),
    ("DELETE", "/services/1", None),
    ("GET", "/masters", None),
    ("POST", "/masters", {"full_name": "New master", "specialization": "Test"}),
    ("PUT", "/masters/1", {"full_name": "Changed master"}),
    ("POST", "/masters/1/toggle", None),
    ("DELETE", "/masters/1", None),
    ("GET", "/salon", None),
    ("PUT", "/salon", {"name": "Changed salon"}),
    ("POST", "/services/1/price", {"price": 1000}),
    ("POST", "/manual-booking", {"master_id": 1, "service_id": 2, "date": "<date>",
                                  "start_time": "14:00", "client_name": "Test client", "client_phone": "+79990000000"}),
]


@pytest_asyncio.fixture
async def permission_data(db_session, tmp_path, monkeypatch):
    """Keep both SQL mutations and salon configuration inside the test sandbox."""
    salon = {"name": "Before"}
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"salon": salon}), encoding="utf-8")
    monkeypatch.setattr(settings, "salon", salon.copy())
    monkeypatch.setattr(booking_service, "CONFIG_PATH", config)
    master_user = User(telegram_id=MASTER_ID, full_name="Test master", role="master", is_active=True)
    db_session.add(master_user)
    await db_session.commit()
    master = await db_session.get(Master, 1)
    master.user_id = master_user.id
    master.telegram_id = MASTER_ID
    await db_session.commit()
    booking = await booking_service.create_booking(
        session=db_session, client_telegram_id=999000101,
        client_name="Test client", client_phone="+79990000000",
        master_id=1, service_id=2, booking_date=date.today() + timedelta(days=2), start_time=time(11),
    )
    assert booking.id == 1
    return config


@pytest.mark.asyncio
@pytest.mark.parametrize("actor", [MASTER_ID, 999000101], ids=["master", "client"])
@pytest.mark.parametrize("method, path, payload", ADMIN_OPERATIONS)
async def test_non_admin_cannot_access_admin_operations(client, permission_data, actor, method, path, payload):
    """A staff role must not grant access to the salon-wide administrator API."""
    headers = {"X-Dev-User-Id": str(actor)}
    identity = await client.get("/api/me", headers=headers)
    assert identity.status_code == 200
    assert identity.json()["role"] == ("master" if actor == MASTER_ID else "client")
    assert identity.json()["is_admin"] is False
    original_config = permission_data.read_text(encoding="utf-8")
    body = None if payload is None else {
        key: (date.today() + timedelta(days=2)).isoformat() if value == "<date>" else value
        for key, value in payload.items()
    }

    response = await client.request(method, "/api/admin" + path, headers=headers, json=body)

    assert response.status_code == 403, response.text
    assert settings.salon == {"name": "Before"}
    assert permission_data.read_text(encoding="utf-8") == original_config


@pytest.mark.asyncio
@pytest.mark.parametrize("role, configured", [
    ("admin", False), ("master", False), ("client", False),
    ("admin", True), ("master", True), ("client", True),
])
async def test_admin_dependency_uses_configured_identity_not_database_role(monkeypatch, role, configured):
    monkeypatch.setattr(settings, "admin_telegram_ids", [MASTER_ID] if configured else [])
    user = User(telegram_id=MASTER_ID, role=role, is_active=True)
    if configured:
        assert await require_admin(user) is user
    else:
        with pytest.raises(HTTPException) as error:
            await require_admin(user)
        assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_configured_admin_can_manage_salon_services_and_masters(client, permission_data):
    headers = {"X-Dev-User-Id": str(ADMIN_ID)}
    response = await client.put("/api/admin/salon", headers=headers, json={"name": "After"})
    assert response.status_code == 200
    assert json.loads(permission_data.read_text(encoding="utf-8"))["salon"]["name"] == "After"
    response = await client.post("/api/admin/services", headers=headers, json={
        "category": "Test", "name": "New service", "price": 1000,
    })
    assert response.status_code == 200
    assert response.json()["name"] == "New service"
    response = await client.post("/api/admin/masters", headers=headers, json={
        "full_name": "New master", "specialization": "Test",
    })
    assert response.status_code == 200
    assert response.json()["full_name"] == "New master"


@pytest.mark.asyncio
async def test_master_keeps_identity_and_access_to_client_catalog(client, permission_data):
    headers = {"X-Dev-User-Id": str(MASTER_ID)}
    identity = await client.get("/api/me", headers=headers)
    assert identity.status_code == 200
    assert identity.json()["role"] == "master"
    assert identity.json()["is_admin"] is False
    assert (await client.get("/api/services", headers=headers)).status_code == 200
    assert (await client.get("/api/masters", headers=headers)).status_code == 200
