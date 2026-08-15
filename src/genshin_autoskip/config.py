"""Settings, kept in the registry so the program leaves no files behind.

Three places were considered and two rejected:

* **Inside the executable.** Not possible, and not desirable. Windows locks the
  file while it runs; a one-file build unpacks to a temporary folder that is
  discarded on exit; each release publishes the binary's SHA-256, which a
  self-modifying executable would immediately invalidate; and a program that
  rewrites its own executable is a malware signature that antivirus software
  reacts to on sight.
* **A file beside the executable**, which earlier versions used. A program
  installed under Program Files cannot write to its own folder without
  administrator rights, and when that write fails there is nothing sensible to
  do about it - so settings silently stopped persisting.
* **HKEY_CURRENT_USER**, which is what this uses. No files, no elevation, and
  the settings survive replacing or moving the program.

Settings from a file left by an earlier version are read once and carried over.
"""
import json
import sys
import winreg
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from .detection import ANCHORS
from .input_backend import is_supported, normalise

REGISTRY_KEY = r"Software\GenshinAutoSkip"

#: Corners the panel may occupy. Top-left is deliberately absent: the panel is
#: captured by the screen grab like anything else, and in that corner it covers
#: the auto-play button the detector reads.
HUD_POSITIONS = ("top-right", "bottom-left", "bottom-right")

_BOOL_TRUE = {"1", "true", "yes", "on"}


def app_dir() -> Path:
    """Where the program itself lives - next to the .exe once frozen."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


#: A settings file left by an earlier version. Read once, then left alone.
LEGACY_PATH = app_dir() / ".env"


@dataclass
class Config:
    """Runtime knobs. Field names map onto registry values of the same name."""

    confirm_button: str = "f"
    #: Which element detection keys on: "auto", "marker" or "both".
    detection_anchor: str = "auto"
    #: Answer dialogue choices as well as advancing lines. Turn it off before a
    #: conversation whose answers you care about.
    auto_answer: bool = True
    press_min_ms: float = 60.0
    press_max_ms: float = 110.0
    key_hold_ms: float = 60.0
    #: How long a detection keeps counting after it stops matching. Zero means
    #: presses stop the instant the dialogue does.
    detection_hold_ms: float = 0.0
    #: How often to look at the screen while nothing is happening - the delay
    #: before a dialogue is noticed. While one is running the loop sleeps until
    #: the next press instead, which needs no polling.
    idle_poll_ms: float = 100.0
    hud: bool = True
    #: Top-right by default. Top-left is the one corner it must not use: the
    #: panel is captured by the screen grab like anything else, and there it
    #: would cover the auto-play button the detector reads.
    hud_position: str = "top-right"
    #: Where the panel was dragged to. Negative means "use the corner above".
    hud_x: float = -1.0
    hud_y: float = -1.0
    #: Opaque by default. Over real game frames even a little transparency let
    #: scene detail through and the secondary text landed on top of it.
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

    # -- validation -------------------------------------------------------

    def _repair(self) -> "Config":
        key = normalise(self.confirm_button)
        self.confirm_button = key if is_supported(key) else "f"

        anchor = self.detection_anchor.strip().lower()
        self.detection_anchor = anchor if anchor in ANCHORS else "auto"

        corner = self.hud_position.strip().lower()
        self.hud_position = corner if corner in HUD_POSITIONS else "top-right"
        return self

    def _adopt(self, values: dict[str, Any]) -> "Config":
        """Take whatever of `values` is usable, ignoring the rest.

        A hand-edited or half-written setting must never stop the program from
        starting; the default simply stands.
        """
        for field in fields(self):
            if field.name not in values:
                continue
            raw = values[field.name]
            try:
                if field.type is bool or isinstance(getattr(self, field.name), bool):
                    setattr(self, field.name, raw if isinstance(raw, bool)
                            else str(raw).strip().lower() in _BOOL_TRUE)
                elif isinstance(getattr(self, field.name), float):
                    setattr(self, field.name, float(raw))
                else:
                    setattr(self, field.name, str(raw))
            except (TypeError, ValueError):
                pass
        return self._repair()

    # -- persistence ------------------------------------------------------

    @staticmethod
    def _read_registry() -> dict[str, Any]:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY) as key:
                out = {}
                for index in range(winreg.QueryInfoKey(key)[1]):
                    name, value, _ = winreg.EnumValue(key, index)
                    out[name] = value
                return out
        except OSError:
            return {}

    @staticmethod
    def _read_legacy(path: Path) -> dict[str, Any]:
        """The `KEY=value` file earlier versions wrote beside the program."""
        if not path.exists():
            return {}
        out: dict[str, Any] = {}
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError:
            return {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            out[name.strip().lower()] = value.strip().strip('"').strip("'")
        return out

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        """Read settings. `path` reads a file instead, for tests and migration."""
        if path is not None:
            try:
                values = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                values = cls._read_legacy(path)
            return cls()._adopt(values)

        values = cls._read_registry()
        if not values:
            values = cls._read_legacy(LEGACY_PATH)
        return cls()._adopt(values)

    def save(self, path: Path | None = None) -> None:
        """Write settings. Each value is written on its own, so a failure
        partway through cannot leave a half-parsed file behind."""
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(asdict(self), indent=2) + "\n",
                            encoding="utf-8")
            return

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY) as key:
            for name, value in asdict(self).items():
                if isinstance(value, bool):
                    winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, int(value))
                elif isinstance(value, float):
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, f"{value:g}")
                else:
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))

    @staticmethod
    def forget() -> None:
        """Remove every stored setting, leaving nothing behind."""
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY)
        except OSError:
            pass


#: Where settings are kept, phrased for a human rather than for a filesystem.
CONFIG_LOCATION = f"HKEY_CURRENT_USER\\{REGISTRY_KEY}"
