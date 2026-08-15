"""Holding at an answer choice when answering is switched off.

Which reference wins says whether the game is waiting for an answer: the button
turns translucent then, and the translucent glyphs are their own references.
Brightness was tried first and is unsound - a translucent glyph over a bright
scene is not dark, so the corner's peak says nothing on its own.
"""
import numpy as np
import pytest

from genshin_autoskip import detection
from genshin_autoskip.app import _hotkeys
from genshin_autoskip.config import Config
from genshin_autoskip.detection import (TRANSLUCENT_CONTRAST, DialogueDetector)
from genshin_autoskip.state import SkipperState
from genshin_autoskip.templates import BUTTON_SIZE
from genshin_autoskip.tray import Tray

from test_detection import render


class _Key:
    def __init__(self, name: str) -> None:
        self._name = name

    def __str__(self) -> str:
        return self._name


@pytest.fixture()
def detector(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(detection, "game_rect", lambda: None)
    instance = DialogueDetector(1920, 1080)
    yield instance
    instance.close()


def test_translucent_button_reads_as_a_pending_choice(
        detector: DialogueDetector, monkeypatch: pytest.MonkeyPatch) -> None:
    """The game fades the button while it waits for an answer.

    Detection does not depend on this - the shape is recovered either way - so
    a wrong reading here only affects whether answers are picked, never whether
    the dialogue is seen.
    """
    faint = render(detector.shapes[1], alpha=0.25)
    monkeypatch.setattr(detector._sct, "grab", lambda _roi: faint)
    result = detector.detect()
    assert result.dialogue is True
    assert result.choice is True


def test_opaque_button_is_not_a_choice(detector: DialogueDetector,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    solid = render(detector.shapes[1], alpha=1.0)
    monkeypatch.setattr(detector._sct, "grab", lambda _roi: solid)
    result = detector.detect()
    assert result.dialogue is True
    assert result.choice is False


def test_translucency_threshold_sits_between_the_measured_medians() -> None:
    """Measured on real frames: 163 lit against 41 translucent."""
    assert 41 < TRANSLUCENT_CONTRAST < 163


def test_no_dialogue_means_no_choice(detector: DialogueDetector,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """Out in the world there is no button, so there is nothing to say."""
    blank = np.zeros((BUTTON_SIZE, BUTTON_SIZE, 3), dtype=np.uint8)
    monkeypatch.setattr(detector._sct, "grab", lambda _roi: blank)
    result = detector.detect()
    assert result.dialogue is False
    assert result.choice is None


def test_marker_anchor_does_not_guess(monkeypatch: pytest.MonkeyPatch) -> None:
    """The marker never sees the button, so it must report nothing."""
    monkeypatch.setattr(detection, "game_rect", lambda: None)
    instance = DialogueDetector(1920, 1080, anchor="marker")
    monkeypatch.setattr(instance._sct, "grab",
                        lambda _roi: np.zeros((40, 40, 3), dtype=np.uint8))
    assert instance.detect().choice is None
    instance.close()


# -- hotkeys ----------------------------------------------------------------

def test_f10_toggles_answering_and_f11_toggles_the_hud() -> None:
    state, config = SkipperState(), Config(auto_answer=True)
    config.save = lambda *a, **k: None  # type: ignore[method-assign]
    handler = _hotkeys(state, config)

    handler(_Key("Key.f10"))
    assert config.auto_answer is False
    assert state.auto_answer is False
    handler(_Key("Key.f10"))
    assert config.auto_answer is True

    visible = state.hud_visible
    handler(_Key("Key.f11"))
    assert state.hud_visible is not visible


def test_f8_toggles_rather_than_only_starting() -> None:
    state, config = SkipperState(running=False), Config()
    config.save = lambda *a, **k: None  # type: ignore[method-assign]
    handler = _hotkeys(state, config)

    handler(_Key("Key.f8"))
    assert state.running is True
    handler(_Key("Key.f8"))
    assert state.running is False


def test_f9_cycles_through_every_anchor_and_wraps() -> None:
    state, config = SkipperState(), Config(detection_anchor="auto")
    config.save = lambda *a, **k: None  # type: ignore[method-assign]
    handler = _hotkeys(state, config)

    seen = []
    for _ in range(len(detection.ANCHORS) + 1):
        handler(_Key("Key.f9"))
        seen.append(config.detection_anchor)
        assert state.anchor == config.detection_anchor

    assert set(seen) == set(detection.ANCHORS)
    assert seen[-1] == seen[0]  # one press past the end wraps around


def test_f9_recovers_from_a_hand_edited_anchor() -> None:
    state, config = SkipperState(), Config()
    config.detection_anchor = "nonsense"
    config.save = lambda *a, **k: None  # type: ignore[method-assign]
    _hotkeys(state, config)(_Key("Key.f9"))
    assert config.detection_anchor in detection.ANCHORS


def test_tray_toggle_matches_the_hotkey() -> None:
    state, config = SkipperState(), Config(auto_answer=True)
    tray = Tray(state, config)
    tray._persist = lambda: None
    tray._toggle_auto_answer()
    assert config.auto_answer is False
    assert state.auto_answer is False


def test_tray_says_it_is_waiting_for_you() -> None:
    state = SkipperState(game_running=True, game_focused=True, dialogue=True,
                         choice=True)
    tray = Tray(state, Config(auto_answer=False))
    assert "your answer" in tray._status_line()
