from pathlib import Path

from genshin_autoskip.config import Config


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    original = Config(confirm_button="e", press_min_ms=40, press_max_ms=70,
                      spam_mode=True, hud=False)
    original.save(path)
    assert Config.load(path) == original


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    assert Config.load(tmp_path / "absent.env") == Config()


def test_unusable_values_fall_back(tmp_path: Path) -> None:
    """A hand-edited file must not stop the app from starting."""
    path = tmp_path / ".env"
    path.write_text("CONFIRM_BUTTON=ф\nPRESS_MIN_MS=oops\n", encoding="utf-8")

    config = Config.load(path)
    assert config.confirm_button == "f"      # Cyrillic key has no scan code
    assert config.press_min_ms == 60.0       # unparseable number


def test_reads_v1_env_and_ignores_extra_keys(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("WIDTH=2560\nHEIGHT=1440\nCONFIRM_BUTTON=f\nDEVICE=mnk\n",
                    encoding="utf-8")
    assert Config.load(path).confirm_button == "f"


def test_comments_and_quotes(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text('# comment\nCONFIRM_BUTTON="e"\n\nHUD=yes\n', encoding="utf-8")

    config = Config.load(path)
    assert config.confirm_button == "e"
    assert config.hud is True


def test_swapped_bounds_are_normalised() -> None:
    config = Config(press_min_ms=110, press_max_ms=60)
    assert config.press_min == 0.06
    assert config.press_max == 0.11
