import asyncio
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.catalog_service import _get_masters_sorted_by_daily_load, get_free_active_masters
from core.config import settings
from core.logger import setup_logger
from core.models import BlockedInterval, Booking, Master, Service, User
from core.slot_service import add_minutes, get_available_slots, get_moscow_now

logger = setup_logger("booking_service")

# Global async mutex to prevent race conditions / double bookings
_booking_lock = asyncio.Lock()

ACTIVE_BOOKING_STATUSES = ["pending", "confirmed", "awaiting_client_choice"]


def _mask_phone(phone: str) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) >= 6:
        return f"+{digits[:2]}***{digits[-2:]}"
    return "***"


def calculate_assignment_deadline(booking_date: date) -> datetime:
    now_m = get_moscow_now()
    if booking_date == now_m.date():
        timeout_mins = int(settings.salon.get("timeout_today_minutes", 10))
    else:
        timeout_mins = int(settings.salon.get("timeout_future_minutes", 30))
    return now_m + timedelta(minutes=timeout_mins)


async def create_booking(
    session: AsyncSession,
    client_telegram_id: int,
    client_name: str,
    client_phone: str,
    master_id: int,
    service_id: int,
    booking_date: date,
    start_time: time,
    comment: Optional[str] = None,
    ignore_lead_time: bool = False,
) -> Booking:
    async with _booking_lock:
        # Check service
        service = (await session.execute(
            select(Service).where(
                Service.id == service_id,
                Service.is_active.is_(True),
                Service.archived_at.is_(None),
            )
        )).scalar_one_or_none()
        if not service:
            raise ValueError("Услуга не найдена или не активна")

        # Check master or assign least-loaded free master if master_id is 0/None ("Любой мастер")
        is_any_master = not master_id
        if not master_id:
            all_masters = await _get_masters_sorted_by_daily_load(session, booking_date)
            chosen_master = None
            st_str = start_time.strftime("%H:%M")
            now_override = get_moscow_now()
            for cand in all_masters:
                cand_slots = await get_available_slots(
                    session=session,
                    master_id=cand.id,
                    service_id=service_id,
                    target_date=booking_date,
                    now_override=now_override,
                    ignore_lead_time=ignore_lead_time,
                )
                if any(s["start_time"] == st_str for s in cand_slots):
                    chosen_master = cand
                    break
            if not chosen_master:
                raise ValueError("На выбранное время нет свободных мастеров")
            master = chosen_master
            master_id = master.id
        else:
            master = (await session.execute(
                select(Master).where(
                    Master.id == master_id,
                    Master.is_active.is_(True),
                    Master.archived_at.is_(None),
                )
            )).scalar_one_or_none()
            if not master:
                raise ValueError("Мастер не найден или недоступен для записи")

        # Calculate end time
        end_time = add_minutes(start_time, service.duration_minutes)

        # Check working hours boundary
        start_hour = int(settings.booking.get("work_start_hour", 10))
        end_hour = int(settings.booking.get("work_end_hour", 21))
        work_end = time(end_hour, 0)
        if (
            start_time < time(start_hour, 0)
            or start_time >= work_end
            or end_time <= start_time
            or end_time > work_end
        ):
            raise ValueError("Выбранное время выходит за рамки рабочего графика студии")

        # Check slot step alignment relative to working day start (e.g. 30 or 45 min) and seconds
        slot_step = int(settings.booking.get("slot_step_minutes", 30))
        offset_minutes = (start_time.hour - start_hour) * 60 + start_time.minute
        if offset_minutes < 0 or offset_minutes % slot_step != 0 or start_time.second != 0:
            raise ValueError(f"Время записи должно быть кратно шагу слота ({slot_step} мин)")

        # Check past date/time, minimum lead time, and booking horizon limit
        now_moscow = get_moscow_now()
        slot_dt = datetime.combine(booking_date, start_time)
        if booking_date < now_moscow.date() or (booking_date == now_moscow.date() and slot_dt < now_moscow):
            raise ValueError("Нельзя записаться на прошедшее время")

        if not ignore_lead_time:
            min_lead_minutes = int(settings.booking.get("min_lead_minutes", 30))
            earliest_allowed = now_moscow + timedelta(minutes=min_lead_minutes)
            if slot_dt < earliest_allowed:
                raise ValueError(
                    f"Запись возможна минимум за {min_lead_minutes} минут до визита"
                )

        horizon_days = int(settings.booking.get("horizon_days", 14))
        max_booking_date = now_moscow.date() + timedelta(days=horizon_days)
        if booking_date > max_booking_date:
            raise ValueError(
                f"Запись доступна максимум на {horizon_days} дней вперед (до {max_booking_date.strftime('%d.%m.%Y')})"
            )

        # Strict check for conflicting active bookings (double booking guard)
        conflict_stmt = select(Booking).where(
            Booking.master_id == master_id,
            Booking.booking_date == booking_date,
            Booking.status.in_(ACTIVE_BOOKING_STATUSES),
            Booking.start_time < end_time,
            Booking.end_time > start_time,
        )
        existing_conflict = (await session.execute(conflict_stmt)).scalars().first()
        if existing_conflict is not None:
            raise ValueError(
                f"Выбранное время ({start_time.strftime('%H:%M')} — {end_time.strftime('%H:%M')}) "
                f"уже занято другим клиентом у мастера {master.full_name}"
            )

        # Strict check for blocked intervals
        block_stmt = select(BlockedInterval).where(
            BlockedInterval.master_id == master_id,
            BlockedInterval.booking_date == booking_date,
            BlockedInterval.start_time < end_time,
            BlockedInterval.end_time > start_time,
        )
        existing_block = (await session.execute(block_stmt)).scalars().first()
        if existing_block is not None:
            raise ValueError(f"Интервал времени заблокирован мастером ({existing_block.reason or 'перерыв'})")

        # Find or create User
        user = (await session.execute(
            select(User).where(User.telegram_id == client_telegram_id)
        )).scalar_one_or_none()

        clean_name = client_name.strip() or "Гость"
        clean_phone = client_phone.strip()

        if not user:
            user = User(
                telegram_id=client_telegram_id,
                full_name=clean_name,
                phone=clean_phone,
                role="admin" if settings.is_admin(client_telegram_id) else "client",
            )
            session.add(user)
            await session.flush()
        else:
            # Protect admin and master profiles from being overwritten with client details
            if not settings.is_admin(user.telegram_id) and user.role not in ("admin", "master"):
                if clean_name and user.full_name != clean_name:
                    user.full_name = clean_name
                if clean_phone and user.phone != clean_phone:
                    user.phone = clean_phone
                await session.flush()

        booking = Booking(
            client_user_id=user.id,
            master_id=master.id,
            service_id=service.id,
            booking_date=booking_date,
            start_time=start_time,
            end_time=end_time,
            price=round(float(service.price), 2),
            status="pending",
            is_any_master=is_any_master,
            assignment_deadline=calculate_assignment_deadline(booking_date) if is_any_master else None,
            client_name=clean_name,
            client_phone=clean_phone,
            comment=comment.strip() if comment else None,
            created_at=datetime.now(timezone.utc),
        )
        session.add(booking)
        try:
            await session.commit()
        except IntegrityError as e:
            await session.rollback()
            err_msg = str(e).lower()
            if "idx_unique_active_master_slot" in err_msg or (
                "unique" in err_msg and any(f in err_msg for f in ("master_id", "booking_date", "start_time"))
            ):
                raise ValueError(
                    f"Выбранное время ({start_time.strftime('%H:%M')} — {end_time.strftime('%H:%M')}) "
                    f"уже занято другим клиентом у мастера {master.full_name}"
                )
            logger.error(f"Неожиданная ошибка целостности базы данных при создании брони: {e}")
            raise
        await session.refresh(booking)

        logger.info(
            f"Booking created #{booking.id}: user_id={user.id} (phone={_mask_phone(clean_phone)}) -> "
            f"master_id={master.id}, service_id={service.id}, "
            f"date={booking_date}, {start_time:%H:%M}-{end_time:%H:%M}"
        )
        return booking


