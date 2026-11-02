from contextlib import asynccontextmanager
from typing import AsyncGenerator
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import settings
from core.logger import setup_logger
from core.models import Base, Master, Service

logger = setup_logger("database")

engine = create_async_engine(settings.database_url, echo=False)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


async def init_db() -> None:
    logger.info("Initializing SQLite database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Safe column migration for existing SQLite databases
        res_m_cols = await conn.execute(text("PRAGMA table_info(masters)"))
        m_cols = {row[1] for row in res_m_cols.fetchall()}
        if "archived_at" not in m_cols:
            await conn.execute(text("ALTER TABLE masters ADD COLUMN archived_at DATETIME"))
        if "telegram_username" not in m_cols:
            await conn.execute(text("ALTER TABLE masters ADD COLUMN telegram_username VARCHAR(80)"))
        if "telegram_id" not in m_cols:
            await conn.execute(text("ALTER TABLE masters ADD COLUMN telegram_id INTEGER"))

        res_s_cols = await conn.execute(text("PRAGMA table_info(services)"))
        s_cols = {row[1] for row in res_s_cols.fetchall()}
        if "archived_at" not in s_cols:
            await conn.execute(text("ALTER TABLE services ADD COLUMN archived_at DATETIME"))

        res_b_cols = await conn.execute(text("PRAGMA table_info(bookings)"))
        b_cols = {row[1] for row in res_b_cols.fetchall()}
        if "is_any_master" not in b_cols:
            await conn.execute(text("ALTER TABLE bookings ADD COLUMN is_any_master BOOLEAN DEFAULT 0"))
        if "declined_master_ids" not in b_cols:
            await conn.execute(text("ALTER TABLE bookings ADD COLUMN declined_master_ids VARCHAR(255)"))
        if "assignment_deadline" not in b_cols:
            await conn.execute(text("ALTER TABLE bookings ADD COLUMN assignment_deadline DATETIME"))
        if "client_reassign_deadline" not in b_cols:
            await conn.execute(text("ALTER TABLE bookings ADD COLUMN client_reassign_deadline DATETIME"))
        if "price" not in b_cols:
            await conn.execute(text("ALTER TABLE bookings ADD COLUMN price FLOAT DEFAULT 0.0"))
            # Backfill price from services table for existing historical bookings
            await conn.execute(text(
                "UPDATE bookings SET price = ("
                "  SELECT price FROM services WHERE services.id = bookings.service_id"
                ") WHERE price IS NULL OR price = 0.0"
            ))

    # Seed initial data if tables are empty
    async with async_session_maker() as session:
        # Check masters
        res_m = await session.execute(select(Master).limit(1))
        if not res_m.scalar_one_or_none():
            logger.info("Seeding initial masters...")
            for m_data in settings.initial_masters:
                master = Master(
                    id=m_data.get("id"),
                    full_name=m_data["full_name"],
                    specialization=m_data.get("specialization", ""),
                    experience_years=m_data.get("experience_years", 3),
                    is_active=m_data.get("is_active", True),
                )
                session.add(master)
            await session.commit()

        # Check services
        res_s = await session.execute(select(Service).limit(1))
        if not res_s.scalar_one_or_none():
            logger.info("Seeding initial nail services...")
            for s_data in settings.initial_services:
                service = Service(
                    id=s_data.get("id"),
                    category=s_data.get("category", "Маникюр"),
                    name=s_data["name"],
                    description=s_data.get("description"),
                    duration_minutes=s_data.get("duration_minutes", 60),
                    price=float(s_data.get("price", 0.0)),
                    is_active=s_data.get("is_active", True),
                )
                session.add(service)
            await session.commit()

    logger.info("Database initialized successfully.")
