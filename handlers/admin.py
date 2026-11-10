import asyncio
import html
from datetime import date, datetime, time, timedelta
import math
import re
from typing import Optional

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.booking_service import (
    block_time_interval,
    cancel_booking,
    complete_booking,
    confirm_booking,
    create_booking,
    get_available_slots,
    get_blocked_intervals,
    get_moscow_now,
    sync_booking_messages,
    toggle_service_active,
    unblock_time_interval,
    update_service_price,
)
from core.config import settings
from core.database import get_session
from core.logger import setup_logger
from core.models import BlockedInterval, Booking, Master, Service, User
from ui.dashboards import (
    admin_booking_card,
    admin_schedule_dashboard,
    notification_booking_cancelled,
    notification_booking_confirmed,
)
from ui.formatters import escape, format_date, format_money, format_time
from ui.keyboards import (
    admin_booking_keyboard,
    admin_main_keyboard,
    admin_schedule_nav_keyboard,
    admin_service_item_keyboard,
    admin_services_keyboard,
    admin_unblock_list_keyboard,
    back_to_menu_keyboard,
)

logger = setup_logger("handlers.admin")
admin_router = Router(name="admin")


class AdminStates(StatesGroup):
    waiting_service_price = State()
    waiting_manual_client_info = State()


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
# Block Time Intervals (Interactive & Command)
# ---------------------------------------------------------

@admin_router.callback_query(F.data == "admin:block_prompt")
async def cb_block_prompt(call: CallbackQuery) -> None:
    if not check_admin(call.from_user.id):
        await call.answer("Доступ ограничен", show_alert=True)
        return
    await call.answer()

    async with get_session() as session:
        res = await session.execute(select(Master).where(Master.is_active.is_(True)).order_by(Master.id))
        masters = res.scalars().all()

    rows = []
    for m in masters:
        rows.append([
            InlineKeyboardButton(
                text=f"{m.full_name} ({m.specialization})",
                callback_data=f"admin_blk_m:{m.id}",
                style="primary",
            )
        ])
    rows.append([
        InlineKeyboardButton(
            text="Панель администратора",
            callback_data="admin:menu",
            style="primary",
        )
    ])

    text = (
        "<b>БЛОКИРОВКА ИНТЕРВАЛА ВРЕМЕНИ</b>\n\n"
        "Выберите мастера для установки перерыва или блокировки записи:\n\n"
        "<i>Или отправьте быструю команду:</i>\n"
        "<code>/block &lt;id_мастера&gt; &lt;ГГГГ-ММ-ДД&gt; &lt;ЧЧ:ММ&gt; &lt;ЧЧ:ММ&gt; [причина]</code>"
    )
    try:
        await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")
    except Exception:
        pass


@admin_router.callback_query(F.data.startswith("admin_blk_m:"))
async def cb_block_choose_master(call: CallbackQuery) -> None:
    if not check_admin(call.from_user.id):
        await call.answer("Доступ ограничен", show_alert=True)
        return
    await call.answer()
    master_id = int(call.data.split(":")[1])
    today = get_moscow_now().date()
    dates = [today + timedelta(days=offset) for offset in range(14)]
    rows = [[InlineKeyboardButton(text=d.strftime("%a %d.%m"), callback_data=f"admin_blk_d:{master_id}:{d.isoformat()}", style="primary") for d in dates[i:i + 3]] for i in range(0, len(dates), 3)]
    rows.append([InlineKeyboardButton(text="Назад к выбору мастера", callback_data="admin:block_prompt", style="primary")])
    text = (
        f"<b>БЛОКИРОВКА ВРЕМЕНИ (Мастер #{master_id})</b>\n\n"
        "Выберите день для блокировки:"
    )
    try:
        await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")
    except Exception:
        pass


