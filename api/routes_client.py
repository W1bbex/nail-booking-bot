from datetime import date, datetime, time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.booking_service import (
    cancel_booking,
    create_booking,
    get_available_slots,
    get_free_active_masters,
    record_booking_message,
    sync_booking_messages,
)
from core.config import settings
from core.database import get_db
from core.logger import setup_logger
from core.models import Booking, Master, Service, User
from core.security import get_current_user
from ui.dashboards import (
    notification_booking_cancelled,
    notification_client_booking_created,
    notification_new_booking,
)
from ui.keyboards import admin_notification_keyboard

logger = setup_logger("api.client")
router = APIRouter(prefix="/api", tags=["client"])

# Reference to global bot instance set on startup for live notifications
telegram_bot_instance = None


class BookingCreateRequest(BaseModel):
    master_id: int
    service_id: int
    date: str  # YYYY-MM-DD
    start_time: str  # HH:MM
    client_name: str = Field(min_length=2, max_length=100)
    client_phone: str = Field(min_length=6, max_length=30)
    comment: Optional[str] = None


@router.get("/salon")
async def get_salon_info() -> Dict[str, Any]:
    return {
        "salon": settings.salon,
        "booking_rules": settings.booking,
        "server": {
            "dev_mode": settings.dev_mode,
            "public_url": settings.public_url,
        },
    }


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return {
        "telegram_id": current_user.telegram_id,
        "full_name": current_user.full_name,
        "phone": current_user.phone,
        "role": current_user.role,
        "is_admin": settings.is_admin(current_user.telegram_id),
    }


@router.get("/services")
async def list_services(db: AsyncSession = Depends(get_db)) -> List[Dict[str, Any]]:
    res = await db.execute(
        select(Service)
        .where(Service.is_active.is_(True), Service.archived_at.is_(None))
        .order_by(Service.category, Service.price)
    )
    services = res.scalars().all()
    return [
        {
            "id": s.id,
            "category": s.category,
            "name": s.name,
            "description": s.description,
            "duration_minutes": s.duration_minutes,
            "price": s.price,
        }
        for s in services
    ]


@router.get("/masters")
async def list_masters(db: AsyncSession = Depends(get_db)) -> List[Dict[str, Any]]:
    res = await db.execute(
        select(Master)
        .where(Master.is_active.is_(True), Master.archived_at.is_(None))
        .order_by(Master.id)
    )
    masters = res.scalars().all()
    return [
        {
            "id": m.id,
            "full_name": m.full_name,
            "specialization": m.specialization,
            "experience_years": m.experience_years,
        }
        for m in masters
    ]


@router.get("/slots")
async def list_available_slots(
    master_id: int = Query(...),
    service_id: int = Query(...),
    date_str: str = Query(..., alias="date"),
    include_unavailable: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный формат даты, ожидается ГГГГ-ММ-ДД")

    slots = await get_available_slots(
        session=db,
        master_id=master_id,
        service_id=service_id,
        target_date=target_date,
        include_unavailable=include_unavailable,
    )
    return slots


@router.post("/bookings")
async def api_create_booking(
    payload: BookingCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        b_date = datetime.strptime(payload.date, "%Y-%m-%d").date()
        parts = [int(x) for x in payload.start_time.split(":")]
        b_time = time(parts[0], parts[1])
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка в формате даты или времени: {e}")

    try:
        booking = await create_booking(
            session=db,
            client_telegram_id=current_user.telegram_id,
            client_name=payload.client_name,
            client_phone=payload.client_phone,
            master_id=payload.master_id,
            service_id=payload.service_id,
            booking_date=b_date,
            start_time=b_time,
            comment=payload.comment,
        )

        # Reload booking with relations for notifications and safe response serialization
        res = await db.execute(
            select(Booking)
            .options(selectinload(Booking.master), selectinload(Booking.service))
            .where(Booking.id == booking.id)
        )
        full_booking = res.scalar_one_or_none() or booking

        # Notify salon admins via Telegram Bot if running
        global telegram_bot_instance
        if telegram_bot_instance and full_booking:
            try:
                # 1. Alert salon admins with interactive action keyboard
                msg_text = notification_new_booking(full_booking)
                kb = admin_notification_keyboard(full_booking.id)
                for admin_id in settings.admin_telegram_ids:
                    try:
                        sent_msg = await telegram_bot_instance.send_message(
                            chat_id=admin_id,
                            text=msg_text,
                            reply_markup=kb,
                            parse_mode="HTML",
                        )
                        msg_id = getattr(sent_msg, "message_id", None)
                        if isinstance(msg_id, int):
                            await record_booking_message(
                                db,
                                full_booking.id,
                                admin_id,
                                msg_id,
                                "admin_card",
                            )
                    except Exception as admin_err:
                        logger.warning(f"Failed to alert admin {admin_id}: {admin_err}")

                # 2. Dispatch to masters
                if full_booking.is_any_master:
                    # Broadcast "Любой мастер" order to all free masters with Telegram
                    from ui.dashboards import master_order_broadcast_card
                    from ui.keyboards import master_claim_keyboard
                    free_masters = await get_free_active_masters(
                        db, full_booking.booking_date, full_booking.start_time, full_booking.end_time
                    )
                    broadcast_text = master_order_broadcast_card(full_booking)
                    claim_kb = master_claim_keyboard(full_booking.id)
                    for fm in free_masters:
                        if fm.telegram_id and fm.telegram_id not in settings.admin_telegram_ids:
                            try:
                                s_msg = await telegram_bot_instance.send_message(
                                    chat_id=fm.telegram_id,
                                    text=broadcast_text,
                                    reply_markup=claim_kb,
                                    parse_mode="HTML",
                                )
                                await record_booking_message(
                                    db,
                                    full_booking.id,
                                    fm.telegram_id,
                                    s_msg.message_id,
                                    "master_claim",
                                )
                            except Exception as m_err:
                                logger.warning(f"Failed to broadcast to master {fm.full_name}: {m_err}")
                elif full_booking.master and full_booking.master.telegram_id and full_booking.master.telegram_id not in settings.admin_telegram_ids:
                    # Alert specifically chosen master
                    from ui.dashboards import master_assigned_card
                    from ui.keyboards import master_assigned_keyboard
                    try:
                        s_msg = await telegram_bot_instance.send_message(
                            chat_id=full_booking.master.telegram_id,
                            text=master_assigned_card(full_booking, is_auto=False),
                            reply_markup=master_assigned_keyboard(full_booking.id),
                            parse_mode="HTML",
                        )
                        await record_booking_message(
                            db,
                            full_booking.id,
                            full_booking.master.telegram_id,
                            s_msg.message_id,
                            "master_card",
                        )
                    except Exception as m_err:
                        logger.warning(f"Failed to alert assigned master: {m_err}")

                # 3. Send instant receipt/confirmation directly to the client
                if current_user and current_user.telegram_id:
                    try:
                        client_msg = notification_client_booking_created(full_booking)
                        await telegram_bot_instance.send_message(
                            chat_id=current_user.telegram_id,
                            text=client_msg,
                            parse_mode="HTML",
                        )
                    except Exception as client_err:
                        logger.warning(f"Failed to send confirmation to client: {client_err}")
            except Exception as notify_err:
                logger.warning(f"Notification error: {notify_err}")

        master_info = None
        if full_booking and full_booking.master:
            master_info = {
                "id": full_booking.master.id,
                "full_name": full_booking.master.full_name,
            }

        return {
            "success": True,
            "booking_id": booking.id,
            "status": booking.status,
            "master": master_info,
            "message": "Заявка на запись успешно оформлена",
        }
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err))
    except Exception as exc:
        logger.exception("Failed to create booking")
        raise HTTPException(status_code=500, detail="Внутренняя ошибка сервера. Пожалуйста, попробуйте позже.")


