import asyncio
from datetime import date, datetime, time, timedelta
import re

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from notifiers.booking_notifier import record_booking_message, sync_booking_messages
from core.booking_service import (
    admin_reassign_booking,
    cancel_booking,
    complete_booking,
    confirm_booking,
    get_moscow_now,
)
from core.catalog_service import (
    get_blocked_intervals,
)
from core.config import settings
from core.database import get_session
from core.logger import setup_logger
from core.models import Booking, Master, Service, User
from handlers.admin_catalog import admin_catalog_router
from handlers.admin_manual_booking import admin_manual_booking_router
from handlers.master import master_router
from ui.dashboards import (
    admin_booking_card,
    admin_schedule_dashboard,
    master_assigned_card,
    notification_booking_cancelled,
    notification_booking_confirmed,
)
from ui.formatters import escape, format_date
from ui.keyboards import (
    admin_booking_keyboard,
    admin_main_keyboard,
    admin_reassign_keyboard,
    admin_schedule_nav_keyboard,
    master_assigned_keyboard,
)

logger = setup_logger("handlers.admin")
admin_router = Router(name="admin")

# Include sub-routers for master callbacks, catalog management, and manual booking FSM
admin_router.include_router(master_router)
admin_router.include_router(admin_catalog_router)
admin_router.include_router(admin_manual_booking_router)


def check_admin(user_id: int) -> bool:
    return settings.is_admin(user_id)


# ---------------------------------------------------------
# Main Admin Menu
# ---------------------------------------------------------

@admin_router.message(Command("admin"))
async def handle_cmd_admin(message: Message, state: FSMContext) -> None:
    if not check_admin(message.from_user.id):
        await message.answer("Доступ ограничен. Раздел только для администраторов и мастеров.")
        return
    await state.clear()
    text = (
        "<b>ПАНЕЛЬ УПРАВЛЕНИЯ СТУДИЕЙ</b>\n\n"
        "Выберите действие для просмотра расписания или управления интервалами:"
    )
    kb = admin_main_keyboard()
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@admin_router.callback_query(F.data == "admin:menu")
async def cb_admin_menu(call: CallbackQuery, state: FSMContext) -> None:
    if not check_admin(call.from_user.id):
        await call.answer("Доступ ограничен", show_alert=True)
        return
    await state.clear()
    await call.answer()
    text = (
        "<b>ПАНЕЛЬ УПРАВЛЕНИЯ СТУДИЕЙ</b>\n\n"
        "Выберите действие:"
    )
    kb = admin_main_keyboard()
    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass


# ---------------------------------------------------------
# Schedule Navigation (Today, Tomorrow, Specific Date)
# ---------------------------------------------------------

async def _render_schedule_view(target_date: date) -> tuple[str, InlineKeyboardMarkup]:
    async with get_session() as session:
        res = await session.execute(
            select(Booking)
            .options(selectinload(Booking.master), selectinload(Booking.service))
            .where(Booking.booking_date == target_date)
            .order_by(Booking.start_time)
        )
        bookings = list(res.scalars().all())
        blocks = await get_blocked_intervals(session, target_date=target_date)

    text = admin_schedule_dashboard(bookings, target_date, blocks=blocks)
    kb = admin_schedule_nav_keyboard(target_date)
    return text, kb


@admin_router.message(Command("schedule"))
async def handle_cmd_schedule(message: Message) -> None:
    if not check_admin(message.from_user.id):
        await message.answer("Доступ ограничен.")
        return

    today = get_moscow_now().date()
    text, kb = await _render_schedule_view(today)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@admin_router.callback_query(F.data == "admin:schedule_today")
async def cb_schedule_today(call: CallbackQuery) -> None:
    if not check_admin(call.from_user.id):
        await call.answer("Доступ ограничен", show_alert=True)
        return
    await call.answer()
    today = get_moscow_now().date()
    text, kb = await _render_schedule_view(today)
    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass


@admin_router.callback_query(F.data == "admin:schedule_tomorrow")
async def cb_schedule_tomorrow(call: CallbackQuery) -> None:
    if not check_admin(call.from_user.id):
        await call.answer("Доступ ограничен", show_alert=True)
        return
    await call.answer()
    tomorrow = get_moscow_now().date() + timedelta(days=1)
    text, kb = await _render_schedule_view(tomorrow)
    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass


@admin_router.callback_query(F.data.startswith("admin:schedule_date:"))
async def cb_schedule_date(call: CallbackQuery) -> None:
    if not check_admin(call.from_user.id):
        await call.answer("Доступ ограничен", show_alert=True)
        return
    await call.answer()
    parts = call.data.split(":")
    try:
        target_date = date.fromisoformat(parts[2])
    except Exception:
        target_date = get_moscow_now().date()

    text, kb = await _render_schedule_view(target_date)
    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass


# ---------------------------------------------------------
# Booking Cards & Actions (Confirm, Cancel, Complete)
# ---------------------------------------------------------

