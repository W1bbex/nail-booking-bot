import asyncio
import json
import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo
from sqlalchemy import and_, func, not_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.config import CONFIG_PATH, settings
from core.logger import setup_logger
from core.models import BlockedInterval, Booking, Master, Service, User

logger = setup_logger("catalog_service")

ACTIVE_BOOKING_STATUSES = ["pending", "confirmed", "awaiting_client_choice"]


def _get_booking_lock() -> asyncio.Lock:
    from core.booking_service import _booking_lock
    return _booking_lock


def get_moscow_now() -> datetime:
    tz_name = settings.salon.get("timezone") or "Europe/Moscow"
    try:
        return datetime.now(ZoneInfo(tz_name)).replace(tzinfo=None)
    except Exception:
        return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=3)


def update_salon_settings(salon_data: Dict[str, Any]) -> Dict[str, Any]:
    # Update in-memory settings
    settings.salon.update(salon_data)

    # Persist to config.json atomically
    try:
        raw_config: Dict[str, Any] = {}
        if CONFIG_PATH.is_file():
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                raw_config = json.load(f)
        raw_config["salon"] = settings.salon

        tmp_path = str(CONFIG_PATH) + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(raw_config, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, CONFIG_PATH)
        logger.info("Salon settings updated and persisted to config.json")
    except Exception as e:
        logger.error(f"Failed to persist salon settings to config.json: {e}")
        raise
    return settings.salon


async def _get_masters_sorted_by_daily_load(
    session: AsyncSession,
    target_date: date,
    exclude_booking_id: Optional[int] = None,
) -> List[Master]:
    masters_res = await session.execute(
        select(Master)
        .where(Master.is_active.is_(True), Master.archived_at.is_(None))
        .order_by(Master.id)
    )
    active_masters = list(masters_res.scalars().all())
    if not active_masters:
        return []

    count_stmt = select(Booking.master_id, func.count(Booking.id)).where(
        Booking.booking_date == target_date,
        Booking.status.in_(ACTIVE_BOOKING_STATUSES),
        not_(and_(Booking.is_any_master.is_(True), Booking.status == "pending")),
    )
    if exclude_booking_id is not None:
        count_stmt = count_stmt.where(Booking.id != exclude_booking_id)

    counts_res = await session.execute(count_stmt.group_by(Booking.master_id))
    load_map = {row[0]: int(row[1]) for row in counts_res.fetchall()}
    active_masters.sort(key=lambda m: (load_map.get(m.id, 0), m.id))
    return active_masters


async def get_free_active_masters(
    session: AsyncSession,
    booking_date: date,
    start_time: time,
    end_time: time,
    exclude_ids: Optional[List[int]] = None,
    exclude_booking_id: Optional[int] = None,
) -> List[Master]:
    exclude_set = set(exclude_ids or [])
    all_sorted = await _get_masters_sorted_by_daily_load(
        session, booking_date, exclude_booking_id=exclude_booking_id
    )
    free_masters = []

    for m in all_sorted:
        if m.id in exclude_set or not m.is_active or m.archived_at is not None:
            continue

        # Check conflicting bookings (ignore unassigned any-master pending reservation or excluded booking)
        conflict_stmt = select(Booking).where(
            Booking.master_id == m.id,
            Booking.booking_date == booking_date,
            Booking.status.in_(ACTIVE_BOOKING_STATUSES),
            Booking.start_time < end_time,
            Booking.end_time > start_time,
            not_(and_(Booking.is_any_master.is_(True), Booking.status == "pending")),
        )
        if exclude_booking_id is not None:
            conflict_stmt = conflict_stmt.where(Booking.id != exclude_booking_id)

        conflict = (await session.execute(conflict_stmt)).scalars().first()
        if conflict:
            continue

        # Check blocked intervals
        blocked = (await session.execute(
            select(BlockedInterval).where(
                BlockedInterval.master_id == m.id,
                BlockedInterval.booking_date == booking_date,
                BlockedInterval.start_time < end_time,
                BlockedInterval.end_time > start_time,
            )
        )).scalars().first()
        if blocked:
            continue

        free_masters.append(m)

    return free_masters


