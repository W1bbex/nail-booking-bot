import asyncio
from datetime import date, time, timedelta
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.booking_service import _mask_phone, create_booking
from core.models import Booking


@pytest.mark.asyncio
async def test_concurrent_double_booking_prevention(db_session: AsyncSession):
    target_date = date.today() + timedelta(days=5)
    booking_time = time(16, 0)
    master_id = 1
    service_id = 3  # 60 min duration (16:00 to 17:00)

    results = []
    errors = []

    # Use an independent AsyncSession per concurrent task bound to the same engine
    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    async def attempt_booking(client_id: int, client_name: str):
        try:
            async with session_factory() as session:
                b = await create_booking(
                    session=session,
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


@pytest.mark.asyncio
async def test_unique_index_rejects_active_slot_and_allows_cancelled_slot(db_session: AsyncSession):
    """Verify DB partial unique index rejects conflicting active slots even if asyncio.Lock is bypassed."""
    target_date = date.today() + timedelta(days=6)
    slot_start = time(14, 0)
    slot_end = time(15, 0)

    b1 = Booking(
        client_user_id=1,
        master_id=1,
        service_id=3,
        booking_date=target_date,
        start_time=slot_start,
        end_time=slot_end,
        price=1900.0,
        status="pending",
        client_name="Клиент 1",
        client_phone="+79991112233",
    )
    db_session.add(b1)
    await db_session.commit()
    b1_id = b1.id

    # A direct conflicting insert bypasses the application lock.
    b2 = Booking(
        client_user_id=1,
        master_id=1,
        service_id=3,
        booking_date=target_date,
        start_time=slot_start,
        end_time=slot_end,
        price=1900.0,
        status="confirmed",
        client_name="Клиент 2",
        client_phone="+79994445566",
    )
    db_session.add(b2)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    # Once first booking is cancelled, the partial index allows re-booking the freed slot
    b1_refreshed = (await db_session.execute(select(Booking).where(Booking.id == b1_id))).scalar_one()
    b1_refreshed.status = "cancelled_by_client"
    await db_session.commit()

    b3 = Booking(
        client_user_id=1,
        master_id=1,
        service_id=3,
        booking_date=target_date,
        start_time=slot_start,
        end_time=slot_end,
        price=1900.0,
        status="pending",
        client_name="Клиент 3",
        client_phone="+79997778899",
    )
    db_session.add(b3)
    await db_session.commit()
    assert b3.id is not None


def test_pii_phone_masking_in_logs():
    masked = _mask_phone("+7 (999) 123-45-67")
    assert "123" not in masked
    assert "45" not in masked
    assert masked == "+79***67"


@pytest.mark.asyncio
async def test_expired_bookings_releases_lock_before_network_io(db_session: AsyncSession):
    from unittest.mock import AsyncMock, MagicMock
    from datetime import datetime, timezone
    from core.booking_service import process_expired_bookings, _booking_lock

    target_date = date.today() + timedelta(days=2)
    b = Booking(
        client_user_id=1,
        master_id=1,
        service_id=1,
        booking_date=target_date,
        start_time=time(10, 0),
        end_time=time(11, 0),
        price=1000.0,
        status="pending",
        client_name="Timeout Client",
        client_phone="+79991112233",
        assignment_deadline=datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    db_session.add(b)
    await db_session.commit()

    lock_held_during_io = []

    mock_bot = MagicMock()

    async def fake_send_message(*args, **kwargs):
        lock_held_during_io.append(_booking_lock.locked())
        return MagicMock(message_id=999)

    mock_bot.send_message = AsyncMock(side_effect=fake_send_message)
    mock_bot.edit_message_text = AsyncMock(return_value=MagicMock())

    count = await process_expired_bookings(db_session, mock_bot)
    assert count >= 1
    assert len(lock_held_during_io) > 0, "Expected network calls to have been made"
    assert not any(lock_held_during_io), "Network I/O must NOT be executed while _booking_lock is held!"


@pytest.mark.asyncio
async def test_expired_bookings_logs_notification_errors(db_session: AsyncSession, caplog):
    import logging
    from unittest.mock import AsyncMock, MagicMock
    from datetime import datetime, timezone
    from core.booking_service import process_expired_bookings

    target_date = date.today() + timedelta(days=3)
    b = Booking(
        client_user_id=1,
        master_id=1,
        service_id=1,
        booking_date=target_date,
        start_time=time(11, 0),
        end_time=time(12, 0),
        price=1000.0,
        status="pending",
        client_name="Error Client",
        client_phone="+79991112233",
        assignment_deadline=datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    db_session.add(b)
    await db_session.commit()

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock(side_effect=RuntimeError("Telegram API down"))
    mock_bot.edit_message_text = AsyncMock(return_value=MagicMock())

    with caplog.at_level(logging.ERROR):
        count = await process_expired_bookings(db_session, mock_bot)
        assert count >= 1
        assert any("Telegram API down" in record.message or "Failed" in record.message for record in caplog.records)
