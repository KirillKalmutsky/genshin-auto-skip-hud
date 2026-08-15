"""The HUD must never sit where the detector looks.

It is drawn on the screen like anything else, so a panel over the auto-play
button would corrupt the very signal it reports. `top-left` did exactly that,
and was an accepted setting.
"""
from pathlib import Path

import pytest

from genshin_autoskip.config import HUD_POSITIONS, Config


def test_top_left_is_not_offered() -> None:
    assert "top-left" not in HUD_POSITIONS
    assert "bottom-left" in HUD_POSITIONS


def test_default_is_a_safe_corner() -> None:
    assert Config().hud_position in HUD_POSITIONS


def test_top_left_in_a_config_file_falls_back(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("HUD_POSITION=top-left\n", encoding="utf-8")
    assert Config.load(path).hud_position in HUD_POSITIONS


@pytest.mark.parametrize("corner", HUD_POSITIONS)
def test_every_offered_corner_survives_a_round_trip(corner: str,
                                                    tmp_path: Path) -> None:
    path = tmp_path / ".env"
    Config(hud_position=corner).save(path)
    assert Config.load(path).hud_position == corner


def test_nonsense_falls_back(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("HUD_POSITION=middle-of-nowhere\n", encoding="utf-8")
    assert Config.load(path).hud_position == "bottom-left"
