from datetime import date, timedelta
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_full_client_and_admin_api_flow(client: AsyncClient):
    # 1. Get salon info
    res_salon = await client.get("/api/salon")
    assert res_salon.status_code == 200
    assert res_salon.json()["salon"]["name"] == "Nail Atelier"

    # 2. Get services list
    res_services = await client.get("/api/services")
    assert res_services.status_code == 200
    services = res_services.json()
    assert len(services) >= 3

    # 3. Get masters list
    res_masters = await client.get("/api/masters")
    assert res_masters.status_code == 200
    masters = res_masters.json()
    assert len(masters) >= 2

    # 4. Get available slots
    target_date = (date.today() + timedelta(days=3)).strftime("%Y-%m-%d")
    res_slots = await client.get(f"/api/slots?master_id=1&service_id=1&date={target_date}")
    assert res_slots.status_code == 200
    slots = res_slots.json()
    assert len(slots) > 0
    slot_time = slots[0]["start_time"]

    # 5. Create booking via API
    booking_payload = {
        "master_id": 1,
        "service_id": 1,
        "date": target_date,
        "start_time": slot_time,
        "client_name": "Тестовая Клиентка",
        "client_phone": "+79997778899",
        "comment": "Французский маникюр",
    }
    res_book = await client.post(
        "/api/bookings",
        json=booking_payload,
        headers={"X-Dev-User-Id": "999000101"},
    )
    assert res_book.status_code == 200
    book_data = res_book.json()
    assert book_data["success"] is True
    booking_id = book_data["booking_id"]

    # 6. Check client's bookings list
    res_my = await client.get(
        "/api/bookings",
        headers={"X-Dev-User-Id": "999000101"},
    )
    assert res_my.status_code == 200
    my_bookings = res_my.json()
    assert any(b["id"] == booking_id for b in my_bookings)

    # 7. Admin views schedule
    res_admin_sched = await client.get(
        f"/api/admin/schedule?date={target_date}",
        headers={"X-Dev-User-Id": "999000199"},
    )
    assert res_admin_sched.status_code == 200
    admin_sched = res_admin_sched.json()
    assert any(b["id"] == booking_id for b in admin_sched["bookings"])

    # 8. Admin confirms booking
    res_confirm = await client.post(
        f"/api/admin/bookings/{booking_id}/confirm",
        headers={"X-Dev-User-Id": "999000199"},
    )
    assert res_confirm.status_code == 200
    assert res_confirm.json()["status"] == "confirmed"

    # 9. Admin blocks an interval
    res_block = await client.post(
        "/api/admin/block",
        json={
            "master_id": 1,
            "date": target_date,
            "start_time": "18:00",
            "end_time": "19:00",
            "reason": "Дезинфекция инструмента",
        },
        headers={"X-Dev-User-Id": "999000199"},
    )
    assert res_block.status_code == 200
    assert res_block.json()["success"] is True
