import asyncio
import signal
import sys

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from api.app import app
import api.routes_client as api_client
from core.backup import database_backup_loop
from core.config import settings
from core.lock import SingleInstanceLock
from core.logger import setup_logger
from handlers.admin import admin_router
from handlers.client import client_router

logger = setup_logger("main")
lock = SingleInstanceLock()


async def setup_bot_commands(bot: Bot) -> None:
    client_commands = [
        BotCommand(command="start", description="Главное меню студии"),
        BotCommand(command="book", description="Онлайн-запись в Mini App"),
        BotCommand(command="bookings", description="Мои записи"),
        BotCommand(command="services", description="Прайс-лист и каталог"),
        BotCommand(command="about", description="О студии"),
        BotCommand(command="contact", description="Контакты и адрес"),
    ]
    admin_commands = client_commands + [
        BotCommand(command="admin", description="Панель администратора"),
        BotCommand(command="schedule", description="Расписание студии"),
        BotCommand(command="services_admin", description="Управление прайсом"),
        BotCommand(command="block", description="Заблокировать интервал мастера"),
        BotCommand(command="unblock", description="Снять блокировки"),
        BotCommand(command="manual_book", description="Записать клиента"),
        BotCommand(command="backup", description="Резервное копирование БД"),
    ]
    try:
        # Default scope for all normal users / clients
        await bot.set_my_commands(client_commands, scope=BotCommandScopeDefault())
        # Personal scope for studio administrators / managers
        for admin_id in settings.admin_telegram_ids:
            try:
                await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
            except Exception as scope_err:
                logger.warning(f"Could not register personal admin scope for {admin_id}: {scope_err}")
        logger.info(f"Successfully registered scoped commands via setMyCommands")
    except Exception as e:
        logger.warning(f"Could not register commands via setMyCommands (offline/mock token): {e}")


async def run_server(server: uvicorn.Server) -> None:
    logger.info(f"FastAPI + Mini App server running at http://{settings.host}:{settings.port}")
    await server.serve()


async def booking_watchdog_loop(bot: Bot | None, stop_event: asyncio.Event) -> None:
    logger.info("Starting booking watchdog background task (interval=30s)...")
    from core.booking_service import process_expired_bookings
    from core.database import get_session
    while not stop_event.is_set():
        if bot:
            try:
                async with get_session() as session:
                    await process_expired_bookings(session, bot)
            except Exception as e:
                logger.error(f"Error in booking watchdog loop: {e}", exc_info=True)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            pass


async def main() -> None:
    # 1. Single Instance Check
    if not lock.acquire():
        logger.error("Another instance of nail-booking-bot is already running. Exiting.")
        sys.exit(0)

    # 2. Setup Uvicorn Server config (DB initialized in app lifespan)
    config = uvicorn.Config(
        app=app,
        host=settings.host,
        port=settings.port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(run_server(server))

    # 4. Check Bot Token & Start Polling
    bot_task = None
    bot = None
    dp = None

    is_dummy_token = (
        settings.dev_mode
        or not settings.bot_token
        or "AAFakeToken" in settings.bot_token
        or settings.bot_token.startswith("123456789:")
    )

    if is_dummy_token:
        logger.warning(
            "Demo BOT_TOKEN detected in .env. "
            "Running in standalone Local Web / Mini App mode (http://127.0.0.1:8080). "
            "To connect live Telegram, specify a real token from @BotFather in .env"
        )
    else:
        try:
            bot = Bot(token=settings.bot_token)
            api_client.telegram_bot_instance = bot
            dp = Dispatcher()
            dp.include_router(client_router)
            dp.include_router(admin_router)

            await setup_bot_commands(bot)
            logger.info("Starting Telegram Bot long-polling...")
            bot_task = asyncio.create_task(dp.start_polling(bot, allowed_updates=["message", "callback_query"]))
        except Exception as bot_err:
            logger.error(f"Failed to start Telegram Bot polling: {bot_err}")

    # 5. Handle Shutdown Signals
    stop_event = asyncio.Event()

    def _signal_handler():
        logger.info("Shutdown signal received. Finalizing gracefully...")
        stop_event.set()

    if sys.platform != "win32":
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _signal_handler)

    stop_task = asyncio.create_task(stop_event.wait())
    watchdog_task = asyncio.create_task(booking_watchdog_loop(bot, stop_event))
    backup_task = asyncio.create_task(database_backup_loop(stop_event))
    core_tasks = [server_task, stop_task]
    if bot_task:
        core_tasks.append(bot_task)
    all_tasks = core_tasks + [watchdog_task, backup_task]

    try:
        done, pending = await asyncio.wait(
            core_tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        logger.info("Shutting down services...")
        server.should_exit = True
        for t in all_tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*all_tasks, return_exceptions=True)
        if bot:
            try:
                await bot.session.close()
            except Exception as close_err:
                logger.warning(f"Error closing bot session: {close_err}")
        lock.release()
        logger.info("Nail Booking Bot stopped cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    finally:
        lock.release()