async def cancel_booking(
    session: AsyncSession,
    booking_id: int,
    actor_telegram_id: int,
    is_admin_action: bool = False,
) -> Booking:
    async with _booking_lock:
        res = await session.execute(
            select(Booking)
            .options(selectinload(Booking.client_user), selectinload(Booking.master), selectinload(Booking.service))
            .where(Booking.id == booking_id)
        )
        booking = res.scalar_one_or_none()
        if not booking:
            raise ValueError("Запись не найдена")

        if booking.status in ["cancelled_by_client", "cancelled_by_admin"]:
            raise ValueError("Запись уже была отменена ранее")

        if booking.status == "completed":
            raise ValueError("Нельзя отменить уже завершённый визит")

        if is_admin_action or settings.is_admin(actor_telegram_id):
            booking.status = "cancelled_by_admin"
        else:
            # Client check
            if not booking.client_user or booking.client_user.telegram_id != actor_telegram_id:
                raise PermissionError("Вы можете отменять только свои собственные записи")

            # Cancellation deadline check
            allow_hours = int(settings.booking.get("allow_client_cancel_hours", 2))
            booking_dt = datetime.combine(booking.booking_date, booking.start_time)
            now_moscow = get_moscow_now()
            if (booking_dt - now_moscow) < timedelta(hours=allow_hours):
                raise ValueError(
                    f"Самостоятельная отмена записи возможна не позднее чем за {allow_hours} ч. до визита"
                )

            booking.status = "cancelled_by_client"

        await session.commit()
        await session.refresh(booking, attribute_names=["status"])
        logger.info(f"Booking #{booking.id} cancelled. New status: {booking.status}")
        return booking


