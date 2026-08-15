"""Hotkeys must take effect in every state, not only mid-dialogue.

Regression: the detector picked up the anchor below the "is it running" and "is
the game focused" guards, while the HUD's copy was refreshed above them. So
pressing F9 while stopped, or while looking at the HUD from another window,
changed the config and nothing else - the loop overwrote the HUD from the
detector's unchanged value, and the mode never actually switched.
"""
import threading
from time import sleep

import pytest

from genshin_autoskip import loop as loop_module
from genshin_autoskip.app import _hotkeys
from genshin_autoskip.config import Config
from genshin_autoskip.detection import ANCHORS
from genshin_autoskip.state import SkipperState


class _Key:
    def __init__(self, name: str) -> None:
        self._name = name

    def __str__(self) -> str:
        return self._name


@pytest.fixture()
def world(monkeypatch: pytest.MonkeyPatch):
    """Genshin is running; whether it is focused is up to each test."""
    monkeypatch.setattr(loop_module, "find_game", lambda: 4242)
    monkeypatch.setattr(loop_module, "press_key",
                        lambda key, hold=0.0: None)


def drive(state: SkipperState, config: Config, presses: list[str],
          seconds: float = 0.9) -> None:
    worker = threading.Thread(target=loop_module.skip_loop,
                              args=(state, config), daemon=True)
    worker.start()
    sleep(0.25)
    handler = _hotkeys(state, config)
    for key in presses:
        handler(_Key(key))
        sleep(0.25)
    sleep(max(seconds - 0.25 * (len(presses) + 1), 0.25))
    state.should_exit = True
    worker.join(timeout=3.0)


def test_f9_switches_the_anchor_while_stopped(world, monkeypatch) -> None:
    monkeypatch.setattr(loop_module, "foreground_title", lambda: "Genshin Impact")
    config = Config(detection_anchor="marker")
    config.save = lambda *a, **k: None  # type: ignore[method-assign]
    state = SkipperState(running=False)

    drive(state, config, ["Key.f9"])

    assert config.detection_anchor != "marker"
    assert state.anchor == config.detection_anchor


def test_f9_switches_the_anchor_while_the_game_is_not_focused(world, monkeypatch) -> None:
    monkeypatch.setattr(loop_module, "foreground_title", lambda: "Some Browser")
    config = Config(detection_anchor="marker")
    config.save = lambda *a, **k: None  # type: ignore[method-assign]
    state = SkipperState(running=True)

    drive(state, config, ["Key.f9"])

    assert config.detection_anchor != "marker"
    assert state.anchor == config.detection_anchor


def test_the_hud_never_disagrees_with_the_config(world, monkeypatch) -> None:
    """Whatever the loop reports must be what the detector is really using."""
    monkeypatch.setattr(loop_module, "foreground_title", lambda: "Genshin Impact")
    config = Config(detection_anchor=ANCHORS[0])
    config.save = lambda *a, **k: None  # type: ignore[method-assign]
    state = SkipperState(running=False)

    drive(state, config, ["Key.f9"] * len(ANCHORS))

    assert state.anchor == config.detection_anchor


def test_f10_reaches_the_detector_while_stopped(world, monkeypatch) -> None:
    monkeypatch.setattr(loop_module, "foreground_title", lambda: "Genshin Impact")
    config = Config(auto_answer=True)
    config.save = lambda *a, **k: None  # type: ignore[method-assign]
    state = SkipperState(running=False)

    drive(state, config, ["Key.f10"])

    assert config.auto_answer is False
    assert state.auto_answer is False
