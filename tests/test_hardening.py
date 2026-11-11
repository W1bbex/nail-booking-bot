import os
from datetime import date, datetime, time, timedelta
from pathlib import Path
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.backup import backup_sqlite_database, cleanup_old_backups, get_backup_stats
from core.booking_service import create_booking, get_moscow_now
from core.catalog_service import update_service_price
from core.config import settings
from core.models import Booking, Master, Service, User


@pytest.mark.asyncio
async def test_booking_slot_step_validation(db_session: AsyncSession):
    """Verify create_booking enforces slot_step_minutes (e.g. 30 min)"""
    target_date = get_moscow_now().date() + timedelta(days=2)

    # 1. Non-multiple minutes (e.g. 14:17) must fail
    with pytest.raises(ValueError, match="кратно шагу слота"):
        await create_booking(
            session=db_session,
            client_telegram_id=111222,
            client_name="Тест Слот",
            client_phone="+79991112233",
            master_id=1,
            service_id=1,
            booking_date=target_date,
            start_time=time(14, 17),
        )

    # 2. Non-zero seconds must fail
    with pytest.raises(ValueError, match="кратно шагу слота"):
        await create_booking(
            session=db_session,
            client_telegram_id=111222,
            client_name="Тест Слот",
            client_phone="+79991112233",
            master_id=1,
            service_id=1,
            booking_date=target_date,
            start_time=time(14, 30, 15),
        )

    # 3. Aligned slot (e.g. 14:30) must succeed
    booking = await create_booking(
        session=db_session,
        client_telegram_id=111222,
        client_name="Тест Слот Успех",
        client_phone="+79991112233",
        master_id=1,
        service_id=1,
        booking_date=target_date,
        start_time=time(14, 30),
    )
    assert booking.id is not None
    assert booking.start_time == time(14, 30)


@pytest.mark.asyncio
async def test_booking_horizon_validation(db_session: AsyncSession):
    """Verify create_booking rejects dates beyond horizon_days (14 days)"""
    horizon = int(settings.booking.get("horizon_days", 14))
    now_date = get_moscow_now().date()
    far_future_date = now_date + timedelta(days=horizon + 5)

    with pytest.raises(ValueError, match="максимум на 14 дней вперед"):
        await create_booking(
            session=db_session,
            client_telegram_id=333444,
            client_name="Тест Горизонт",
            client_phone="+79991112233",
            master_id=1,
            service_id=1,
            booking_date=far_future_date,
            start_time=time(12, 0),
        )


@pytest.mark.asyncio
async def test_booking_price_snapshot_immutability(db_session: AsyncSession):
    """
    Verify booking captures service.price at creation time,
    and subsequent service price changes do NOT mutate the booking's price.
    """
    target_date = get_moscow_now().date() + timedelta(days=3)

    # Service 1 initial price is 2400.0
    service = (await db_session.execute(select(Service).where(Service.id == 1))).scalar_one()
    initial_price = service.price
    assert initial_price > 0

    booking = await create_booking(
        session=db_session,
        client_telegram_id=555666,
        client_name="Тест Снапшот Цены",
        client_phone="+79991112233",
        master_id=1,
        service_id=1,
        booking_date=target_date,
        start_time=time(11, 0),
    )
    assert booking.price == initial_price

    # Admin changes service price from 2400 to 3500
    new_price = 3500.0
    settings.admin_telegram_ids.append(999)
    try:
        updated_service = await update_service_price(db_session, service_id=1, new_price=new_price, admin_telegram_id=999)
        assert updated_service.price == new_price
    finally:
        if 999 in settings.admin_telegram_ids:
            settings.admin_telegram_ids.remove(999)

    # Reload booking from DB and ensure booking.price is STILL initial_price
    reloaded_booking = (await db_session.execute(select(Booking).where(Booking.id == booking.id))).scalar_one()
    assert reloaded_booking.price == initial_price
    assert reloaded_booking.price != updated_service.price


def test_sqlite_backup_rotation_limits(tmp_path: Path):
    """
    Verify cleanup_old_backups strictly enforces max_backups limit
    and prunes oldest files first, preventing unbounded growth.
    """
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    # Generate 10 dummy backup files with different timestamps
    files = []
    base_time = datetime(2026, 11, 1, 10, 0, 0).timestamp()
    for i in range(10):
        f = backup_dir / f"studio_2026110{i}_120000.db"
        f.write_text(f"dummy db content {i}")
        # Artificially set file modification times
        os.utime(f, (base_time + i * 3600, base_time + i * 3600))
        files.append(f)

    # Clean up keeping only 4 backups
    removed = cleanup_old_backups(backup_dir, max_backups=4)
    assert len(removed) == 6

    remaining = sorted(backup_dir.glob("studio_*.db"))
    assert len(remaining) == 4

    # The remaining 4 must be the 4 newest ones (indices 6, 7, 8, 9)
    expected_newest = [f"studio_2026110{i}_120000.db" for i in range(6, 10)]
    assert [p.name for p in remaining] == expected_newest

    # Verify get_backup_stats works
    stats = get_backup_stats(backup_dir)
    assert stats["count"] == 4
    assert stats["latest"]["name"] == "studio_20261109_120000.db"
