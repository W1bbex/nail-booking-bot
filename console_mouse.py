"""Mouse and keyboard input for a Windows console menu."""
import ctypes
from ctypes import wintypes


class Coord(ctypes.Structure):
    _fields_ = [("x", ctypes.c_short), ("y", ctypes.c_short)]


class SmallRect(ctypes.Structure):
    _fields_ = [("left", ctypes.c_short), ("top", ctypes.c_short),
                ("right", ctypes.c_short), ("bottom", ctypes.c_short)]


class ScreenInfo(ctypes.Structure):
    _fields_ = [("size", Coord), ("cursor", Coord), ("attributes", wintypes.WORD),
                ("window", SmallRect), ("maximum", Coord)]


class KeyChar(ctypes.Union):
    _fields_ = [("unicode", ctypes.c_wchar), ("ascii", ctypes.c_char)]


class KeyEvent(ctypes.Structure):
    _fields_ = [("down", wintypes.BOOL), ("repeat", wintypes.WORD),
                ("virtual_key", wintypes.WORD), ("scan", wintypes.WORD),
                ("char", KeyChar), ("control", wintypes.DWORD)]


class MouseEvent(ctypes.Structure):
    _fields_ = [("position", Coord), ("buttons", wintypes.DWORD),
                ("control", wintypes.DWORD), ("flags", wintypes.DWORD)]


class EventData(ctypes.Union):
    _fields_ = [("key", KeyEvent), ("mouse", MouseEvent), ("padding", ctypes.c_byte * 16)]


class InputRecord(ctypes.Structure):
    _fields_ = [("event_type", wintypes.WORD), ("event", EventData)]


def menu_hit(x: int, y: int, origin_x: int, origin_y: int, count: int) -> int | None:
    """Map the item row and the space beneath it to the same item."""
    relative_x, relative_y = x - origin_x, y - origin_y
    row = relative_y - 6
    if 2 <= relative_x <= 44 and row >= 0 and row // 2 < count:
        return row // 2
    return None


class ConsoleInput:
    def __enter__(self):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.GetStdHandle.restype = wintypes.HANDLE
        self.kernel.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.GetConsoleScreenBufferInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(ScreenInfo)]
        self.kernel.ReadConsoleInputW.argtypes = [wintypes.HANDLE, ctypes.POINTER(InputRecord),
                                                 wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        self.input = self.kernel.GetStdHandle(-10)
        self.output = self.kernel.GetStdHandle(-11)
        self.mode = wintypes.DWORD()
        if not self.kernel.GetConsoleMode(self.input, ctypes.byref(self.mode)):
            raise OSError(ctypes.get_last_error(), "Cannot read console input mode")
        self.enable_mouse()
        return self

    def enable_mouse(self):
        mode = (self.mode.value | 0x0080 | 0x0010) & ~(0x0040 | 0x0200)
        if not self.kernel.SetConsoleMode(self.input, mode):
            raise OSError(ctypes.get_last_error(), "Cannot enable console mouse input")

    def __exit__(self, *_args):
        self.kernel.SetConsoleMode(self.input, self.mode.value)

    def cursor(self) -> tuple[int, int]:
        info = ScreenInfo()
        if not self.kernel.GetConsoleScreenBufferInfo(self.output, ctypes.byref(info)):
            raise OSError(ctypes.get_last_error(), "Cannot read console cursor position")
        return info.cursor.x, info.cursor.y

    def read(self) -> InputRecord:
        record, count = InputRecord(), wintypes.DWORD()
        if not self.kernel.ReadConsoleInputW(self.input, ctypes.byref(record), 1, ctypes.byref(count)):
            raise OSError(ctypes.get_last_error(), "Cannot read console input")
        return record
