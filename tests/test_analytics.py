from datetime import date, time
import pytest

from core.analytics_service import calculate_schedule_stats
from core.models import Booking, Service
from handlers.admin import admin_router
from handlers.admin_manual_booking import admin_manual_booking_router


def test_calculate_schedule_stats_empty():
    stats = calculate_schedule_stats([])
    assert stats["revenue"] == 0.0
    assert stats["expected_revenue"] == 0.0
    assert stats["total"] == 0
    assert stats["pending"] == 0
    assert stats["confirmed"] == 0
    assert stats["completed"] == 0
    assert stats["cancelled"] == 0
    assert stats["avg_check"] == 0


def test_calculate_schedule_stats_with_bookings():
    s1 = Service(id=1, category="Нейл", name="Маникюр", duration_minutes=60, price=2000.0)
    s2 = Service(id=2, category="Нейл", name="Педикюр", duration_minutes=60, price=3000.0)

    # b1: completed with custom snapshotted price 2500
    b1 = Booking(
        id=1,
        client_user_id=1,
        master_id=1,
        service_id=1,
        booking_date=date(2026, 6, 1),
        start_time=time(10, 0),
        end_time=time(11, 0),
        status="completed",
        price=2500.0,
    )
    b1.service = s1

    # b2: confirmed, no snapshotted price, falls back to s2 price (3000)
    b2 = Booking(
        id=2,
        client_user_id=2,
        master_id=1,
        service_id=2,
        booking_date=date(2026, 6, 1),
        start_time=time(11, 0),
        end_time=time(12, 0),
        status="confirmed",
        price=None,
    )
    b2.service = s2

    # b3: pending, expected revenue only
    b3 = Booking(
        id=3,
        client_user_id=3,
        master_id=1,
        service_id=1,
        booking_date=date(2026, 6, 1),
        start_time=time(13, 0),
        end_time=time(14, 0),
        status="pending",
        price=2000.0,
    )
    b3.service = s1

    # b4: cancelled by client, zero revenue
    b4 = Booking(
        id=4,
        client_user_id=4,
        master_id=1,
        service_id=1,
        booking_date=date(2026, 6, 1),
        start_time=time(15, 0),
        end_time=time(16, 0),
        status="cancelled_by_client",
        price=2000.0,
    )
    b4.service = s1

    bookings = [b1, b2, b3, b4]
    stats = calculate_schedule_stats(bookings)

    # revenue = 2500 + 3000 = 5500
    assert stats["revenue"] == 5500.0
    # expected_revenue = 2500 + 3000 + 2000 = 7500
    assert stats["expected_revenue"] == 7500.0
    assert stats["total"] == 4
    assert stats["completed"] == 1
    assert stats["confirmed"] == 1
    assert stats["pending"] == 1
    assert stats["cancelled"] == 1
    # avg_check = 5500 / 2 = 2750
    assert stats["avg_check"] == 2750


def test_admin_manual_booking_router_included():
    assert admin_manual_booking_router in admin_router.sub_routers


def test_free_booking_snapshot_remains_zero_after_catalog_price_changes():
    from ui.dashboards import get_booking_price

    booking = Booking(price=0, status="completed", service=Service(price=2500))
    stats = calculate_schedule_stats([booking])
    assert stats["revenue"] == stats["expected_revenue"] == stats["avg_check"] == 0
    assert get_booking_price(booking) == 0


@pytest.mark.asyncio
async def test_free_booking_snapshot_is_preserved_in_all_api_views(client, db_session):
    from core.slot_service import get_moscow_now
    from datetime import timedelta

    day = get_moscow_now().date() + timedelta(days=2)
    booking = Booking(client_user_id=1, master_id=1, service_id=1, booking_date=day,
                      start_time=time(12), end_time=time(13), price=0, status="completed",
                      client_name="Synthetic client", client_phone="synthetic-contact")
    db_session.add(booking)
    await db_session.commit()
    admin = {"X-Dev-User-Id": "5568814893"}
    schedule = (await client.get(f"/api/admin/schedule?date={day}", headers=admin)).json()
    rows = (await client.get("/api/admin/bookings", headers=admin)).json()
    mine = (await client.get("/api/bookings", headers={"X-Dev-User-Id": "999000101"})).json()
    assert schedule["bookings"][0]["service_price"] == 0
    assert schedule["stats"]["revenue"] == 0
    assert rows[0]["service_price"] == mine[0]["service_price"] == 0
