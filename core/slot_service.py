"""
Slot calculation and schedule availability service.
Pure domain logic: calculating free intervals, handling working hours,
service duration matching, and master load balancing.
"""
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.catalog_service import _get_masters_sorted_by_daily_load
from core.config import settings
from core.logger import setup_logger
from core.models import BlockedInterval, Booking, Master, Service

logger = setup_logger("slot_service")

ACTIVE_BOOKING_STATUSES = ["pending", "confirmed", "awaiting_client_choice"]


def get_moscow_now() -> datetime:
    tz_name = settings.salon.get("timezone") or "Europe/Moscow"
    try:
        return datetime.now(ZoneInfo(tz_name)).replace(tzinfo=None)
    except Exception:
        return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=3)


def add_minutes(t: time, minutes: int) -> time:
    dummy_dt = datetime.combine(date.today(), t) + timedelta(minutes=minutes)
    return dummy_dt.time()


async def get_available_slots(
    session: AsyncSession,
    master_id: Optional[int],
    service_id: int,
    target_date: date,
    now_override: Optional[datetime] = None,
    include_unavailable: bool = False,
    ignore_lead_time: bool = False,
) -> List[Dict[str, Any]]:
    # If master_id is 0 or None, find slots across ANY active master ("Любой мастер")
    if not master_id:
        active_masters = await _get_masters_sorted_by_daily_load(session, target_date)
        if not active_masters:
            return []

        slot_map: Dict[str, Dict[str, Any]] = {}
        for m in active_masters:
            m_slots = await get_available_slots(
                session=session,
                master_id=m.id,
                service_id=service_id,
                target_date=target_date,
                now_override=now_override,
                include_unavailable=include_unavailable,
                ignore_lead_time=ignore_lead_time,
            )
            for s in m_slots:
                st = s["start_time"]
                is_avail = s.get("available", True)
                if st not in slot_map:
                    slot_copy = dict(s)
                    slot_copy["master_id"] = m.id if is_avail else 0
                    slot_copy["master_name"] = m.full_name if is_avail else ""
                    slot_map[st] = slot_copy
                elif is_avail and not slot_map[st].get("available", True):
                    # Upgrade from unavailable to available with this free master
                    slot_copy = dict(s)
                    slot_copy["master_id"] = m.id
                    slot_copy["master_name"] = m.full_name
                    slot_map[st] = slot_copy

        return [slot_map[k] for k in sorted(slot_map.keys())]

    # 1. Fetch master and service
    master = (await session.execute(
        select(Master).where(
            Master.id == master_id,
            Master.is_active.is_(True),
            Master.archived_at.is_(None),
        )
    )).scalar_one_or_none()

    service = (await session.execute(
        select(Service).where(
            Service.id == service_id,
            Service.is_active.is_(True),
            Service.archived_at.is_(None),
        )
    )).scalar_one_or_none()

    if not master or not service:
        return []

    # 2. Salon operational limits
    start_hour = int(settings.booking.get("work_start_hour", 10))
    end_hour = int(settings.booking.get("work_end_hour", 21))
    step_minutes = int(settings.booking.get("slot_step_minutes", 30))
    duration_minutes = service.duration_minutes

    work_start = time(start_hour, 0)
    work_end = time(end_hour, 0)

    # 3. Fetch all active bookings for this master on this date
    res_bookings = await session.execute(
        select(Booking).where(
            Booking.master_id == master_id,
            Booking.booking_date == target_date,
            Booking.status.in_(ACTIVE_BOOKING_STATUSES),
        )
    )
    existing_bookings = res_bookings.scalars().all()

    # 4. Fetch blocked intervals
    res_blocks = await session.execute(
        select(BlockedInterval).where(
            BlockedInterval.master_id == master_id,
            BlockedInterval.booking_date == target_date,
        )
    )
    blocked_intervals = res_blocks.scalars().all()

    # 5. Current time check for today
    current_dt = now_override or get_moscow_now()
    if target_date < current_dt.date():
        return []
    is_today = (target_date == current_dt.date())
    min_lead_minutes = 0 if ignore_lead_time else int(settings.booking.get("min_lead_minutes", 30))

    slots = []
    cursor_dt = datetime.combine(target_date, work_start)
    work_end_dt = datetime.combine(target_date, work_end)

    while cursor_dt + timedelta(minutes=duration_minutes) <= work_end_dt:
        slot_start_time = cursor_dt.time()
        slot_end_time = (cursor_dt + timedelta(minutes=duration_minutes)).time()

        # Check if in past
        if is_today:
            earliest_allowed = current_dt + timedelta(minutes=min_lead_minutes)
            if cursor_dt < earliest_allowed:
                cursor_dt += timedelta(minutes=step_minutes)
                continue

        # Check overlapping bookings: [slot_start, slot_end) vs [b_start, b_end)
        has_booking_conflict = False
        for b in existing_bookings:
            if slot_start_time < b.end_time and slot_end_time > b.start_time:
                has_booking_conflict = True
                break

        # Check overlapping blocked intervals
        has_block_conflict = False
        if not has_booking_conflict:
            for blk in blocked_intervals:
                if slot_start_time < blk.end_time and slot_end_time > blk.start_time:
                    has_block_conflict = True
                    break

        if has_booking_conflict or has_block_conflict:
            if include_unavailable:
                slots.append({
                    "start_time": slot_start_time.strftime("%H:%M"),
                    "end_time": slot_end_time.strftime("%H:%M"),
                    "duration_minutes": duration_minutes,
                    "available": False,
                    "reason": "booked" if has_booking_conflict else "break",
                })
            cursor_dt += timedelta(minutes=step_minutes)
            continue

        slots.append({
            "start_time": slot_start_time.strftime("%H:%M"),
            "end_time": slot_end_time.strftime("%H:%M"),
            "duration_minutes": duration_minutes,
            "available": True,
            "reason": None,
        })

        cursor_dt += timedelta(minutes=step_minutes)

    return slots
