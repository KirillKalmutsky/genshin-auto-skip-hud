import ctypes

import pytest

from genshin_autoskip import input_backend as backend


def test_every_key_has_both_encodings() -> None:
    """A binding offered as a scan code must also resolve as a virtual key."""
    assert not set(backend.SCANCODES) - set(backend.VIRTUAL_KEYS)


def test_known_codes() -> None:
    assert backend.SCANCODES["f"] == 0x21
    assert backend.VIRTUAL_KEYS["f"] == 0x46


def test_normalise() -> None:
    assert backend.normalise("  F ") == "f"
    assert backend.is_supported("F")
    assert not backend.is_supported("ф")


def test_input_struct_matches_the_win32_abi() -> None:
    assert ctypes.sizeof(backend._INPUT) == 40  # x64 layout


def test_event_flags() -> None:
    down = backend._event(backend._KEYEVENTF_SCANCODE, scan=0x21)
    up = backend._event(backend._KEYEVENTF_SCANCODE | backend._KEYEVENTF_KEYUP,
                        scan=0x21)
    assert down.u.ki.wScan == 0x21
    assert down.u.ki.dwFlags == 0x0008
    assert up.u.ki.dwFlags == 0x000A


@pytest.mark.parametrize("key", ["ф", "f1", "", "ctrl"])
def test_unknown_keys_raise_rather_than_press_something_else(key: str) -> None:
    with pytest.raises(KeyError):
        backend.press_key(key)
