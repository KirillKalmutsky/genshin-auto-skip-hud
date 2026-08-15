"""Key injection that Genshin Impact actually reacts to.

pyautogui drives the keyboard through the legacy ``keybd_event`` call. Measured
against the live game (see ``tools/input_probe.py``), the game ignores those
events completely, whether the key is released instantly or held for 60 ms:

    pyautogui.press('f')          change= 0.21   no effect
    pyautogui keyDown/Up 60ms     change= 0.21   no effect
    SendInput virtual-key 60ms    change=31.70   ADVANCED THE DIALOGUE
    SendInput SCANCODE  60ms      change=17.65   ADVANCED THE DIALOGUE

So the fix is to go through ``SendInput`` directly. We default to scan codes
because they address a *physical* key: a virtual key code is translated through
the active keyboard layout, which misfires when the user is on a non-Latin
layout, while scan code 0x21 is the F key no matter what layout is active.

Note that the game only registers the key if it stays down across at least one
of its input polls, hence the short hold.
"""
import ctypes
import time
from ctypes import wintypes

# Set-1 scan codes for the keys that are plausible interaction bindings.
SCANCODES = {
    "escape": 0x01, "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06,
    "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A, "0": 0x0B,
    "tab": 0x0F,
    "q": 0x10, "w": 0x11, "e": 0x12, "r": 0x13, "t": 0x14, "y": 0x15,
    "u": 0x16, "i": 0x17, "o": 0x18, "p": 0x19,
    "enter": 0x1C,
    "a": 0x1E, "s": 0x1F, "d": 0x20, "f": 0x21, "g": 0x22, "h": 0x23,
    "j": 0x24, "k": 0x25, "l": 0x26,
    "z": 0x2C, "x": 0x2D, "c": 0x2E, "v": 0x2F, "b": 0x30, "n": 0x31,
    "m": 0x32,
    "space": 0x39,
}

VIRTUAL_KEYS = {
    "escape": 0x1B, "tab": 0x09, "enter": 0x0D, "space": 0x20,
    **{c: 0x41 + i for i, c in enumerate("abcdefghijklmnopqrstuvwxyz")},
    **{str(d): 0x30 + d for d in range(10)},
}

DEFAULT_HOLD = 0.06

#: Created with use_last_error so that GetLastError is captured for us. Without
#: it the error reported on a failed SendInput is whatever happened last
#: anywhere in the process - in practice always 0, which made the one
#: diagnostic the user gets permanently blank.
_user32 = ctypes.WinDLL("user32", use_last_error=True)

_PUL = ctypes.POINTER(ctypes.c_ulong)


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", _PUL)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", _PUL)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


_INPUT_KEYBOARD = 1
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_SCANCODE = 0x0008


class InputError(RuntimeError):
    """Raised when Windows refuses to deliver a synthetic input event."""


def _event(flags: int, scan: int = 0, vk: int = 0) -> _INPUT:
    return _INPUT(type=_INPUT_KEYBOARD,
                  u=_INPUTUNION(ki=_KEYBDINPUT(wVk=vk, wScan=scan,
                                               dwFlags=flags, time=0,
                                               dwExtraInfo=None)))


def _send(*events: _INPUT) -> None:
    count = len(events)
    array = (_INPUT * count)(*events)
    sent = _user32.SendInput(count, array, ctypes.sizeof(_INPUT))
    if sent != count:
        err = ctypes.get_last_error()
        raise InputError(
            f"SendInput delivered {sent}/{count} events (error {err}). "
            "This usually means the script is not running as Administrator "
            "while the game is - Windows then blocks the input silently."
        )


def normalise(key: str) -> str:
    """Map user input like 'F' or ' f ' onto a canonical key name."""
    return key.strip().lower()


def is_supported(key: str) -> bool:
    return normalise(key) in SCANCODES


def press_key(key: str, hold: float = DEFAULT_HOLD,
              use_scancode: bool = True) -> None:
    """Press and release *key* so that the game registers it.

    :param key: key name, e.g. ``"f"`` or ``"space"``.
    :param hold: seconds to keep the key down; must span an input poll.
    :param use_scancode: send a physical scan code (layout independent)
        instead of a virtual key code.
    """
    name = normalise(key)
    if use_scancode:
        scan = SCANCODES.get(name)
        if scan is None:
            raise KeyError(f"no scan code known for key {key!r}")
        down = _event(_KEYEVENTF_SCANCODE, scan=scan)
        up = _event(_KEYEVENTF_SCANCODE | _KEYEVENTF_KEYUP, scan=scan)
    else:
        vk = VIRTUAL_KEYS.get(name)
        if vk is None:
            raise KeyError(f"no virtual key code known for key {key!r}")
        down = _event(0, vk=vk)
        up = _event(_KEYEVENTF_KEYUP, vk=vk)

    _send(down)
    try:
        time.sleep(hold)
    finally:
        # Never leave the key down. Without this, an exception during the hold -
        # or a shutdown that kills the presser thread mid-press - sticks the key
        # down system wide, and the user has to clear it by hand.
        _send(up)
