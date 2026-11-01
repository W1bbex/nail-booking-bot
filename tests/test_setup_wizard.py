import json
import sys
import pytest

from setup_wizard import configure, valid_https_url, read_token, token_display, token_hint, normalize_app_url


@pytest.mark.parametrize("value", ["example.org/demo/", "https://example.org/demo/miniapp/", "http://example.org/demo"])
def test_app_url_is_normalized(value):
    assert normalize_app_url(value) == "https://example.org/demo"


@pytest.mark.parametrize("stage", ["token", "method", "username", "owner", "url"])
def test_cancel_at_each_setup_stage_preserves_saved_settings(stage, tmp_path, monkeypatch):
    original = '{"server": {"dev_mode": true}, "admin_telegram_ids": []}'
    (tmp_path / "config.json").write_text(original, encoding="utf-8")
    (tmp_path / ".env").write_text("BOT_TOKEN=existing\n", encoding="utf-8")
    def cancel(*args, **kwargs): raise KeyboardInterrupt
    monkeypatch.setattr("setup_wizard.read_token", cancel if stage == "token" else lambda: "123456:abcdef")
    monkeypatch.setattr("setup_wizard.api_call", lambda *args: {"is_bot": True, "username": "sample_bot"})
    monkeypatch.setattr("setup_wizard.mini_app_status", lambda *args: ("отключён", "команды"))
    def choose(*args):
        if stage == "method": cancel()
        return "3" if stage == "username" else "1"
    monkeypatch.setattr("wizard_ui.choose", choose)
    monkeypatch.setattr("wizard_ui.field", lambda *args: cancel())
    monkeypatch.setattr("setup_wizard.identify_owner", cancel if stage == "owner" else lambda *args: 42)
    assert configure(tmp_path, telegram_only=True) is False
    assert (tmp_path / "config.json").read_text(encoding="utf-8") == original
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "BOT_TOKEN=existing\n"


def test_token_hint_distinguishes_typical_format_from_digits():
    expected, matches = token_hint("1234567890:" + "A" * 35)
    assert expected == 46 and matches
    assert token_hint("12345678901234567890") == (None, False)
    assert token_hint("1234567890:" + "A" * 34) == (46, False)