@admin_router.message(F.text.regexp(r"^/booking_(\d+)(?:@\w+)?$"))
async def handle_booking_id_cmd(message: Message) -> None:
    if not check_admin(message.from_user.id):
        await message.answer("Доступ ограничен.")
        return

    m = re.match(r"^/booking_(\d+)(?:@\w+)?$", message.text.strip())
    if not m:
        return
    booking_id = int(m.group(1))

    async with get_session() as session:
        res = await session.execute(
            select(Booking)
            .options(
                selectinload(Booking.client_user),
                selectinload(Booking.master),
                selectinload(Booking.service),
            )
            .where(Booking.id == booking_id)
        )
        b = res.scalar_one_or_none()

    if not b:
        await message.answer(f"Запись #{booking_id} не найдена.")
        return

    text = admin_booking_card(b)
    kb = admin_booking_keyboard(b.id, b.status, client_telegram_id=b.client_user.telegram_id if b.client_user else None)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@admin_router.callback_query(F.data.startswith("admin_card:"))
async def cb_admin_card(call: CallbackQuery) -> None:
    if not check_admin(call.from_user.id):
        await call.answer("Доступ ограничен", show_alert=True)
        return

    parts = call.data.split(":")
    booking_id = int(parts[1])
    back_target = parts[2] if len(parts) > 2 else "today"
    async with get_session() as session:
        res = await session.execute(
            select(Booking)
            .options(
                selectinload(Booking.client_user),
                selectinload(Booking.master),
                selectinload(Booking.service),
            )
            .where(Booking.id == booking_id)
        )
        b = res.scalar_one_or_none()

    if not b:
        await call.answer("Запись не найдена", show_alert=True)
        return

    await call.answer()

    text = admin_booking_card(b)
    kb = admin_booking_keyboard(
        b.id,
        b.status,
        back_target=back_target,
        client_telegram_id=b.client_user.telegram_id if b.client_user else None,
    )
    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass


@admin_router.callback_query(F.data.startswith("admin_confirm:"))
async def cb_admin_confirm(call: CallbackQuery) -> None:
    if not check_admin(call.from_user.id):
        await call.answer("Доступ ограничен", show_alert=True)
        return

    parts = call.data.split(":")
    booking_id = int(parts[1])
    back_target = parts[2] if len(parts) > 2 else "today"
    async with get_session() as session:
        try:
            booking = await confirm_booking(session, booking_id, call.from_user.id)
            try:
                if booking.client_user and booking.client_user.telegram_id and booking.client_user.telegram_id > 0:
                    bot = call.bot
                    msg = notification_booking_confirmed(booking)
                    await bot.send_message(booking.client_user.telegram_id, msg, parse_mode="HTML")
            except Exception as notify_err:
                logger.warning(f"Failed to notify client: {notify_err}")

            text = (
                f"<b>Заявка #{booking.id} подтверждена!</b>\n\n"
                f"{admin_booking_card(booking)}"
            )
            kb = admin_booking_keyboard(
                booking.id,
                booking.status,
                back_target=back_target,
                client_telegram_id=booking.client_user.telegram_id if booking.client_user else None,
            )
            try:
                await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            except Exception:
                pass
            if call.bot:
                await sync_booking_messages(session, call.bot, booking.id)
            await call.answer("Запись подтверждена", show_alert=False)
        except Exception as e:
            logger.info(f"Confirm notice for booking #{booking_id}: {e}")
            await call.answer("Запись уже была подтверждена или обновлена", show_alert=False)


@admin_router.callback_query(F.data.startswith("admin_reassign:"))
async def cb_admin_reassign_select(call: CallbackQuery) -> None:
    if not check_admin(call.from_user.id):
        await call.answer("Доступ ограничен", show_alert=True)
        return
    parts = call.data.split(":")
    booking_id = int(parts[1])
    back_target = parts[2] if len(parts) > 2 else "today"

    async with get_session() as session:
        res = await session.execute(
            select(Master).where(Master.is_active.is_(True), Master.archived_at.is_(None)).order_by(Master.id)
        )
        masters = res.scalars().all()

    kb = admin_reassign_keyboard(booking_id, masters, back_target)
    text = f"<b>Переназначение записи #{booking_id}</b>\n\nВыберите мастера из списка:"
    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass
    await call.answer()


