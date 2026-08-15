"""The drag handle's geometry.

The panel itself is click-through, which is why it cannot be picked up with the
mouse at all: Windows leaves a `WS_EX_TRANSPARENT` window out of hit-testing, so
no binding inside it ever sees the click. The handle is a separate window
without that style, and these are the rules it has to keep.
"""
import pytest

from genshin_autoskip.hud import GRIP_H, GRIP_INSET, GRIP_W, WIDTH, clamp, grip_origin


def test_handle_sits_inside_the_panel() -> None:
    x, y = grip_origin(100, 200)
    assert x >= 100 and x + GRIP_W <= 100 + WIDTH
    assert y >= 200


def test_handle_hugs_the_top_right_corner() -> None:
    x, y = grip_origin(0, 0)
    assert x == WIDTH - GRIP_W - GRIP_INSET
    assert y == GRIP_INSET


def test_handle_moves_with_the_panel() -> None:
    first = grip_origin(0, 0)
    second = grip_origin(-350, 640)
    assert (second[0] - first[0], second[1] - first[1]) == (-350, 640)


def test_handle_is_big_enough_to_grab() -> None:
    # Small enough not to swallow game clicks by accident, big enough to hit
    # without aiming. Windows' own resize borders are about this size.
    assert 16 <= GRIP_W <= 40
    assert 16 <= GRIP_H <= 40


AREA = (0, 0, 1920, 1040)


def test_a_position_on_screen_is_left_alone() -> None:
    assert clamp(AREA, 300, 400, 330, 245) == (300, 400)


@pytest.mark.parametrize("point", [(-500, -500), (5000, 5000), (1900, 1030)])
def test_the_panel_cannot_be_dragged_off_screen(point: tuple[int, int]) -> None:
    x, y = clamp(AREA, *point, 330, 245)
    assert 0 <= x <= 1920 - 330
    assert 0 <= y <= 1040 - 245


def test_clamping_is_what_makes_a_dragged_position_restore_unchanged() -> None:
    """Drag and reload apply the same rule, so the panel comes back where it
    was left rather than shifting on the next start."""
    dropped = clamp(AREA, 5000, 5000, 330, 245)
    assert clamp(AREA, *dropped, 330, 245) == dropped


def test_a_screen_smaller_than_the_panel_still_gives_a_visible_corner() -> None:
    # Nothing fits, but the top-left is reachable - never a negative offset
    # that would put the panel out of reach entirely.
    assert clamp((0, 0, 200, 150), 400, 400, 330, 245) == (0, 0)
