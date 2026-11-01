import asyncio
from datetime import date, time, timedelta
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.booking_service import create_booking
from core.models import Booking


@pytest.mark.asyncio
async def test_concurrent_double_booking_prevention(db_session: AsyncSession):
    target_date = date.today() + timedelta(days=5)
    booking_time = time(16, 0)
    master_id = 1
    service_id = 3  # 60 min duration (16:00 to 17:00)

    results = []
    errors = []

    async def attempt_booking(client_id: int, client_name: str):
        try:
            b = await create_booking(
                session=db_session,
                client_telegram_id=client_id,
                client_name=client_name,
                client_phone=f"+7999000{client_id}",
                master_id=master_id,
                service_id=service_id,
                booking_date=target_date,
                start_time=booking_time,
            )
            results.append(b)
        except ValueError as e:
            errors.append(str(e))

    # Run 5 simultaneous booking attempts for the same master and slot
    tasks = [
        attempt_booking(999000200 + i, f"Клиент #{i}")
        for i in range(5)
    ]
    await asyncio.gather(*tasks)

    # Exactly ONE booking must succeed
    assert len(results) == 1, f"Expected exactly 1 successful booking, got {len(results)}"
    # The other 4 attempts must be rejected
    assert len(errors) == 4, f"Expected 4 rejected attempts, got {len(errors)}"

    # All errors must explain that the time is already occupied
    for err in errors:
        assert "уже занято другим клиентом" in err

    # Verify database state has exactly 1 record
    res = await db_session.execute(
        select(Booking).where(
            Booking.master_id == master_id,
            Booking.booking_date == target_date,
            Booking.start_time == booking_time,
        )
    )
    db_bookings = res.scalars().all()
    assert len(db_bookings) == 1
    assert db_bookings[0].id == results[0].id