@router.get("/bookings")
async def list_my_bookings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    res = await db.execute(
        select(Booking)
        .options(selectinload(Booking.service), selectinload(Booking.master))
        .where(Booking.client_user_id == current_user.id)
        .order_by(desc(Booking.booking_date), desc(Booking.start_time))
    )
    bookings = res.scalars().all()
    return [
        {
            "id": b.id,
            "date": b.booking_date.strftime("%Y-%m-%d"),
            "start_time": b.start_time.strftime("%H:%M"),
            "end_time": b.end_time.strftime("%H:%M"),
            "status": b.status,
            "service_name": b.service.name if b.service else "",
            "service_duration": b.service.duration_minutes if b.service else 60,
            "service_price": b.price if b.price is not None else (b.service.price if b.service else 0.0),
            "master_name": b.master.full_name if b.master else "",
            "comment": b.comment,
        }
        for b in bookings
    ]


@router.post("/bookings/{booking_id}/cancel")
async def api_cancel_booking(
    booking_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        booking = await cancel_booking(
            session=db,
            booking_id=booking_id,
            actor_telegram_id=current_user.telegram_id,
            is_admin_action=settings.is_admin(current_user.telegram_id),
        )

        # Notify admins and client via Telegram Bot
        global telegram_bot_instance
        if telegram_bot_instance:
            await sync_booking_messages(db, telegram_bot_instance, booking.id)
            try:
                actor_role = "admin" if settings.is_admin(current_user.telegram_id) else "client"
                cancel_msg = notification_booking_cancelled(booking, actor_role)
                for admin_id in settings.admin_telegram_ids:
                    try:
                        await telegram_bot_instance.send_message(
                            chat_id=admin_id,
                            text=cancel_msg,
                            parse_mode="HTML",
                        )
                    except Exception as admin_err:
                        logger.warning(f"Failed to alert admin {admin_id} on cancellation: {admin_err}")

                if booking.client_user and booking.client_user.telegram_id and booking.client_user.telegram_id > 0:
                    try:
                        await telegram_bot_instance.send_message(
                            chat_id=booking.client_user.telegram_id,
                            text=cancel_msg,
                            parse_mode="HTML",
                        )
                    except Exception as client_err:
                        logger.warning(f"Failed to alert client on cancellation: {client_err}")
            except Exception as notify_err:
                logger.warning(f"Cancellation notification error: {notify_err}")

        return {
            "success": True,
            "booking_id": booking.id,
            "status": booking.status,
            "message": "Запись успешно отменена",
        }
    except (ValueError, PermissionError) as e:
        raise HTTPException(status_code=400, detail=str(e))
