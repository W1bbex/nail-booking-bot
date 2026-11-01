import sys
import time
import urllib.error

import pytest

import owner_setup


@pytest.mark.parametrize(("bot", "button", "main_text", "menu_text"), [
    ({"has_main_web_app": True}, {"type": "web_app"}, "включён", "настроен"),
    ({"has_main_web_app": False}, {"type": "commands"}, "отключён", "команды"),
    ({}, {"type": "default"}, "не сообщил", "команды"),
    ({}, {}, "не сообщил", "не сообщил"),
])
def test_mini_app_status_reports_only_known_states(monkeypatch, bot, button, main_text, menu_text):
    monkeypatch.setattr(owner_setup, "api_call", lambda *args: button)
    main, menu = owner_setup.mini_app_status("test", bot)
    assert main_text in main
    assert menu_text in menu


def test_mini_app_status_handles_network_error(monkeypatch):
    def fail(*args):
        raise owner_setup.SetupError("offline")
    monkeypatch.setattr(owner_setup, "api_call", fail)
    assert "не удалось проверить" in owner_setup.mini_app_status("test", {})[1]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_owner_requires_fresh_private_start_and_confirmation(monkeypatch, capsys):
    now = int(time.time())
    updates = [{"update_id": 1, "message": {"date": now - 100, "chat": {"type": "private", "id": 11},
                "from": {"id": 11, "first_name": "Old"}, "text": "/start"}},
               {"update_id": 2, "message": {"date": now, "chat": {"type": "private", "id": 42},
                "from": {"id": 42, "first_name": "Анна", "username": "anna"}, "text": "/start"}}]
    sent = []
    def api(token, method, params=None):
        if method == "getWebhookInfo":
            return {}
        if method == "sendMessage":
            sent.append(params)
            return {}
        return updates
    monkeypatch.setattr(owner_setup, "api_call", api)
    monkeypatch.setattr("msvcrt.kbhit", lambda: False)
    monkeypatch.setattr("builtins.input", lambda prompt: "да")
    assert owner_setup.identify_owner("test", "example_bot") == 42
    assert sent == [{"chat_id": 42, "text": "Проверьте терминал."}]
    output = capsys.readouterr().out
    assert "Анна" in output and "@anna" in output and "Old" not in output


def test_webhook_is_not_changed(monkeypatch):
    monkeypatch.setattr(owner_setup, "api_call", lambda *args: {"url": "https://example.org"})
    with pytest.raises(owner_setup.SetupError, match="webhook"):
        owner_setup.identify_owner("test", "example_bot")


def test_username_filter_requires_matching_start(monkeypatch):
    now = int(time.time())
    updates = [
        {"update_id": 1, "message": {"date": now, "chat": {"type": "private", "id": 11},
         "from": {"id": 11, "first_name": "Other", "username": "other"}, "text": "/start"}},
        {"update_id": 2, "message": {"date": now, "chat": {"type": "private", "id": 42},
         "from": {"id": 42, "first_name": "Owner", "username": "RightUser"}, "text": "/start"}},
    ]
    sent = []
    def api(token, method, params=None):
        if method == "getWebhookInfo": return {}
        if method == "sendMessage":
            sent.append(params["chat_id"])
            return {}
        return updates
    monkeypatch.setattr(owner_setup, "api_call", api)
    monkeypatch.setattr("msvcrt.kbhit", lambda: False)
    def no_confirmation(prompt):
        raise AssertionError("Matched username must not require another confirmation")
    monkeypatch.setattr("builtins.input", no_confirmation)
    assert owner_setup.identify_owner("test", "bot", expected_username="rightuser") == 42
    assert sent == [42]


def test_telegram_auth_error_does_not_expose_token(monkeypatch):
    secret = "123:example_secret"
    def fail(*args, **kwargs):
        raise urllib.error.HTTPError("https://example.invalid/" + secret, 401, "unauthorized", {}, None)
    monkeypatch.setattr(owner_setup.urllib.request, "urlopen", fail)
    with pytest.raises(owner_setup.SetupError) as error:
        owner_setup.api_call(secret, "getMe")
    assert secret not in str(error.value)
