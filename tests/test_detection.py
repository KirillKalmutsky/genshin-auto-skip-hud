"""Detection recovers the glyph's shape instead of describing its pixels.

The button is a light disc with a dark glyph composited over the scene, so the
difference between glyph and disc is ``alpha * (disc colour - glyph colour)``:
the scene cancels, and dividing by the peak cancels the opacity. These tests
therefore build fixtures the way the game does - a glyph on a disc over some
background - and vary both the background and the opacity.
"""
import cv2
import numpy as np
import pytest

from genshin_autoskip import detection
from genshin_autoskip.detection import (ANCHORS, MIN_CONFIDENCE,
                                        MIN_GLYPH_CONTRAST, DialogueDetector)
from genshin_autoskip.templates import BUTTON_REF, BUTTON_SIZE, load_shapes


@pytest.fixture()
def detector(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(detection, "game_rect", lambda: None)
    instance = DialogueDetector(1920, 1080)
    yield instance
    instance.close()


def render(shape: np.ndarray, alpha: float = 1.0,
           background: int | np.ndarray = 40) -> np.ndarray:
    """A button drawn the way the game draws it.

    A light disc with the dark glyph on it, the pair composited over some
    background at the given opacity.
    """
    disc_colour, glyph_colour = 235.0, 60.0
    layer = np.full((BUTTON_SIZE, BUTTON_SIZE), 0.0, dtype=np.float32)
    mask = np.zeros((BUTTON_SIZE, BUTTON_SIZE), dtype=np.float32)

    centre = BUTTON_SIZE // 2
    cv2.circle(mask, (centre, centre), centre - 8, 1.0, thickness=-1)
    layer[:] = disc_colour

    x0, y0, x1, y1 = detection.GLYPH_BOX
    layer[y0:y1, x0:x1] = (disc_colour * (1 - shape)
                           + glyph_colour * shape)

    scene = (np.full((BUTTON_SIZE, BUTTON_SIZE), float(background))
             if np.isscalar(background) else background.astype(np.float32))
    composite = np.where(mask > 0, alpha * layer + (1 - alpha) * scene, scene)
    return cv2.cvtColor(np.clip(composite, 0, 255).astype(np.uint8),
                        cv2.COLOR_GRAY2BGR)


# -- the references ---------------------------------------------------------

def test_two_references_are_enough() -> None:
    shapes = load_shapes()
    assert shapes.shape[0] == 2
    assert shapes.min() >= 0.0 and shapes.max() <= 1.0


@pytest.mark.parametrize("index", [0, 1])
def test_each_reference_matches_itself(detector: DialogueDetector,
                                       index: int) -> None:
    score, contrast, _ = detector.match_button(render(detector.shapes[index]))
    assert score >= 0.95
    assert contrast >= MIN_GLYPH_CONTRAST


# -- the point of the whole approach ---------------------------------------

@pytest.mark.parametrize("alpha", [1.0, 0.7, 0.45, 0.3])
def test_opacity_does_not_matter(detector: DialogueDetector,
                                 alpha: float) -> None:
    """Dividing by the recovered peak cancels alpha, so one reference serves."""
    score, _, _ = detector.match_button(render(detector.shapes[1], alpha=alpha))
    assert score >= MIN_CONFIDENCE


@pytest.mark.parametrize("background", [0, 90, 180, 255])
def test_background_does_not_matter(detector: DialogueDetector,
                                    background: int) -> None:
    """The scene cancels algebraically, including where it is brighter than
    the button - which is what made simple thresholding pick the wrong side."""
    score, _, _ = detector.match_button(
        render(detector.shapes[0], alpha=0.5, background=background))
    assert score >= MIN_CONFIDENCE


def test_textured_background_does_not_matter(detector: DialogueDetector) -> None:
    rng = np.random.default_rng(7)
    texture = rng.integers(0, 255, (BUTTON_SIZE, BUTTON_SIZE)).astype(np.float32)
    texture = cv2.GaussianBlur(texture, (21, 21), 0)
    score, _, _ = detector.match_button(
        render(detector.shapes[1], alpha=0.6, background=texture))
    assert score >= MIN_CONFIDENCE


# -- things that are not the button ----------------------------------------

def test_flat_region_has_no_glyph(detector: DialogueDetector) -> None:
    flat = np.full((BUTTON_SIZE, BUTTON_SIZE, 3), 128, dtype=np.uint8)
    score, contrast, _ = detector.match_button(flat)
    assert contrast < MIN_GLYPH_CONTRAST
    assert score == 0.0


def test_plain_disc_is_not_a_match(detector: DialogueDetector) -> None:
    """The Paimon button and every menu's back arrow are also white circles."""
    blank = np.zeros((detector.shapes[0].shape), dtype=np.float32)
    score, _, _ = detector.match_button(render(blank))
    assert score < MIN_CONFIDENCE


def test_noise_is_not_a_match(detector: DialogueDetector) -> None:
    rng = np.random.default_rng(0)
    noise = rng.integers(0, 255, (BUTTON_SIZE, BUTTON_SIZE, 3), dtype=np.uint8)
    score, _, _ = detector.match_button(noise)
    assert score < MIN_CONFIDENCE


@pytest.mark.parametrize("seed", range(8))
def test_confidence_is_never_negative(detector: DialogueDetector,
                                      seed: int) -> None:
    """Correlation runs -1..1, and the raw value reached the HUD.

    A region that is the inverse of the shape correlates negatively; that is no
    more a match than no correlation, and it must not be reported as a number
    below zero.
    """
    rng = np.random.default_rng(seed)
    region = rng.integers(0, 255, (BUTTON_SIZE, BUTTON_SIZE, 3), dtype=np.uint8)
    score, _, _ = detector.match_button(region)
    assert score >= 0.0

    inverted = 255 - render(detector.shapes[0])
    assert detector.match_button(inverted)[0] >= 0.0


def test_wrong_shape_is_not_a_match(detector: DialogueDetector) -> None:
    """A blob of the right size but the wrong outline must not pass."""
    wrong = np.zeros(detector.shapes[0].shape, dtype=np.float32)
    cv2.circle(wrong, (wrong.shape[1] // 2, wrong.shape[0] // 2),
               wrong.shape[0] // 4, 1.0, thickness=-1)
    score, _, _ = detector.match_button(render(wrong))
    assert score < MIN_CONFIDENCE


def test_rescaled_region_still_matches(detector: DialogueDetector) -> None:
    """Crops from other resolutions are resized before anything else."""
    region = render(detector.shapes[1])
    for size in (BUTTON_SIZE // 2, int(BUTTON_SIZE * 1.8)):
        scaled = cv2.resize(region, (size, size), interpolation=cv2.INTER_AREA)
        score, _, _ = detector.match_button(scaled)
        assert score >= MIN_CONFIDENCE * 0.9


# -- geometry ---------------------------------------------------------------

@pytest.mark.parametrize("size", [(1920, 1080), (2560, 1440), (3440, 1440),
                                  (5120, 1440), (3840, 2160)])
def test_geometry_scales_with_height_only(monkeypatch: pytest.MonkeyPatch,
                                          size: tuple[int, int]) -> None:
    monkeypatch.setattr(detection, "game_rect", lambda: None)
    instance = DialogueDetector(*size)
    scale = size[1] / 1080
    assert instance.auto_roi["left"] == int(BUTTON_REF[0] * scale)
    assert instance.auto_roi["width"] == int((BUTTON_REF[2] - BUTTON_REF[0]) * scale)
    instance.close()


def test_roi_follows_a_moved_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(detection, "game_rect", lambda: None)
    instance = DialogueDetector(1920, 1080)
    assert instance.auto_roi["left"] == BUTTON_REF[0]

    monkeypatch.setattr(detection, "game_rect", lambda: (400, 250, 1920, 1080))
    assert instance.refresh_geometry() is True
    assert instance.auto_roi["left"] == 400 + BUTTON_REF[0]
    instance.close()


def test_anchor_choice_is_validated() -> None:
    assert DialogueDetector(1920, 1080, anchor="nonsense").anchor == "auto"
    for anchor in ANCHORS:
        instance = DialogueDetector(1920, 1080, anchor=anchor)
        assert instance.anchor == anchor
        instance.close()


# -- the continue marker ----------------------------------------------------

MARKER_BGR = (30, 87, 115)


def marker_frame(detector: DialogueDetector, size: int | None = None,
                 dx: int = 0) -> np.ndarray:
    roi = np.zeros((detector.marker_roi["height"], detector.marker_roi["width"], 3),
                   dtype=np.uint8)
    half = (size or int(detector.expected_marker_size)) // 2
    cx, cy = roi.shape[1] // 2 + dx, roi.shape[0] // 2
    points = np.array([[cx, cy - half], [cx + half, cy],
                       [cx, cy + half], [cx - half, cy]])
    cv2.polylines(roi, [points], True, MARKER_BGR, thickness=max(2, half // 4))
    return roi


def test_marker_is_recognised(detector: DialogueDetector) -> None:
    assert detector._score_marker(marker_frame(detector)) >= MIN_CONFIDENCE


def test_collapsed_marker_is_recognised(detector: DialogueDetector) -> None:
    assert detector._score_marker(marker_frame(detector, size=10)) >= MIN_CONFIDENCE


def test_off_centre_warm_blob_is_ignored(detector: DialogueDetector) -> None:
    far = detector.marker_roi["width"] // 2 - 10
    assert detector._score_marker(marker_frame(detector, dx=far)) < MIN_CONFIDENCE


def test_empty_marker_band_scores_zero(detector: DialogueDetector) -> None:
    blank = np.zeros((detector.marker_roi["height"],
                      detector.marker_roi["width"], 3), dtype=np.uint8)
    assert detector._score_marker(blank) == 0.0
