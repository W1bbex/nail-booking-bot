import math
import re
from datetime import date, datetime, time, timedelta

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from core.catalog_service import (
    block_time_interval,
    get_blocked_intervals,
    get_moscow_now,
    toggle_service_active,
    unblock_time_interval,
    update_service_price,
)
from core.config import settings
from core.database import get_session
from core.logger import setup_logger
from core.models import BlockedInterval, Master, Service
from ui.formatters import escape, format_date, format_money
from ui.keyboards import (
    admin_main_keyboard,
    admin_service_item_keyboard,
    admin_services_keyboard,
    admin_unblock_list_keyboard,
)

logger = setup_logger("handlers.admin_catalog")
admin_catalog_router = Router(name="admin_catalog")


class CatalogAdminStates(StatesGroup):
    waiting_service_price = State()


def check_admin(user_id: int) -> bool:
    return settings.is_admin(user_id)


# ---------------------------------------------------------
# Block Time Intervals (Interactive & Command)
# ---------------------------------------------------------

@admin_catalog_router.callback_query(F.data == "admin:block_prompt")
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


@admin_catalog_router.callback_query(F.data.startswith("admin_blk_m:"))
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


@admin_catalog_router.callback_query(F.data.startswith("admin_blk_d:"))
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


@admin_catalog_router.callback_query(F.data.startswith("admin_blk_set:"))
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
            await block_time_interval(
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


@admin_catalog_router.message(Command("block"))
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

@admin_catalog_router.message(Command("unblock"))
@admin_catalog_router.callback_query(F.data == "admin:unblock_list")
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


@admin_catalog_router.callback_query(F.data.startswith("admin_unblock:"))
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


@admin_catalog_router.message(F.text.regexp(r"^/unblock_(\d+)$"))
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

@admin_catalog_router.message(Command("services_admin"))
@admin_catalog_router.callback_query(F.data == "admin:services")
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


@admin_catalog_router.callback_query(F.data.startswith("admin_srv:"))
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


@admin_catalog_router.callback_query(F.data.startswith("admin_srv_toggle:"))
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


@admin_catalog_router.callback_query(F.data.startswith("admin_srv_price:"))
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

    await state.set_state(CatalogAdminStates.waiting_service_price)
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


@admin_catalog_router.message(StateFilter(CatalogAdminStates.waiting_service_price), F.text)
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
