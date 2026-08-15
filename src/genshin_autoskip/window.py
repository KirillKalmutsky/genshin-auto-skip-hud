"""Window queries, via ctypes so that pyautogui is not needed for one call.

pyautogui was previously pulled in purely for ``getActiveWindowTitle``; it drags
pyscreeze, pygetwindow, pymsgbox, pytweening, mouseinfo and pyperclip along with
it, all of which end up in the frozen executable.
"""
import ctypes
from ctypes import wintypes
from typing import Optional

GAME_TITLE = "Genshin Impact"

_user32 = ctypes.windll.user32

# Declaring these matters on 64-bit Windows. Without an explicit restype ctypes
# assumes a C int, so a HWND - a 64-bit pointer - comes back truncated and
# sign-extended, and every later call using that handle silently does nothing.
# It happens to work whenever the handle is small, which makes it an
# intermittent bug rather than an obvious one.
_user32.GetForegroundWindow.argtypes = []
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
_user32.GetWindowTextLengthW.restype = ctypes.c_int
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetWindowTextW.restype = ctypes.c_int
_user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
_user32.FindWindowW.restype = wintypes.HWND
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetWindowRect.restype = wintypes.BOOL
_user32.GetSystemMetrics.argtypes = [ctypes.c_int]
_user32.GetSystemMetrics.restype = ctypes.c_int


def declare_dpi_aware() -> str:
    """Ask Windows for real pixel coordinates. Returns the mode it granted.

    Without this the process is DPI-virtualised: on a display scaled to 125% or
    150%, GetWindowRect and GetSystemMetrics report layout pixels while the
    screen grab returns physical ones, so every region is measured in one unit
    and read in another. Nothing is wrong at 100%, which is why it goes
    unnoticed until someone else runs it.

    Must be called before any window is created or measured - tkinter caches
    the answer when it initialises.
    """
    try:  # Windows 10 1703+: per-monitor, and correct across mixed-DPI setups
        if _user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return "per-monitor-v2"
    except (AttributeError, OSError):
        pass
    try:  # Windows 8.1+
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            return "per-monitor"
    except (AttributeError, OSError):
        pass
    try:  # Vista+
        if _user32.SetProcessDPIAware():
            return "system"
    except (AttributeError, OSError):
        pass
    return "none"


def foreground_title() -> str:
    """Title of the window that currently owns the input focus."""
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return ""
    length = _user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def game_is_focused() -> bool:
    return foreground_title() == GAME_TITLE


def find_game() -> int:
    """HWND of the game window, or 0 when it is not running."""
    return _user32.FindWindowW(None, GAME_TITLE) or 0


def game_rect() -> Optional[tuple[int, int, int, int]]:
    """(left, top, width, height) of the game window, or None if not found."""
    hwnd = find_game()
    if not hwnd:
        return None
    rect = wintypes.RECT()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None
    return rect.left, rect.top, width, height


def primary_screen_size() -> tuple[int, int]:
    """Fallback geometry for when the game window cannot be located."""
    return _user32.GetSystemMetrics(0), _user32.GetSystemMetrics(1)


_ERROR_ALREADY_EXISTS = 183
_instance_mutex = None


def claim_single_instance(name: str = "GenshinAutoSkipSingleInstance") -> bool:
    """False if another copy is already running.

    Two copies would both press the interaction key, doubling the real rate and
    making the configured interval meaningless. The handle is deliberately kept
    in a module global so it lives as long as the process does.
    """
    global _instance_mutex
    kernel32 = ctypes.windll.kernel32
    _instance_mutex = kernel32.CreateMutexW(None, False, name)
    return kernel32.GetLastError() != _ERROR_ALREADY_EXISTS


def is_elevated() -> bool:
    """The game runs elevated; without this, Windows drops our input silently."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False
