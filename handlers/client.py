from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy import desc, select
from sqlalchemy.orm import selectinload

from core.booking_service import cancel_booking, sync_booking_messages
from core.config import settings
from core.database import get_session
from core.logger import setup_logger
from core.models import Booking, Service, User
from ui.dashboards import (
    about_dashboard,
    contact_dashboard,
    my_bookings_dashboard,
    notification_booking_cancelled,
    services_dashboard,
    start_dashboard,
)
from ui.keyboards import (
    back_to_menu_keyboard,
    client_cancel_confirmation_keyboard,
    client_main_keyboard,
    client_my_bookings_keyboard,
)

logger = setup_logger("handlers.client")
client_router = Router(name="client")


@client_router.message(CommandStart())
async def handle_start(message: Message) -> None:
    is_admin = settings.is_admin(message.from_user.id)
    bound_master = None
    if message.from_user and message.from_user.username:
        async with get_session() as session:
            from core.booking_service import bind_master_by_telegram
            bound_master = await bind_master_by_telegram(
                session=session,
                telegram_id=message.from_user.id,
                username=message.from_user.username,
            )

    if bound_master and is_admin:
        from ui.dashboards import master_start_dashboard
        text = f"{start_dashboard(is_admin=True)}\n\n{master_start_dashboard(bound_master.full_name)}"
    elif bound_master:
        from ui.dashboards import master_start_dashboard
        text = master_start_dashboard(bound_master.full_name)
    else:
        text = start_dashboard(is_admin=is_admin)

    kb = client_main_keyboard(is_admin=is_admin)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@client_router.message(Command("book"))
async def handle_cmd_book(message: Message) -> None:
    is_admin = settings.is_admin(message.from_user.id)
    text = (
        "<b>ОНЛАЙН-ЗАПИСЬ В NAIL ATELIER</b>\n\n"
        "Нажмите кнопку ниже, чтобы запустить интерактивное приложение записи:\n"
        " ├ Выберите услугу и мастера\n"
        " ├ Подберите удобный день и свободный слот\n"
        " └ Подтвердите запись в один клик"
    )
    kb = client_main_keyboard(is_admin=is_admin)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@client_router.message(Command("bookings"))
async def handle_cmd_bookings(message: Message) -> None:
    async with get_session() as session:
        user = (await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )).scalar_one_or_none()
        bookings = []
        if user:
            res = await session.execute(
                select(Booking)
                .options(selectinload(Booking.service), selectinload(Booking.master))
                .where(Booking.client_user_id == user.id)
                .order_by(desc(Booking.booking_date), desc(Booking.start_time))
            )
            bookings = list(res.scalars().all())

    text = my_bookings_dashboard(bookings)
    kb = client_my_bookings_keyboard(bookings)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@client_router.message(Command("services"))
async def handle_cmd_services(message: Message) -> None:
    async with get_session() as session:
        res = await session.execute(
            select(Service)
            .where(Service.is_active.is_(True), Service.archived_at.is_(None))
            .order_by(Service.category, Service.price)
        )
        services = list(res.scalars().all())

    text = services_dashboard(services)
    kb = back_to_menu_keyboard()
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@client_router.message(Command("about"))
async def handle_cmd_about(message: Message) -> None:
    text = about_dashboard()
    kb = back_to_menu_keyboard()
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@client_router.message(Command("contact"))
async def handle_cmd_contact(message: Message) -> None:
    text = contact_dashboard()
    kb = back_to_menu_keyboard()
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


# --- Callbacks ---

@client_router.callback_query(F.data == "nav:main")
async def cb_main_menu(call: CallbackQuery) -> None:
    is_admin = settings.is_admin(call.from_user.id)
    text = start_dashboard(is_admin=is_admin)
    kb = client_main_keyboard(is_admin=is_admin)
    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await call.answer()


