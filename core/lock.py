import os
import sys
import time
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

        for attempt in range(2):
            try:
                # O_CREAT | O_EXCL guarantees atomic creation with zero TOCTOU race
                fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, str(current_pid).encode("utf-8"))
                finally:
                    os.close(fd)
                self._acquired = True
                return True
            except FileExistsError:
                # File exists: inspect if the PID inside is alive
                try:
                    stat = self.lock_path.stat()
                    content = self.lock_path.read_text(encoding="utf-8").strip()
                    old_pid = int(content) if content.isdigit() else None
                    if old_pid is not None:
                        if self._is_pid_running(old_pid):
                            logger.warning(f"Another instance is already running with PID {old_pid}.")
                            return False
                    else:
                        # File is empty or being written right now; if very fresh (< 2s), retry once
                        if time.time() - stat.st_mtime < 2.0 and attempt == 0:
                            time.sleep(0.1)
                            continue
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
            kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            SYNCHRONIZE = 0x00100000
            STILL_ACTIVE = 259

            process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
            if not process:
                process = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if process:
                try:
                    exit_code = wintypes.DWORD()
                    if kernel32.GetExitCodeProcess(process, ctypes.byref(exit_code)):
                        return exit_code.value == STILL_ACTIVE
                    return True
                finally:
                    kernel32.CloseHandle(process)
            return False
        else:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False