async def confirm_booking(
    session: AsyncSession,
    booking_id: int,
    admin_telegram_id: int,
) -> Booking:
    if not settings.is_admin(admin_telegram_id):
        raise PermissionError("Действие разрешено только администратору или мастеру")

    async with _booking_lock:
        res = await session.execute(
            select(Booking)
            .options(selectinload(Booking.client_user), selectinload(Booking.master), selectinload(Booking.service))
            .where(Booking.id == booking_id)
        )
        booking = res.scalar_one_or_none()
        if not booking:
            raise ValueError("Запись не найдена")

        if booking.status == "confirmed":
            return booking

        if booking.status != "pending":
            raise ValueError(f"Невозможно подтвердить запись в статусе '{booking.status}'")

        booking.status = "confirmed"
        booking.confirmed_at = datetime.now(timezone.utc)
        booking.assignment_deadline = None
        booking.client_reassign_deadline = None
        await session.commit()
        await session.refresh(booking, attribute_names=["status", "confirmed_at", "assignment_deadline", "client_reassign_deadline"])
        logger.info(f"Booking #{booking.id} confirmed by admin {admin_telegram_id}")
        return booking


async def complete_booking(
    session: AsyncSession,
    booking_id: int,
    admin_telegram_id: int,
) -> Booking:
    if not settings.is_admin(admin_telegram_id):
        raise PermissionError("Действие разрешено только администратору или мастеру")

    async with _booking_lock:
        res = await session.execute(
            select(Booking)
            .options(selectinload(Booking.client_user), selectinload(Booking.master), selectinload(Booking.service))
            .where(Booking.id == booking_id)
        )
        booking = res.scalar_one_or_none()
        if not booking:
            raise ValueError("Запись не найдена")

        if booking.status not in ("confirmed", "pending"):
            raise ValueError(f"Невозможно завершить запись в статусе '{booking.status}'")

        booking.status = "completed"
        await session.commit()
        await session.refresh(booking, attribute_names=["status"])
        logger.info(f"Booking #{booking.id} marked as completed by admin {admin_telegram_id}")
        return booking