@admin_router.callback_query(F.data.startswith("admin_blk_d:"))
async def cb_block_choose_date(call: CallbackQuery) -> None:
    if not check_admin(call.from_user.id):
        await call.answer("Доступ ограничен", show_alert=True)
        return
    await call.answer()
    parts = call.data.split(":")
    master_id = int(parts[1])
    target_date_str = parts[2]

    presets = [
        ("Обед (13:00 — 14:00)", "13:00", "14:00", "Обед"),
        ("Обед (14:00 — 15:00)", "14:00", "15:00", "Обед"),
        ("Утро (10:00 — 14:00)", "10:00", "14:00", "Перерыв"),
        ("Вечер (16:00 — 21:00)", "16:00", "21:00", "Перерыв"),
        ("Весь день (10:00 — 21:00)", "10:00", "21:00", "Выходной"),
    ]

    rows = []
    for label, st, et, reason in presets:
        rows.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"admin_blk_set:{master_id}:{target_date_str}:{st.replace(':', '')}:{et.replace(':', '')}:{reason}",
                style="primary",
            )
        ])
    rows.append([
        InlineKeyboardButton(text="Назад", callback_data=f"admin_blk_m:{master_id}", style="primary")
    ])

    text = (
        f"<b>БЛОКИРОВКА ВРЕМЕНИ (Мастер #{master_id}, {target_date_str})</b>\n\n"
        "Выберите готовый интервал для закрытия записи:"
    )
    try:
        await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")
    except Exception:
        pass


@admin_router.callback_query(F.data.startswith("admin_blk_set:"))
async def cb_block_apply(call: CallbackQuery) -> None:
    if not check_admin(call.from_user.id):
        await call.answer("Доступ ограничен", show_alert=True)
        return

    parts = call.data.split(":")
    master_id = int(parts[1])
    block_date = date.fromisoformat(parts[2])
    st_p = [int(parts[3][:2]), int(parts[3][2:])]
    et_p = [int(parts[4][:2]), int(parts[4][2:])]
    start_time = time(st_p[0], st_p[1])
    end_time = time(et_p[0], et_p[1])
    reason = parts[5] if len(parts) > 5 else "Перерыв"

    async with get_session() as session:
        try:
            blk = await block_time_interval(
                session=session,
                master_id=master_id,
                block_date=block_date,
                start_time=start_time,
                end_time=end_time,
                reason=reason,
                admin_telegram_id=call.from_user.id,
            )
            await call.answer("Интервал заблокирован!")
            text = (
                f"<b>Интервал успешно заблокирован</b>\n"
                f" ├ Мастер ID: {master_id}\n"
                f" ├ Дата: {format_date(block_date)}\n"
                f" ├ Время: {start_time:%H:%M} — {end_time:%H:%M}\n"
                f" └ Причина: {escape(reason)}\n\n"
                "Слоты исключены из онлайн-записи."
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Снять блокировку", callback_data="admin:unblock_list", style="danger")],
                [InlineKeyboardButton(text="Панель администратора", callback_data="admin:menu", style="primary")],
            ])
            await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            await call.answer(f"Ошибка: {e}", show_alert=True)


@admin_router.message(Command("block"))
async def handle_cmd_block(message: Message) -> None:
    if not check_admin(message.from_user.id):
        await message.answer("Доступ ограничен.")
        return

    parts = message.text.split(maxsplit=5)
    if len(parts) < 5:
        await message.answer(
            "<b>Формат команды блокировки:</b>\n"
            "<code>/block &lt;id_мастера&gt; &lt;ГГГГ-ММ-ДД&gt; &lt;ЧЧ:ММ&gt; &lt;ЧЧ:ММ&gt; [причина]</code>\n\n"
            "Пример: <code>/block 1 2026-11-01 13:00 14:00 Обед</code>",
            parse_mode="HTML",
        )
        return

    try:
        master_id = int(parts[1])
        block_date = datetime.strptime(parts[2], "%Y-%m-%d").date()
        st_parts = [int(x) for x in parts[3].split(":")]
        et_parts = [int(x) for x in parts[4].split(":")]
        start_time = time(st_parts[0], st_parts[1])
        end_time = time(et_parts[0], et_parts[1])
        reason = parts[5] if len(parts) > 5 else "Технический перерыв"

        async with get_session() as session:
            await block_time_interval(
                session=session,
                master_id=master_id,
                block_date=block_date,
                start_time=start_time,
                end_time=end_time,
                reason=reason,
                admin_telegram_id=message.from_user.id,
            )

        await message.answer(
            f"<b>Интервал успешно заблокирован</b>\n"
            f" ├ Мастер ID: {master_id}\n"
            f" ├ Дата: {block_date}\n"
            f" ├ Время: {start_time:%H:%M} — {end_time:%H:%M}\n"
            f" └ Причина: {escape(reason)}",
            reply_markup=admin_main_keyboard(),
            parse_mode="HTML",
        )
    except Exception as e:
        await message.answer(f"Ошибка блокировки: {e}")


