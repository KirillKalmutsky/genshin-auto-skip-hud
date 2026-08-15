"""Wiring: config, worker loop, hotkeys, tray icon and HUD.

Thread layout is dictated by tkinter needing the main thread:

    main thread     the status HUD (hud.Overlay.run)
    worker thread   detection and press scheduling (loop.skip_loop)
    presser thread  holds the key down for its dwell time
    tray thread     pystray's own message pump
    pynput thread   global F8/F9/F10/F12 hotkeys
"""
import ctypes
import sys
import threading
from time import sleep
from typing import Union

from pynput.keyboard import Key, KeyCode, Listener  # type: ignore[import-untyped]

from . import __version__
from .config import CONFIG_LOCATION, Config
from .detection import ANCHORS
from .loop import skip_loop
from .state import SkipperState
from .tray import Tray
from .window import claim_single_instance, declare_dpi_aware, is_elevated


def _persist(config: Config) -> None:
    """Save a hotkey-driven change; a read-only install must not crash the app."""
    try:
        config.save()
    except OSError:
        pass


def _hotkeys(state: SkipperState, config: Config | None = None):
    def on_press(pressed: Union[Key, KeyCode, None]) -> bool | None:
        name = str(pressed)
        if name == "Key.f8":
            state.running = not state.running
        elif name == "Key.f9" and config is not None:
            # Cycle the anchor rather than offering three keys for it: which
            # one works best depends on the scene, so it gets tried in place.
            order = list(ANCHORS)
            try:
                index = order.index(config.detection_anchor)
            except ValueError:
                index = -1
            config.detection_anchor = order[(index + 1) % len(order)]
            state.anchor = config.detection_anchor
            _persist(config)
        elif name == "Key.f10" and config is not None:
            # The more frequently needed of the two, so it gets the nearer key:
            # the point is to switch answering off the moment a dialogue you
            # care about starts.
            config.auto_answer = not config.auto_answer
            state.auto_answer = config.auto_answer
            _persist(config)
        elif name == "Key.f11":
            state.hud_visible = not state.hud_visible
        elif name == "Key.f12":
            state.should_exit = True
            return False  # stop the listener
        return None

    return on_press


def _warn_not_elevated() -> None:
    """The game runs elevated; without matching rights our input is dropped.

    Shown from a daemon thread: MessageBoxW is modal, and blocking startup on it
    would leave the tray icon and HUD uncreated until the user clicked OK.
    """
    def show() -> None:
        ctypes.windll.user32.MessageBoxW(
            None,
            "Genshin Impact runs with administrator rights, so Windows will "
            "silently discard every key this tool sends.\n\n"
            "Close it and start again as administrator.",
            "Genshin auto-skip - not elevated",
            0x00000030 | 0x00040000,  # MB_ICONWARNING | MB_TOPMOST
        )

    threading.Thread(target=show, daemon=True, name="elevation-warning").start()


def main(state: SkipperState | None = None,
         config: Config | None = None) -> int:
    """Start every thread and hand the main one to the HUD.

    The state and config can be supplied by a caller that needs to observe or
    shut the app down from outside, which is what the integration test does.
    """
    # First, before anything measures or draws a window.
    declare_dpi_aware()

    config = config or Config.load()
    state = state or SkipperState(hud_visible=config.hud)

    if not claim_single_instance():
        ctypes.windll.user32.MessageBoxW(
            None,
            "Genshin auto-skip is already running - look for its icon in the "
            "system tray.\n\nTwo copies would both press the key, so this one "
            "will close.",
            "Genshin auto-skip",
            0x00000040 | 0x00040000,  # MB_ICONINFORMATION | MB_TOPMOST
        )
        return 1

    if not is_elevated():
        state.note = "not elevated - input will be ignored"
        _warn_not_elevated()

    worker = threading.Thread(target=skip_loop, args=(state, config),
                              daemon=True, name="skip-loop")
    worker.start()

    listener = Listener(on_press=_hotkeys(state, config))
    listener.start()

    tray = Tray(state, config)
    tray.start()

    try:
        if config.hud:
            from .hud import Overlay  # imported late: tkinter is heavy

            def remember(x: int, y: int) -> None:
                config.hud_x, config.hud_y = float(x), float(y)
                _persist(config)

            point = ((int(config.hud_x), int(config.hud_y))
                     if config.hud_x >= 0 and config.hud_y >= 0 else None)
            Overlay(state, position=config.hud_position, point=point,
                    alpha=min(max(config.hud_opacity, 0.3), 1.0),
                    on_move=remember).run()
        else:
            while not state.should_exit:
                sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        state.should_exit = True
        tray.stop()
        listener.stop()
        worker.join(timeout=2.0)
    return 0


def cli() -> int:
    """Console entry point; prints what the windowed build shows in the HUD."""
    print(f"  Genshin dialogue auto-skip {__version__}")
    print(f"  settings: {CONFIG_LOCATION}")
    print("  [F8] start/stop  [F9] mode  [F10] answers  [F11] HUD  [F12] exit")
    if not is_elevated():
        print("  [WARN] not running as administrator - input will be ignored")
    return main()


if __name__ == "__main__":
    sys.exit(cli())
