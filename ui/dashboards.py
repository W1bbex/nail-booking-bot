from datetime import date
from typing import Any, List, Optional
from core.config import settings
from core.models import Booking, Service
from ui.formatters import escape, format_date, format_money, format_status, format_time
from ui.icons import tg_icon


def start_dashboard(is_admin: bool = False) -> str:
    salon = settings.salon
    name_str = salon.get('name', 'Nail Atelier').upper()
    lines = [
        f"<b>{tg_icon('info')} {escape(name_str)}</b>",
        f"<i>{escape(salon.get('tagline', 'Студия эстетического маникюра'))}</i>",
        "",
        f"<b>{tg_icon('info')} Информация о студии:</b>",
        f" ├ Адрес: {escape(salon.get('address', ''))}",
        f" ├ Режим: {escape(salon.get('working_hours', ''))}",
        f" └ Телефон: {escape(salon.get('phone', ''))}",
        "",
        f"<b>{tg_icon('clock')} Онлайн-запись:</b>",
        " ├ Выберите услугу, мастера и свободное время",
        " └ Управление записями доступно через Mini App и меню",
    ]
    if is_admin:
        lines.extend([
            "",
            "<b>Режим администратора:</b>",
            " └ Вам доступны управление расписанием и подтверждение заявок",
        ])
    return "\n".join(lines)


def my_bookings_dashboard(bookings: List[Booking]) -> str:
    lines = [
        f"<b>{tg_icon('user')} МОИ ЗАПИСИ</b>",
        "",
    ]
    if not bookings:
        lines.extend([
            "<b>Активных записей не найдено</b>",
            " └ Нажмите «Записаться», чтобы выбрать услугу и время визита.",
        ])
        return "\n".join(lines)

    lines.append(f"Всего записей: {len(bookings)}")
    lines.append("")

    for i, b in enumerate(bookings, 1):
        is_last = (i == len(bookings))
        prefix = " └ " if is_last else " ├ "
        lines.append(f"<b>Запись #{b.id}</b> · {format_status(b.status)}")
        lines.append(f" ├ Услуга: {escape(b.service.name if b.service else 'Услуга')}")
        lines.append(f" ├ Мастер: {escape(b.master.full_name if b.master else 'Мастер')}")
        lines.append(f" ├ Дата: {format_date(b.booking_date)} · {format_time(b.start_time)}—{format_time(b.end_time)}")
        lines.append(f"{prefix}Стоимость: {format_money(b.service.price if b.service else 0)}")
        if not is_last:
            lines.append("")

    return "\n".join(lines)


def services_dashboard(services: List[Service]) -> str:
    lines = [
        f"<b>{tg_icon('clock')} ПРАЙС-ЛИСТ И КАТАЛОГ УСЛУГ</b>",
        "<i>Все материалы стерильны, одноразовые расходники для каждого клиента</i>",
        "",
    ]

    # Group by category
    categories = {}
    for s in services:
        categories.setdefault(s.category, []).append(s)

    for cat_name, cat_services in categories.items():
        lines.append(f"<b>Категория: {escape(cat_name)}</b>")
        for i, s in enumerate(cat_services):
            is_last = (i == len(cat_services) - 1)
            prefix = " └ " if is_last else " ├ "
            lines.append(
                f"{prefix}<b>{escape(s.name)}</b> · {s.duration_minutes} мин · {format_money(s.price)}"
            )
            if s.description:
                subprefix = "    " if is_last else " │  "
                lines.append(f"{subprefix}<i>{escape(s.description)}</i>")
        lines.append("")

    lines.append("Для быстрой записи с выбором времени откройте Mini App.")
    return "\n".join(lines)


def about_dashboard() -> str:
    salon = settings.salon
    name_str = salon.get('name', 'Nail Atelier').upper()
    desc = (salon.get('description') or '').strip()
    lines = [
        f"<b>{tg_icon('info')} О СТУДИИ {escape(name_str)}</b>",
        f"<i>{escape(salon.get('tagline', ''))}</i>",
        "",
    ]
    if desc:
        lines.extend([
            escape(desc),
            "",
        ])
    lines.extend([
        "<b>Наши стандарты качества:</b>",
        " ├ Трёхэтапная медицинская стерилизация инструмента (СанПиН)",
        " ├ Крафт-пакет вскрывается исключительно в присутствии клиента",
        " ├ Премиальные гипоаллергенные покрытия европейского качества",
        " ├ Топ-мастера с непрерывным стажем от 3 до 5 лет",
        " └ Уютная эстетичная атмосфера, свежий кофе и чай для гостей",
        "",
        "<b>Гарантия на покрытие:</b>",
        " └ 7 дней безусловной гарантии на стойкость и целостность покрытия",
    ])
    return "\n".join(lines)


