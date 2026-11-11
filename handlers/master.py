import html
from aiogram import Router, F
from aiogram.types import CallbackQuery

from core.booking_notifier import record_booking_message, sync_booking_messages
from core import booking_service
from core.catalog_service import get_free_active_masters
from core.config import settings
from core.database import get_session
from core.logger import setup_logger
from ui.dashboards import (
    client_master_declined_message,
    master_assigned_card,
    master_order_broadcast_card,
    notification_booking_confirmed,
)
from ui.keyboards import (
    client_reassign_choice_keyboard,
    master_assigned_keyboard,
    master_claim_keyboard,
)

logger = setup_logger("handlers.master")
master_router = Router(name="master")


@master_router.callback_query(F.data.startswith("master_claim:"))
async def cb_master_claim(call: CallbackQuery) -> None:
    parts = call.data.split(":")
    booking_id = int(parts[1])
    async with get_session() as session:
        try:
            ok, msg, booking = await booking_service.claim_booking_by_master(session, booking_id, call.from_user.id)
            if not ok or not booking:
                await call.answer(msg, show_alert=True)
                if "уже" in msg.lower() or "отменена" in msg.lower():
                    try:
                        await call.message.edit_text(
                            f"<b>Заявка #{booking_id}</b>\n\n{html.escape(msg)}",
                            parse_mode="HTML",
                        )
                    except Exception:
                        pass
                return

            card_text = master_assigned_card(booking, is_auto=False)
            kb = master_assigned_keyboard(booking.id)
            try:
                await call.message.edit_text(card_text, reply_markup=kb, parse_mode="HTML")
            except Exception:
                pass

            if booking.client_user and booking.client_user.telegram_id and booking.client_user.telegram_id > 0 and call.bot:
                try:
                    c_msg = notification_booking_confirmed(booking)
                    await call.bot.send_message(booking.client_user.telegram_id, c_msg, parse_mode="HTML")
                except Exception as n_err:
                    logger.warning(f"Failed to notify client on claim: {n_err}")

            if call.bot:
                for aid in settings.admin_telegram_ids:
                    if aid != call.from_user.id:
                        try:
                            m_name = html.escape(booking.master.full_name) if booking.master else "Мастер"
                            c_name = html.escape(booking.client_user.full_name) if booking.client_user else "Клиент"
                            c_phone = html.escape(booking.client_user.phone or "") if booking.client_user else ""
                            b_date_str = booking.booking_date.strftime("%d.%m.%Y")
                            b_time_str = booking.start_time.strftime("%H:%M")
                            await call.bot.send_message(
                                aid,
                                f"<b>Заказ #{booking.id} взят мастером!</b>\n\n"
                                f"Мастер: {m_name}\n"
                                f"Клиент: {c_name} ({c_phone})\n"
                                f"Дата: {b_date_str} {b_time_str}",
                                parse_mode="HTML",
                            )
                        except Exception:
                            pass
                await sync_booking_messages(session, call.bot, booking.id)

            await call.answer("Заказ успешно взят в работу!", show_alert=False)
        except ValueError as val_err:
            await call.answer(str(val_err), show_alert=True)
            try:
                await call.message.edit_text(
                    f"<b>Заявка #{booking_id}</b>\n\nЗаказ уже распределён или принят другим мастером.",
                    parse_mode="HTML",
                )
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Error in master_claim: {e}", exc_info=True)
            await call.answer(f"Ошибка: {e}", show_alert=True)


@master_router.callback_query(F.data.startswith("master_decline:"))
async def cb_master_decline(call: CallbackQuery) -> None:
    parts = call.data.split(":")
    booking_id = int(parts[1])
    async with get_session() as session:
        try:
            ok, flow_status, booking = await booking_service.decline_booking_by_master(session, booking_id, call.from_user.id)
            if not ok or not booking:
                await call.answer(flow_status, show_alert=True)
                return
            master_name = booking.master.full_name if booking.master else "Мастер"

            try:
                await call.message.edit_text(
                    f"<b>Заявка #{booking.id}</b>\n\nВы отказались от выполнения этого заказа.",
                    parse_mode="HTML",
                )
            except Exception:
                pass
            await call.answer("Вы отказались от заказа", show_alert=False)

            if flow_status == "declined_specific":
                if booking.client_user and booking.client_user.telegram_id and booking.client_user.telegram_id > 0 and call.bot:
                    try:
                        c_text = client_master_declined_message(booking, master_name)
                        c_kb = client_reassign_choice_keyboard(booking.id)
                        await call.bot.send_message(
                            chat_id=booking.client_user.telegram_id,
                            text=c_text,
                            reply_markup=c_kb,
                            parse_mode="HTML",
                        )
                    except Exception as c_err:
                        logger.warning(f"Failed to send decline notice to client: {c_err}")

                if call.bot:
                    for aid in settings.admin_telegram_ids:
                        try:
                            c_name = html.escape(booking.client_user.full_name) if booking.client_user else "Клиент"
                            esc_master = html.escape(master_name)
                            await call.bot.send_message(
                                aid,
                                f"<b>Мастер отказался от заказа #{booking.id}!</b>\n\n"
                                f"Мастер: {esc_master}\n"
                                f"Клиент: {c_name}\n"
                                f"Клиенту предложено выбрать другого мастера (ожидание 10 мин).",
                                parse_mode="HTML",
                            )
                        except Exception:
                            pass

            elif flow_status == "declined_any" and call.bot:
                declined_ids = [
                    int(x) for x in (booking.declined_master_ids or "").split(",") if x.strip().isdigit()
                ]
                free_masters = await get_free_active_masters(
                    session, booking.booking_date, booking.start_time, booking.end_time, exclude_ids=declined_ids
                )
                b_text = master_order_broadcast_card(booking)
                c_kb = master_claim_keyboard(booking.id)
                for fm in free_masters:
                    if fm.telegram_id:
                        try:
                            s_msg = await call.bot.send_message(
                                chat_id=fm.telegram_id,
                                text=b_text,
                                reply_markup=c_kb,
                                parse_mode="HTML",
                            )
                            await record_booking_message(
                                session, booking.id, fm.telegram_id, s_msg.message_id, "master_claim"
                            )
                        except Exception as m_err:
                            logger.warning(f"Failed to forward order to {fm.full_name}: {m_err}")

            elif flow_status == "all_declined" and call.bot:
                for aid in settings.admin_telegram_ids:
                    try:
                        c_name = html.escape(booking.client_user.full_name) if booking.client_user else "Клиент"
                        b_date_str = booking.booking_date.strftime("%d.%m.%Y")
                        b_time_str = booking.start_time.strftime("%H:%M")
                        await call.bot.send_message(
                            aid,
                            f"<b>Все мастера отклонили заказ #{booking.id}!</b>\n\n"
                            f"Клиент: {c_name}\n"
                            f"Дата: {b_date_str} {b_time_str}\n"
                            f"Требуется ручное назначение мастера в админ-панели: /booking_{booking.id}",
                            parse_mode="HTML",
                        )
                    except Exception:
                        pass

            if call.bot:
                await sync_booking_messages(session, call.bot, booking.id)

        except Exception as e:
            logger.error(f"Error in master_decline: {e}", exc_info=True)
            await call.answer(f"Ошибка: {e}", show_alert=True)