async def claim_booking_by_master(
    session: AsyncSession,
    booking_id: int,
    master_telegram_id: int,
) -> tuple[bool, str, Optional[Booking]]:
    async with _booking_lock:
        master = (await session.execute(
            select(Master).where(
                Master.telegram_id == master_telegram_id,
                Master.is_active.is_(True),
                Master.archived_at.is_(None),
            )
        )).scalar_one_or_none()
        if not master:
            return False, "Вы не зарегистрированы как мастер студии", None

        booking = (await session.execute(
            select(Booking)
            .options(
                selectinload(Booking.client_user),
                selectinload(Booking.master),
                selectinload(Booking.service),
            )
            .where(Booking.id == booking_id)
        )).scalar_one_or_none()
        if not booking:
            return False, "Запись не найдена", None

        if booking.status == "confirmed":
            if booking.master_id == master.id:
                return True, "Вы уже приняли эту запись", booking
            other_name = booking.master.full_name if booking.master else "другим мастером"
            return False, f"Заказ уже принят мастером {other_name}", booking

        if booking.status != "pending":
            return False, f"Невозможно принять заказ в статусе '{booking.status}'", booking

        if not booking.is_any_master and booking.master_id != master.id:
            return False, "Заказ оформлен к конкретному мастеру", booking

        # Check master conflict
        conflict = (await session.execute(
            select(Booking).where(
                Booking.id != booking.id,
                Booking.master_id == master.id,
                Booking.booking_date == booking.booking_date,
                Booking.status.in_(ACTIVE_BOOKING_STATUSES),
                Booking.start_time < booking.end_time,
                Booking.end_time > booking.start_time,
            )
        )).scalars().first()
        if conflict:
            return False, "У вас уже есть другая запись в это время", booking

        blocked = (await session.execute(
            select(BlockedInterval).where(
                BlockedInterval.master_id == master.id,
                BlockedInterval.booking_date == booking.booking_date,
                BlockedInterval.start_time < booking.end_time,
                BlockedInterval.end_time > booking.start_time,
            )
        )).scalars().first()
        if blocked:
            return False, f"На это время у вас установлен перерыв ({blocked.reason or 'перерыв'})", booking

        booking.master_id = master.id
        booking.status = "confirmed"
        booking.confirmed_at = datetime.now(timezone.utc)
        booking.assignment_deadline = None
        booking.client_reassign_deadline = None
        await session.commit()
        await session.refresh(booking)
        logger.info(f"Booking #{booking.id} claimed by master {master.full_name} (tg: {master_telegram_id})")
        return True, f"Вы успешно приняли заказ #{booking.id}!", booking


async def decline_booking_by_master(
    session: AsyncSession,
    booking_id: int,
    master_telegram_id: int,
) -> tuple[bool, str, Optional[Booking]]:
    async with _booking_lock:
        master = (await session.execute(
            select(Master).where(
                Master.telegram_id == master_telegram_id,
                Master.archived_at.is_(None),
            )
        )).scalar_one_or_none()
        if not master:
            return False, "Вы не зарегистрированы как мастер студии", None

        booking = (await session.execute(
            select(Booking)
            .options(
                selectinload(Booking.client_user),
                selectinload(Booking.master),
                selectinload(Booking.service),
            )
            .where(Booking.id == booking_id)
        )).scalar_one_or_none()
        if not booking:
            return False, "Запись не найдена", None

        if booking.status not in ("pending", "confirmed"):
            return False, f"Нельзя отклонить заказ в статусе '{booking.status}'", booking

        if booking.master_id != master.id:
            if booking.is_any_master:
                # Мастер не назначен персонально, но получил броадкаст и отказывается от заявки
                cur_declined = [int(x) for x in (booking.declined_master_ids or "").split(",") if x.strip().isdigit()]
                if master.id not in cur_declined:
                    cur_declined.append(master.id)
                booking.declined_master_ids = ",".join(str(x) for x in cur_declined)
                await session.commit()
                await session.refresh(booking)
                return True, "declined_broadcast", booking
            return False, "Вы не являетесь назначенным мастером этой записи", booking

        # Append master.id to declined list
        cur_declined = [int(x) for x in (booking.declined_master_ids or "").split(",") if x.strip().isdigit()]
        if master.id not in cur_declined:
            cur_declined.append(master.id)
        booking.declined_master_ids = ",".join(str(x) for x in cur_declined)
        booking.confirmed_at = None

        if booking.is_any_master:
            # "Любой мастер": return back to search among other free masters
            other_free = await get_free_active_masters(
                session,
                booking.booking_date,
                booking.start_time,
                booking.end_time,
                exclude_ids=cur_declined,
                exclude_booking_id=booking.id,
            )
            if other_free:
                booking.status = "pending"
                booking.assignment_deadline = calculate_assignment_deadline(booking.booking_date)
                booking.master_id = other_free[0].id
                await session.commit()
                await session.refresh(booking)
                logger.info(f"Master {master.full_name} declined booking #{booking.id} (any_master). Status: pending.")
                return True, "declined_any", booking
            else:
                booking.status = "cancelled_by_admin"
                booking.assignment_deadline = None
                await session.commit()
                await session.refresh(booking)
                logger.info(f"Master {master.full_name} declined booking #{booking.id} (any_master). No other free masters left. Status: cancelled_by_admin.")
                return True, "all_declined", booking
        else:
            # Specific master chosen by client: give client 10 minutes to choose another or auto-reassign
            booking.status = "awaiting_client_choice"
            booking.client_reassign_deadline = get_moscow_now() + timedelta(minutes=10)
            await session.commit()
            await session.refresh(booking)
            logger.info(f"Master {master.full_name} declined specific booking #{booking.id}. Status: awaiting_client_choice.")
            return True, "declined_specific", booking


