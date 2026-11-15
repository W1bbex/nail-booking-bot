from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api.app import app
from api.dependencies import get_bot


def test_get_bot_from_app_state():
    mock_request = MagicMock()
    mock_bot = MagicMock()
    mock_request.app.state.bot = mock_bot

    result = get_bot(mock_request)
    assert result is mock_bot


def test_get_bot_fallback_when_app_state_empty(monkeypatch):
    mock_request = MagicMock()
    del mock_request.app.state.bot
    mock_bot = MagicMock()
    monkeypatch.setattr("api.routes_client.telegram_bot_instance", mock_bot)

    result = get_bot(mock_request)
    assert result is mock_bot


def test_global_exception_handlers():
    test_app = FastAPI()
    # Import exception handlers from main app
    for exc_class, handler in app.exception_handlers.items():
        test_app.add_exception_handler(exc_class, handler)

    @test_app.get("/test-permission-error")
    async def route_permission():
        raise PermissionError("Доступ запрещен")

    @test_app.get("/test-lookup-error")
    async def route_lookup():
        raise LookupError("Мастер не найден")

    @test_app.get("/test-value-error-not-found")
    async def route_not_found():
        raise ValueError("Услуга не найдена в каталоге")

    @test_app.get("/test-value-error-bad-request")
    async def route_bad_request():
        raise ValueError("Некорректный формат времени")

    client = TestClient(test_app, raise_server_exceptions=False)

    r_perm = client.get("/test-permission-error")
    assert r_perm.status_code == 403
    assert r_perm.json()["detail"] == "Доступ запрещен"

    r_lookup = client.get("/test-lookup-error")
    assert r_lookup.status_code == 404
    assert r_lookup.json()["detail"] == "Мастер не найден"

    r_not_found = client.get("/test-value-error-not-found")
    assert r_not_found.status_code == 404

    r_bad = client.get("/test-value-error-bad-request")
    assert r_bad.status_code == 400
    assert r_bad.json()["detail"] == "Некорректный формат времени"


def test_alembic_config_resolves():
    from alembic.config import Config
    from core.config import settings

    alembic_cfg = Config("alembic.ini")
    url = alembic_cfg.get_main_option("sqlalchemy.url")
    assert url is not None
