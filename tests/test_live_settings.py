"""Settings changed from the tray must take effect without a restart.

A menu that appears to switch something but only does so after a restart is
worse than no menu at all, so each live-editable setting is pinned by a test.
"""
from genshin_autoskip.config import Config
from genshin_autoskip.detection import DialogueDetector
from genshin_autoskip.loop import KeyPresser, random_interval
from genshin_autoskip.tray import Tray
from genshin_autoskip.state import SkipperState


def test_anchor_switches_at_runtime() -> None:
    detector = DialogueDetector(1920, 1080, anchor="auto")
    assert detector.set_anchor("marker") is True
    assert detector.anchor == "marker"
    assert detector.set_anchor("marker") is False   # no needless churn
    assert detector.set_anchor("rubbish") is True   # falls back
    assert detector.anchor == "auto"
    detector.close()


def test_both_regions_exist_whatever_the_anchor() -> None:
    """Switching must not need geometry to be recomputed."""
    for anchor in ("auto", "marker", "both"):
        detector = DialogueDetector(1920, 1080, anchor=anchor)
        assert detector.auto_roi["width"] > 0
        assert detector.marker_roi["width"] > 0
        detector.close()


def test_key_and_hold_are_read_at_press_time() -> None:
    config = Config(confirm_button="f", key_hold_ms=60)
    presser = KeyPresser(config)
    assert presser.config.confirm_button == "f"

    config.confirm_button = "e"
    config.key_hold_ms = 45
    assert presser.config.confirm_button == "e"
    assert presser.config.key_hold == 0.045
    presser.stop()


def test_speed_is_read_at_press_time() -> None:
    config = Config(press_min_ms=60, press_max_ms=110)
    assert 0.06 <= random_interval(config) <= 0.14

    config.press_min_ms, config.press_max_ms = 200, 260
    assert random_interval(config) >= 0.20


def test_tray_writes_through_to_the_shared_config() -> None:
    """The tray edits the very object the loop reads, not a copy."""
    config = Config()
    tray = Tray(SkipperState(), config)
    tray._persist = lambda: None  # do not touch the real .env

    tray._set_anchor("marker")()
    assert config.detection_anchor == "marker"

    tray._set_key("e")()
    assert config.confirm_button == "e"

    tray._set_speed(40, 70)()
    assert (config.press_min_ms, config.press_max_ms) == (40, 70)
