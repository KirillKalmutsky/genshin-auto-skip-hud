"""State shared between the detection worker, the HUD and the tray icon."""
from dataclasses import dataclass


@dataclass
class SkipperState:
    """Live snapshot of what the skipper is doing.

    Plain attribute reads and writes are enough here: every field holds a single
    immutable value, so a reader can never observe a half-written one.
    """

    running: bool = False
    game_focused: bool = False
    #: Title of whatever currently holds the foreground. Shown when it is not
    #: the game, so "not focused" can be told apart from "focus was stolen".
    foreground: str = ""
    game_running: bool = False
    #: True while presses are being scheduled - which includes the hysteresis
    #: window after the button dims, so it can be set while confidence is 0.
    dialogue: bool = False
    #: True when that is only the hysteresis window keeping it alive.
    holding: bool = False
    #: The game is waiting for an answer to be picked.
    choice: bool = False
    #: Whether answers are being picked automatically.
    auto_answer: bool = True
    #: Which anchor detection is currently keying on.
    anchor: str = "auto"
    confidence: float = 0.0
    presses: int = 0
    rate: float = 0.0
    note: str = ""
    should_exit: bool = False
    hud_visible: bool = True
    #: While true the panel stops being click-through so it can be dragged.
    hud_movable: bool = False
