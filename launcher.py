"""Interactive launcher for the local Windows installation."""
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def enable_color() -> bool:
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR") is not None:
        return False
    if os.name != "nt":
        return True
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetStdHandle.restype = wintypes.HANDLE
    kernel.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    handle = kernel.GetStdHandle(-11)
    mode = wintypes.DWORD()
    return bool(kernel.GetConsoleMode(handle, ctypes.byref(mode)) and
                kernel.SetConsoleMode(handle, mode.value | 0x0004))


MENU_ITEMS = (
    ("1", "Посмотреть пример записи", "Открыть готовый пример в браузере"),
    ("2", "Подключить своего бота", "Настроить Telegram для вашей студии"),
    ("3", "Запустить бота", "Принимать записи от клиентов"),
    ("0", "Выход", "Закрыть панель"),
)


def show_menu(selected: int = 0, interactive: bool = False) -> None:
    colored = enable_color()
    def paint(text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if colored else text

    print("\n  ┌─ NAIL ATELIER ──────────────────────────┐")
    print(f"  │  {'Панель студии':<39}│")
    print("  ├─────────────────────────────────────────┤")
    print(f"  │  {'Выберите действие':<39}│")
    print(f"  │  {'':<39}│")
    for index, (key, label, _description) in enumerate(MENU_ITEMS):
        prefix = ("›  " if index == selected else "   ") if interactive else f"{key}  "
        row = f"  {prefix + label:<39}"
        print("  │" + (paint(row, "7") if interactive and index == selected else row) + "│")
        print(f"  │  {'':<39}│")
    print("  └─────────────────────────────────────────┘")
    print("\n  ↑↓ / колесо / мышь  Выбрать   Enter / 2 клика  Открыть   Esc  Выход" if interactive else
          "\n  Введите номер действия и нажмите Enter")
    print()


def choose_action() -> str:
    if os.name != "nt" or not sys.stdin.isatty() or not sys.stdout.isatty():
        show_menu()
        return input("  Ваш выбор: ").strip()
    from console_mouse import ConsoleInput, menu_hit
    selected = 0
    armed = None
    left_down = False
    with ConsoleInput() as console:
        enable_color()
        return read_menu_events(console, menu_hit, selected, armed, left_down)


def read_menu_events(console, menu_hit, selected=0, armed=None, left_down=False) -> str:
        while True:
            os.system("cls")
            console.enable_mouse()
            origin_x, origin_y = console.cursor()
            show_menu(selected, interactive=True)
            sys.stdout.flush()
            while True:
                event = console.read()
                if event.event_type == 1 and event.event.key.down:
                    key = event.event.key
                    if key.virtual_key in (0x26, 0x28):
                        selected = (selected + (-1 if key.virtual_key == 0x26 else 1)) % len(MENU_ITEMS)
                        armed = None
                        break
                    if key.virtual_key == 0x0D:
                        return MENU_ITEMS[selected][0]
                    if key.virtual_key == 0x1B:
                        return "0"
                    if key.char.unicode in {item[0] for item in MENU_ITEMS}:
                        return key.char.unicode
                elif event.event_type == 2:
                    mouse = event.event.mouse
                    if mouse.flags == 4:
                        delta = (mouse.buttons >> 16) & 0xFFFF
                        delta = delta - 0x10000 if delta & 0x8000 else delta
                        if delta:
                            selected = max(0, min(len(MENU_ITEMS) - 1, selected + (-1 if delta > 0 else 1)))
                            armed = None
                            break
                    pressed = bool(mouse.buttons & 1)
                    if pressed and not left_down and mouse.flags in (0, 2):
                        index = menu_hit(mouse.position.x, mouse.position.y, origin_x, origin_y, len(MENU_ITEMS))
                        if index is not None:
                            if armed == index:
                                return MENU_ITEMS[index][0]
                            armed = index
                            if selected != index:
                                selected = index
                                left_down = True
                                break
                        else:
                            armed = None
                    left_down = pressed


def preview() -> None:
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    port = int(config["server"].get("port", 8080))
    address = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env["NAIL_LOCAL_PREVIEW"] = "1"
    print("\n  Открываем пример. Подождите несколько секунд.\n"
          "  Чтобы закончить просмотр, вернитесь сюда и нажмите Enter.\n")
    process = subprocess.Popen(
        [sys.executable, "-u", str(ROOT / "bot.py")], cwd=ROOT, env=env,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )

    def open_when_ready() -> None:
        for _ in range(60):
            if process.poll() is not None:
                return
            try:
                with urllib.request.urlopen(address + "/api/health", timeout=0.5) as response:
                    health = json.load(response)
                if health.get("service") == "nail-booking-bot" and health.get("dev_mode") is True:
                    webbrowser.open(address + "/miniapp/")
                    return
            except (OSError, ValueError):
                pass
            time.sleep(0.25)
        print("\n  Не удалось открыть пример. Проверьте сообщение об ошибке выше.")

    threading.Thread(target=open_when_ready, daemon=True).start()
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        if process.poll() is None:
            try:
                process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
                process.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                process.terminate()
                process.wait(timeout=5)


def main() -> None:
    from wizard_ui import field, clear, panel
    while True:
        try:
            choice = choose_action()
            if choice == "0": return
            clear()
            if choice == "1":
                preview()
            elif choice == "2":
                from setup_wizard import configure
                if not configure(telegram_only=True): continue
            elif choice == "3":
                config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
                if config["server"].get("dev_mode", False):
                    panel("Бот пока не подключён", ("Выберите «Подключить своего бота» в главном меню.",))
                else:
                    print("  Бот запускается. Ctrl+C — остановить и вернуться.")
                    subprocess.run([sys.executable, "-u", str(ROOT / "bot.py")], cwd=ROOT, check=False)
            field("Enter — вернуться в меню")
        except EOFError:
            return
        except KeyboardInterrupt:
            # Never prompt inside cancellation handling: repeated Ctrl+C is safe.
            continue


if __name__ == "__main__":
    main()