# ---------------------------------------------------------
# Unblock Intervals (Interactive & Command)
# ---------------------------------------------------------

@admin_router.message(Command("unblock"))
@admin_router.callback_query(F.data == "admin:unblock_list")
async def handle_unblock_list(event: Message | CallbackQuery) -> None:
    user_id = event.from_user.id
    if not check_admin(user_id):
        if isinstance(event, CallbackQuery):
            await event.answer("Доступ ограничен", show_alert=True)
        else:
            await event.answer("Доступ ограничен.")
        return

    if isinstance(event, CallbackQuery):
        await event.answer()

    today = get_moscow_now().date()
    async with get_session() as session:
        blocks = await get_blocked_intervals(session)
        active_blocks = [b for b in blocks if b.booking_date >= today]

    if not active_blocks:
        text = (
            "<b>БЛОКИРОВКИ РАСПИСАНИЯ</b>\n\n"
            "Активных заблокированных интервалов не найдено.\n"
            "Все окна доступны для онлайн-записи."
        )
        kb = admin_main_keyboard()
    else:
        text = (
            "<b>АКТИВНЫЕ БЛОКИРОВКИ ВРЕМЕНИ</b>\n\n"
            "Нажмите на интервал, чтобы разблокировать его:"
        )
        kb = admin_unblock_list_keyboard(active_blocks)

    if isinstance(event, CallbackQuery):
        try:
            await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass
    else:
        await event.answer(text, reply_markup=kb, parse_mode="HTML")


@admin_router.callback_query(F.data.startswith("admin_unblock:"))
async def cb_admin_unblock_item(call: CallbackQuery) -> None:
    if not check_admin(call.from_user.id):
        await call.answer("Доступ ограничен", show_alert=True)
        return

    block_id = int(call.data.split(":")[1])
    async with get_session() as session:
        try:
            await unblock_time_interval(session, block_id, call.from_user.id)
            await call.answer("Интервал разблокирован!")

            today = get_moscow_now().date()
            blocks = await get_blocked_intervals(session)
            active_blocks = [b for b in blocks if b.booking_date >= today]
            if not active_blocks:
                text = "<b>БЛОКИРОВКИ РАСПИСАНИЯ</b>\n\nВсе интервалы разблокированы."
                kb = admin_main_keyboard()
            else:
                text = "<b>АКТИВНЫЕ БЛОКИРОВКИ ВРЕМЕНИ</b>\n\nВыберите интервал для снятия:"
                kb = admin_unblock_list_keyboard(active_blocks)
            await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            await call.answer(f"Ошибка: {e}", show_alert=True)


@admin_router.message(F.text.regexp(r"^/unblock_(\d+)$"))
async def handle_unblock_id_cmd(message: Message) -> None:
    if not check_admin(message.from_user.id):
        await message.answer("Доступ ограничен.")
        return

    m = re.match(r"^/unblock_(\d+)$", message.text.strip())
    if not m:
        return
    block_id = int(m.group(1))

    async with get_session() as session:
        try:
            await unblock_time_interval(session, block_id, message.from_user.id)
            await message.answer(
                f"Интервал #{block_id} успешно разблокирован.",
                reply_markup=admin_main_keyboard(),
                parse_mode="HTML",
            )
        except Exception as e:
            await message.answer(f"Ошибка разблокировки: {e}")


# ---------------------------------------------------------
# Services & Prices Management
# ---------------------------------------------------------

@admin_router.message(Command("services_admin"))
@admin_router.callback_query(F.data == "admin:services")
async def handle_services_admin(event: Message | CallbackQuery, state: FSMContext) -> None:
    user_id = event.from_user.id
    if not check_admin(user_id):
        if isinstance(event, CallbackQuery):
            await event.answer("Доступ ограничен", show_alert=True)
        else:
            await event.answer("Доступ ограничен.")
        return

    await state.clear()
    if isinstance(event, CallbackQuery):
        await event.answer()

    async with get_session() as session:
        res = await session.execute(
            select(Service).where(Service.archived_at.is_(None)).order_by(Service.category, Service.price)
        )
        services = res.scalars().all()

    text = (
        "<b>УПРАВЛЕНИЕ УСЛУГАМИ И ЦЕНАМИ</b>\n\n"
        "Выберите услугу для настройки цены или видимости в онлайн-записи:\n"
        " ├ [✓] — услуга активна и доступна клиентам\n"
        " └ [✗] — услуга скрыта из каталога"
    )
    kb = admin_services_keyboard(services)

    if isinstance(event, CallbackQuery):
        try:
            await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass
    else:
        await event.answer(text, reply_markup=kb, parse_mode="HTML")


