"""Settings live in the registry, and old file settings are carried over.

Tests point the module at a scratch key rather than the real one, and remove it
afterwards, so running the suite leaves the machine as it found it.
"""
import winreg
from pathlib import Path

import pytest

from genshin_autoskip import config as config_module
from genshin_autoskip.config import HUD_POSITIONS, Config

TEST_KEY = r"Software\GenshinAutoSkipTests"


@pytest.fixture()
def registry(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config_module, "REGISTRY_KEY", TEST_KEY)
    yield
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, TEST_KEY)
    except OSError:
        pass


def test_round_trip_through_the_registry(registry) -> None:
    original = Config(confirm_button="e", press_min_ms=40, press_max_ms=70,
                      auto_answer=False, hud_x=284, hud_y=1006,
                      detection_anchor="marker", hud_opacity=0.8)
    original.save()
    assert Config.load() == original


def test_types_survive(registry) -> None:
    """The registry stores strings and DWORDs; booleans and floats must come
    back as booleans and floats, not as the text of them."""
    Config(auto_answer=False, hud=True, press_min_ms=42.5).save()
    loaded = Config.load()
    assert loaded.auto_answer is False
    assert loaded.hud is True
    assert isinstance(loaded.press_min_ms, float)
    assert loaded.press_min_ms == 42.5


def test_nothing_stored_gives_defaults(registry, monkeypatch) -> None:
    monkeypatch.setattr(config_module, "LEGACY_PATH", Path("nowhere.env"))
    assert Config.load() == Config()


def test_settings_from_an_older_version_are_carried_over(
        registry, monkeypatch, tmp_path: Path) -> None:
    """Earlier versions kept a KEY=value file beside the program."""
    legacy = tmp_path / ".env"
    legacy.write_text("CONFIRM_BUTTON=e\nDETECTION_ANCHOR=both\n"
                      "AUTO_ANSWER=0\nPRESS_MIN_MS=120\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "LEGACY_PATH", legacy)

    loaded = Config.load()
    assert loaded.confirm_button == "e"
    assert loaded.detection_anchor == "both"
    assert loaded.auto_answer is False
    assert loaded.press_min_ms == 120.0


def test_stored_settings_win_over_the_old_file(registry, monkeypatch,
                                               tmp_path: Path) -> None:
    legacy = tmp_path / ".env"
    legacy.write_text("CONFIRM_BUTTON=e\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "LEGACY_PATH", legacy)
    Config(confirm_button="r").save()
    assert Config.load().confirm_button == "r"


def test_forget_removes_everything(registry) -> None:
    Config(confirm_button="e").save()
    config_module.Config.forget()
    with pytest.raises(OSError):
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, TEST_KEY)


def test_nonsense_values_do_not_stop_startup(registry) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, TEST_KEY) as key:
        winreg.SetValueEx(key, "confirm_button", 0, winreg.REG_SZ, "ф")
        winreg.SetValueEx(key, "press_min_ms", 0, winreg.REG_SZ, "soon")
        winreg.SetValueEx(key, "detection_anchor", 0, winreg.REG_SZ, "elsewhere")
        winreg.SetValueEx(key, "hud_position", 0, winreg.REG_SZ, "top-left")

    loaded = Config.load()
    assert loaded.confirm_button == "f"
    assert loaded.press_min_ms == 60.0
    assert loaded.detection_anchor == "auto"
    assert loaded.hud_position in HUD_POSITIONS
