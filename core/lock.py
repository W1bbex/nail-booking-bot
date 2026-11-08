import os
import sys
from pathlib import Path

from core.logger import setup_logger

BASE_DIR = Path(__file__).resolve().parent.parent
LOCK_FILE = BASE_DIR / "bot.lock"
logger = setup_logger("core.lock")


class SingleInstanceLock:
    def __init__(self, lock_path: Path = LOCK_FILE) -> None:
        self.lock_path = lock_path
        self._acquired = False

    def acquire(self) -> bool:
        current_pid = os.getpid()

        for _ in range(2):
            try:
                # O_CREAT | O_EXCL guarantees atomic creation with zero TOCTOU race
                fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(str(current_pid))
                self._acquired = True
                return True
            except FileExistsError:
                # File exists: inspect if the PID inside is alive
                try:
                    content = self.lock_path.read_text(encoding="utf-8").strip()
                    old_pid = int(content) if content.isdigit() else None
                    if old_pid and self._is_pid_running(old_pid):
                        logger.warning(f"Another instance is already running with PID {old_pid}.")
                        return False
                except Exception:
                    pass

                # If stale or unreadable, remove it and retry atomically
                try:
                    self.lock_path.unlink(missing_ok=True)
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"Failed to create lock file {self.lock_path}: {e}")
                return False

        return False

    def release(self) -> None:
        if self._acquired and self.lock_path.exists():
            try:
                content = self.lock_path.read_text(encoding="utf-8").strip()
                if content == str(os.getpid()):
                    self.lock_path.unlink(missing_ok=True)
            except Exception:
                pass
            finally:
                self._acquired = False

    @staticmethod
    def _is_pid_running(pid: int) -> bool:
        if pid <= 0:
            return False
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.windll.kernel32
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            SYNCHRONIZE = 0x00100000
            process = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if process:
                kernel32.CloseHandle(process)
                return True
            return False
        else:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False
