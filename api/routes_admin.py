from datetime import date, datetime, time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.booking_notifier import sync_booking_messages
from core.booking_service import (
    cancel_booking,
    complete_booking,
    confirm_booking,
    create_booking,
    get_moscow_now,
)
from core.catalog_service import (
    block_time_interval,
    create_master,
    create_service,
    delete_master,
    delete_service,
    get_all_masters,
    get_all_services,
    toggle_master_active,
    toggle_service_active,
    unblock_time_interval,
    update_master,
    update_salon_settings,
    update_service,
    update_service_price,
)
from core.config import settings
from core.database import get_db
from core.logger import setup_logger
from core.models import BlockedInterval, Booking, Master, Service, User
from core.security import require_admin
from ui.dashboards import notification_booking_cancelled, notification_booking_confirmed

logger = setup_logger("api.admin")
router = APIRouter(prefix="/api/admin", tags=["admin"])


class BlockIntervalRequest(BaseModel):
    master_id: int
    date: str  # YYYY-MM-DD
    start_time: str  # HH:MM
    end_time: str  # HH:MM
    reason: Optional[str] = "Технический перерыв"


@router.get("/schedule")
async def get_admin_schedule(
    date_str: Optional[str] = Query(None, alias="date"),
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Неверный формат даты")
    else:
        target_date = get_moscow_now().date()

    # Fetch bookings with client and service relations
    res_b = await db.execute(
        select(Booking)
        .options(selectinload(Booking.master), selectinload(Booking.service), selectinload(Booking.client_user))
        .where(Booking.booking_date == target_date)
        .order_by(Booking.start_time)
    )
    bookings = res_b.scalars().all()

    # Calculate rich statistics using snapshotted booking price
    revenue = sum(
        (b.price if (b.price is not None and b.price > 0) else (b.service.price if b.service else 0.0))
        for b in bookings
        if b.status in ("confirmed", "completed")
    )
    expected_revenue = sum(
        (b.price if (b.price is not None and b.price > 0) else (b.service.price if b.service else 0.0))
        for b in bookings
        if b.status in ("confirmed", "completed", "pending")
    )
    total_count = len(bookings)
    pending_count = sum(1 for b in bookings if b.status == "pending")
    confirmed_count = sum(1 for b in bookings if b.status == "confirmed")
    completed_count = sum(1 for b in bookings if b.status == "completed")
    cancelled_count = sum(1 for b in bookings if b.status.startswith("cancelled"))
    avg_check = round(revenue / (completed_count + confirmed_count), 0) if (completed_count + confirmed_count) > 0 else 0

    # Fetch blocked intervals
    res_blk = await db.execute(
        select(BlockedInterval)
        .options(selectinload(BlockedInterval.master))
        .where(BlockedInterval.booking_date == target_date)
        .order_by(BlockedInterval.start_time)
    )
    blocks = res_blk.scalars().all()

    return {
        "date": target_date.strftime("%Y-%m-%d"),
        "stats": {
            "revenue": revenue,
            "expected_revenue": expected_revenue,
            "total": total_count,
            "pending": pending_count,
            "confirmed": confirmed_count,
            "completed": completed_count,
            "cancelled": cancelled_count,
            "avg_check": avg_check,
        },
        "bookings": [
            {
                "id": b.id,
                "start_time": b.start_time.strftime("%H:%M"),
                "end_time": b.end_time.strftime("%H:%M"),
                "status": b.status,
                "client_name": b.client_name,
                "client_phone": b.client_phone,
                "client_telegram_id": b.client_user.telegram_id if b.client_user else None,
                "service_name": b.service.name if b.service else "",
                "service_price": b.price if (b.price is not None and b.price > 0) else (b.service.price if b.service else 0.0),
                "master_id": b.master_id,
                "master_name": b.master.full_name if b.master else "",
                "comment": b.comment,
            }
            for b in bookings
        ],
        "blocked_intervals": [
            {
                "id": blk.id,
                "master_id": blk.master_id,
                "master_name": blk.master.full_name if blk.master else "",
                "start_time": blk.start_time.strftime("%H:%M"),
                "end_time": blk.end_time.strftime("%H:%M"),
                "reason": blk.reason,
            }
            for blk in blocks
        ],
    }


@router.get("/bookings")
async def list_admin_bookings(
    status_filter: Optional[str] = Query(None, alias="status"),
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    stmt = (
        select(Booking)
        .options(selectinload(Booking.master), selectinload(Booking.service), selectinload(Booking.client_user))
        .order_by(desc(Booking.booking_date), desc(Booking.start_time))
    )
    if status_filter:
        stmt = stmt.where(Booking.status == status_filter)

    res = await db.execute(stmt)
    bookings = res.scalars().all()

    return [
        {
            "id": b.id,
            "date": b.booking_date.strftime("%Y-%m-%d"),
            "start_time": b.start_time.strftime("%H:%M"),
            "end_time": b.end_time.strftime("%H:%M"),
            "status": b.status,
            "client_name": b.client_name,
            "client_phone": b.client_phone,
            "client_telegram_id": b.client_user.telegram_id if b.client_user else None,
            "master_id": b.master_id,
            "master_name": b.master.full_name if b.master else "",
            "service_name": b.service.name if b.service else "",
            "service_price": b.price if (b.price is not None and b.price > 0) else (b.service.price if b.service else 0.0),
            "comment": b.comment,
            "created_at": b.created_at.isoformat() if b.created_at else None,
        }
        for b in bookings
    ]


@router.post("/bookings/{booking_id}/confirm")
async def api_admin_confirm(
    booking_id: int,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        booking = await confirm_booking(db, booking_id, admin_user.telegram_id)
        from api.routes_client import telegram_bot_instance
        if telegram_bot_instance:
            await sync_booking_messages(db, telegram_bot_instance, booking.id)
            if booking.client_user and booking.client_user.telegram_id and booking.client_user.telegram_id > 0:
                try:
                    msg = notification_booking_confirmed(booking)
                    await telegram_bot_instance.send_message(
                        chat_id=booking.client_user.telegram_id,
                        text=msg,
                        parse_mode="HTML",
                    )
                except Exception as notify_err:
                    logger.warning(f"Failed to notify client: {notify_err}")

        return {"success": True, "booking_id": booking.id, "status": booking.status}
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/bookings/{booking_id}/cancel")
async def api_admin_cancel(
    booking_id: int,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        booking = await cancel_booking(db, booking_id, admin_user.telegram_id, is_admin_action=True)
        from api.routes_client import telegram_bot_instance
        if telegram_bot_instance:
            await sync_booking_messages(db, telegram_bot_instance, booking.id)
            if booking.client_user and booking.client_user.telegram_id and booking.client_user.telegram_id > 0:
                try:
                    msg = notification_booking_cancelled(booking, "admin")
                    await telegram_bot_instance.send_message(
                        chat_id=booking.client_user.telegram_id,
                        text=msg,
                        parse_mode="HTML",
                    )
                except Exception as notify_err:
                    logger.warning(f"Failed to notify client: {notify_err}")

        return {"success": True, "booking_id": booking.id, "status": booking.status}
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/bookings/{booking_id}/complete")
async def api_admin_complete(
    booking_id: int,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        booking = await complete_booking(db, booking_id, admin_user.telegram_id)
        from api.routes_client import telegram_bot_instance
        if telegram_bot_instance:
            await sync_booking_messages(db, telegram_bot_instance, booking.id)
        return {"success": True, "booking_id": booking.id, "status": booking.status}
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/block/{interval_id}")
async def api_admin_unblock(
    interval_id: int,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        interval = await unblock_time_interval(db, interval_id, admin_user.telegram_id)
        return {"success": True, "id": interval.id, "message": "Интервал успешно разблокирован"}
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/block")
async def api_admin_block(
    payload: BlockIntervalRequest,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        b_date = datetime.strptime(payload.date, "%Y-%m-%d").date()
        st = datetime.strptime(payload.start_time, "%H:%M").time()
        et = datetime.strptime(payload.end_time, "%H:%M").time()
    except (ValueError, TypeError) as parse_err:
        raise HTTPException(
            status_code=400,
            detail=f"Некорректный формат даты или времени: {parse_err}",
        )

    try:
        if payload.master_id == 0:
            masters = await get_all_masters(db, include_inactive=False)
            if not masters:
                raise ValueError("Нет активных мастеров для блокировки времени")
            created_ids = []
            for m in masters:
                interval = await block_time_interval(
                    session=db,
                    master_id=m.id,
                    block_date=b_date,
                    start_time=st,
                    end_time=et,
                    reason=payload.reason,
                    admin_telegram_id=admin_user.telegram_id,
                )
                created_ids.append(interval.id)
            return {
                "success": True,
                "id": created_ids[0],
                "ids": created_ids,
                "master_id": 0,
                "date": b_date.strftime("%Y-%m-%d"),
                "start_time": st.strftime("%H:%M"),
                "end_time": et.strftime("%H:%M"),
                "reason": payload.reason,
            }

        interval = await block_time_interval(
            session=db,
            master_id=payload.master_id,
            block_date=b_date,
            start_time=st,
            end_time=et,
            reason=payload.reason,
            admin_telegram_id=admin_user.telegram_id,
        )
        return {
            "success": True,
            "id": interval.id,
            "master_id": interval.master_id,
            "date": interval.booking_date.strftime("%Y-%m-%d"),
            "start_time": interval.start_time.strftime("%H:%M"),
            "end_time": interval.end_time.strftime("%H:%M"),
            "reason": interval.reason,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/services")
async def list_admin_services(
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    services = await get_all_services(db, include_inactive=True)
    return [
        {
            "id": s.id,
            "category": s.category,
            "name": s.name,
            "description": s.description,
            "duration_minutes": s.duration_minutes,
            "price": s.price,
            "is_active": s.is_active,
        }
        for s in services
    ]


@router.post("/services/{service_id}/toggle")
async def api_admin_toggle_service(
    service_id: int,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        service = await toggle_service_active(db, service_id, admin_user.telegram_id)
        return {
            "success": True,
            "id": service.id,
            "name": service.name,
            "is_active": service.is_active,
        }
    except (ValueError, PermissionError) as e:
        raise HTTPException(status_code=400, detail=str(e))


class ServiceCreateRequest(BaseModel):
    category: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    description: Optional[str] = None
    duration_minutes: int = Field(default=60, ge=15, le=360)
    price: float = Field(default=0.0, ge=0.0)
    is_active: bool = True


class ServiceUpdateRequest(BaseModel):
    category: Optional[str] = Field(None, max_length=80)
    name: Optional[str] = Field(None, max_length=160)
    description: Optional[str] = None
    duration_minutes: Optional[int] = Field(None, ge=15, le=360)
    price: Optional[float] = Field(None, ge=0.0)
    is_active: Optional[bool] = None


@router.post("/services")
async def api_admin_create_service(
    payload: ServiceCreateRequest,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        service = await create_service(
            session=db,
            category=payload.category,
            name=payload.name,
            description=payload.description,
            duration_minutes=payload.duration_minutes,
            price=payload.price,
            is_active=payload.is_active,
            admin_telegram_id=admin_user.telegram_id,
        )
        return {
            "success": True,
            "id": service.id,
            "category": service.category,
            "name": service.name,
            "description": service.description,
            "duration_minutes": service.duration_minutes,
            "price": service.price,
            "is_active": service.is_active,
        }
    except (ValueError, PermissionError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/services/{service_id}")
async def api_admin_update_service(
    service_id: int,
    payload: ServiceUpdateRequest,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        service = await update_service(
            session=db,
            service_id=service_id,
            category=payload.category,
            name=payload.name,
            description=payload.description,
            duration_minutes=payload.duration_minutes,
            price=payload.price,
            is_active=payload.is_active,
            admin_telegram_id=admin_user.telegram_id,
        )
        return {
            "success": True,
            "id": service.id,
            "category": service.category,
            "name": service.name,
            "description": service.description,
            "duration_minutes": service.duration_minutes,
            "price": service.price,
            "is_active": service.is_active,
        }
    except (ValueError, PermissionError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/services/{service_id}")
async def api_admin_delete_service(
    service_id: int,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        service = await delete_service(db, service_id, admin_user.telegram_id)
        return {
            "success": True,
            "id": service.id,
            "name": service.name,
            "message": f"Услуга «{service.name}» удалена",
        }
    except (ValueError, PermissionError) as e:
        raise HTTPException(status_code=400, detail=str(e))


class MasterCreateRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    specialization: str = Field(default="", max_length=200)
    experience_years: int = Field(default=3, ge=0, le=50)
    is_active: bool = True
    telegram_username: Optional[str] = Field(None, max_length=80)


class MasterUpdateRequest(BaseModel):
    full_name: Optional[str] = Field(None, max_length=120)
    specialization: Optional[str] = Field(None, max_length=200)
    experience_years: Optional[int] = Field(None, ge=0, le=50)
    is_active: Optional[bool] = None
    telegram_username: Optional[str] = Field(None, max_length=80)


@router.get("/masters")
async def list_admin_masters(
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    masters = await get_all_masters(db, include_inactive=True)
    return [
        {
            "id": m.id,
            "full_name": m.full_name,
            "specialization": m.specialization,
            "experience_years": m.experience_years,
            "is_active": m.is_active,
            "telegram_username": m.telegram_username,
            "telegram_id": m.telegram_id,
        }
        for m in masters
    ]


@router.post("/masters")
async def api_admin_create_master(
    payload: MasterCreateRequest,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        master = await create_master(
            session=db,
            full_name=payload.full_name,
            specialization=payload.specialization,
            experience_years=payload.experience_years,
            is_active=payload.is_active,
            telegram_username=payload.telegram_username,
            admin_telegram_id=admin_user.telegram_id,
        )
        return {
            "success": True,
            "id": master.id,
            "full_name": master.full_name,
            "specialization": master.specialization,
            "experience_years": master.experience_years,
            "is_active": master.is_active,
            "telegram_username": master.telegram_username,
        }
    except (ValueError, PermissionError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/masters/{master_id}")
async def api_admin_update_master(
    master_id: int,
    payload: MasterUpdateRequest,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        master = await update_master(
            session=db,
            master_id=master_id,
            full_name=payload.full_name,
            specialization=payload.specialization,
            experience_years=payload.experience_years,
            is_active=payload.is_active,
            telegram_username=payload.telegram_username,
            admin_telegram_id=admin_user.telegram_id,
        )
        return {
            "success": True,
            "id": master.id,
            "full_name": master.full_name,
            "specialization": master.specialization,
            "experience_years": master.experience_years,
            "is_active": master.is_active,
            "telegram_username": master.telegram_username,
        }
    except (ValueError, PermissionError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/masters/{master_id}/toggle")
async def api_admin_toggle_master(
    master_id: int,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        master = await toggle_master_active(db, master_id, admin_user.telegram_id)
        return {
            "success": True,
            "id": master.id,
            "full_name": master.full_name,
            "is_active": master.is_active,
        }
    except (ValueError, PermissionError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/masters/{master_id}")
async def api_admin_delete_master(
    master_id: int,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        master = await delete_master(db, master_id, admin_user.telegram_id)
        return {
            "success": True,
            "id": master.id,
            "full_name": master.full_name,
            "message": f"Мастер «{master.full_name}» удалён",
        }
    except (ValueError, PermissionError) as e:
        raise HTTPException(status_code=400, detail=str(e))


class SalonSettingsUpdateRequest(BaseModel):
    name: Optional[str] = None
    tagline: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    working_hours: Optional[str] = None
    description: Optional[str] = None
    contact_telegram: Optional[str] = None
    landmark: Optional[str] = None
    socials: Optional[str] = None
    timezone: Optional[str] = None
    timeout_today_minutes: Optional[int] = None
    timeout_future_minutes: Optional[int] = None
    auto_assign_on_timeout: Optional[bool] = None


@router.get("/salon")
async def api_admin_get_salon(
    admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    return {"salon": settings.salon}


@router.put("/salon")
async def api_admin_update_salon(
    payload: SalonSettingsUpdateRequest,
    admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    update_data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="Нет данных для обновления")
    try:
        updated = update_salon_settings(update_data)
        return {"success": True, "salon": updated}
    except Exception as e:
        logger.exception("Failed to update salon settings")
        raise HTTPException(status_code=500, detail="Внутренняя ошибка сервера при сохранении настроек.")


class UpdatePriceRequest(BaseModel):
    price: float = Field(..., gt=0)


@router.post("/services/{service_id}/price")
async def api_admin_update_service_price(
    service_id: int,
    payload: UpdatePriceRequest,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        service = await update_service_price(db, service_id, payload.price, admin_user.telegram_id)
        return {
            "success": True,
            "id": service.id,
            "name": service.name,
            "price": service.price,
        }
    except (ValueError, PermissionError) as e:
        raise HTTPException(status_code=400, detail=str(e))


class AdminManualBookingRequest(BaseModel):
    master_id: int
    service_id: int
    date: str  # YYYY-MM-DD
    start_time: str  # HH:MM
    client_name: str
    client_phone: str
    comment: Optional[str] = "Создано администратором через Mini App"


@router.post("/manual-booking")
async def api_admin_manual_booking(
    payload: AdminManualBookingRequest,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        b_date = datetime.strptime(payload.date, "%Y-%m-%d").date()
        st_parts = [int(x) for x in payload.start_time.split(":")]
        b_time = time(st_parts[0], st_parts[1])
    except (ValueError, IndexError, TypeError) as parse_err:
        raise HTTPException(status_code=400, detail=f"Некорректная дата или время: {parse_err}")

    clean_phone = payload.client_phone.strip()
    clean_name = payload.client_name.strip() or "Клиент"

    try:
        existing_client = (await db.execute(
            select(User).where(User.phone == clean_phone)
        )).scalars().first()
        from core.security import deterministic_virtual_telegram_id
        target_tg_id = existing_client.telegram_id if existing_client else deterministic_virtual_telegram_id(clean_phone)

        booking = await create_booking(
            session=db,
            client_telegram_id=target_tg_id,
            client_name=clean_name,
            client_phone=clean_phone,
            master_id=payload.master_id,
            service_id=payload.service_id,
            booking_date=b_date,
            start_time=b_time,
            comment=payload.comment,
            ignore_lead_time=True,
        )
        confirmed_booking = await confirm_booking(db, booking.id, admin_user.telegram_id)

        from api.routes_client import telegram_bot_instance
        if telegram_bot_instance:
            try:
                res = await db.execute(
                    select(Booking)
                    .options(selectinload(Booking.master), selectinload(Booking.service))
                    .where(Booking.id == booking.id)
                )
                full_booking = res.scalar_one_or_none()
                if full_booking:
                    admin_msg = notification_booking_confirmed(full_booking)
                    for aid in settings.admin_telegram_ids:
                        if aid != admin_user.telegram_id:
                            try:
                                await telegram_bot_instance.send_message(aid, admin_msg, parse_mode="HTML")
                            except Exception:
                                pass
            except Exception as notify_err:
                logger.warning(f"Failed to send admin notification: {notify_err}")

        return {
            "success": True,
            "booking_id": confirmed_booking.id,
            "status": confirmed_booking.status,
            "message": "Клиент успешно записан",
        }
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err))
    except Exception as exc:
        logger.exception("Manual booking creation failed")
        raise HTTPException(status_code=500, detail="Внутренняя ошибка сервера при создании записи.")