def contact_dashboard() -> str:
    salon = settings.salon
    landmark = (salon.get('landmark') or '').strip()
    contact_tg = (salon.get('contact_telegram') or salon.get('admin_contact') or '').strip()

    loc_items = [
        f"Адрес: {escape(salon.get('address', ''))}",
        f"Режим работы: {escape(salon.get('working_hours', ''))}",
    ]
    if landmark:
        loc_items.append(f"Ориентир: {escape(landmark)}")

    comm_items = [
        f"Телефон: {escape(salon.get('phone', ''))}",
    ]
    if contact_tg:
        comm_items.append(f"Telegram / WhatsApp: {escape(contact_tg)}")
    comm_items.append("Онлайн-запись: круглосуточно через Telegram Mini App")

    lines = [
        f"<b>{tg_icon('user')} КОНТАКТЫ И АДРЕС</b>",
        "",
        "<b>Локация и график:</b>",
    ]
    for idx, item in enumerate(loc_items):
        prefix = " └ " if idx == len(loc_items) - 1 else " ├ "
        lines.append(f"{prefix}{item}")

    lines.extend([
        "",
        "<b>Связь с администратором:</b>",
    ])
    for idx, item in enumerate(comm_items):
        prefix = " └ " if idx == len(comm_items) - 1 else " ├ "
        lines.append(f"{prefix}{item}")

    return "\n".join(lines)


def admin_schedule_dashboard(bookings: List[Booking], target_date: date, blocks: Optional[List[Any]] = None) -> str:
    total_rev = sum(b.service.price for b in bookings if b.service and b.status in ("confirmed", "completed"))
    done_rev = sum(b.service.price for b in bookings if b.service and b.status == "completed")
    done_count = sum(1 for b in bookings if b.status == "completed")

    lines = [
        f"<b>{tg_icon('clock')} РАСПИСАНИЕ СТУДИИ НА {format_date(target_date)}</b>",
        f" ├ Активных визитов: {len(bookings)} · Ожидаемая касса: {format_money(total_rev)}",
        f" └ Завершено и оплачено: {done_count} ({format_money(done_rev)})",
        "",
    ]

    if blocks:
        lines.append("<b>Заблокированные интервалы:</b>")
        for blk in blocks:
            m_name = blk.master.full_name if blk.master else "Мастер"
            lines.append(f" ├ {format_time(blk.start_time)}—{format_time(blk.end_time)} · {escape(m_name)} ({escape(blk.reason)}) · /unblock_{blk.id}")
        lines.append("")

    if not bookings:
        lines.extend([
            "<b>Записей клиентов на эту дату нет</b>",
            " └ Свободные окна открыты для онлайн-бронирования.",
        ])
        return "\n".join(lines)

    for i, b in enumerate(bookings, 1):
        is_last = (i == len(bookings))
        lines.append(
            f"<b>{format_time(b.start_time)}—{format_time(b.end_time)}</b> · "
            f"Запись #{b.id} {format_status(b.status)}"
        )
        lines.append(f" ├ Клиент: {escape(b.client_name)} · {escape(b.client_phone)}")
        lines.append(f" ├ Мастер: {escape(b.master.full_name if b.master else 'Мастер')}")
        lines.append(f" ├ Услуга: {escape(b.service.name if b.service else 'Услуга')} ({format_money(b.service.price if b.service else 0)})")
        if b.comment:
            lines.append(f" ├ Пожелания: <i>{escape(b.comment)}</i>")
        lines.append(f" └ Управление: /booking_{b.id}")
        if not is_last:
            lines.append("")

    return "\n".join(lines)