@admin_router.callback_query(F.data.startswith("admin_assign:"))
async def cb_admin_assign(call: CallbackQuery) -> None:
    if not check_admin(call.from_user.id):
        await call.answer("Доступ ограничен", show_alert=True)
        return
    parts = call.data.split(":")
    booking_id = int(parts[1])
    new_master_id = int(parts[2])
    back_target = parts[3] if len(parts) > 3 else "today"
    async with get_session() as session:
        try:
            booking = await admin_reassign_booking(session, booking_id, new_master_id, call.from_user.id)

            if booking.master and booking.master.telegram_id and call.bot:
                try:
                    m_msg = await call.bot.send_message(
                        chat_id=booking.master.telegram_id,
                        text=master_assigned_card(booking, is_auto=False),
                        reply_markup=master_assigned_keyboard(booking.id),
                        parse_mode="HTML",
                    )
                    await record_booking_message(
                        session, booking.id, booking.master.telegram_id, m_msg.message_id, "master_card"
                    )
                except Exception as m_err:
                    logger.warning(f"Failed to notify reassigned master: {m_err}")

            if booking.client_user and booking.client_user.telegram_id and booking.client_user.telegram_id > 0 and call.bot:
                try:
                    c_msg = notification_booking_confirmed(booking)
                    await call.bot.send_message(booking.client_user.telegram_id, c_msg, parse_mode="HTML")
                except Exception as n_err:
                    logger.warning(f"Failed to notify client: {n_err}")

            if call.bot:
                await sync_booking_messages(session, call.bot, booking.id)

            m_name = booking.master.full_name if booking.master else "Мастер"
            await call.answer(f"Мастер {m_name} назначен!", show_alert=False)
            try:
                text = (
                    f"<b>Заявка #{booking.id} назначена мастеру {m_name}!</b>\n\n"
                    f"{admin_booking_card(booking)}"
                )
                kb = admin_booking_keyboard(
                    booking.id,
                    booking.status,
                    back_target,
                    booking.client_user.telegram_id if booking.client_user else None,
                )
                await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            except Exception:
                pass
        except Exception as e:
            await call.answer(f"Ошибка назначения: {e}", show_alert=True)


@admin_router.callback_query(F.data.startswith("admin_cancel:"))
async def cb_admin_cancel(call: CallbackQuery) -> None:
    if not check_admin(call.from_user.id):
        await call.answer("Доступ ограничен", show_alert=True)
        return

    parts = call.data.split(":")
    booking_id = int(parts[1])
    back_target = parts[2] if len(parts) > 2 else "today"
    async with get_session() as session:
        try:
            booking = await cancel_booking(
                session=session,
                booking_id=booking_id,
                actor_telegram_id=call.from_user.id,
                is_admin_action=True,
            )
            try:
                if booking.client_user and booking.client_user.telegram_id and booking.client_user.telegram_id > 0:
                    bot = call.bot
                    msg = notification_booking_cancelled(booking, "admin")
                    await bot.send_message(booking.client_user.telegram_id, msg, parse_mode="HTML")
            except Exception as notify_err:
                logger.warning(f"Failed to notify client: {notify_err}")

            text = (
                f"<b>Заявка #{booking.id} отменена</b>\n\n"
                f"{admin_booking_card(booking)}"
            )
            kb = admin_booking_keyboard(
                booking.id,
                booking.status,
                back_target=back_target,
                client_telegram_id=booking.client_user.telegram_id if booking.client_user else None,
            )
            await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            await sync_booking_messages(session, call.bot, booking.id)
            await call.answer("Запись отменена")
        except Exception as e:
            await call.answer(f"Ошибка: {e}", show_alert=True)


@admin_router.callback_query(F.data.startswith("admin_complete:"))
async def cb_admin_complete(call: CallbackQuery) -> None:
    if not check_admin(call.from_user.id):
        await call.answer("Доступ ограничен", show_alert=True)
        return

    parts = call.data.split(":")
    booking_id = int(parts[1])
    back_target = parts[2] if len(parts) > 2 else "today"
    async with get_session() as session:
        try:
            booking = await complete_booking(session, booking_id, call.from_user.id)
            text = (
                f"<b>Визит #{booking.id} успешно завершён и оплачен!</b>\n\n"
                f"{admin_booking_card(booking)}"
            )
            kb = admin_booking_keyboard(
                booking.id,
                booking.status,
                back_target=back_target,
                client_telegram_id=booking.client_user.telegram_id if booking.client_user else None,
            )
            await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            await sync_booking_messages(session, call.bot, booking.id)
            await call.answer("Визит завершён и оплачен")
        except Exception as e:
            await call.answer(f"Ошибка: {e}", show_alert=True)


@admin_router.message(Command("backup"))
async def cmd_admin_backup(message: Message) -> None:
    if not check_admin(message.from_user.id):
        return

    from core.backup import backup_sqlite_database, get_backup_stats

    status_msg = await message.answer("🔄 Выполняю безопасный онлайн-снапшот базы данных SQLite...")
    backup_file = await asyncio.to_thread(backup_sqlite_database)
    stats = get_backup_stats()

    if backup_file and backup_file.exists():
        size_kb = backup_file.stat().st_size / 1024
        lines = [
            "<b>💾 РЕЗЕРВНОЕ КОПИРОВАНИЕ ЗАВЕРШЕНО</b>",
            "",
            f" ├ Создан файл: <code>{backup_file.name}</code>",
            f" ├ Размер копии: <b>{size_kb:.1f} КБ</b>",
            f" ├ Всего бэкапов в хранилище: <b>{stats['count']}/7</b>",
            f" └ Общий объём хранилища: <b>{stats['total_kb']:.1f} КБ</b>",
            "",
            "<i>Ротация активна: старые копии сверх лимита 7 удаляются автоматически.</i>",
        ]
        await status_msg.edit_text("\n".join(lines), parse_mode="HTML")
    else:
        await status_msg.edit_text("❌ Ошибка при создании резервной копии базы данных.")
