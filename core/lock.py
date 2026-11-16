import os
import sys
from pathlib import Path
from typing import Optional

from core.logger import setup_logger

BASE_DIR = Path(__file__).resolve().parent.parent
LOCK_FILE = BASE_DIR / "bot.lock"
logger = setup_logger("core.lock")

_WIN_LOCK_OFFSET = 0x40000000


def _try_lock_fd(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, _WIN_LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_fd(fd: int) -> None:
    try:
        if sys.platform == "win32":
            import msvcrt

            os.lseek(fd, _WIN_LOCK_OFFSET, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass


class SingleInstanceLock:
    def __init__(self, lock_path: Path = LOCK_FILE) -> None:
        self.lock_path = lock_path
        self._acquired = False
        self._fd: Optional[int] = None

    def acquire(self) -> bool:
        if self._acquired:
            return True

        current_pid = os.getpid()
        fd: Optional[int] = None
        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR)
            try:
                _try_lock_fd(fd)
            except OSError:
                try:
                    content = self.lock_path.read_text(encoding="utf-8").strip()
                    if content.isdigit():
                        logger.warning(f"Another instance is already running with PID {content}.")
                except OSError:
                    pass
                os.close(fd)
                return False

            os.lseek(fd, 0, os.SEEK_SET)
            content = os.read(fd, 64).decode("utf-8", errors="replace").strip()
            old_pid = int(content) if content.isdigit() else None
            if old_pid is not None and old_pid != current_pid and self._is_pid_running(old_pid):
                logger.warning(f"Another instance is already running with PID {old_pid}.")
                _unlock_fd(fd)
                os.close(fd)
                return False

            os.lseek(fd, 0, os.SEEK_SET)
            os.ftruncate(fd, 0)
            os.write(fd, str(current_pid).encode("utf-8"))
            self._fd = fd
            self._acquired = True
            return True
        except Exception as e:
            logger.error(f"Failed to create lock file {self.lock_path}: {e}")
            if fd is not None:
                _unlock_fd(fd)
                try:
                    os.close(fd)
                except OSError:
                    pass
            return False

    def release(self) -> None:
        if not self._acquired and self._fd is None:
            return

        matches_owner = False
        try:
            if self.lock_path.exists():
                content = self.lock_path.read_text(encoding="utf-8").strip()
                matches_owner = content == str(os.getpid())
        except OSError:
            pass
        finally:
            if self._fd is not None:
                _unlock_fd(self._fd)
                try:
                    os.close(self._fd)
                except OSError:
                    pass
                self._fd = None
            self._acquired = False

        if matches_owner:
            try:
                self.lock_path.unlink(missing_ok=True)
            except OSError:
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