async def get_all_masters(session: AsyncSession, include_inactive: bool = True) -> List[Master]:
    stmt = select(Master).where(Master.archived_at.is_(None)).order_by(Master.id)
    if not include_inactive:
        stmt = stmt.where(Master.is_active.is_(True))
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def create_master(
    session: AsyncSession,
    full_name: str,
    specialization: str,
    experience_years: int = 3,
    is_active: bool = True,
    telegram_username: Optional[str] = None,
    admin_telegram_id: Optional[int] = None,
) -> Master:
    clean_name = full_name.strip()
    if not clean_name:
        raise ValueError("Имя мастера не может быть пустым")
    if experience_years < 0:
        raise ValueError("Стаж мастера не может быть отрицательным")

    clean_tg = telegram_username.strip().lstrip("@") if telegram_username else None
    master = Master(
        full_name=clean_name,
        specialization=specialization.strip(),
        experience_years=int(experience_years),
        is_active=bool(is_active),
        telegram_username=clean_tg or None,
    )
    session.add(master)
    await session.commit()
    await session.refresh(master)
    logger.info(f"Master #{master.id} '{master.full_name}' created")
    return master


async def update_master(
    session: AsyncSession,
    master_id: int,
    full_name: Optional[str] = None,
    specialization: Optional[str] = None,
    experience_years: Optional[int] = None,
    is_active: Optional[bool] = None,
    telegram_username: Optional[str] = None,
    admin_telegram_id: Optional[int] = None,
) -> Master:
    res = await session.execute(select(Master).where(Master.id == master_id, Master.archived_at.is_(None)))
    master = res.scalar_one_or_none()
    if not master:
        raise ValueError("Мастер не найден")

    if full_name is not None:
        clean_name = full_name.strip()
        if not clean_name:
            raise ValueError("Имя мастера не может быть пустым")
        master.full_name = clean_name
    if specialization is not None:
        master.specialization = specialization.strip()
    if experience_years is not None:
        if experience_years < 0:
            raise ValueError("Стаж мастера не может быть отрицательным")
        master.experience_years = int(experience_years)
    if is_active is not None:
        master.is_active = bool(is_active)
    if telegram_username is not None:
        clean_tg = telegram_username.strip().lstrip("@")
        master.telegram_username = clean_tg if clean_tg else None

    await session.commit()
    await session.refresh(master)
    logger.info(f"Master #{master.id} '{master.full_name}' updated")
    return master


async def toggle_master_active(
    session: AsyncSession,
    master_id: int,
    admin_telegram_id: Optional[int] = None,
) -> Master:
    res = await session.execute(select(Master).where(Master.id == master_id, Master.archived_at.is_(None)))
    master = res.scalar_one_or_none()
    if not master:
        raise ValueError("Мастер не найден")

    master.is_active = not master.is_active
    await session.commit()
    await session.refresh(master)
    logger.info(f"Master #{master.id} '{master.full_name}' active set to {master.is_active}")
    return master


async def delete_master(
    session: AsyncSession,
    master_id: int,
    admin_telegram_id: Optional[int] = None,
) -> Master:
    if admin_telegram_id and not settings.is_admin(admin_telegram_id):
        raise PermissionError("Удаление мастера доступно только администраторам")

    res = await session.execute(select(Master).where(Master.id == master_id, Master.archived_at.is_(None)))
    master = res.scalar_one_or_none()
    if not master:
        raise ValueError("Мастер не найден")

    active_booking = (await session.execute(
        select(Booking).where(
            Booking.master_id == master_id,
            Booking.status.in_(ACTIVE_BOOKING_STATUSES),
        )
    )).scalars().first()
    if active_booking:
        raise ValueError(
            f"Невозможно удалить мастера «{master.full_name}»: есть активная запись #{active_booking.id} "
            f"на {active_booking.booking_date.strftime('%d.%m.%Y')}. Сначала отмените или завершите запись."
        )

    master.is_active = False
    master.archived_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(master)
    logger.info(f"Master #{master.id} '{master.full_name}' archived by admin {admin_telegram_id}")
    return master


async def get_all_services(session: AsyncSession, include_inactive: bool = True) -> List[Service]:
    stmt = select(Service).where(Service.archived_at.is_(None)).order_by(Service.category, Service.name)
    if not include_inactive:
        stmt = stmt.where(Service.is_active.is_(True))
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def create_service(
    session: AsyncSession,
    category: str,
    name: str,
    description: Optional[str] = None,
    duration_minutes: int = 60,
    price: float = 0.0,
    is_active: bool = True,
    admin_telegram_id: Optional[int] = None,
) -> Service:
    clean_name = name.strip()
    clean_category = category.strip()
    if not clean_name:
        raise ValueError("Название услуги не может быть пустым")
    if not clean_category:
        raise ValueError("Категория услуги не может быть пустой")
    if duration_minutes <= 0:
        raise ValueError("Длительность услуги должна быть больше 0 минут")
    if price < 0:
        raise ValueError("Цена услуги не может быть отрицательной")

    service = Service(
        category=clean_category,
        name=clean_name,
        description=description.strip() if description else None,
        duration_minutes=int(duration_minutes),
        price=round(float(price), 2),
        is_active=bool(is_active),
    )
    session.add(service)
    await session.commit()
    await session.refresh(service)
    logger.info(f"Service #{service.id} '{service.name}' created in category '{service.category}'")
    return service