@admin_router.callback_query(F.data.startswith("admin_srv:"))
async def cb_service_card(call: CallbackQuery, state: FSMContext) -> None:
    if not check_admin(call.from_user.id):
        await call.answer("Доступ ограничен", show_alert=True)
        return
    await state.clear()
    service_id = int(call.data.split(":")[1])

    async with get_session() as session:
        res = await session.execute(select(Service).where(Service.id == service_id))
        s = res.scalar_one_or_none()

    if not s:
        await call.answer("Услуга не найдена", show_alert=True)
        return

    await call.answer()

    status_text = "Активна (доступна для записи)" if s.is_active else "Скрыта из каталога"
    text = (
        f"<b>УПРАВЛЕНИЕ УСЛУГОЙ #{s.id}</b>\n\n"
        f" ├ <b>Название:</b> {escape(s.name)}\n"
        f" ├ <b>Категория:</b> {escape(s.category)}\n"
        f" ├ <b>Длительность:</b> {s.duration_minutes} мин\n"
        f" ├ <b>Текущая цена:</b> {format_money(s.price)}\n"
        f" └ <b>Статус:</b> {status_text}\n\n"
        "Выберите действие:"
    )
    kb = admin_service_item_keyboard(s.id, s.is_active)
    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass


@admin_router.callback_query(F.data.startswith("admin_srv_toggle:"))
async def cb_service_toggle(call: CallbackQuery) -> None:
    if not check_admin(call.from_user.id):
        await call.answer("Доступ ограничен", show_alert=True)
        return

    service_id = int(call.data.split(":")[1])
    async with get_session() as session:
        try:
            s = await toggle_service_active(session, service_id, call.from_user.id)
            state_msg = "активирована" if s.is_active else "скрыта"
            await call.answer(f"Услуга {state_msg}")

            status_text = "Активна (доступна для записи)" if s.is_active else "Скрыта из каталога"
            text = (
                f"<b>УПРАВЛЕНИЕ УСЛУГОЙ #{s.id}</b>\n\n"
                f" ├ <b>Название:</b> {escape(s.name)}\n"
                f" ├ <b>Категория:</b> {escape(s.category)}\n"
                f" ├ <b>Длительность:</b> {s.duration_minutes} мин\n"
                f" ├ <b>Текущая цена:</b> {format_money(s.price)}\n"
                f" └ <b>Статус:</b> {status_text}\n\n"
                "Выберите действие:"
            )
            kb = admin_service_item_keyboard(s.id, s.is_active)
            await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            await call.answer(f"Ошибка: {e}", show_alert=True)


@admin_router.callback_query(F.data.startswith("admin_srv_price:"))
async def cb_service_price_prompt(call: CallbackQuery, state: FSMContext) -> None:
    if not check_admin(call.from_user.id):
        await call.answer("Доступ ограничен", show_alert=True)
        return

    service_id = int(call.data.split(":")[1])
    async with get_session() as session:
        res = await session.execute(select(Service).where(Service.id == service_id))
        s = res.scalar_one_or_none()

    if not s:
        await call.answer("Услуга не найдена", show_alert=True)
        return

    await call.answer()

    await state.set_state(AdminStates.waiting_service_price)
    await state.update_data(service_id=s.id)

    text = (
        f"<b>ИЗМЕНЕНИЕ ЦЕНЫ УСЛУГИ</b>\n\n"
        f"Услуга: <b>{escape(s.name)}</b>\n"
        f"Текущая цена: {format_money(s.price)}\n\n"
        "Отправьте новую цену числом в чат (например: <code>2800</code>):"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отмена", callback_data=f"admin_srv:{s.id}", style="primary")]
    ])
    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass


