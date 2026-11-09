from datetime import date, datetime, time, timedelta
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.booking_service import (
    cancel_booking,
    confirm_booking,
    create_booking,
    get_moscow_now,
)
from core.models import Booking


@pytest.mark.asyncio
async def test_booking_creation_and_status_flow(db_session: AsyncSession):
    target_date = date.today() + timedelta(days=2)

    # 1. Create booking
    booking = await create_booking(
        session=db_session,
        client_telegram_id=999000101,
        client_name="Дарья",
        client_phone="+79991112233",
        master_id=1,
        service_id=3,  # 60 min
        booking_date=target_date,
        start_time=time(11, 0),
        comment="Снятие чужого покрытия",
    )

    assert booking.id is not None
    assert booking.status == "pending"
    assert booking.start_time == time(11, 0)
    assert booking.end_time == time(12, 0)
    assert booking.client_name == "Дарья"

    # 2. Admin confirms booking
    confirmed_b = await confirm_booking(
        session=db_session,
        booking_id=booking.id,
        admin_telegram_id=999000199,
    )
    assert confirmed_b.status == "confirmed"
    assert confirmed_b.confirmed_at is not None

    # 3. Client cancels booking
    cancelled_b = await cancel_booking(
        session=db_session,
        booking_id=booking.id,
        actor_telegram_id=999000101,
        is_admin_action=False,
    )
    assert cancelled_b.status == "cancelled_by_client"


@pytest.mark.asyncio
async def test_client_cannot_cancel_past_deadline(db_session: AsyncSession, monkeypatch):
    target_date = date.today()
    # Booking starts in 1 hour
    now_fixed = datetime.combine(target_date, time(14, 0))
    monkeypatch.setattr("core.booking_service.get_moscow_now", lambda: now_fixed)

    booking = await create_booking(
        session=db_session,
        client_telegram_id=999000101,
        client_name="Дарья",
        client_phone="+79991112233",
        master_id=1,
        service_id=2,  # 30 min
        booking_date=target_date,
        start_time=time(15, 0),  # 1 hour from now, less than 2 hours deadline!
    )

    with pytest.raises(ValueError, match="не позднее чем за 2 ч"):
        await cancel_booking(
            session=db_session,
            booking_id=booking.id,
            actor_telegram_id=999000101,
            is_admin_action=False,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("minutes_before_start", [60, 0])
async def test_admin_cancels_booking_inside_client_deadline(db_session: AsyncSession, monkeypatch, minutes_before_start):
    """The client is denied near the visit; the administrator can still cancel it."""
    target_date = get_moscow_now().date()
    monkeypatch.setattr("core.booking_service.get_moscow_now", lambda: datetime.combine(target_date, time(14, 0)))
    booking = await create_booking(
        session=db_session,
        client_telegram_id=999000101,
        client_name="Дарья",
        client_phone="+79991112233",
        master_id=1,
        service_id=2,
        booking_date=target_date,
        start_time=time(15, 0),
    )

    cancellation_time = datetime.combine(target_date, time(15, 0)) - timedelta(minutes=minutes_before_start)
    monkeypatch.setattr("core.booking_service.get_moscow_now", lambda: cancellation_time)
    with pytest.raises(ValueError, match="не позднее чем за 2 ч"):
        await cancel_booking(
            session=db_session, booking_id=booking.id,
            actor_telegram_id=999000101, is_admin_action=False,
        )
    assert booking.status == "pending"

    cancelled = await cancel_booking(
        session=db_session,
        booking_id=booking.id,
        actor_telegram_id=999000199,
        is_admin_action=True,
    )
    assert cancelled.status == "cancelled_by_admin"
