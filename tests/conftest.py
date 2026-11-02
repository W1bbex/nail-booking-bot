import asyncio
import os
from datetime import date, time
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.app import app
from core.config import settings
from core.database import get_db
from core.models import Base, Master, Service, User

# In-memory test SQLite DB
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DB_URL,
    echo=False,
    poolclass=StaticPool,
    connect_args={"check_same_thread": False},
)
TestingSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def setup_test_settings():
    old_dev = settings.dev_mode
    old_admins = list(settings.admin_telegram_ids)
    settings.dev_mode = True
    if 5568814893 not in settings.admin_telegram_ids:
        settings.admin_telegram_ids.append(5568814893)
    yield
    settings.dev_mode = old_dev
    settings.admin_telegram_ids = old_admins


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestingSessionLocal() as session:
        # Seed test master
        m1 = Master(
            id=1,
            full_name="Анна Смирнова",
            specialization="Топ-мастер",
            experience_years=5,
            is_active=True,
        )
        m2 = Master(
            id=2,
            full_name="Кристина Романова",
            specialization="Мастер сервиса",
            experience_years=3,
            is_active=True,
        )
        session.add_all([m1, m2])

        # Seed test services
        s1 = Service(
            id=1,
            category="Комплексы",
            name="Комплекс Маникюр + Гель-лак",
            duration_minutes=90,
            price=2400.0,
            is_active=True,
        )
        s2 = Service(
            id=2,
            category="Маникюр",
            name="Экспресс-маникюр",
            duration_minutes=30,
            price=1200.0,
            is_active=True,
        )
        s3 = Service(
            id=3,
            category="Маникюр",
            name="Классический маникюр",
            duration_minutes=60,
            price=1600.0,
            is_active=True,
        )
        session.add_all([s1, s2, s3])

        # Seed test users
        u_client = User(
            id=1,
            telegram_id=999000101,
            full_name="Тестовая Дарья",
            phone="+79991112233",
            role="client",
        )
        u_admin = User(
            id=2,
            telegram_id=5568814893,
            full_name="Администратор",
            phone="+79998887766",
            role="admin",
        )
        session.add_all([u_client, u_admin])

        await session.commit()
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