@admin_router.message(StateFilter(AdminStates.waiting_service_price), F.text)
async def handle_input_service_price(message: Message, state: FSMContext) -> None:
    if not check_admin(message.from_user.id):
        await state.clear()
        return

    val = message.text.strip().replace(" ", "").replace(",", ".")
    try:
        new_price = float(val)
        if math.isnan(new_price) or math.isinf(new_price) or new_price <= 0:
            raise ValueError()
    except Exception:
        await message.answer("Пожалуйста, введите положительное число (например: <code>2500</code>):", parse_mode="HTML")
        return

    data = await state.get_data()
    service_id = data.get("service_id")
    await state.clear()

    async with get_session() as session:
        try:
            s = await update_service_price(session, service_id, new_price, message.from_user.id)
            text = (
                f"<b>Цена успешно обновлена!</b>\n\n"
                f" ├ Услуга: {escape(s.name)}\n"
                f" └ Новая цена: {format_money(s.price)}"
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Карточка услуги", callback_data=f"admin_srv:{s.id}", style="primary")],
                [InlineKeyboardButton(text="К списку услуг", callback_data="admin:services", style="primary")],
            ])
            await message.answer(text, reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            await message.answer(f"Ошибка обновления цены: {e}")


# ---------------------------------------------------------
# Manual Booking by Admin (+ Записать клиента)
# ---------------------------------------------------------

@admin_router.message(Command("manual_book"))
@admin_router.callback_query(F.data == "admin:manual_book")
async def handle_manual_book_start(event: Message | CallbackQuery, state: FSMContext) -> None:
    user_id = event.from_user.id
    if not check_admin(user_id):
        if isinstance(event, CallbackQuery):
            await event.answer("Доступ ограничен", show_alert=True)
        else:
            await event.answer("Доступ ограничен.")
        return

    await state.clear()
    if isinstance(event, CallbackQuery):
        await event.answer()

    async with get_session() as session:
        res = await session.execute(select(Master).where(Master.is_active.is_(True)).order_by(Master.id))
        masters = res.scalars().all()

    rows = [
        [InlineKeyboardButton(text="✦ Любой свободный мастер", callback_data="admin_mb_m:0", style="primary")]
    ]
    for m in masters:
        rows.append([
            InlineKeyboardButton(text=f"{m.full_name} ({m.specialization})", callback_data=f"admin_mb_m:{m.id}", style="primary")
        ])
    rows.append([InlineKeyboardButton(text="Панель администратора", callback_data="admin:menu", style="primary")])

    text = (
        "<b>РУЧНАЯ ЗАПИСЬ КЛИЕНТА (Шаг 1 из 4)</b>\n\n"
        "Выберите мастера для визита:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    if isinstance(event, CallbackQuery):
        try:
            await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass
    else:
        await event.answer(text, reply_markup=kb, parse_mode="HTML")


@admin_router.callback_query(F.data.startswith("admin_mb_m:"))
async def cb_manual_book_master(call: CallbackQuery) -> None:
    if not check_admin(call.from_user.id):
        await call.answer("Доступ ограничен", show_alert=True)
        return
    await call.answer()
    master_id = int(call.data.split(":")[1])

    async with get_session() as session:
        res = await session.execute(
            select(Service)
            .where(Service.is_active.is_(True), Service.archived_at.is_(None))
            .order_by(Service.category, Service.price)
        )
        services = res.scalars().all()

    rows = []
    for s in services:
        rows.append([
            InlineKeyboardButton(text=f"{s.name} ({int(s.price)} ₽)", callback_data=f"admin_mb_s:{master_id}:{s.id}", style="primary")
        ])
    rows.append([InlineKeyboardButton(text="Назад", callback_data="admin:manual_book", style="primary")])

    text = (
        "<b>РУЧНАЯ ЗАПИСЬ КЛИЕНТА (Шаг 2 из 4)</b>\n\n"
        "Выберите услугу из каталога:"
    )
    try:
        await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")
    except Exception:
        pass


@admin_router.callback_query(F.data.startswith("admin_mb_s:"))
async def cb_manual_book_service(call: CallbackQuery) -> None:
    if not check_admin(call.from_user.id):
        await call.answer("Доступ ограничен", show_alert=True)
        return
    await call.answer()
    parts = call.data.split(":")
    master_id = int(parts[1])
    service_id = int(parts[2])

    today = get_moscow_now().date()
    dates = [today + timedelta(days=offset) for offset in range(14)]
    rows = [[InlineKeyboardButton(text=d.strftime("%a %d.%m"), callback_data=f"admin_mb_d:{master_id}:{service_id}:{d.isoformat()}", style="primary") for d in dates[i:i + 3]] for i in range(0, len(dates), 3)]
    rows.append([InlineKeyboardButton(text="Назад", callback_data=f"admin_mb_m:{master_id}", style="primary")])
    text = (
        "<b>РУЧНАЯ ЗАПИСЬ КЛИЕНТА (Шаг 3 из 4)</b>\n\n"
        "Выберите дату визита:"
    )
    try:
        await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")
    except Exception:
        pass


@admin_router.callback_query(F.data.startswith("admin_mb_d:"))
async def cb_manual_book_date(call: CallbackQuery) -> None:
    if not check_admin(call.from_user.id):
        await call.answer("Доступ ограничен", show_alert=True)
        return
    await call.answer()
    parts = call.data.split(":")
    master_id = int(parts[1])
    service_id = int(parts[2])
    target_date = date.fromisoformat(parts[3])

    async with get_session() as session:
        slots = await get_available_slots(
            session=session,
            master_id=master_id,
            service_id=service_id,
            target_date=target_date,
        )

    if not slots:
        text = (
            f"<b>НЕТ СВОБОДНЫХ ОКОН</b>\n\n"
            f"На {format_date(target_date)} нет свободных интервалов нужной длительности.\n"
            "Пожалуйста, выберите другую дату или мастера."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Выбрать другую дату", callback_data=f"admin_mb_s:{master_id}:{service_id}", style="primary")]
        ])
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        return

    # Build slot buttons grid (4 per row)
    rows = []
    chunk = []
    for s in slots:
        st = s["start_time"]
        chunk.append(
            InlineKeyboardButton(text=st, callback_data=f"admin_mb_t:{master_id}:{service_id}:{target_date.isoformat()}:{st.replace(':', '')}", style="primary")
        )
        if len(chunk) == 4:
            rows.append(chunk)
            chunk = []
    if chunk:
        rows.append(chunk)

    rows.append([InlineKeyboardButton(text="Назад к датам", callback_data=f"admin_mb_s:{master_id}:{service_id}", style="primary")])

    text = (
        f"<b>РУЧНАЯ ЗАПИСЬ (Шаг 4 из 4: Выбор времени)</b>\n\n"
        f"Дата: <b>{format_date(target_date)}</b>\n"
        "Выберите удобное время визита:"
    )
    try:
        await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")
    except Exception:
        pass


@admin_router.callback_query(F.data.startswith("admin_mb_t:"))
async def cb_manual_book_time(call: CallbackQuery, state: FSMContext) -> None:
    if not check_admin(call.from_user.id):
        await call.answer("Доступ ограничен", show_alert=True)
        return
    await call.answer()
    parts = call.data.split(":")
    master_id = int(parts[1])
    service_id = int(parts[2])
    target_date_str = parts[3]
    slot_time = f"{parts[4][:2]}:{parts[4][2:]}"

    await state.set_state(AdminStates.waiting_manual_client_info)
    await state.update_data(
        master_id=master_id,
        service_id=service_id,
        date=target_date_str,
        time=slot_time,
    )

    async with get_session() as session:
        srv = (await session.execute(select(Service).where(Service.id == service_id))).scalar_one()
        m_name = "Любой свободный"
        if master_id:
            m = (await session.execute(select(Master).where(Master.id == master_id))).scalar_one_or_none()
            if m:
                m_name = m.full_name

    text = (
        "<b>ВВЕДИТЕ ДАННЫЕ КЛИЕНТА</b>\n\n"
        f" ├ <b>Услуга:</b> {escape(srv.name)}\n"
        f" ├ <b>Мастер:</b> {escape(m_name)}\n"
        f" └ <b>Дата и время:</b> {target_date_str} в {slot_time}\n\n"
        "Отправьте имя и телефон клиента в чат:\n"
        "<i>Пример:</i> <code>Анна +79991234567</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отмена", callback_data="admin:menu", style="primary")]
    ])
    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass


