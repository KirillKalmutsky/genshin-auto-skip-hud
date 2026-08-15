from genshin_autoskip import window


def test_single_instance_guard() -> None:
    """The second claim must fail, or two copies would both press the key."""
    name = "GenshinAutoSkipTestMutex"
    assert window.claim_single_instance(name) is True
    assert window.claim_single_instance(name) is False


def test_dpi_awareness_is_granted() -> None:
    """Without it, regions are measured in layout pixels and read in physical
    ones - which only diverge once the display is scaled above 100%."""
    mode = window.declare_dpi_aware()
    assert mode in {"per-monitor-v2", "per-monitor", "system"}


def test_dpi_declaration_is_idempotent() -> None:
    """Windows refuses a second, different declaration; that must not raise."""
    first = window.declare_dpi_aware()
    assert window.declare_dpi_aware() == first


def test_primary_screen_size_is_sane() -> None:
    width, height = window.primary_screen_size()
    assert width > 0 and height > 0


def test_foreground_title_returns_a_string() -> None:
    assert isinstance(window.foreground_title(), str)


def test_game_rect_shape() -> None:
    rect = window.game_rect()
    if rect is not None:  # only when Genshin happens to be running
        left, top, width, height = rect
        assert width > 0 and height > 0
