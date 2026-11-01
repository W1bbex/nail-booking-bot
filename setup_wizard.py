"""Interactive local configuration for Nail Atelier."""
import getpass
import json
import os
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit

from core.lock import SingleInstanceLock
from owner_setup import SetupError, api_call, identify_owner, mini_app_status

ROOT = Path(__file__).resolve().parent


def show_error(message: str) -> None:
    from launcher import enable_color
    print(f"\033[31m{message}\033[0m" if enable_color() else message)


def clipboard_text() -> str | None:
    """Read Unicode text only on an explicit Ctrl+V, without displaying it."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
    if not user32.OpenClipboard(None):
        return None
    try:
        handle = user32.GetClipboardData(13)  # CF_UNICODETEXT
        if not handle:
            return None
        address = kernel32.GlobalLock(handle)
        if not address:
            return None
        try:
            return ctypes.wstring_at(address)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def token_hint(token: str) -> tuple[int | None, bool]:
    """Typical token shape is only a hint; Telegram performs the actual validation."""
    prefix, separator, suffix = token.partition(":")
    if not separator or not prefix.isascii() or not prefix.isdigit():
        return None, False
    expected = len(prefix) + 1 + 35
    looks_typical = bool(re.fullmatch(r"[A-Za-z0-9_-]{35}", suffix))
    return expected, looks_typical


def token_display(token: str, width: int) -> tuple[str, bool]:
    expected, looks_typical = token_hint(token)
    count = f"{len(token)} / ~{expected}" if expected is not None else str(len(token))
    status = "формат похож" if looks_typical else "проверьте формат"
    prefix = "  Токен: "
    suffix = f"  < {count} >  {status}"
    available = max(0, width - 1 - len(prefix) - len(suffix))
    if available < len(token):
        masked = "*" * max(0, available - 1) + ("…" if available else "")
    else:
        masked = "*" * len(token)
    text = prefix + masked + suffix
    if len(text) >= width:
        text = (f"  Токен: < {len(token)} >")[:max(0, width - 1)]
    return text, looks_typical


def read_token() -> str | None:
    if os.name != "nt" or not sys.stdin.isatty():
        return getpass.getpass("\n  Вставьте токен: ").strip()

    import msvcrt

    print()
    chars = []
    from launcher import enable_color
    colored = enable_color()
    previous_width = 0

    def refresh() -> None:
        nonlocal previous_width
        columns = shutil.get_terminal_size((80, 25)).columns
        line, looks_typical = token_display("".join(chars), columns)
        padding = " " * max(0, min(previous_width, columns - 1) - len(line))
        if colored:
            code = "32" if looks_typical else "31"
            line = f"\033[{code}m{line}\033[0m"
        print(f"\r{line}{padding}", end="", flush=True)
        previous_width = len(token_display("".join(chars), columns)[0])

    refresh()
    while True:
        key = msvcrt.getwch()
        if key == "\x1b":
            print()
            return None
        if key in ("\r", "\n"):
            print()
            return "".join(chars).strip()
        if key == "\x03":
            raise KeyboardInterrupt
        if key == "\b":
            if chars:
                chars.pop()
                refresh()
        elif key == "\x16":
            pasted = clipboard_text()
            if pasted is None:
                print("\n  Не удалось прочитать буфер обмена. Попробуйте вставить ещё раз.")
                refresh()
            else:
                pasted = "".join(ch for ch in pasted if not ch.isspace())
                chars.extend(pasted)
                refresh()
        elif key in ("\x00", "\xe0"):
            msvcrt.getwch()
        elif key.isprintable() and not key.isspace():
            chars.append(key)
            refresh()


def valid_https_url(value: str) -> bool:
    url = urlsplit(value)
    return url.scheme == "https" and bool(url.hostname) and not url.username and not url.password


def normalize_app_url(value: str) -> str:
    value = value.strip()
    if "://" not in value:
        value = "https://" + value
    if value.startswith("http://"):
        value = "https://" + value[7:]
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or any(c.isspace() for c in value)):
            raise ValueError("Некорректный адрес")
        parsed.port
        path = parsed.path.rstrip("/")
        if path.endswith("/miniapp"):
            path = path[:-8]
        return f"https://{parsed.netloc}{path}"
    except ValueError:
        raise ValueError("Укажите адрес сайта, например example.org/app") from None


def configure(root: Path = ROOT, *, telegram_only: bool = False) -> bool:
    try:
        return _configure(root, telegram_only=telegram_only)
    except (KeyboardInterrupt, EOFError):
        return False


def _configure(root: Path, *, telegram_only: bool) -> bool:
    from wizard_ui import panel, clear, field, choose
    config_path, env_path = root / "config.json", root / ".env"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not telegram_only:
        choice = choose("Настройка", (("2", "Подключить бота"), ("1", "Локальное демо"), ("0", "Назад")))
        if choice == "0": return False
        if choice == "1":
            port = int(config["server"].get("port", 8080))
            config["server"].update(host="127.0.0.1", dev_mode=True, public_url=f"http://127.0.0.1:{port}")
            config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return True
    clear()
    panel("1 / 3  ·  Подключаем бота", ("Вставьте токен из @BotFather.", "Enter — проверить. Esc / Ctrl+C — назад."))
    while True:
        token = read_token()
        if not token: return False
        if not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", token):
            show_error("  Токен неполный. Скопируйте его целиком из @BotFather → API Token.")
            continue
        try:
            print("  Проверяем…", flush=True)
            bot = api_call(token, "getMe")
            if not bot.get("is_bot") or not bot.get("username"):
                raise SetupError("Не удалось определить бота.")
        except SetupError as exc:
            show_error(f"  {exc}")
            continue
        break
    bot_label = f"{bot.get('first_name') or 'Бот'} · @{bot['username']}"
    lock = SingleInstanceLock(root / "bot.lock")
    if not lock.acquire():
        panel("Бот уже запущен", ("Остановите его и повторите настройку.",))
        field("Enter — назад")
        return False
    try:
        main_status, menu_status = mini_app_status(token, bot)
        main = "[ВКЛ]" if "включён" in main_status else "[НЕТ]" if "отключён" in main_status else "[?]"
        menu = "[ВКЛ]" if "настроен" in menu_status else "[НЕТ]" if "команды" in menu_status else "[?]"
        method = choose("2 / 3  ·  Кто владелец?", (
            ("1", "Определить через /start"), ("2", "Ввести Telegram ID"),
            ("3", "Указать @username"), ("0", "Назад")),
            (bot_label, "", f"{main} Кнопка приложения в профиле", f"{menu} Кнопка приложения в чате",
             "Настроить: @BotFather → Mini Apps → Fullsize"))
        if method == "0": return False
        clear()
        panel("Владелец", (bot_label, "Esc / Ctrl+C — назад"))
        if method == "2":
            while True:
                value = field("Telegram ID")
                if value.isdigit() and int(value) > 0:
                    admin = int(value)
                    break
                show_error("  Введите числовой ID.")
        elif method == "3":
            while True:
                expected = field("Ваш @username").lstrip("@")
                if re.fullmatch(r"[A-Za-z0-9_]{5,32}", expected): break
                show_error("  Username — от 5 до 32 латинских букв, цифр или _.")
            admin = identify_owner(token, bot["username"], expected_username=expected)
        elif method == "1":
            admin = identify_owner(token, bot["username"])
        else:
            return False
    except SetupError as exc:
        panel("Не удалось продолжить", (str(exc),))
        field("Enter — назад")
        return False
    finally:
        lock.release()
    if admin is None: return False
    owner_label = f"@{expected} · ID {admin}" if method == "3" else f"ID {admin}"
    clear()
    panel("3 / 3  ·  Где открывать запись?", (bot_label, f"Владелец: {owner_label}", "", "Вставьте ссылку на приложение.", "https:// и нужный путь подставим сами."))
    while True:
        raw = field("Ссылка")
        if not raw: return False
        try:
            url = normalize_app_url(raw)
            break
        except ValueError as exc:
            show_error(f"  {exc}")
    existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    lines = [line for line in existing.splitlines() if not re.match(r"\s*(?:export\s+)?BOT_TOKEN\s*=", line)]
    lines.append(f"BOT_TOKEN={token}")
    config["admin_telegram_ids"] = [admin]
    config["server"].update(public_url=url, dev_mode=False)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    clear()
    panel("ГОТОВО · настройки сохранены", (bot_label, f"Владелец: {owner_label}", f"Приложение: {url}/miniapp/"))
    return True


if __name__ == "__main__":
    configure()
