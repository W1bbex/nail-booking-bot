from typing import Any, List, Optional
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from core.config import settings
from ui.icons import ICONS


def client_main_keyboard(is_admin: bool = False, webapp_url: Optional[str] = None) -> InlineKeyboardMarkup:
    url = webapp_url or settings.public_url
    miniapp_url = f"{url.rstrip('/')}/miniapp/"

    rows = [
        # Hero row: WebApp Launch Button
        [
            InlineKeyboardButton(
                text="Открыть кабинет",
                web_app=WebAppInfo(url=miniapp_url),
                style="success",
                icon_custom_emoji_id=ICONS["booking"],
            )
        ],
        # 2-column navigation grid
        [
            InlineKeyboardButton(
                text="Мои записи",
                callback_data="nav:my_bookings",
                style="primary",
                icon_custom_emoji_id=ICONS["calendar"],
            ),
            InlineKeyboardButton(
                text="Услуги и цены",
                callback_data="nav:services",
                style="primary",
                icon_custom_emoji_id=ICONS["service"],
            ),
        ],
        [
            InlineKeyboardButton(
                text="О студии",
                callback_data="nav:about",
                style="primary",
                icon_custom_emoji_id=ICONS["info"],
            ),
            InlineKeyboardButton(
                text="Контакты",
                callback_data="nav:contact",
                style="primary",
                icon_custom_emoji_id=ICONS["user"],
            ),
        ],
    ]

    if is_admin:
        rows.append([
            InlineKeyboardButton(
                text="Управление студией в боте",
                callback_data="admin:menu",
                style="primary",
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Главное меню",
                    callback_data="nav:main",
                    style="primary",
                )
            ]
        ]
    )


def client_my_bookings_keyboard(bookings: list) -> InlineKeyboardMarkup:
    rows = []
    # Add cancel buttons for active upcoming appointments
    active = [b for b in bookings if b.status in ("pending", "confirmed")]
    for b in active:
        rows.append([
            InlineKeyboardButton(
                text=f"Отменить запись #{b.id}",
                callback_data=f"client_cancel:{b.id}",
                style="danger",
            )
        ])
    rows.append([
        InlineKeyboardButton(
            text="Главное меню",
            callback_data="nav:main",
            style="primary",
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def client_booking_actions_keyboard(booking_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Отменить эту запись",
                    callback_data=f"client_cancel:{booking_id}",
                    style="danger",
                )
            ],
            [
                InlineKeyboardButton(
                    text="К списку записей",
                    callback_data="nav:my_bookings",
                    style="primary",
                )
            ],
        ]
    )


def client_cancel_confirmation_keyboard(booking_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да, отменить запись", callback_data=f"client_cancel:{booking_id}:confirm", style="danger", icon_custom_emoji_id=ICONS["inactive"])],
        [InlineKeyboardButton(text="Оставить запись", callback_data="nav:my_bookings", style="primary", icon_custom_emoji_id=ICONS["back"])],
    ])


def admin_main_keyboard() -> InlineKeyboardMarkup:
    admin_webapp_url = f"{settings.public_url.rstrip('/')}/miniapp/?tab=admin"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть админку (Mini App)",
                    web_app=WebAppInfo(url=admin_webapp_url),
                    style="success",
                    icon_custom_emoji_id=ICONS["admin"],
                )
            ],
            [
                InlineKeyboardButton(
                    text="Расписание на сегодня",
                    callback_data="admin:schedule_today",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text="Расписание на завтра",
                    callback_data="admin:schedule_tomorrow",
                    style="primary",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Заблокировать интервал",
                    callback_data="admin:block_prompt",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text="Снять блокировку",
                    callback_data="admin:unblock_list",
                    style="primary",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Прайс и услуги",
                    callback_data="admin:services",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text="+ Записать клиента",
                    callback_data="admin:manual_book",
                    style="primary",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Главное меню",
                    callback_data="nav:main",
                    style="primary",
                ),
            ],
        ]
    )


def admin_schedule_nav_keyboard(target_date: Any) -> InlineKeyboardMarkup:
    from datetime import date, timedelta
    if isinstance(target_date, str):
        target_date = date.fromisoformat(target_date)
    prev_d = (target_date - timedelta(days=1)).isoformat()
    next_d = (target_date + timedelta(days=1)).isoformat()

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="‹ Вчера",
                    callback_data=f"admin:schedule_date:{prev_d}",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text=f"{target_date.strftime('%d.%m')}",
                    callback_data="admin:schedule_today",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text="Завтра ›",
                    callback_data=f"admin:schedule_date:{next_d}",
                    style="primary",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Панель администратора",
                    callback_data="admin:menu",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text="Главное меню",
                    callback_data="nav:main",
                    style="primary",
                ),
            ],
        ]
    )