def admin_booking_card(b: Booking) -> str:
    tg_link = (
        f"<a href='tg://user?id={b.client_user.telegram_id}'>Написать в Telegram</a>"
        if (b.client_user and b.client_user.telegram_id and b.client_user.telegram_id > 0)
        else "Не привязан"
    )
    lines = [
        f"<b>{tg_icon('user')} КАРТОЧКА ЗАПИСИ #{b.id}</b>",
        f"Статус: <b>{format_status(b.status)}</b>",
        "",
        "<b>Параметры визита:</b>",
        f" ├ Дата: {format_date(b.booking_date)}",
        f" ├ Время: {format_time(b.start_time)} — {format_time(b.end_time)} ({b.service.duration_minutes if b.service else 60} мин)",
        f" ├ Мастер: {escape(b.master.full_name if b.master else 'Мастер')}",
        f" └ Услуга: {escape(b.service.name if b.service else 'Услуга')}",
        "",
        "<b>Данные клиента:</b>",
        f" ├ Имя: {escape(b.client_name)}",
        f" ├ Телефон: {escape(b.client_phone)}",
        f" ├ Telegram: {tg_link} (ID: <code>{b.client_user.telegram_id if b.client_user else '—'}</code>)",
        f" └ Комментарий: {escape(b.comment) if b.comment else 'Без комментария'}",
        "",
        f"Стоимость к оплате: <b>{format_money(b.service.price if b.service else 0)}</b>",
    ]
    return "\n".join(lines)


def notification_new_booking(b: Booking) -> str:
    lines = [
        f"<b>{tg_icon('clock')} НОВАЯ ЗАЯВКА НА ЗАПИСЬ</b>",
        f"Номер заявки: <b>#{b.id}</b>",
        "",
        "<b>Детали записи:</b>",
        f" ├ Дата: {format_date(b.booking_date)} · {format_time(b.start_time)}—{format_time(b.end_time)}",
        f" ├ Мастер: {escape(b.master.full_name if b.master else 'Мастер')}",
        f" ├ Услуга: {escape(b.service.name if b.service else 'Услуга')}",
        f" └ Стоимость: {format_money(b.service.price if b.service else 0)}",
        "",
        "<b>Клиент:</b>",
        f" ├ {escape(b.client_name)} ({escape(b.client_phone)})",
        f" └ Комментарий: {escape(b.comment) if b.comment else '—'}",
        "",
        "Требуется действие администратора:",
    ]
    return "\n".join(lines)


def notification_client_booking_created(b: Booking) -> str:
    salon = settings.salon
    lines = [
        f"<b>{tg_icon('clock')} ЗАЯВКА НА ЗАПИСЬ ОТПРАВЛЕНА</b>",
        f"Номер заявки: <b>#{b.id}</b> · <i>Ожидает подтверждения</i>",
        "",
        "<b>Детали визита:</b>",
        f" ├ Дата: {format_date(b.booking_date)}",
        f" ├ Время: {format_time(b.start_time)} — {format_time(b.end_time)}",
        f" ├ Мастер: {escape(b.master.full_name if b.master else 'Мастер')}",
        f" ├ Услуга: {escape(b.service.name if b.service else 'Услуга')}",
        f" └ Стоимость: {format_money(b.service.price if b.service else 0)}",
        "",
        f"Адрес студии: {escape(salon.get('address', ''))}",
        "",
        "Мы сообщим вам, как только визит будет подтверждён администратором. "
        "Управлять визитом можно в разделе «Мои записи».",
    ]
    return "\n".join(lines)


def notification_booking_confirmed(b: Booking) -> str:
    lines = [
        f"<b>{tg_icon('check')} ВАША ЗАПИСЬ ПОДТВЕРЖДЕНА</b>",
        f"Номер записи: <b>#{b.id}</b>",
        "",
        "<b>Детали визита:</b>",
        f" ├ Дата: {format_date(b.booking_date)}",
        f" ├ Время: {format_time(b.start_time)} — {format_time(b.end_time)}",
        f" ├ Мастер: {escape(b.master.full_name if b.master else 'Мастер')}",
        f" ├ Услуга: {escape(b.service.name if b.service else 'Услуга')}",
        f" └ Адрес: {escape(settings.salon.get('address', ''))}",
        "",
        "Ждём вас в студии! Если ваши планы изменятся, пожалуйста, предупредите нас заранее.",
    ]
    return "\n".join(lines)


