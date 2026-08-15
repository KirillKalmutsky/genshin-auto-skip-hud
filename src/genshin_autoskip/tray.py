"""System tray icon and menu.

pystray runs its own Windows message pump, so it lives on a worker thread while
tkinter keeps the main thread for the HUD.
"""
import threading
import webbrowser
from time import sleep
from typing import Callable, Optional

import pystray

from .config import Config
from .icons import icon_for
from .input_backend import SCANCODES
from .state import SkipperState

#: Offered in the tray menu. The full scan-code table is large and most of it
#: makes no sense as an interaction key.
KEY_CHOICES = ["f", "e", "r", "t", "space", "enter"]

PROJECT_URL = "https://github.com/KirillKalmutsky/genshin-auto-skip-hud"


class Tray:
    def __init__(self, state: SkipperState, config: Config,
                 on_config_change: Optional[Callable[[], None]] = None) -> None:
        self.state = state
        self.config = config
        self.on_config_change = on_config_change or (lambda: None)
        self._icon: Optional[pystray.Icon] = None
        self._thread: Optional[threading.Thread] = None
        self._last_look: tuple[bool, bool] = (False, False)

    # -- menu actions ------------------------------------------------------

    def _toggle_running(self) -> None:
        self.state.running = not self.state.running

    def _toggle_hud(self) -> None:
        self.state.hud_visible = not self.state.hud_visible
        self.config.hud = self.state.hud_visible
        self._persist()

    def _toggle_movable(self) -> None:
        """Let the panel be dragged. It stops being click-through meanwhile,
        so it is a mode rather than something always on."""
        self.state.hud_movable = not self.state.hud_movable
        if self.state.hud_movable:
            self.state.hud_visible = True

    def _reset_position(self) -> None:
        self.config.hud_x = self.config.hud_y = -1.0
        self.state.hud_movable = False
        self._persist()
        self.state.note = "restart to return the panel to its corner"

    def _toggle_auto_answer(self) -> None:
        self.config.auto_answer = not self.config.auto_answer
        self.state.auto_answer = self.config.auto_answer
        self._persist()

    def _toggle_spam(self) -> None:
        self.config.spam_mode = not self.config.spam_mode
        self._persist()

    def _set_key(self, key: str) -> Callable[[], None]:
        def apply() -> None:
            if key in SCANCODES:
                self.config.confirm_button = key
                self._persist()
        return apply

    def _set_anchor(self, anchor: str) -> Callable[[], None]:
        def apply() -> None:
            self.config.detection_anchor = anchor
            self._persist()
        return apply

    def _set_speed(self, low: float, high: float) -> Callable[[], None]:
        def apply() -> None:
            self.config.press_min_ms = low
            self.config.press_max_ms = high
            self._persist()
        return apply

    def _persist(self) -> None:
        try:
            self.config.save()
        except OSError:
            pass  # a read-only install directory must not crash the app
        self.on_config_change()

    @staticmethod
    def _open_project() -> None:
        # In a thread: the tray's menu handler runs on the pump that keeps the
        # icon alive, and launching a browser can block for a second or two.
        threading.Thread(target=webbrowser.open, args=(PROJECT_URL,),
                         daemon=True, name="open-project").start()

    def _quit(self) -> None:
        self.state.should_exit = True
        if self._icon is not None:
            self._icon.stop()

    # -- menu construction -------------------------------------------------

    def _build_menu(self) -> pystray.Menu:
        item = pystray.MenuItem

        speeds = [
            ("Fast      40-70 ms", 40.0, 70.0),
            ("Normal    60-110 ms", 60.0, 110.0),
            ("Relaxed  120-200 ms", 120.0, 200.0),
            # About twice a second: slow enough to read along, and slow enough
            # to stop before a choice you did not mean to answer.
            ("Slow     400-600 ms", 400.0, 600.0),
        ]

        return pystray.Menu(
            item(lambda _: "Stop  (F8)" if self.state.running else "Start  (F8)",
                 lambda: self._toggle_running(), default=True),
            pystray.Menu.SEPARATOR,
            item("Interaction key", pystray.Menu(*[
                item(key.upper(), self._set_key(key),
                     checked=lambda _, k=key: self.config.confirm_button == k,
                     radio=True)
                for key in KEY_CHOICES
            ])),
            item("Detect by  (F9 cycles)", pystray.Menu(*[
                item(label, self._set_anchor(anchor),
                     checked=lambda _, a=anchor: self.config.detection_anchor == a,
                     radio=True)
                for label, anchor in (
                    ("Auto-play button (top left)", "auto"),
                    ("Orange marker (bottom)", "marker"),
                    ("Either", "both"),
                )
            ])),
            item("Speed", pystray.Menu(*[
                item(label, self._set_speed(low, high),
                     checked=lambda _, lo=low: self.config.press_min_ms == lo,
                     radio=True)
                for label, low, high in speeds
            ])),
            pystray.Menu.SEPARATOR,
            item("Answer choices too  (F10)",
                 lambda: self._toggle_auto_answer(),
                 checked=lambda _: self.config.auto_answer),
            item("Show HUD  (F11)", lambda: self._toggle_hud(),
                 checked=lambda _: self.state.hud_visible),
            item("Move HUD", lambda: self._toggle_movable(),
                 checked=lambda _: self.state.hud_movable),
            item("Reset HUD position", lambda: self._reset_position()),
            item("Spam mode (ignore detection)", lambda: self._toggle_spam(),
                 checked=lambda _: self.config.spam_mode),
            pystray.Menu.SEPARATOR,
            item(lambda _: self._status_line(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            item("Project page on GitHub", lambda: self._open_project()),
            item("Exit  (F12)", lambda: self._quit()),
        )

    def _status_line(self) -> str:
        if not self.state.game_running:
            return "Genshin not running"
        if not self.state.game_focused:
            return "Genshin not focused"
        if self.state.choice and not self.config.auto_answer:
            return "waiting for your answer"
        if self.state.dialogue:
            return f"dialogue {self.state.confidence:.2f} - {self.state.presses} presses"
        return f"waiting - {self.state.presses} presses"

    # -- lifecycle ---------------------------------------------------------

    def _watch(self) -> None:
        """Keep the icon's colour and tooltip in step with the state."""
        while not self.state.should_exit:
            look = (self.state.running, self.state.game_running)
            if look != self._last_look and self._icon is not None:
                self._last_look = look
                self._icon.icon = icon_for(*look)
                self._icon.title = f"Genshin auto-skip - {self._status_line()}"
            sleep(0.3)

    def start(self) -> None:
        self._icon = pystray.Icon(
            "genshin-autoskip",
            icon=icon_for(self.state.running, self.state.game_running),
            title="Genshin auto-skip",
            menu=self._build_menu(),
        )
        self._thread = threading.Thread(target=self._icon.run, daemon=True,
                                        name="tray")
        self._thread.start()
        threading.Thread(target=self._watch, daemon=True,
                         name="tray-watch").start()

    def stop(self) -> None:
        if self._icon is not None:
            self._icon.stop()