async def update_service(
    session: AsyncSession,
    service_id: int,
    category: Optional[str] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    duration_minutes: Optional[int] = None,
    price: Optional[float] = None,
    is_active: Optional[bool] = None,
    admin_telegram_id: Optional[int] = None,
) -> Service:
    res = await session.execute(select(Service).where(Service.id == service_id, Service.archived_at.is_(None)))
    service = res.scalar_one_or_none()
    if not service:
        raise ValueError("Услуга не найдена")

    if category is not None:
        clean_cat = category.strip()
        if not clean_cat:
            raise ValueError("Категория не может быть пустой")
        service.category = clean_cat
    if name is not None:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Название услуги не может быть пустым")
        service.name = clean_name
    if description is not None:
        clean_desc = description.strip()
        service.description = clean_desc if clean_desc else None
    if duration_minutes is not None:
        if duration_minutes <= 0:
            raise ValueError("Длительность услуги должна быть больше 0")
        service.duration_minutes = int(duration_minutes)
    if price is not None:
        if price < 0:
            raise ValueError("Цена услуги не может быть отрицательной")
        service.price = round(float(price), 2)
    if is_active is not None:
        service.is_active = bool(is_active)

    await session.commit()
    await session.refresh(service)
    logger.info(f"Service #{service.id} '{service.name}' updated")
    return service


async def delete_service(
    session: AsyncSession,
    service_id: int,
    admin_telegram_id: Optional[int] = None,
) -> Service:
    if admin_telegram_id and not settings.is_admin(admin_telegram_id):
        raise PermissionError("Удаление услуги доступно только администраторам")

    res = await session.execute(select(Service).where(Service.id == service_id, Service.archived_at.is_(None)))
    service = res.scalar_one_or_none()
    if not service:
        raise ValueError("Услуга не найдена")

    active_booking = (await session.execute(
        select(Booking).where(
            Booking.service_id == service_id,
            Booking.status.in_(ACTIVE_BOOKING_STATUSES),
        )
    )).scalars().first()
    if active_booking:
        raise ValueError(
            f"Невозможно удалить услугу «{service.name}»: есть активная запись #{active_booking.id} "
            f"на {active_booking.booking_date.strftime('%d.%m.%Y')}. Сначала отмените или завершите запись."
        )

    service.is_active = False
    service.archived_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(service)
    logger.info(f"Service #{service.id} '{service.name}' archived by admin {admin_telegram_id}")
    return service


async def update_service_price(
    session: AsyncSession,
    service_id: int,
    new_price: float,
    admin_telegram_id: int,
) -> Service:
    if not settings.is_admin(admin_telegram_id):
        raise PermissionError("Действие разрешено только администраторам")
    if new_price <= 0:
        raise ValueError("Цена услуги должна быть больше нуля")

    res = await session.execute(select(Service).where(Service.id == service_id))
    service = res.scalar_one_or_none()
    if not service:
        raise ValueError("Услуга не найдена")

    service.price = round(float(new_price), 2)
    await session.commit()
    await session.refresh(service)
    logger.info(f"Service #{service.id} '{service.name}' price updated to {service.price} by admin {admin_telegram_id}")
    return service


async def toggle_service_active(
    session: AsyncSession,
    service_id: int,
    admin_telegram_id: int,
) -> Service:
    if not settings.is_admin(admin_telegram_id):
        raise PermissionError("Действие разрешено только администраторам")

    res = await session.execute(select(Service).where(Service.id == service_id))
    service = res.scalar_one_or_none()
    if not service:
        raise ValueError("Услуга не найдена")

    service.is_active = not service.is_active
    await session.commit()
    await session.refresh(service)
    logger.info(f"Service #{service.id} '{service.name}' active state toggled to {service.is_active}")
    return service


