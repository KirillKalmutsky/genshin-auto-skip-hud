"""Settings, persisted next to the executable in a plain .env file.

The format is deliberately trivial (``KEY=value`` lines) so it can be edited by
hand, and reading it needs no dependency in the frozen build.
"""
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from .detection import ANCHORS
from .input_backend import is_supported, normalise


def app_dir() -> Path:
    """Where settings live: next to the .exe, or the repo root from source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # config.py -> genshin_autoskip -> src -> repository root
    return Path(__file__).resolve().parents[2]


CONFIG_PATH = app_dir() / ".env"

_BOOL_TRUE = {"1", "true", "yes", "on"}

#: Corners the HUD may occupy. Top-left is deliberately absent: the panel is
#: captured by the screen grab like anything else, and in that corner it covers
#: the auto-play button the detector reads - measured at 2560x1440, a
#: top-left HUD lands on (28,28)-(396,273) against a button region at
#: (56,26)-(160,130).
HUD_POSITIONS = ("bottom-left", "bottom-right", "top-right")


@dataclass
class Config:
    """Runtime knobs. Field names map onto upper-cased .env keys."""

    confirm_button: str = "f"
    press_min_ms: float = 60.0
    press_max_ms: float = 110.0
    key_hold_ms: float = 60.0
    #: How long a detection keeps counting after it stops matching. Zero means
    #: presses stop the instant the dialogue does.
    detection_hold_ms: float = 0.0
    #: How often to look at the screen while nothing is happening. This is the
    #: delay before a dialogue is noticed, so it trades responsiveness against
    #: CPU; while a dialogue *is* running the loop instead sleeps until the next
    #: press is due, which needs no polling at all.
    idle_poll_ms: float = 100.0
    #: Which element detection keys on: "auto", "marker" or "both".
    detection_anchor: str = "auto"
    #: Answer dialogue choices as well as advancing lines. Turn it off before a
    #: conversation whose answers you care about: the skipper then holds at the
    #: choice and waits for you, instead of picking for you.
    auto_answer: bool = True
    hud: bool = True
    #: Bottom-left by default: it is the one corner the game leaves empty
    #: during a dialogue, and it is clear of both regions detection reads -
    #: the auto-play button top-left and the marker at bottom centre.
    hud_position: str = "bottom-left"
    #: Where the panel was dragged to, in screen pixels. Negative means "use
    #: the corner above" - the corners stay meaningful for anyone who has never
    #: moved it, and dragging quietly takes over once they have.
    hud_x: float = -1.0
    hud_y: float = -1.0
    #: Opaque by default. Photographed over real game frames, even a little
    #: transparency let scene detail through the panel and the secondary text
    #: landed on top of it - a status panel that is sometimes unreadable is
    #: worse than one that hides a little scenery. Lower it if you disagree.
    hud_opacity: float = 1.0
    #: Press on a timer regardless of detection - a fallback for when a game
    #: update moves the UI and detection needs re-measuring.
    spam_mode: bool = False
    #: Idle pauses. Off by default: they cost speed and hide nothing, since
    #: Windows flags injected input however it is timed.
    random_breaks: bool = False
    profile: bool = False

    # -- derived ----------------------------------------------------------

    @property
    def press_min(self) -> float:
        return min(self.press_min_ms, self.press_max_ms) / 1000.0

    @property
    def press_max(self) -> float:
        return max(self.press_min_ms, self.press_max_ms) / 1000.0

    @property
    def key_hold(self) -> float:
        return self.key_hold_ms / 1000.0

    # -- persistence ------------------------------------------------------

    @staticmethod
    def _read_pairs(path: Path) -> dict[str, str]:
        pairs: dict[str, str] = {}
        if not path.exists():
            return pairs
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            pairs[name.strip().upper()] = value.strip().strip('"').strip("'")
        return pairs

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "Config":
        pairs = cls._read_pairs(path)
        config = cls()
        for field_name, current in asdict(config).items():
            raw = pairs.get(field_name.upper())
            if raw is None or raw == "":
                continue
            try:
                if isinstance(current, bool):
                    setattr(config, field_name, raw.lower() in _BOOL_TRUE)
                elif isinstance(current, float):
                    setattr(config, field_name, float(raw))
                else:
                    setattr(config, field_name, raw)
            except ValueError:
                pass  # keep the default rather than refusing to start

        key = normalise(config.confirm_button)
        config.confirm_button = key if is_supported(key) else "f"

        anchor = config.detection_anchor.strip().lower()
        config.detection_anchor = anchor if anchor in ANCHORS else "auto"

        corner = config.hud_position.strip().lower()
        config.hud_position = corner if corner in HUD_POSITIONS else "bottom-left"
        return config

    def save(self, path: Path = CONFIG_PATH) -> None:
        lines = ["# Genshin dialogue auto-skipper settings", ""]
        for field_name, value in asdict(self).items():
            if isinstance(value, bool):
                value = "1" if value else "0"
            elif isinstance(value, float):
                value = f"{value:g}"
            lines.append(f"{field_name.upper()}={value}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
