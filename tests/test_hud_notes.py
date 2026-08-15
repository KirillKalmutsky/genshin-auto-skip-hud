"""A warning has to become a state, not a footnote.

`not elevated - input will be ignored` is the panel's most important message:
without it the tool looks like it is running while every keystroke it sends is
discarded. When the status sentence was removed for taking up room, that message
had to survive somewhere, so it now sets the headline itself.
"""
import pytest

from genshin_autoskip.hud import HOLD, STOP, Overlay, note_state
from genshin_autoskip.state import SkipperState


def panel(**fields: object) -> Overlay:
    base = dict(running=True, game_running=True, game_focused=True)
    return Overlay(SkipperState(**{**base, **fields}))


def test_no_note_is_not_a_state() -> None:
    assert note_state("") is None
    assert note_state("   ") is None


def test_the_elevation_warning_reaches_the_headline() -> None:
    word, detail, colour = note_state("not elevated - input will be ignored")
    assert word == "NO ADMIN"
    assert detail == "keys are ignored"
    assert colour == STOP


def test_an_input_error_keeps_what_windows_reported() -> None:
    word, detail, colour = note_state("input error: SendInput returned 0")
    assert word == "KEY FAILED"
    assert detail == "SendInput returned 0"
    assert colour == STOP


def test_a_break_is_not_an_error() -> None:
    word, _, colour = note_state("break 4.2s")
    assert (word, colour) == ("BREAK", HOLD)


def test_an_unknown_note_is_still_shown() -> None:
    """Better a vague headline than a message that vanishes."""
    word, detail, colour = note_state("something new went wrong")
    assert word == "PROBLEM"
    assert detail == "something new went wrong"
    assert colour == STOP


def test_a_warning_shows_while_running() -> None:
    assert panel(note="not elevated - x")._headline() == ("NO ADMIN", STOP)


def test_stopping_still_reads_as_stopped() -> None:
    """The elevation note is set once at startup and never cleared, so a
    warning that outranked everything would swallow F8's only feedback."""
    assert panel(running=False, note="not elevated - x")._headline()[0] == "STOPPED"


def test_the_detail_says_who_stole_the_focus() -> None:
    text, _ = panel(game_focused=False, foreground="Google Chrome")._detail()
    assert text == "Google Chrome"


@pytest.mark.parametrize("state", [
    dict(dialogue=True),
    dict(dialogue=False),
    dict(game_running=False),
    dict(running=False),
])
def test_nothing_is_said_when_there_is_nothing_to_add(state: dict) -> None:
    """The sentence was dropped because it restated the headline; the detail
    must not quietly grow back into one."""
    assert panel(**state)._detail()[0] == ""


def test_a_long_error_is_trimmed_rather_than_run_off_the_panel() -> None:
    detail, _ = panel(note="input error: " + "verbose " * 10)._detail()
    assert len(detail) <= 23