def test_token_display_fits_narrow_terminal_without_revealing_token():
    token = "1234567890:" + "A" * 130
    line, matches = token_display(token, 52)
    assert len(line) < 52
    assert token not in line
    assert "141 / ~46" in line
    assert not matches


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_long_paste_and_backspace_never_wrap_counter(monkeypatch, capsys):
    import msvcrt
    import os
    import setup_wizard

    secret = "1234567890:" + "A" * 100
    keys = iter(["\x16", "\b", "\x1b"])
    monkeypatch.setattr(setup_wizard.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(msvcrt, "getwch", lambda: next(keys))
    monkeypatch.setattr(setup_wizard, "clipboard_text", lambda: secret)
    monkeypatch.setattr(setup_wizard.shutil, "get_terminal_size", lambda *args, **kwargs: os.terminal_size((52, 25)))
    assert read_token() is None
    output = capsys.readouterr().out
    assert secret not in output
    assert all(len(line) < 52 for line in output.replace("\n", "\r").split("\r"))
    assert "111 / ~46" in output and "110 / ~46" in output


def test_escape_cancels_secret_input_without_echo(monkeypatch, capsys):
    import msvcrt
    import setup_wizard

    keys = iter(["s", "e", "c", "\x1b"])
    monkeypatch.setattr(setup_wizard.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(msvcrt, "getwch", lambda: next(keys))
    assert read_token() is None
    assert "sec" not in capsys.readouterr().out


def test_ctrl_v_pastes_token_without_exposing_it(monkeypatch, capsys):
    import msvcrt
    import setup_wizard

    keys = iter(["\x16", "\r"])
    monkeypatch.setattr(setup_wizard.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(msvcrt, "getwch", lambda: next(keys))
    monkeypatch.setattr(setup_wizard, "clipboard_text", lambda: " 123456 :abc def\n")
    assert read_token() == "123456:abcdef"
    output = capsys.readouterr().out
    assert "123456:abcdef" not in output
    assert "*************" in output


def test_token_entry_ignores_accidental_spaces(monkeypatch, capsys):
    import msvcrt
    import setup_wizard

    keys = iter([" ", "1", "2", "3", ":", "a", " ", "b", " ", "\r"])
    monkeypatch.setattr(setup_wizard.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(msvcrt, "getwch", lambda: next(keys))
    assert read_token() == "123:ab"
    assert "123:ab" not in capsys.readouterr().out


def test_cancel_does_not_change_settings(tmp_path, monkeypatch):
    config = '{"server": {"dev_mode": true}}'
    (tmp_path / "config.json").write_text(config, encoding="utf-8")
    (tmp_path / ".env").write_text("BOT_TOKEN=existing\n", encoding="utf-8")
    monkeypatch.setattr("setup_wizard.read_token", lambda: None)
    assert not configure(tmp_path, telegram_only=True)
    assert (tmp_path / "config.json").read_text(encoding="utf-8") == config
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "BOT_TOKEN=existing\n"


def test_invalid_token_can_be_retried_then_cancelled(tmp_path, monkeypatch, capsys):
    (tmp_path / "config.json").write_text('{"server": {"dev_mode": true}}', encoding="utf-8")
    tokens = iter(["incomplete", None])
    monkeypatch.setattr("setup_wizard.read_token", lambda: next(tokens))
    assert not configure(tmp_path, telegram_only=True)
    assert "@BotFather" in capsys.readouterr().out
    assert not (tmp_path / ".env").exists()


def test_telegram_setup_disables_demo_and_preserves_other_secrets(tmp_path, monkeypatch, capsys):
    config = {"server": {"host": "127.0.0.1", "port": 8080, "dev_mode": True}, "admin_telegram_ids": []}
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET_KEY=keep\nBOT_TOKEN=old\n", encoding="utf-8")
    answers = iter(["2", "1", "https://example.org"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    monkeypatch.setattr("getpass.getpass", lambda prompt: "123456:abcdefghijklmnopqrstuvwxyz")
    monkeypatch.setattr("setup_wizard.api_call", lambda *args: {"is_bot": True, "username": "example_bot"})
    monkeypatch.setattr("setup_wizard.mini_app_status", lambda *args: ("Main App: статус", "Menu Button: статус"))
    monkeypatch.setattr("setup_wizard.identify_owner", lambda *args: 42)
    assert configure(tmp_path)
    result = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert result["server"]["dev_mode"] is False
    assert result["admin_telegram_ids"] == [42]
    assert "SECRET_KEY=keep" in (tmp_path / ".env").read_text(encoding="utf-8")
    output = capsys.readouterr().out
    assert "Fullsize" in output and "@example_bot" in output and "настройки сохранены" in output


def test_https_address_validation():
    assert valid_https_url("https://example.org")
    assert not valid_https_url("http://example.org")
    assert not valid_https_url("https://user:pass@example.org")


def test_owner_can_be_confirmed_by_numeric_id(tmp_path, monkeypatch):
    config = {"server": {"host": "127.0.0.1", "dev_mode": True}, "admin_telegram_ids": []}
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    answers = iter(["2", "42", "https://example.org/demo/miniapp/"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    monkeypatch.setattr("setup_wizard.read_token", lambda: "123456:abcdef")
    monkeypatch.setattr("setup_wizard.api_call", lambda *args: {"is_bot": True, "username": "example_bot"})
    monkeypatch.setattr("setup_wizard.mini_app_status", lambda *args: ("Main App: отключён", "Menu Button: команды"))
    assert configure(tmp_path, telegram_only=True)
    result = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert result["admin_telegram_ids"] == [42]
    assert result["server"]["public_url"] == "https://example.org/demo"


def test_preview_uses_local_demo_without_changing_configuration(monkeypatch):
    from core.config import Settings

    monkeypatch.setenv("NAIL_LOCAL_PREVIEW", "1")
    settings = Settings()
    assert settings.dev_mode is True
    assert settings.host == "127.0.0.1"
    assert settings.public_url == f"http://127.0.0.1:{settings.port}"