@client_router.callback_query(F.data == "nav:my_bookings")
async def cb_my_bookings(call: CallbackQuery) -> None:
    async with get_session() as session:
        user = (await session.execute(
            select(User).where(User.telegram_id == call.from_user.id)
        )).scalar_one_or_none()
        bookings = []
        if user:
            res = await session.execute(
                select(Booking)
                .options(selectinload(Booking.service), selectinload(Booking.master))
                .where(Booking.client_user_id == user.id)
                .order_by(desc(Booking.booking_date), desc(Booking.start_time))
            )
            bookings = list(res.scalars().all())

    text = my_bookings_dashboard(bookings)
    kb = client_my_bookings_keyboard(bookings)
    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await call.answer()


@client_router.callback_query(F.data == "nav:services")
async def cb_services(call: CallbackQuery) -> None:
    async with get_session() as session:
        res = await session.execute(
            select(Service)
            .where(Service.is_active.is_(True), Service.archived_at.is_(None))
            .order_by(Service.category, Service.price)
        )
        services = list(res.scalars().all())

    text = services_dashboard(services)
    kb = back_to_menu_keyboard()
    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await call.answer()


@client_router.callback_query(F.data == "nav:about")
async def cb_about(call: CallbackQuery) -> None:
    text = about_dashboard()
    kb = back_to_menu_keyboard()
    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await call.answer()


@client_router.callback_query(F.data == "nav:contact")
async def cb_contact(call: CallbackQuery) -> None:
    text = contact_dashboard()
    kb = back_to_menu_keyboard()
    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await call.answer()


@client_router.callback_query(F.data.regexp(r"^client_cancel:\d+$"))
async def cb_client_cancel(call: CallbackQuery) -> None:
    booking_id = int(call.data.split(":")[1])
    try:
        await call.message.edit_text(
            f"<b>Отменить запись #{booking_id}?</b>\n\nДействие освободит выбранное время для других клиентов.",
            reply_markup=client_cancel_confirmation_keyboard(booking_id),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await call.answer()


@client_router.callback_query(F.data.regexp(r"^client_cancel:\d+:confirm$"))
async def cb_client_cancel_confirm(call: CallbackQuery) -> None:
    booking_id = int(call.data.split(":")[1])
    async with get_session() as session:
        try:
            booking = await cancel_booking(
                session=session,
                booking_id=booking_id,
                actor_telegram_id=call.from_user.id,
                is_admin_action=False,
            )

            # Alert salon admins
            bot = call.bot
            if bot:
                await sync_booking_messages(session, bot, booking.id)
                admin_msg = notification_booking_cancelled(booking, "client")
                for admin_id in settings.admin_telegram_ids:
                    try:
                        await bot.send_message(admin_id, admin_msg, parse_mode="HTML")
                    except Exception as err:
                        logger.warning(f"Failed to alert admin {admin_id}: {err}")

            text = (
                f"<b>Запись #{booking.id} успешно отменена</b>\n\n"
                f"{notification_booking_cancelled(booking, 'client')}"
            )
            kb = back_to_menu_keyboard()
            await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            await call.answer("Запись отменена")
        except Exception as e:
            await call.answer(f"Ошибка: {e}", show_alert=True)


@client_router.callback_query(F.data.startswith("client_accept_any:"))
async def cb_client_accept_any(call: CallbackQuery) -> None:
    parts = call.data.split(":")
    booking_id = int(parts[1])
    async with get_session() as session:
        from core.booking_service import (
            client_accept_any_master,
            get_free_active_masters,
            record_booking_message,
            sync_booking_messages,
        )
        from ui.dashboards import master_order_broadcast_card
        from ui.keyboards import master_claim_keyboard
        try:
            ok, msg, booking = await client_accept_any_master(session, booking_id, call.from_user.id)
            if not ok or not booking:
                await call.answer(msg, show_alert=True)
                return
            await call.answer("Ищем свободного мастера...")
            await call.message.edit_text(
                f"<b>Заявка #{booking.id}</b>\n\n"
                f"Мы ищем для вас свободного мастера. Как только мастер подтвердит визит, вам придёт уведомление!",
                parse_mode="HTML",
            )
            # Sync existing messages
            if call.bot:
                await sync_booking_messages(session, call.bot, booking.id)
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
                            logger.warning(f"Failed to broadcast to master {fm.full_name}: {m_err}")
        except Exception as e:
            await call.answer(f"Ошибка: {e}", show_alert=True)