def master_start_dashboard(master_name: str) -> str:
    salon = settings.salon
    lines = [
        f"<b>{tg_icon('user')} КАБИНЕТ МАСТЕРА · {escape(master_name.upper())}</b>",
        f"<i>Студия {escape(salon.get('name', 'Nail Atelier'))}</i>",
        "",
        "<b>Статус авторизации:</b>",
        " ├ Аккаунт успешно синхронизирован с Telegram",
        " ├ Вам будут поступать уведомления о новых заказах студии",
        " └ Вы можете принимать свободные заказы и просматривать график",
        "",
        "Используйте кнопки меню или Mini App для навигации.",
    ]
    return "\n".join(lines)


def master_order_broadcast_card(b: Booking) -> str:
    lines = [
        f"<b>{tg_icon('clock')} СВОБОДНЫЙ ЗАКАЗ #{b.id}</b>",
        "<i>Клиент выбрал вариант «Любой свободный мастер»</i>",
        "",
        "<b>Параметры визита:</b>",
        f" ├ Дата: {format_date(b.booking_date)}",
        f" ├ Время: {format_time(b.start_time)} — {format_time(b.end_time)} ({b.service.duration_minutes if b.service else 60} мин)",
        f" ├ Услуга: {escape(b.service.name if b.service else 'Услуга')}",
        f" └ Стоимость: {format_money(b.service.price if b.service else 0)}",
        "",
        "<b>Данные клиента:</b>",
        f" ├ Имя: {escape(b.client_name)}",
        f" └ Пожелания: {escape(b.comment) if b.comment else 'Без комментария'}",
        "",
        "Нажмите кнопку ниже, чтобы забрать заказ себе:",
    ]
    return "\n".join(lines)


def master_assigned_card(b: Booking, is_auto: bool = False) -> str:
    title = "ВАМ АВТОМАТИЧЕСКИ НАЗНАЧЕН ЗАКАЗ" if is_auto else "ВЫ ЗАКРЕПЛЕНЫ ЗА ЗАКАЗОМ"
    lines = [
        f"<b>{tg_icon('check')} {title} #{b.id}</b>",
        f"<i>{'Назначен по правилу наименьшей дневной нагрузки' if is_auto else 'Заказ успешно подтверждён'}</i>",
        "",
        "<b>Параметры визита:</b>",
        f" ├ Дата: {format_date(b.booking_date)}",
        f" ├ Время: {format_time(b.start_time)} — {format_time(b.end_time)}",
        f" ├ Услуга: {escape(b.service.name if b.service else 'Услуга')}",
        f" └ Стоимость: {format_money(b.service.price if b.service else 0)}",
        "",
        "<b>Клиент:</b>",
        f" ├ {escape(b.client_name)} ({escape(b.client_phone)})",
        f" └ Пожелания: {escape(b.comment) if b.comment else 'Без комментария'}",
        "",
        "Если у вас возник форс-мажор, вы можете отказаться от выполнения заказа:",
    ]
    return "\n".join(lines)


def client_master_declined_message(b: Booking, master_name: str) -> str:
    lines = [
        f"<b>{tg_icon('back')} ОБНОВЛЕНИЕ ПО ЗАЯВКЕ #{b.id}</b>",
        "",
        f"Сожалеем, мастер <b>{escape(master_name)}</b> не сможет принять заказ на "
        f"{format_date(b.booking_date)} в {format_time(b.start_time)} из-за непредвиденного изменения графика.",
        "",
        "Хотите, чтобы мы автоматически подобрали другого свободного специалиста студии на это же время?",
        "<i>У вас есть 10 минут для выбора, после чего заказ будет передан свободным мастерам студии.</i>",
    ]
    return "\n".join(lines)


def notification_booking_cancelled(b: Booking, actor_role: str) -> str:
    by_text = "клиентом" if actor_role == "client" else "администратором студии"
    lines = [
        f"<b>{tg_icon('back')} ЗАПИСЬ ОТМЕНЕНА</b>",
        f"Запись #{b.id} была отменена {by_text}.",
        "",
        "<b>Детали отменённого визита:</b>",
        f" ├ Дата: {format_date(b.booking_date)}",
        f" ├ Время: {format_time(b.start_time)} — {format_time(b.end_time)}",
        f" ├ Мастер: {escape(b.master.full_name if b.master else 'Мастер')}",
        f" └ Услуга: {escape(b.service.name if b.service else 'Услуга')}",
        "",
        "Свободные слоты возвращены в расписание.",
    ]
    return "\n".join(lines)