def admin_booking_keyboard(
    booking_id: int,
    status: str,
    back_target: str = "today",
    client_telegram_id: Optional[int] = None,
) -> InlineKeyboardMarkup:
    rows = []
    if status == "pending":
        rows.append([
            InlineKeyboardButton(
                text="Подтвердить запись",
                callback_data=f"admin_confirm:{booking_id}:{back_target}",
                style="success",
            ),
            InlineKeyboardButton(
                text="Отклонить",
                callback_data=f"admin_cancel:{booking_id}:{back_target}",
                style="danger",
            ),
        ])
    elif status == "confirmed":
        rows.append([
            InlineKeyboardButton(
                text="Визит завершён / Оплачено",
                callback_data=f"admin_complete:{booking_id}:{back_target}",
                style="success",
            )
        ])
        rows.append([
            InlineKeyboardButton(
                text="Отменить визит",
                callback_data=f"admin_cancel:{booking_id}:{back_target}",
                style="danger",
            )
        ])

    if client_telegram_id and client_telegram_id > 0:
        rows.append([
            InlineKeyboardButton(
                text="Написать клиенту в Telegram",
                url=f"tg://user?id={client_telegram_id}",
            )
        ])

    back_cb = (
        f"admin:schedule_date:{back_target}"
        if len(back_target) == 10 and "-" in back_target
        else ("admin:schedule_tomorrow" if back_target == "tomorrow" else "admin:schedule_today")
    )
    rows.append([
        InlineKeyboardButton(
            text="Назад к расписанию",
            callback_data=back_cb,
            style="primary",
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_notification_keyboard(booking_id: int, client_telegram_id: Optional[int] = None) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="Подтвердить",
                callback_data=f"admin_confirm:{booking_id}:today",
                style="success",
            ),
            InlineKeyboardButton(
                text="Отклонить",
                callback_data=f"admin_cancel:{booking_id}:today",
                style="danger",
            ),
        ],
        [
            InlineKeyboardButton(
                text="Открыть карточку",
                callback_data=f"admin_card:{booking_id}:today",
                style="primary",
            )
        ],
    ]
    if client_telegram_id and client_telegram_id > 0:
        rows.append([
            InlineKeyboardButton(
                text="Написать клиенту",
                url=f"tg://user?id={client_telegram_id}",
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def master_claim_keyboard(booking_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Взять заказ",
                    callback_data=f"master_claim:{booking_id}",
                    style="success",
                    icon_custom_emoji_id=ICONS.get("check"),
                )
            ]
        ]
    )


def master_assigned_keyboard(booking_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Отказаться от выполнения",
                    callback_data=f"master_decline:{booking_id}",
                    style="danger",
                )
            ]
        ]
    )


def client_reassign_choice_keyboard(booking_id: int, webapp_url: Optional[str] = None) -> InlineKeyboardMarkup:
    url = webapp_url or settings.public_url
    miniapp_url = f"{url.rstrip('/')}/miniapp/"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Подобрать свободного мастера",
                    callback_data=f"client_accept_any:{booking_id}",
                    style="success",
                    icon_custom_emoji_id=ICONS.get("check"),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Выбрать в приложении",
                    web_app=WebAppInfo(url=miniapp_url),
                    style="primary",
                    icon_custom_emoji_id=ICONS.get("booking"),
                )
            ],
        ]
    )


def admin_unblock_list_keyboard(blocks: list) -> InlineKeyboardMarkup:
    rows = []
    for blk in blocks:
        m_name = blk.master.full_name.split()[0] if (blk.master and blk.master.full_name and blk.master.full_name.split()) else "Мастер"
        date_str = blk.booking_date.strftime("%d.%m")
        time_str = f"{blk.start_time.strftime('%H:%M')}-{blk.end_time.strftime('%H:%M')}"
        rows.append([
            InlineKeyboardButton(
                text=f"Снять #{blk.id}: {m_name} {date_str} {time_str}",
                callback_data=f"admin_unblock:{blk.id}",
                style="danger",
            )
        ])
    rows.append([
        InlineKeyboardButton(
            text="Панель администратора",
            callback_data="admin:menu",
            style="primary",
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_services_keyboard(services: list) -> InlineKeyboardMarkup:
    rows = []
    for s in services:
        status_icon = "✓" if s.is_active else "✗"
        rows.append([
            InlineKeyboardButton(
                text=f"{status_icon} {s.name} — {int(s.price)} ₽",
                callback_data=f"admin_srv:{s.id}",
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
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_service_item_keyboard(service_id: int, is_active: bool) -> InlineKeyboardMarkup:
    toggle_text = "Скрыть из прайса" if is_active else "Активировать услугу"
    toggle_style = "danger" if is_active else "success"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Изменить цену",
                    callback_data=f"admin_srv_price:{service_id}",
                    style="primary",
                )
            ],
            [
                InlineKeyboardButton(
                    text=toggle_text,
                    callback_data=f"admin_srv_toggle:{service_id}",
                    style=toggle_style,
                )
            ],
            [
                InlineKeyboardButton(
                    text="Назад к списку услуг",
                    callback_data="admin:services",
                    style="primary",
                )
            ],
        ]
    )

