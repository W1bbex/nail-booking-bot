from datetime import date, datetime, time, timedelta
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.booking_service import create_booking, get_available_slots
from core.catalog_service import block_time_interval


@pytest.mark.asyncio
async def test_slot_calculation_respects_service_duration(db_session: AsyncSession):
    # Service 2: 30 min duration
    target_date = date.today() + timedelta(days=2)
    slots_30m = await get_available_slots(
        session=db_session,
        master_id=1,
        service_id=2,  # 30 min
        target_date=target_date,
        now_override=datetime.combine(target_date - timedelta(days=1), time(10, 0)),
    )
    assert len(slots_30m) > 0
    # Between 10:00 and 21:00 with 30m steps: 22 slots for 30m service
    assert slots_30m[0]["start_time"] == "10:00"
    assert slots_30m[0]["end_time"] == "10:30"
    assert slots_30m[-1]["start_time"] == "20:30"
    assert slots_30m[-1]["end_time"] == "21:00"

    # Service 1: 90 min duration (requires 3 consecutive 30m blocks)
    slots_90m = await get_available_slots(
        session=db_session,
        master_id=1,
        service_id=1,  # 90 min
        target_date=target_date,
        now_override=datetime.combine(target_date - timedelta(days=1), time(10, 0)),
    )
    assert len(slots_90m) > 0
    assert slots_90m[0]["start_time"] == "10:00"
    assert slots_90m[0]["end_time"] == "11:30"
    # Last slot can only start at 19:30 so it ends at 21:00
    assert slots_90m[-1]["start_time"] == "19:30"
    assert slots_90m[-1]["end_time"] == "21:00"


@pytest.mark.asyncio
async def test_existing_booking_excludes_overlapping_slots(db_session: AsyncSession):
    target_date = date.today() + timedelta(days=3)

    # Book 14:00 to 15:30 (90 min)
    await create_booking(
        session=db_session,
        client_telegram_id=999000101,
        client_name="Дарья",
        client_phone="+79991112233",
        master_id=1,
        service_id=1,  # 90 min
        booking_date=target_date,
        start_time=time(14, 0),
    )

    # Check available 60 min slots (Service 3)
    slots = await get_available_slots(
        session=db_session,
        master_id=1,
        service_id=3,  # 60 min
        target_date=target_date,
        now_override=datetime.combine(target_date - timedelta(days=1), time(10, 0)),
    )
    start_times = [s["start_time"] for s in slots]

    # Slot 13:00-14:00 ends at 14:00 -> NO overlap, should be AVAILABLE
    assert "13:00" in start_times
    # Slot 13:30-14:30 overlaps with 14:00-15:30 -> MUST NOT BE AVAILABLE
    assert "13:30" not in start_times
    # Slot 14:00-15:00 overlaps -> MUST NOT BE AVAILABLE
    assert "14:00" not in start_times
    # Slot 14:30-15:30 overlaps -> MUST NOT BE AVAILABLE
    assert "14:30" not in start_times
    # Slot 15:00-16:00 overlaps with 15:00-15:30 -> MUST NOT BE AVAILABLE
    assert "15:00" not in start_times
    # Slot 15:30-16:30 starts at 15:30 -> NO overlap, should be AVAILABLE
    assert "15:30" in start_times


@pytest.mark.asyncio
async def test_blocked_interval_excludes_slots(db_session: AsyncSession):
    target_date = date.today() + timedelta(days=4)

    # Block 13:00 to 14:00 (lunch) for Master 1
    await block_time_interval(
        session=db_session,
        master_id=1,
        block_date=target_date,
        start_time=time(13, 0),
        end_time=time(14, 0),
        reason="Обед мастера",
    )

    slots = await get_available_slots(
        session=db_session,
        master_id=1,
        service_id=2,  # 30 min
        target_date=target_date,
        now_override=datetime.combine(target_date - timedelta(days=1), time(10, 0)),
    )
    start_times = [s["start_time"] for s in slots]

    assert "12:30" in start_times  # 12:30-13:00 free
    assert "13:00" not in start_times  # blocked
    assert "13:30" not in start_times  # blocked
    assert "14:00" in start_times  # 14:00-14:30 free