@admin_router.message(StateFilter(AdminStates.waiting_manual_client_info), F.text)
async def handle_input_manual_client_info(message: Message, state: FSMContext) -> None:
    if not check_admin(message.from_user.id):
        await state.clear()
        return

    text = message.text.strip()
    data = await state.get_data()

    # Simple name + phone extraction
    parts = text.split(maxsplit=1)
    if len(parts) == 2:
        name, phone = parts[0], parts[1]
    else:
        name = "Клиент студии"
        phone = text

    clean_phone = re.sub(r"[^\d+]", "", phone)
    if len(clean_phone) < 6:
        await message.answer(
            "Пожалуйста, укажите имя и контактный телефон (например: <code>Елена +79991112233</code>):",
            parse_mode="HTML",
        )
        return

    await state.clear()

    master_id = data.get("master_id")
    service_id = data.get("service_id")
    raw_date = data.get("date")
    raw_time = data.get("time")
    if service_id is None or not raw_date or not raw_time:
        await message.answer(
            "Сессия ручной записи истекла. Пожалуйста, начните оформление заново.",
            reply_markup=admin_main_keyboard(),
        )
        return
    b_date = date.fromisoformat(raw_date)
    st_p = [int(x) for x in raw_time.split(":")]
    b_time = time(st_p[0], st_p[1])

    async with get_session() as session:
        try:
            # Look up existing client by phone or assign virtual ID (never overwrite admin profile)
            existing_client = (await session.execute(
                select(User).where(User.phone == clean_phone)
            )).scalar_one_or_none()
            from core.security import deterministic_virtual_telegram_id
            target_tg_id = existing_client.telegram_id if existing_client else deterministic_virtual_telegram_id(clean_phone)

            booking = await create_booking(
                session=session,
                client_telegram_id=target_tg_id,
                client_name=name,
                client_phone=clean_phone,
                master_id=master_id,
                service_id=service_id,
                booking_date=b_date,
                start_time=b_time,
                comment="Создано администратором вручную",
                ignore_lead_time=True,
            )
            # Auto-confirm manual admin booking
            booking = await confirm_booking(session, booking.id, message.from_user.id)

            card = admin_booking_card(booking)
            kb = admin_booking_keyboard(booking.id, booking.status)
            await message.answer(
                f"<b>Клиент успешно записан! Запись #{booking.id} подтверждена.</b>\n\n{card}",
                reply_markup=kb,
                parse_mode="HTML",
            )
        except Exception as e:
            await message.answer(f"Ошибка при создании записи: {e}", reply_markup=admin_main_keyboard())


