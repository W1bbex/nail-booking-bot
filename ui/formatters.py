import html
from datetime import date, time
from typing import Optional
from ui.icons import STATUS_BADGES


def escape(text: Optional[str]) -> str:
    if not text:
        return ""
    return html.escape(str(text), quote=False)


def format_money(amount: float) -> str:
    return f"{int(amount):,} ₽".replace(",", " ")


def format_time(t: time) -> str:
    return t.strftime("%H:%M")


def format_date(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def format_status(status_key: str) -> str:
    return STATUS_BADGES.get(status_key, f"[{status_key.upper()}]")