async def bind_master_by_telegram(
    session: AsyncSession,
    telegram_id: int,
    username: Optional[str],
) -> Optional[Master]:
    if not username:
        return None
    clean_name = username.strip().lstrip("@").lower()
    if not clean_name:
        return None

    res = await session.execute(
        select(Master).where(
            func.lower(func.replace(Master.telegram_username, "@", "")) == clean_name,
            Master.archived_at.is_(None),
        )
    )
    master = res.scalar_one_or_none()
    if not master:
        return None

    master.telegram_id = telegram_id
    user_res = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = user_res.scalar_one_or_none()
    if user:
        if not settings.is_admin(telegram_id):
            user.role = "master"
    else:
        user = User(
            telegram_id=telegram_id,
            full_name=master.full_name,
            role="admin" if settings.is_admin(telegram_id) else "master",
        )
        session.add(user)

    await session.commit()
    await session.refresh(master)
    logger.info(f"Master #{master.id} '{master.full_name}' successfully bound to telegram_id {telegram_id} (@{clean_name})")
    return master


async def block_time_interval(
    session: AsyncSession,
    master_id: int,
    block_date: date,
    start_time: time,
    end_time: time,
    reason: Optional[str] = "Технический перерыв",
    admin_telegram_id: Optional[int] = None,
    now_override: Optional[datetime] = None,
) -> BlockedInterval:
    if admin_telegram_id and not settings.is_admin(admin_telegram_id):
        raise PermissionError("Блокировка времени доступна только администраторам")

    if start_time >= end_time:
        raise ValueError("Время начала блокировки должно быть раньше времени окончания")

    now_dt = now_override or get_moscow_now()
    if block_date < now_dt.date():
        raise ValueError("Нельзя установить перерыв на прошедшую дату")
    if block_date == now_dt.date() and end_time <= now_dt.time():
        raise ValueError("Нельзя установить перерыв в прошедшем времени")

    async with _get_booking_lock():
        # Check duplicate / overlapping blocked interval for the same master
        existing_block = (await session.execute(
            select(BlockedInterval).where(
                BlockedInterval.master_id == master_id,
                BlockedInterval.booking_date == block_date,
                BlockedInterval.start_time < end_time,
                BlockedInterval.end_time > start_time,
            )
        )).scalars().first()

        if existing_block:
            raise ValueError(
                f"У мастера уже установлен перерыв на это время "
                f"({existing_block.start_time.strftime('%H:%M')} — {existing_block.end_time.strftime('%H:%M')})"
            )

        # Check conflicting active (pending or confirmed) bookings
        conflict = (await session.execute(
            select(Booking).where(
                Booking.master_id == master_id,
                Booking.booking_date == block_date,
                Booking.status.in_(ACTIVE_BOOKING_STATUSES),
                Booking.start_time < end_time,
                Booking.end_time > start_time,
            )
        )).scalars().first()

        if conflict:
            raise ValueError(
                f"Невозможно заблокировать интервал: на это время уже есть активная запись #{conflict.id} "
                f"({conflict.client_name})"
            )

        interval = BlockedInterval(
            master_id=master_id,
            booking_date=block_date,
            start_time=start_time,
            end_time=end_time,
            reason=reason,
        )
        session.add(interval)
        await session.commit()
        await session.refresh(interval)
        logger.info(f"Blocked interval created for master {master_id} on {block_date}: {start_time}-{end_time}")
        return interval


async def unblock_time_interval(
    session: AsyncSession,
    interval_id: int,
    admin_telegram_id: Optional[int] = None,
) -> BlockedInterval:
    if admin_telegram_id and not settings.is_admin(admin_telegram_id):
        raise PermissionError("Разблокировка времени доступна только администраторам")

    async with _get_booking_lock():
        res = await session.execute(
            select(BlockedInterval)
            .options(selectinload(BlockedInterval.master))
            .where(BlockedInterval.id == interval_id)
        )
        interval = res.scalar_one_or_none()
        if not interval:
            raise ValueError(f"Заблокированный интервал #{interval_id} не найден")

        await session.delete(interval)
        await session.commit()
        logger.info(f"Unblocked interval #{interval_id} for master {interval.master_id} on {interval.booking_date}")
        return interval


async def get_blocked_intervals(
    session: AsyncSession,
    target_date: Optional[date] = None,
    master_id: Optional[int] = None,
) -> List[BlockedInterval]:
    stmt = (
        select(BlockedInterval)
        .options(selectinload(BlockedInterval.master))
        .order_by(BlockedInterval.booking_date, BlockedInterval.start_time)
    )
    if target_date:
        stmt = stmt.where(BlockedInterval.booking_date == target_date)
    if master_id:
        stmt = stmt.where(BlockedInterval.master_id == master_id)
    res = await session.execute(stmt)
    return list(res.scalars().all())