async def client_accept_any_master(
    session: AsyncSession,
    booking_id: int,
    client_telegram_id: int,
) -> tuple[bool, str, Optional[Booking]]:
    async with _booking_lock:
        booking = (await session.execute(
            select(Booking)
            .options(
                selectinload(Booking.client_user),
                selectinload(Booking.master),
                selectinload(Booking.service),
            )
            .where(Booking.id == booking_id)
        )).scalar_one_or_none()
        if not booking:
            return False, "Запись не найдена", None

        if not booking.client_user or booking.client_user.telegram_id != client_telegram_id:
            return False, "Действие доступно только клиенту данной записи", None

        if booking.status != "awaiting_client_choice":
            return False, f"Нельзя перевести запись в поиск мастера из статуса '{booking.status}'", booking

        cur_declined = [int(x) for x in (booking.declined_master_ids or "").split(",") if x.strip().isdigit()]
        other_free = await get_free_active_masters(
            session,
            booking.booking_date,
            booking.start_time,
            booking.end_time,
            exclude_ids=cur_declined,
            exclude_booking_id=booking.id,
        )
        if not other_free:
            return False, "На выбранное время нет других свободных мастеров. Пожалуйста, выберите другое время или отмените запись.", booking

        booking.is_any_master = True
        booking.status = "pending"
        booking.client_reassign_deadline = None
        booking.assignment_deadline = calculate_assignment_deadline(booking.booking_date)
        booking.master_id = other_free[0].id

        await session.commit()
        await session.refresh(booking)
        logger.info(f"Client {client_telegram_id} accepted any master for booking #{booking.id}. Status: pending.")
        return True, "Поиск свободного мастера запущен!", booking


async def admin_reassign_booking(
    session: AsyncSession,
    booking_id: int,
    new_master_id: int,
    admin_telegram_id: int,
) -> Booking:
    if not settings.is_admin(admin_telegram_id):
        raise PermissionError("Действие разрешено только администраторам")

    async with _booking_lock:
        booking = (await session.execute(
            select(Booking)
            .options(
                selectinload(Booking.client_user),
                selectinload(Booking.master),
                selectinload(Booking.service),
            )
            .where(Booking.id == booking_id)
        )).scalar_one_or_none()
        if not booking:
            raise ValueError("Запись не найдена")

        if booking.status not in ("pending", "confirmed", "awaiting_client_choice"):
            raise ValueError(f"Невозможно переназначить запись в статусе '{booking.status}'")

        master = (await session.execute(
            select(Master).where(
                Master.id == new_master_id,
                Master.is_active.is_(True),
                Master.archived_at.is_(None),
            )
        )).scalar_one_or_none()
        if not master:
            raise ValueError("Мастер не найден")

        # Check if new master has conflicting active bookings
        conflict_stmt = select(Booking).where(
            Booking.id != booking.id,
            Booking.master_id == master.id,
            Booking.booking_date == booking.booking_date,
            Booking.status.in_(ACTIVE_BOOKING_STATUSES),
            Booking.start_time < booking.end_time,
            Booking.end_time > booking.start_time,
        )
        existing_conflict = (await session.execute(conflict_stmt)).scalars().first()
        if existing_conflict is not None:
            raise ValueError(f"Мастер {master.full_name} уже занят в это время (запись #{existing_conflict.id})")

        # Check if new master has conflicting blocked intervals
        block_stmt = select(BlockedInterval).where(
            BlockedInterval.master_id == master.id,
            BlockedInterval.booking_date == booking.booking_date,
            BlockedInterval.start_time < booking.end_time,
            BlockedInterval.end_time > booking.start_time,
        )
        existing_block = (await session.execute(block_stmt)).scalars().first()
        if existing_block is not None:
            raise ValueError(f"Мастер {master.full_name} имеет перерыв в это время ({existing_block.reason or 'перерыв'})")

        booking.master_id = master.id
        booking.status = "confirmed"
        booking.confirmed_at = datetime.now(timezone.utc)
        booking.client_reassign_deadline = None
        booking.assignment_deadline = None

        await session.commit()
        await session.refresh(booking)
        logger.info(f"Booking #{booking.id} manually reassigned to master {master.full_name} by admin {admin_telegram_id}")
        return booking


