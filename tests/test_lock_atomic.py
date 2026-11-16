import os
import pytest
from pathlib import Path
from core.lock import SingleInstanceLock


def test_lock_acquire_and_release(tmp_path: Path):
    lock_file = tmp_path / "test.lock"
    lock = SingleInstanceLock(lock_path=lock_file)

    assert lock.acquire() is True
    assert lock_file.exists()
    assert lock_file.read_text(encoding="utf-8").strip() == str(os.getpid())

    # Second acquire with same running PID (simulating another process with active PID)
    lock2 = SingleInstanceLock(lock_path=lock_file)
    assert lock2.acquire() is False

    # Release first lock
    lock.release()
    assert not lock_file.exists()


def test_lock_stale_pid_recovery(tmp_path: Path):
    lock_file = tmp_path / "stale.lock"
    # Write a non-existent dead PID (e.g. 99999999)
    lock_file.write_text("99999999", encoding="utf-8")

    lock = SingleInstanceLock(lock_path=lock_file)
    # Stale lock must be detected as dead and successfully overtaken atomically
    assert lock.acquire() is True
    assert lock_file.read_text(encoding="utf-8").strip() == str(os.getpid())
    lock.release()
    assert not lock_file.exists()


def test_lock_does_not_release_others(tmp_path: Path):
    lock_file = tmp_path / "other.lock"
    lock = SingleInstanceLock(lock_path=lock_file)
    assert lock.acquire() is True

    # Simulate another PID having taken the lock
    lock_file.write_text("12345", encoding="utf-8")
    lock.release()

    # The file should still exist with 12345 because it didn't belong to current PID
    assert lock_file.exists()
    assert lock_file.read_text(encoding="utf-8").strip() == "12345"
    lock_file.unlink()


def test_lock_stale_pid_concurrent_acquire_only_one_wins(tmp_path: Path):
    import threading

    lock_file = tmp_path / "stale_race.lock"
    lock_file.write_text("99999999", encoding="utf-8")

    workers = 4
    barrier = threading.Barrier(workers)
    locks = [SingleInstanceLock(lock_path=lock_file) for _ in range(workers)]
    results = [False] * workers

    def _run(idx: int) -> None:
        barrier.wait(timeout=5)
        results[idx] = locks[idx].acquire()

    threads = [threading.Thread(target=_run, args=(i,)) for i in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    try:
        assert results.count(True) == 1
        assert results.count(False) == workers - 1
    finally:
        for lock_obj in locks:
            lock_obj.release()
