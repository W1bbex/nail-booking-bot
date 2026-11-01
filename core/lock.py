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
        if self.lock_path.exists():
            try:
                content = self.lock_path.read_text(encoding="utf-8").strip()
                old_pid = int(content) if content.isdigit() else None
                if old_pid and self._is_pid_running(old_pid):
                    logger.warning(f"Another instance is already running with PID {old_pid}.")
                    return False
            except Exception:
                pass
            # If stale or unreadable, remove it
            try:
                self.lock_path.unlink()
            except Exception:
                pass

        try:
            current_pid = os.getpid()
            self.lock_path.write_text(str(current_pid), encoding="utf-8")
            self._acquired = True
            return True
        except Exception as e:
            print(f"[ERROR] Failed to create lock file {self.lock_path}: {e}", file=sys.stderr)
            return False

    def release(self) -> None:
        if self._acquired and self.lock_path.exists():
            try:
                self.lock_path.unlink()
                self._acquired = False
            except Exception:
                pass

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
