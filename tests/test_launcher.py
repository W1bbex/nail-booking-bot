import json
from types import SimpleNamespace

import launcher
import console_mouse
from console_mouse import menu_hit


def test_repeated_cancel_never_opens_another_prompt(monkeypatch):
    choices = iter(["interrupt", "2", "0"])
    def choose():
        value = next(choices)
        if value == "interrupt": raise KeyboardInterrupt
        return value
    def cancel(**kwargs): raise KeyboardInterrupt
    def unexpected(*args): raise AssertionError("No prompt is allowed during cancellation")
    monkeypatch.setattr(launcher, "choose_action", choose)
    monkeypatch.setattr("setup_wizard.configure", cancel)
    monkeypatch.setattr("wizard_ui.field", unexpected)
    launcher.main()


def test_mouse_hit_only_accepts_menu_rows():
    assert menu_hit(8, 16, 0, 10, 4) == 0
    assert menu_hit(8, 18, 0, 10, 4) == 1
    assert menu_hit(8, 17, 0, 10, 4) == 0
    assert menu_hit(44, 19, 0, 10, 4) == 1
    assert menu_hit(2, 16, 0, 10, 4) == 0
    assert menu_hit(50, 16, 0, 10, 4) is None
    assert menu_hit(8, 24, 0, 10, 4) is None


def test_first_click_selects_and_second_click_activates(monkeypatch):
    def mouse(y, pressed):
        return SimpleNamespace(event_type=2, event=SimpleNamespace(mouse=SimpleNamespace(
            position=SimpleNamespace(x=10, y=y), buttons=int(pressed), flags=0)))

    events = iter([mouse(6, True), mouse(6, False), mouse(6, True)])
    seen = []

    class FakeConsole:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def cursor(self):
            return (0, 0)

        def enable_mouse(self):
            pass

        def read(self):
            seen.append("read")
            return next(events)

    monkeypatch.setattr(console_mouse, "ConsoleInput", FakeConsole)
    monkeypatch.setattr(launcher.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(launcher.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(launcher.os, "system", lambda _: 0)
    monkeypatch.setattr(launcher, "show_menu", lambda *args, **kwargs: None)
    assert launcher.choose_action() == "1"
    assert len(seen) == 3


def test_mouse_wheel_moves_selection(monkeypatch):
    wheel = SimpleNamespace(event_type=2, event=SimpleNamespace(mouse=SimpleNamespace(
        position=SimpleNamespace(x=10, y=6), buttons=(0xFF88 << 16), flags=4)))
    enter = SimpleNamespace(event_type=1, event=SimpleNamespace(key=SimpleNamespace(
        down=True, virtual_key=0x0D, char=SimpleNamespace(unicode="\r"))))
    events = iter([wheel, enter])

    class FakeConsole:
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def cursor(self): return (0, 0)
        def enable_mouse(self): pass
        def read(self): return next(events)

    monkeypatch.setattr(console_mouse, "ConsoleInput", FakeConsole)
    monkeypatch.setattr(launcher.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(launcher.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(launcher.os, "system", lambda _: 0)
    monkeypatch.setattr(launcher, "show_menu", lambda *args, **kwargs: None)
    assert launcher.choose_action() == "2"


def test_menu_items_do_not_move_with_selection(capsys):
    positions = []
    for selected in range(len(launcher.MENU_ITEMS)):
        launcher.show_menu(selected, interactive=True)
        lines = capsys.readouterr().out.splitlines()
        positions.append([next(i for i, line in enumerate(lines) if label in line)
                          for _, label, _ in launcher.MENU_ITEMS])
    assert all(position == positions[0] for position in positions)


def test_preview_stops_process_on_enter(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text(json.dumps({"server": {"port": 8080}}), encoding="utf-8")
    events = []

    class Process:
        def poll(self):
            return None

        def send_signal(self, value):
            events.append("stop")

        def wait(self, timeout=None):
            events.append("wait")

    class Thread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(launcher.threading, "Thread", Thread)
    monkeypatch.setattr("builtins.input", lambda: "")
    launcher.preview()
    assert events == ["stop", "wait"]