# ---------------------------------------------------------
# Booking Cards & Actions (Confirm, Cancel, Complete)
# ---------------------------------------------------------

@admin_router.message(F.text.regexp(r"^/booking_(\d+)$"))
async def handle_booking_id_cmd(message: Message) -> None:
    if not check_admin(message.from_user.id):
        await message.answer("Доступ ограничен.")
        return

    m = re.match(r"^/booking_(\d+)$", message.text.strip())
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


@admin_router.callback_query(F.data.startswith("master_claim:"))
async def cb_master_claim(call: CallbackQuery) -> None:
    parts = call.data.split(":")
    booking_id = int(parts[1])
    async with get_session() as session:
        from core.booking_service import claim_booking_by_master, sync_booking_messages
        from ui.dashboards import master_assigned_card
        from ui.keyboards import master_assigned_keyboard
        try:
            ok, msg, booking = await claim_booking_by_master(session, booking_id, call.from_user.id)
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


@admin_router.callback_query(F.data.startswith("master_decline:"))
async def cb_master_decline(call: CallbackQuery) -> None:
    parts = call.data.split(":")
    booking_id = int(parts[1])
    async with get_session() as session:
        from core.booking_service import (
            decline_booking_by_master,
            get_free_active_masters,
            record_booking_message,
            sync_booking_messages,
        )
        from ui.dashboards import client_master_declined_message, master_order_broadcast_card
        from ui.keyboards import client_reassign_choice_keyboard, master_claim_keyboard
        try:
            ok, flow_status, booking = await decline_booking_by_master(session, booking_id, call.from_user.id)
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


@admin_router.callback_query(F.data.startswith("admin_assign:"))
async def cb_admin_assign(call: CallbackQuery) -> None:
    if not check_admin(call.from_user.id):
        await call.answer("Доступ ограничен", show_alert=True)
        return
    parts = call.data.split(":")
    booking_id = int(parts[1])
    new_master_id = int(parts[2])
    async with get_session() as session:
        try:
            from core.booking_service import admin_reassign_booking, record_booking_message, sync_booking_messages
            from ui.dashboards import master_assigned_card
            from ui.keyboards import master_assigned_keyboard
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
                kb = admin_booking_keyboard(booking.id, booking.status)
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

