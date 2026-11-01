"""Standalone visual comparison of terminal menu patterns."""
import os
import sys

from launcher import enable_color

ITEMS = ("Посмотреть пример записи", "Подключить своего бота", "Запустить бота", "Выход")
STYLES = (("1", "Рамка"), ("2", "Рамка · компактная"),
          ("3", "Рамка · панель"), ("4", "Рамка · с пояснением"))
DESCRIPTIONS = ("Открыть страницу записи в браузере", "Настроить бота для своей студии",
                "Начать принимать записи", "Закрыть окно")


def render(style: int, selected: int, colored: bool) -> str:
    def color(value: str, code: str) -> str:
        return f"\x1b[{code}m{value}\x1b[0m" if colored else value

    number, title = STYLES[style]
    lines = [f"  ОБРАЗЕЦ {number}  ·  {title}", ""]
    if number == "1":
        lines += ["  NAIL ATELIER", "  Выберите действие", ""]
        for index, label in enumerate(ITEMS):
            if index == selected:
                lines += ["  ┌─────────────────────────────────────────┐",
                          f"  │  ›  {label:<36}│",
                          "  └─────────────────────────────────────────┘"]
            else:
                lines += [f"       {label}", ""]
    elif number == "2":
        lines += ["  NAIL ATELIER  /  УПРАВЛЕНИЕ", "", "  Выберите действие", ""]
        for index, label in enumerate(ITEMS):
            if index == selected:
                lines.append(f"  [ › {label:<34} ]")
            else:
                lines.append(f"      {label}")
    elif number == "3":
        lines += ["  ┌─ NAIL ATELIER ──────────────────────────┐",
                  f"  │  {'Панель студии':<39}│",
                  "  ├─────────────────────────────────────────┤",
                  f"  │  {'Выберите действие':<39}│",
                  f"  │  {'':<39}│"]
        for index, label in enumerate(ITEMS):
            text = f"›  {label}" if index == selected else f"   {label}"
            row = f"  {text:<39}"
            lines.append("  │" + (color(row, "7") if index == selected else row) + "│")
            lines.append(f"  │  {'':<39}│")
        lines.append("  └─────────────────────────────────────────┘")
    else:
        lines += ["  NAIL ATELIER", "  Панель управления студией", ""]
        for index, label in enumerate(ITEMS):
            if index == selected:
                lines += ["  ┌─────────────────────────────────────────┐",
                          f"  │  ›  {label:<36}│",
                          "  ├─────────────────────────────────────────┤",
                          f"  │  {'ПОСЛЕ ВЫБОРА':<39}│",
                          f"  │  {DESCRIPTIONS[index]:<39}│",
                          "  └─────────────────────────────────────────┘"]
            else:
                lines.append(f"       {label}")
        lines.append("")
    lines += ["", color("  Tab — следующий  ·  1–4 — образец  ·  ↑↓ — выбор  ·  Esc — выход", "90")]
    return "\n".join(lines)


def main() -> None:
    colored = enable_color()
    if os.name != "nt" or not sys.stdin.isatty() or not sys.stdout.isatty():
        for style in range(len(STYLES)):
            print(render(style, 0, False), "\n")
        return
    import msvcrt

    style = selected = 0
    while True:
        os.system("cls")
        print(render(style, selected, colored), flush=True)
        key = msvcrt.getwch()
        if key in ("\x00", "\xe0"):
            direction = msvcrt.getwch()
            if direction == "H":
                selected = (selected - 1) % len(ITEMS)
            elif direction == "P":
                selected = (selected + 1) % len(ITEMS)
        elif key == "\t":
            style = (style + 1) % len(STYLES)
        elif key in {number for number, _ in STYLES}:
            style = next(index for index, (number, _) in enumerate(STYLES) if number == key)
        elif key in ("\x1b", "\x03"):
            return


if __name__ == "__main__":
    main()
