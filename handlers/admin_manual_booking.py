"""
Admin manual booking FSM router.
Handles multi-step wizard for administrators recording manual client bookings
(master selection, service selection, date picker, slot grid, and client contact input).
"""
import re
from datetime import date, datetime, time, timedelta

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from core.booking_service import confirm_booking, create_booking, resolve_manual_client_telegram_id
from core.config import settings
from core.database import get_session
from core.logger import setup_logger
from core.models import Master, Service, User
from core.slot_service import get_available_slots, get_moscow_now
from ui.dashboards import admin_booking_card
from ui.formatters import escape, format_date
from ui.keyboards import admin_booking_keyboard, admin_main_keyboard

logger = setup_logger("handlers.admin_manual_booking")
admin_manual_booking_router = Router(name="admin_manual_booking")


class AdminManualBookingStates(StatesGroup):
    waiting_manual_client_info = State()


def check_admin(user_id: int) -> bool:
    return settings.is_admin(user_id)


# ---------------------------------------------------------
# Manual Booking by Admin (+ Записать клиента)
# ---------------------------------------------------------

@admin_manual_booking_router.message(Command("manual_book"))
@admin_manual_booking_router.callback_query(F.data == "admin:manual_book")
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
        res = await session.execute(
            select(Master).where(Master.is_active.is_(True), Master.archived_at.is_(None)).order_by(Master.id)
        )
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


@admin_manual_booking_router.callback_query(F.data.startswith("admin_mb_m:"))
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


@admin_manual_booking_router.callback_query(F.data.startswith("admin_mb_s:"))
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


@admin_manual_booking_router.callback_query(F.data.startswith("admin_mb_d:"))
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

    # Build slot buttons grid (3 per row to prevent text clipping on mobile)
    rows = []
    chunk = []
    for s in slots:
        st = s["start_time"]
        chunk.append(
            InlineKeyboardButton(text=st, callback_data=f"admin_mb_t:{master_id}:{service_id}:{target_date.isoformat()}:{st.replace(':', '')}", style="primary")
        )
        if len(chunk) == 3:
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


@admin_manual_booking_router.callback_query(F.data.startswith("admin_mb_t:"))
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

    await state.set_state(AdminManualBookingStates.waiting_manual_client_info)
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


@admin_manual_booking_router.message(StateFilter(AdminManualBookingStates.waiting_manual_client_info), F.text)
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
            target_tg_id = await resolve_manual_client_telegram_id(session, clean_phone)

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
