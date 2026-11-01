# tg-bot-ui Icon registry & helpers
# In accordance with tg-bot-ui skill:
# 1. No generic Unicode emojis in text or buttons.
# 2. Text uses clean typography, box-drawing characters, and HTML formatting.

# IDs copied from the verified adaptive icon map shipped with tg-bot-ui.
ICONS = {
    "booking": "5420099516093214877",
    "calendar": "5420358515506064338",
    "service": "5420398828069103773",
    "clock": "5420099516093214877",
    "check": "5422357565084314125",
    "back": "5420414676498424358",
    "info": "5420370627313839231",
    "user": "5420254134915878201",
    "admin": "5420219070802864426",
    "active": "5422357565084314125",
    "inactive": "5420414676498424358",
}

FALLBACKS = {
    "booking": "🕒", "calendar": "📅", "service": "🏷️", "clock": "🕒",
    "check": "✅", "back": "⬅️", "info": "ℹ️", "user": "👤", "admin": "⚙️",
    "active": "✅", "inactive": "⬅️",
}


def tg_icon(name: str) -> str:
    emoji_id = ICONS.get(name)
    fallback = FALLBACKS.get(name, "·")
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>' if emoji_id else fallback

# Status badges and symbols using clean typographic markers
STATUS_BADGES = {
    "pending": "[ОЖИДАЕТ]",
    "confirmed": "[ПОДТВЕРЖДЕНА]",
    "cancelled_by_client": "[ОТМЕНЕНА КЛИЕНТОМ]",
    "cancelled_by_admin": "[ОТМЕНЕНА МАСТЕРОМ]",
    "completed": "[ЗАВЕРШЕНА]",
}
