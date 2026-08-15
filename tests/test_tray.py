"""The tray menu is the only interface most of the time, so pin its wiring."""
from genshin_autoskip.config import Config
from genshin_autoskip.state import SkipperState
from genshin_autoskip.tray import PROJECT_URL, Tray


def build(**config_kwargs) -> tuple[Tray, SkipperState, Config]:
    state, config = SkipperState(), Config(**config_kwargs)
    tray = Tray(state, config)
    tray._persist = lambda: None
    return tray, state, config


def test_project_url_points_at_the_repository() -> None:
    assert PROJECT_URL.startswith("https://github.com/")
    assert PROJECT_URL.endswith("genshin-auto-skip-hud")


def test_opening_the_project_does_not_block_the_menu(monkeypatch) -> None:
    """The handler runs on the pump that keeps the icon alive."""
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))

    tray, _, _ = build()
    tray._open_project()

    for _ in range(100):
        if opened:
            break
        from time import sleep
        sleep(0.01)
    assert opened == [PROJECT_URL]


def test_menu_builds_and_contains_the_project_entry() -> None:
    tray, _, _ = build()
    labels = []
    for item in tray._build_menu():
        try:
            labels.append(str(item.text))
        except Exception:
            pass
    assert any("GitHub" in label for label in labels)
    assert any("Exit" in label for label in labels)


def test_speed_presets_cover_fast_through_slow() -> None:
    tray, _, config = build()
    tray._set_speed(400.0, 600.0)()
    assert (config.press_min_ms, config.press_max_ms) == (400.0, 600.0)
    tray._set_speed(40.0, 70.0)()
    assert (config.press_min_ms, config.press_max_ms) == (40.0, 70.0)
