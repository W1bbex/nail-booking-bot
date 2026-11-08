import asyncio
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.config import DATA_DIR, DB_PATH
from core.logger import setup_logger

logger = setup_logger("backup")

DEFAULT_MAX_BACKUPS = 7
BACKUP_DIR = DATA_DIR / "backups"


def cleanup_old_backups(backup_dir: Path | str, max_backups: int = DEFAULT_MAX_BACKUPS) -> List[Path]:
    """
    Scans backup_dir for studio_*.db files and removes the oldest ones
    if the total count exceeds max_backups. Prevents unbounded storage growth ("матрёшка").
    """
    backup_path = Path(backup_dir)
    if not backup_path.exists():
        return []

    # Only match single-level flat backup files
    backups = [p for p in backup_path.glob("studio_*.db") if p.is_file()]
    # Sort descending: newest first
    backups.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    removed: List[Path] = []
    if len(backups) > max_backups:
        for old in backups[max_backups:]:
            try:
                old.unlink()
                removed.append(old)
                logger.info(f"Rotated old database backup: {old.name}")
            except OSError as e:
                logger.warning(f"Could not remove old backup {old.name}: {e}")

    return removed


def backup_sqlite_database(
    db_path: Optional[Path | str] = None,
    backup_dir: Optional[Path | str] = None,
    max_backups: int = DEFAULT_MAX_BACKUPS,
) -> Optional[Path]:
    """
    Creates a consistent SQLite online snapshot using sqlite3.Connection.backup()
    without blocking WAL writers or risking page corruption.
    Enforces strict retention limit (max_backups).
    """
    src_file = Path(db_path) if db_path else DB_PATH
    dest_dir = Path(backup_dir) if backup_dir else BACKUP_DIR

    if not src_file.is_file() or src_file.stat().st_size == 0:
        logger.debug(f"Source database does not exist or is empty: {src_file}")
        return None

    dest_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_file = dest_dir / f"studio_{timestamp}.db"

    try:
        # sqlite3 native online backup
        src_conn = sqlite3.connect(str(src_file))
        dst_conn = sqlite3.connect(str(dest_file))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
            src_conn.close()

        logger.info(
            f"Database backup created: {dest_file.name} "
            f"({dest_file.stat().st_size / 1024:.1f} KB)"
        )
        cleanup_old_backups(dest_dir, max_backups=max_backups)
        return dest_file
    except Exception as e:
        logger.error(f"Failed to create database backup: {e}", exc_info=True)
        if dest_file.exists():
            try:
                dest_file.unlink()
            except OSError:
                pass
        return None


def get_backup_stats(backup_dir: Optional[Path | str] = None) -> Dict[str, Any]:
    """
    Returns summary info about stored backups.
    """
    dest_dir = Path(backup_dir) if backup_dir else BACKUP_DIR
    if not dest_dir.exists():
        return {"count": 0, "total_kb": 0.0, "latest": None, "backups": []}

    backups = [p for p in dest_dir.glob("studio_*.db") if p.is_file()]
    backups.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    items = []
    total_bytes = 0
    for b in backups:
        sz = b.stat().st_size
        total_bytes += sz
        mtime = datetime.fromtimestamp(b.stat().st_mtime)
        items.append({
            "name": b.name,
            "size_kb": round(sz / 1024, 1),
            "created_at": mtime.strftime("%d.%m.%Y %H:%M:%S"),
        })

    return {
        "count": len(backups),
        "total_kb": round(total_bytes / 1024, 1),
        "latest": items[0] if items else None,
        "backups": items,
    }


async def database_backup_loop(
    stop_event: asyncio.Event,
    interval_hours: int = 24,
    max_backups: int = DEFAULT_MAX_BACKUPS,
) -> None:
    """
    Background worker: executes periodic database backups every interval_hours.
    """
    logger.info(f"Starting database backup background task (interval={interval_hours}h, max={max_backups})...")

    # Initial safety backup on startup (delayed 5s to allow DB init to complete)
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        pass

    if not stop_event.is_set():
        await asyncio.to_thread(backup_sqlite_database, max_backups=max_backups)

    interval_seconds = interval_hours * 3600
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            if not stop_event.is_set():
                await asyncio.to_thread(backup_sqlite_database, max_backups=max_backups)
