import re
from xml.etree import ElementTree

from ui.dashboards import start_dashboard
from ui.icons import FALLBACKS, ICONS
from ui.keyboards import client_main_keyboard


def test_start_dashboard_custom_emoji_html_is_parseable():
    text = start_dashboard()
    root = ElementTree.fromstring(f"<root>{text}</root>")

    assert root.find(".//tg-emoji") is not None
    assert "<tg-emoji" in text
    assert "ENTITY_TEXT_INVALID" not in text


def test_custom_emoji_registry_uses_known_ids_and_emoji_fallbacks():
    documented = {
        "5420099516093214877": "🕒",
        "5420358515506064338": "📅",
        "5420398828069103773": "🏷️",
        "5422357565084314125": "✅",
        "5420414676498424358": "⬅️",
        "5420370627313839231": "ℹ️",
        "5420254134915878201": "👤",
        "5420219070802864426": "⚙️",
    }
    for key, emoji_id in ICONS.items():
        assert emoji_id in documented.values() or emoji_id in documented
        assert FALLBACKS[key] == documented[emoji_id]


def test_online_booking_button_is_green_and_has_custom_emoji_chip():
    keyboard = client_main_keyboard()
    button = keyboard.inline_keyboard[0][0]

    assert button.text == "Открыть кабинет"
    assert button.style == "success"
    assert button.icon_custom_emoji_id == ICONS["booking"]
    assert not re.search(r"[\U0001F300-\U0001FAFF]", button.text)
