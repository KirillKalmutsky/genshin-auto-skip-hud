"""The HUD must keep telling the truth while the skipper is switched off.

Regression: the foreground check sat behind the "is it running" guard, so with
the skipper paused nothing ever updated `game_focused` and the HUD went on
reporting "Genshin: not focused" no matter what was actually in front. That
reads as a broken focus detector rather than as a paused tool.
"""
import threading
from time import sleep

import pytest

from genshin_autoskip import loop as loop_module
from genshin_autoskip.config import Config
from genshin_autoskip.state import SkipperState


def run_briefly(state: SkipperState, config: Config, seconds: float = 0.6) -> None:
    worker = threading.Thread(target=loop_module.skip_loop, args=(state, config),
                              daemon=True)
    worker.start()
    sleep(seconds)
    state.should_exit = True
    worker.join(timeout=3.0)


@pytest.fixture()
def fake_world(monkeypatch: pytest.MonkeyPatch):
    """A world where the game is running and in the foreground."""
    monkeypatch.setattr(loop_module, "find_game", lambda: 4242)
    monkeypatch.setattr(loop_module, "foreground_title", lambda: "Genshin Impact")


def test_focus_is_reported_while_paused(fake_world) -> None:
    state = SkipperState(running=False)
    run_briefly(state, Config())

    assert state.game_focused is True
    assert state.game_running is True
    assert state.foreground == ""


def test_other_window_is_named_while_paused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loop_module, "find_game", lambda: 4242)
    monkeypatch.setattr(loop_module, "foreground_title", lambda: "Some Browser")

    state = SkipperState(running=False)
    run_briefly(state, Config())

    assert state.game_focused is False
    assert state.foreground == "Some Browser"


def test_settings_are_mirrored_while_paused(fake_world) -> None:
    """The HUD shows the anchor and answer mode; both must be live when paused."""
    state = SkipperState(running=False)
    run_briefly(state, Config(detection_anchor="marker", auto_answer=False))

    assert state.anchor == "marker"
    assert state.auto_answer is False


def test_paused_loop_presses_nothing(fake_world, monkeypatch: pytest.MonkeyPatch) -> None:
    presses: list[str] = []
    monkeypatch.setattr(loop_module, "press_key",
                        lambda key, hold=0.0: presses.append(key))

    state = SkipperState(running=False)
    run_briefly(state, Config())

    assert presses == []
    assert state.presses == 0
    assert state.dialogue is False
