"""Small, consistent terminal controls for the setup wizard."""
import os
import shutil
import sys
import textwrap


def clear() -> None:
    if os.name == "nt" and sys.stdout.isatty():
        os.system("cls")


def panel(title: str, lines=()) -> None:
    from launcher import enable_color
    width = max(25, min(58, shutil.get_terminal_size((80, 25)).columns - 6))
    print("\n  ┌" + "─" * width + "┐")
    heading = f" {title} "[:width].ljust(width)
    print("  │" + (f"\033[7m{heading}\033[0m" if enable_color() else heading) + "│")
    print("  ├" + "─" * width + "┤")
    for line in lines:
        for part in textwrap.wrap(str(line), width=width - 4) or [""]:
            print("  │  " + part.ljust(width - 4) + "  │")
    print("  └" + "─" * width + "┘")


def field(label: str, default: str = "") -> str:
    prompt = f"  {label}" + (f" [{default}]" if default else "") + ": "
    if os.name != "nt" or not sys.stdin.isatty() or not sys.stdout.isatty():
        value = input(prompt).strip()
        if value == "\x1b":
            raise KeyboardInterrupt
        return value or default
    import msvcrt
    from setup_wizard import clipboard_text
    print(prompt, end="", flush=True)
    chars = []
    length = 0
    while True:
        key = msvcrt.getwch()
        if key in ("\x1b", "\x03"):
            raise KeyboardInterrupt
        if key == "\r":
            print()
            return "".join(chars).strip() or default
        if key == "\b":
            if chars: chars.pop()
        elif key == "\x16":
            chars.extend(ch for ch in (clipboard_text() or "") if ch.isprintable())
        elif key in ("\x00", "\xe0"):
            msvcrt.getwch()
        elif key.isprintable():
            chars.append(key)
        available = max(1, shutil.get_terminal_size((80, 25)).columns - len(prompt) - 2)
        visible = "".join(chars)[-available:]
        print("\r" + prompt + visible + " " * max(0, length - len(visible)), end="", flush=True)
        length = len(visible)


def choose(title: str, options: tuple, lines=()) -> str:
    if os.name != "nt" or not sys.stdin.isatty() or not sys.stdout.isatty():
        panel(title, lines)
        for key, label in options: print(f"  {key}. {label}")
        return field("Выбор", options[0][0])
    from console_mouse import ConsoleInput
    from launcher import enable_color
    selected, armed, left = 0, None, False
    with ConsoleInput() as console:
        while True:
            clear()
            console.enable_mouse()
            panel(title, lines)
            x, y = console.cursor()
            for index, (_key, label) in enumerate(options):
                row = f"  {'›' if index == selected else ' '}  {label}"
                print(f"\033[7m{row}\033[0m" if index == selected and enable_color() else row)
                print()
            print("  ↑↓ / колесо / мышь — выбор  ·  Enter — дальше  ·  Esc — назад", flush=True)
            while True:
                event = console.read()
                if event.event_type == 1 and event.event.key.down:
                    key = event.event.key
                    if key.virtual_key in (0x1B,): raise KeyboardInterrupt
                    if key.virtual_key == 13: return options[selected][0]
                    if key.virtual_key in (0x26, 0x28):
                        selected = (selected + (-1 if key.virtual_key == 0x26 else 1)) % len(options)
                        armed = None
                        break
                    if key.char.unicode in {key for key, _ in options}: return key.char.unicode
                elif event.event_type == 2:
                    mouse = event.event.mouse
                    if mouse.flags == 4:
                        selected = max(0, min(len(options)-1, selected + (-1 if mouse.buttons >> 16 < 32768 else 1)))
                        armed = None
                        break
                    pressed = bool(mouse.buttons & 1)
                    row = (mouse.position.y - y) // 2
                    if pressed and not left and mouse.flags in (0, 2):
                        if 0 <= row < len(options) and 2 <= mouse.position.x <= 60:
                            if armed == row: return options[row][0]
                            armed, selected, left = row, row, True
                            break
                        armed = None
                    left = pressed
