import asyncio
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.config import settings
from core.logger import setup_logger
from core.models import Booking, BookingMessage

logger = setup_logger("booking_notifier")


async def record_booking_message(
    session: AsyncSession,
    booking_id: int,
    chat_id: int,
    message_id: int,
    kind: str = "admin_card",
) -> BookingMessage:
    entry = BookingMessage(
        booking_id=booking_id,
        chat_id=chat_id,
        message_id=message_id,
        kind=kind,
    )
    session.add(entry)
    await session.commit()
    return entry


async def sync_booking_messages(
    session: AsyncSession,
    bot: Any,
    booking_id: int,
) -> None:
    if not bot:
        return

    from ui.dashboards import admin_booking_card
    from ui.keyboards import admin_booking_keyboard, master_claim_keyboard, master_assigned_keyboard

    res = await session.execute(
        select(Booking)
        .options(
            selectinload(Booking.client_user),
            selectinload(Booking.master),
            selectinload(Booking.service),
        )
        .where(Booking.id == booking_id)
    )
    booking = res.scalar_one_or_none()
    if not booking:
        return

    msgs_res = await session.execute(
        select(BookingMessage).where(BookingMessage.booking_id == booking_id)
    )
    tracked_msgs = list(msgs_res.scalars().all())
    if not tracked_msgs:
        return

    status_titles = {
        "confirmed": f"<b>Заявка #{booking.id} подтверждена!</b>",
        "completed": f"<b>Визит #{booking.id} успешно завершён и оплачен!</b>",
        "cancelled_by_admin": f"<b>Заявка #{booking.id} отменена администратором</b>",
        "cancelled_by_client": f"<b>Заявка #{booking.id} отменена клиентом</b>",
        "awaiting_client_choice": f"<b>Заявка #{booking.id} ожидает решения клиента</b>",
        "pending": f"<b>НОВАЯ ЗАЯВКА НА ЗАПИСЬ #{booking.id}</b>",
    }
    header = status_titles.get(booking.status, f"<b>КАРТОЧКА ЗАПИСИ #{booking.id}</b>")
    card_text = f"{header}\n\n{admin_booking_card(booking)}"

    for tm in tracked_msgs:
        try:
            if tm.kind == "admin_card":
                kb = admin_booking_keyboard(
                    booking.id,
                    booking.status,
                    client_telegram_id=booking.client_user.telegram_id if booking.client_user else None,
                )
                await bot.edit_message_text(
                    chat_id=tm.chat_id,
                    message_id=tm.message_id,
                    text=card_text,
                    reply_markup=kb,
                    parse_mode="HTML",
                )
            elif tm.kind == "master_claim":
                if booking.status == "confirmed":
                    if booking.master and booking.master.telegram_id == tm.chat_id:
                        assigned_text = (
                            f"<b>ВЫ ЗАКРЕПЛЕНЫ ЗА ЗАКАЗОМ #{booking.id}</b>\n\n"
                            f"{admin_booking_card(booking)}"
                        )
                        kb = master_assigned_keyboard(booking.id)
                        await bot.edit_message_text(
                            chat_id=tm.chat_id,
                            message_id=tm.message_id,
                            text=assigned_text,
                            reply_markup=kb,
                            parse_mode="HTML",
                        )
                    else:
                        m_name = booking.master.full_name if booking.master else "другим мастером"
                        claimed_text = (
                            f"<b>ЗАКАЗ #{booking.id} УЖЕ ПРИНЯТ</b>\n\n"
                            f"Заказ закреплён за мастером: <b>{m_name}</b>\n\n"
                            f"{admin_booking_card(booking)}"
                        )
                        await bot.edit_message_text(
                            chat_id=tm.chat_id,
                            message_id=tm.message_id,
                            text=claimed_text,
                            reply_markup=None,
                            parse_mode="HTML",
                        )
                elif booking.status in ("cancelled_by_admin", "cancelled_by_client"):
                    cancel_text = f"<b>ЗАКАЗ #{booking.id} ОТМЕНЕН</b>\n\n{admin_booking_card(booking)}"
                    await bot.edit_message_text(
                        chat_id=tm.chat_id,
                        message_id=tm.message_id,
                        text=cancel_text,
                        reply_markup=None,
                        parse_mode="HTML",
                    )
                elif booking.status == "awaiting_client_choice":
                    await_text = (
                        f"<b>ЗАКАЗ #{booking.id} ОЖИДАЕТ РЕШЕНИЯ КЛИЕНТА</b>\n\n"
                        f"Клиенту предложен выбор другого мастера.\n\n"
                        f"{admin_booking_card(booking)}"
                    )
                    await bot.edit_message_text(
                        chat_id=tm.chat_id,
                        message_id=tm.message_id,
                        text=await_text,
                        reply_markup=None,
                        parse_mode="HTML",
                    )
                elif booking.status == "completed":
                    done_text = f"<b>ЗАКАЗ #{booking.id} ЗАВЕРШЕН</b>\n\n{admin_booking_card(booking)}"
                    await bot.edit_message_text(
                        chat_id=tm.chat_id,
                        message_id=tm.message_id,
                        text=done_text,
                        reply_markup=None,
                        parse_mode="HTML",
                    )
                else:
                    # Still pending
                    claim_text = f"<b>СВОБОДНЫЙ ЗАКАЗ #{booking.id}</b>\n\n{admin_booking_card(booking)}"
                    kb = master_claim_keyboard(booking.id)
                    await bot.edit_message_text(
                        chat_id=tm.chat_id,
                        message_id=tm.message_id,
                        text=claim_text,
                        reply_markup=kb,
                        parse_mode="HTML",
                    )
        except Exception as e:
            logger.debug(f"Could not sync booking message {tm.message_id} in chat {tm.chat_id}: {e}")


