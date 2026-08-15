"""Detection and press scheduling - everything that runs off the main thread."""
import csv
import threading
from pathlib import Path
from random import randint, uniform
from time import perf_counter, sleep
from typing import Optional

from .config import Config, app_dir
from .detection import ANCHOR_MARKER, DETECTION_HOLD, DialogueDetector
from .input_backend import press_key
from .state import SkipperState
from .window import (GAME_TITLE, find_game, foreground_title,
                     primary_screen_size)

PROFILE_PATH = app_dir() / "loop_profile.csv"


class KeyPresser:
    """Presses a key on its own thread, so the dwell time costs the loop nothing.

    The game only registers a press that stays down across one of its input
    polls; blocking the detection loop for that long was a large slice of the
    original loop's period.

    The key and its dwell time are read from the config at press time rather
    than captured at construction, so changing either from the tray menu takes
    effect on the next press instead of at the next restart.
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self.errors = 0
        self.last_error = ""
        self._request = threading.Event()
        self._stop = threading.Event()
        self._busy = False
        threading.Thread(target=self._run, daemon=True,
                         name="key-presser").start()

    @property
    def busy(self) -> bool:
        return self._busy

    def press(self) -> bool:
        """Ask for a press. Returns False if the previous one is still held."""
        if self._busy:
            return False
        self._request.set()
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self._request.wait(0.1):
                continue
            self._request.clear()
            self._busy = True
            try:
                press_key(self.config.confirm_button, hold=self.config.key_hold)
            except Exception as exc:  # surface it, but keep the loop alive
                self.errors += 1
                self.last_error = str(exc)
            finally:
                self._busy = False

    def stop(self) -> None:
        self._stop.set()


def random_interval(config: Config) -> float:
    """Randomised gap between presses, so the cadence is not perfectly regular."""
    span = config.press_max - config.press_min
    if randint(1, 6) == 6:
        return config.press_max + span * 0.2
    return uniform(config.press_min, config.press_max)


class _Profiler:
    """Optional per-iteration log, for diagnosing an unexpected press rate."""

    def __init__(self, path: Path) -> None:
        self._file = open(path, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow(["t", "phase", "detect_ms", "confidence",
                               "pressed", "gap"])
        self._start = perf_counter()

    def row(self, phase: str, detect_ms: float = 0.0, confidence: float = 0.0,
            pressed: int = 0, gap: str = "") -> None:
        self._writer.writerow([f"{perf_counter() - self._start:.3f}", phase,
                               f"{detect_ms:.2f}", f"{confidence:.2f}",
                               pressed, gap])

    def close(self) -> None:
        self._file.close()


def skip_loop(state: SkipperState, config: Config) -> None:
    """Detect the dialogue UI and schedule presses. Runs on a worker thread."""
    detector = DialogueDetector(*primary_screen_size(),
                                anchor=config.detection_anchor)
    presser = KeyPresser(config)
    profiler: Optional[_Profiler] = _Profiler(PROFILE_PATH) if config.profile else None

    last_press = 0.0
    last_seen = 0.0     # when the dialogue UI was last positively detected
    last_geometry = 0.0
    last_game_check = 0.0
    interval = random_interval(config)
    last_break_check = perf_counter()
    recent: list[float] = []

    try:
        while not state.should_exit:
            now = perf_counter()

            if now - last_game_check > 2.0:
                last_game_check = now
                state.game_running = bool(find_game())

            # Kept current even while paused. These describe the world rather
            # than the work, and freezing them makes the HUD look broken: with
            # the skipper switched off it went on claiming the game was not
            # focused no matter what was actually in front.
            title = foreground_title()
            focused = title == GAME_TITLE
            state.game_focused = focused
            state.foreground = "" if focused else title
            state.auto_answer = config.auto_answer

            # Applied here rather than further down, for the same reason: below
            # this point the loop has already returned for a stopped skipper or
            # an unfocused game, so settings changed by a hotkey while either
            # was true never reached the detector - F9 appeared to do nothing.
            detector.set_anchor(config.detection_anchor)
            detector.detect_choice = not config.auto_answer
            state.anchor = detector.anchor

            if not state.running:
                state.dialogue = False
                state.choice = False
                sleep(0.05)
                continue

            if not focused:
                # Never press while another window owns the input, or the key
                # lands in whatever the user switched to.
                state.dialogue = False
                if profiler:
                    profiler.row("unfocused")
                sleep(0.15)
                continue

            # The window can be moved or resized between passes, and
            # re-anchoring costs microseconds, so do it periodically.
            if now - last_geometry > 3.0:
                last_geometry = now
                detector.refresh_geometry()

            started = perf_counter()
            result = detector.detect()
            detect_ms = (perf_counter() - started) * 1000.0
            state.confidence = result.confidence

            # Hysteresis, off by default: it bridges a momentary dip, but it
            # also keeps pressing after the dialogue has closed.
            if result.dialogue:
                last_seen = perf_counter()
            hold = config.detection_hold_ms / 1000.0
            active = (result.dialogue
                      or (hold > 0 and (perf_counter() - last_seen) < hold)
                      or config.spam_mode)
            state.dialogue = active
            state.holding = active and not result.dialogue

            if not active:
                if profiler:
                    profiler.row("no-dialogue", detect_ms, result.confidence)
                sleep(config.idle_poll_ms / 1000.0)
                continue

            if config.random_breaks and now - last_break_check > 30.0:
                last_break_check = now
                if randint(1, 25) == 1:
                    pause = uniform(3.0, 8.0)
                    state.note = f"break {pause:.1f}s"
                    sleep(pause)
                    state.note = ""
                    last_press = perf_counter()
                    continue

            # Hold at a choice when answering is switched off, so an answer
            # that matters is left to the player. Detection keeps running, so
            # the HUD still shows what is happening and pressing resumes by
            # itself once the choice is gone.
            state.choice = bool(result.choice)
            if result.choice and not config.auto_answer:
                if profiler:
                    profiler.row("awaiting-answer", detect_ms, result.confidence)
                sleep(0.05)
                continue

            pressed, gap = 0, ""
            if now - last_press >= interval and presser.press():
                pressed = 1
                gap = f"{now - last_press:.3f}"
                state.presses += 1
                last_press = now
                interval = random_interval(config)

                recent.append(now)
                cutoff = now - 3.0
                while recent and recent[0] < cutoff:
                    recent.pop(0)
                state.rate = len(recent) / 3.0

            if presser.errors:
                state.note = f"input error: {presser.last_error[:40]}"

            if profiler:
                profiler.row("dialogue", detect_ms, result.confidence, pressed, gap)

            # Sleep until the next press is actually due instead of polling
            # through the wait. The screen was being read about a hundred times
            # per key press, all of it discarded - and every read is a screen
            # grab competing with the game for the GPU.
            due = last_press + interval - perf_counter()
            sleep(max(min(due, config.idle_poll_ms / 1000.0), 0.002))
    finally:
        presser.stop()
        detector.close()
        if profiler:
            profiler.close()