async def process_expired_bookings(session: AsyncSession, bot: Any) -> int:
    now_m = get_moscow_now()
    processed_count = 0
    notifications_to_send: List[Tuple[str, Dict[str, Any]]] = []

    async with _booking_lock:
        # 1. Process awaiting_client_choice where deadline expired -> broadcast to other free masters
        res_awaiting = await session.execute(
            select(Booking)
            .options(
                selectinload(Booking.client_user),
                selectinload(Booking.master),
                selectinload(Booking.service),
            )
            .where(
                Booking.status == "awaiting_client_choice",
                Booking.client_reassign_deadline.is_not(None),
                Booking.client_reassign_deadline <= now_m,
            )
        )
        awaiting_list = list(res_awaiting.scalars().all())
        for b in awaiting_list:
            cur_declined = [int(x) for x in (b.declined_master_ids or "").split(",") if x.strip().isdigit()]
            other_free = await get_free_active_masters(
                session,
                b.booking_date,
                b.start_time,
                b.end_time,
                exclude_ids=cur_declined,
                exclude_booking_id=b.id,
            )
            if other_free:
                b.is_any_master = True
                b.status = "pending"
                b.client_reassign_deadline = None
                b.assignment_deadline = calculate_assignment_deadline(b.booking_date)
                b.master_id = other_free[0].id
                await session.commit()
                await session.refresh(b)
                processed_count += 1
                logger.info(f"Booking #{b.id} client reassign deadline expired -> switched to pending broadcast")

                if bot:
                    notifications_to_send.append((
                        "awaiting_broadcast",
                        {
                            "booking_id": b.id,
                            "other_free": list(other_free),
                        },
                    ))
            else:
                b.status = "cancelled_by_admin"
                b.client_reassign_deadline = None
                b.assignment_deadline = None
                await session.commit()
                await session.refresh(b)
                processed_count += 1
                logger.warning(f"Booking #{b.id} client reassign deadline expired with no free masters. Status: cancelled_by_admin.")

                if bot:
                    notifications_to_send.append((
                        "unassigned_alert",
                        {
                            "booking_id": b.id,
                        },
                    ))

        # 2. Process pending bookings where assignment_deadline expired
        res_pending = await session.execute(
            select(Booking)
            .options(
                selectinload(Booking.client_user),
                selectinload(Booking.master),
                selectinload(Booking.service),
            )
            .where(
                Booking.status == "pending",
                Booking.assignment_deadline.is_not(None),
                Booking.assignment_deadline <= now_m,
            )
        )
        pending_list = list(res_pending.scalars().all())
        auto_assign_enabled = bool(settings.salon.get("auto_assign_on_timeout", True))

        for b in pending_list:
            cur_declined = [int(x) for x in (b.declined_master_ids or "").split(",") if x.strip().isdigit()]
            other_free = await get_free_active_masters(
                session,
                b.booking_date,
                b.start_time,
                b.end_time,
                exclude_ids=cur_declined,
                exclude_booking_id=b.id,
            )

            if auto_assign_enabled and other_free:
                best_master = other_free[0]
                b.master_id = best_master.id
                b.status = "confirmed"
                b.confirmed_at = datetime.now(timezone.utc)
                b.assignment_deadline = None
                await session.commit()
                await session.refresh(b, attribute_names=["master_id", "status", "confirmed_at", "assignment_deadline"])
                processed_count += 1
                logger.info(f"Booking #{b.id} auto-assigned to master {best_master.full_name} upon timeout")

                if bot:
                    notifications_to_send.append((
                        "auto_assigned",
                        {
                            "booking_id": b.id,
                            "best_master": best_master,
                            "client_telegram_id": b.client_user.telegram_id if b.client_user else None,
                        },
                    ))
            else:
                b.status = "cancelled_by_admin"
                b.assignment_deadline = None
                await session.commit()
                await session.refresh(b, attribute_names=["status", "assignment_deadline"])
                processed_count += 1
                logger.warning(f"Booking #{b.id} expired without auto-assignment. Cancelled and alerting owners.")
                if bot:
                    notifications_to_send.append((
                        "unassigned_alert",
                        {
                            "booking_id": b.id,
                        },
                    ))

    # Network I/O is performed completely outside _booking_lock to prevent blocking concurrent bookings
    if bot and notifications_to_send:
        from notifiers.booking_notifier import dispatch_expired_booking_notifications
        await dispatch_expired_booking_notifications(session, bot, notifications_to_send)

    return processed_count