async def dispatch_expired_booking_notifications(
    session: AsyncSession,
    bot: Any,
    notifications_to_send: List[Tuple[str, Dict[str, Any]]],
) -> None:
    if not bot or not notifications_to_send:
        return

    from ui.dashboards import (
        master_order_broadcast_card,
        master_assigned_card,
        notification_booking_confirmed,
    )
    from ui.keyboards import master_claim_keyboard, master_assigned_keyboard

    for action_type, payload in notifications_to_send:
        booking_id = payload["booking_id"]
        try:
            await sync_booking_messages(session, bot, booking_id)
        except Exception as e:
            logger.error(f"Failed to sync booking messages for #{booking_id}: {e}", exc_info=True)

        # Load refreshed booking object for rendering message cards
        res_b = await session.execute(
            select(Booking)
            .options(
                selectinload(Booking.client_user),
                selectinload(Booking.master),
                selectinload(Booking.service),
            )
            .where(Booking.id == booking_id)
        )
        b = res_b.scalar_one_or_none()
        if not b:
            continue

        if action_type == "awaiting_broadcast":
            other_free = payload.get("other_free", [])
            claim_text = master_order_broadcast_card(b)
            claim_kb = master_claim_keyboard(b.id)
            for m in other_free:
                if m.telegram_id:
                    try:
                        s_msg = await bot.send_message(m.telegram_id, claim_text, reply_markup=claim_kb, parse_mode="HTML")
                        await record_booking_message(session, b.id, m.telegram_id, s_msg.message_id, "master_claim")
                    except Exception as e:
                        logger.error(
                            f"Failed to send broadcast claim to master {m.id} ({m.telegram_id}) for booking #{b.id}: {e}",
                            exc_info=True,
                        )

        elif action_type == "auto_assigned":
            best_master = payload["best_master"]
            client_telegram_id = payload.get("client_telegram_id")

            if best_master.telegram_id:
                try:
                    m_text = master_assigned_card(b, is_auto=True)
                    m_kb = master_assigned_keyboard(b.id)
                    await bot.send_message(best_master.telegram_id, m_text, reply_markup=m_kb, parse_mode="HTML")
                except Exception as e:
                    logger.error(
                        f"Failed to notify master {best_master.id} ({best_master.telegram_id}) of auto-assignment for booking #{b.id}: {e}",
                        exc_info=True,
                    )

            if client_telegram_id and client_telegram_id > 0:
                try:
                    c_text = notification_booking_confirmed(b)
                    await bot.send_message(client_telegram_id, c_text, parse_mode="HTML")
                except Exception as e:
                    logger.error(
                        f"Failed to notify client ({client_telegram_id}) of auto-assignment for booking #{b.id}: {e}",
                        exc_info=True,
                    )

            for admin_id in settings.admin_telegram_ids:
                try:
                    await bot.send_message(
                        admin_id,
                        f"<b>Внимание:</b> Заявка #{b.id} автоматически закреплена за мастером <b>{best_master.full_name}</b> (по истечении времени ожидания).",
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to notify admin ({admin_id}) of auto-assignment for booking #{b.id}: {e}",
                        exc_info=True,
                    )

        elif action_type == "unassigned_alert":
            for admin_id in settings.admin_telegram_ids:
                try:
                    await bot.send_message(
                        admin_id,
                        f"<b>Заявка #{b.id} ожидает назначения мастера!</b>\n\nНи один мастер не взял заказ, требуется ручное назначение через карточку: /booking_{b.id}",
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to alert admin ({admin_id}) about unassigned booking #{b.id}: {e}",
                        exc_info=True,
                    )
