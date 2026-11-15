"""
Shared FastAPI dependencies.
Provides Dependency Injection for Aiogram Bot instance, database sessions, and current users.
"""
from typing import Optional
from aiogram import Bot
from fastapi import Request


def get_bot(request: Request) -> Optional[Bot]:
    """
    Retrieves the active Aiogram Bot instance via Dependency Injection from app.state,
    falling back to routes_client.telegram_bot_instance for backward-compatible test fixtures.
    """
    bot = getattr(request.app.state, "bot", None)
    if bot is not None:
        return bot
    from api import routes_client
    return getattr(routes_client, "telegram_bot_instance", None)
