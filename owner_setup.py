"""Validate a bot and identify its owner during interactive setup."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime


class SetupError(Exception):
    pass


def api_call(token: str, method: str, params: dict | None = None) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    body = urllib.parse.urlencode(params or {}).encode("utf-8")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=8) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise SetupError("Telegram отклонил токен. Откройте @BotFather → /mybots → ваш бот → API Token, скопируйте токен целиком и вставьте снова.") from None
        if exc.code == 409:
            raise SetupError("Бот уже запущен в другом месте. Остановите его и повторите настройку.") from None
        raise SetupError(f"Telegram вернул ошибку {exc.code}. Попробуйте позже.") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise SetupError("Не удалось связаться с Telegram. Проверьте интернет и повторите попытку.") from None
    if not result.get("ok"):
        raise SetupError("Telegram не выполнил запрос. Попробуйте повторить настройку.")
    return result.get("result")


def mini_app_status(token: str, bot: dict) -> tuple[str, str]:
    """Report only the configuration states exposed by the Bot API."""
    main = bot.get("has_main_web_app")
    if main is True:
        main_status = "Main App: включён."
    elif main is False:
        main_status = "Main App: отключён."
    else:
        main_status = "Main App: Telegram не сообщил статус."
    try:
        button = api_call(token, "getChatMenuButton")
    except SetupError:
        return main_status, "Menu Button: не удалось проверить."
    if not isinstance(button, dict):
        return main_status, "Menu Button: Telegram не сообщил статус."
    if button.get("type") == "web_app":
        menu_status = "Menu Button: настроен для Mini App."
    elif button.get("type") in ("default", "commands"):
        menu_status = "Menu Button: открывает команды, а не Mini App."
    else:
        menu_status = "Menu Button: Telegram не сообщил статус."
    return main_status, menu_status


def identify_owner(token: str, username: str, *, timeout: float = 180, expected_username: str | None = None) -> int | None:
    from wizard_ui import panel, clear, choose
    webhook = api_call(token, "getWebhookInfo")
    if webhook.get("url"):
        raise SetupError("У бота включён webhook. Для настройки нужен свободный тестовый бот; webhook не изменён.")

    clear()
    panel("Ждём сообщение в Telegram", (f"Откройте @{username} и отправьте /start.",
          f"Ждём @{expected_username}." if expected_username else "Покажем профиль первого написавшего.",
          "Esc / Ctrl+C — назад. Ожидание до 3 минут."))
    started = int(time.time()) - 30
    deadline = time.monotonic() + timeout
    offset = None
    while time.monotonic() < deadline:
        try:
            import msvcrt
            if msvcrt.kbhit() and msvcrt.getwch() == "\x1b":
                return None
        except ImportError:
            pass
        params = {"timeout": 2, "allowed_updates": '["message"]'}
        if offset is not None:
            params["offset"] = offset
        try:
            updates = api_call(token, "getUpdates", params)
        except SetupError:
            time.sleep(1)
            continue
        for update in updates:
            offset = max(offset or 0, update["update_id"] + 1)
            message = update.get("message") or {}
            chat = message.get("chat") or {}
            user = message.get("from") or {}
            command = (message.get("text") or "").split(maxsplit=1)[0:1]
            command = command[0].split("@", 1)[0] if command else ""
            if (message.get("date", 0) < started or chat.get("type") != "private"
                    or user.get("is_bot") or not user.get("id") or command != "/start"):
                continue
            if expected_username and user.get("username", "").casefold() != expected_username.casefold():
                print("  Это другой аккаунт. Ждём /start от указанного пользователя.")
                continue
            try:
                api_call(token, "sendMessage", {"chat_id": chat["id"], "text": "Проверьте терминал."})
            except SetupError:
                print("  Не удалось отправить ответ в Telegram. Проверьте профиль ниже.")
            name = " ".join(filter(None, (user.get("first_name"), user.get("last_name")))) or "Без имени"
            name = "".join(ch for ch in name if ch.isprintable())
            handle = "@" + user["username"] if user.get("username") else "имя пользователя не указано"
            stamp = datetime.fromtimestamp(message["date"]).strftime("%H:%M:%S")
            print(f"\n  {stamp}  {name}  |  ID: {user['id']}  |  {handle}")
            if expected_username:
                print(f"  @{expected_username} найден. Владелец определён.")
                return int(user["id"])
            answer = choose("Назначить владельцем?", (("1", "Да, это мой аккаунт"), ("2", "Нет, ждать другого")),
                            (name, f"ID: {user['id']} · {handle}"))
            if answer in ("1", "д", "да", "y", "yes"):
                return int(user["id"])
            print("  Не назначаем администратора. Отправьте /start ещё раз с нужного аккаунта.")
    print("  Время ожидания истекло. Повторите настройку, когда будете готовы.")
    return None
