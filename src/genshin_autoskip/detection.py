"""Dialogue detection by matching the auto-play button's glyph.

Earlier versions described the button with heuristics - bright, square, hollow,
roughly this size, roughly this colour - and every one of those descriptions
also fits something else the game draws: the quest journal's category icon, the
back arrow in full-screen menus, the Paimon menu button, markers on the minimap.
Tightening the heuristics to exclude them kept excluding the real button too,
because it changes appearance: play triangle or pause bars, lit or translucent,
and while translucent it blends with whatever is behind it.

So the button is identified by its *glyph*, matched against reference images of
every appearance it actually has. The circle around it is deliberately excluded
- that is the part every other round control shares.

Matching uses TM_CCOEFF_NORMED, which subtracts the mean and normalises by
variance, so it does not care how bright the scene is. Measured over 122 real
frames with the references in :mod:`templates`:

    dialogue on screen   0.872 .. 1.000
    no dialogue          0.102 .. 0.711

Geometry notes:

* Regions are anchored to the *game window*, not the primary monitor, so the
  game may sit on a second display or in a window.
* Sizes scale with window **height**. Genshin scales its HUD uniformly and
  anchors it to the screen edges, so on an ultrawide display the button stays
  the same size and the same distance from the left edge.
"""
from dataclasses import dataclass, field
from typing import Optional

import cv2
import mss
import numpy as np

from .templates import (BUTTON_REF, BUTTON_SIZE, DISC_KERNEL, GLYPH_BOX,
                        SHAPE_NAMES, load_shapes)
from .window import game_rect

REFERENCE_HEIGHT = 1080

#: Which on-screen element to key on.
#:
#: ``auto``   the auto-play button, top left. Says "a dialogue UI is open".
#: ``marker`` the orange diamond under the dialogue text. Says "the game is
#:            waiting for you to advance".
#: ``both``   fire on either.
ANCHOR_AUTO = "auto"
ANCHOR_MARKER = "marker"
ANCHOR_BOTH = "both"
ANCHORS = (ANCHOR_AUTO, ANCHOR_MARKER, ANCHOR_BOTH)

#: Halfway between the worst real match (0.776) and the best false one (0.485).
MIN_CONFIDENCE = 0.63

#: Below this recovered contrast there is nothing meaningfully darker than the
#: disc, so there is no button. Measured: 40-163 with the button on screen,
#: 2-22 without it.
MIN_GLYPH_CONTRAST = 30.0

#: Below this the button is translucent, which is what the game does while it
#: waits for an answer to be picked. Medians measured 163 lit against 41
#: translucent, but the ranges overlap, so this is a hint rather than a fact -
#: it only gates answering, never detection.
TRANSLUCENT_CONTRAST = 90.0

#: The marker's own floor. It has to be separate: the two scores are not on the
#: same scale, and the marker's real range starts at 0.710, so moving the
#: button's threshold would silently switch the marker anchor off.
#:
#: Measured over 23 real frames:
#:     line running    0.710 .. 0.927   fires 13/13
#:     choice waiting  0.000            marker genuinely absent - the game is
#:                                      waiting for an answer, not for "next"
#:     no dialogue     0.000            fires 0/3
MARKER_MIN_CONFIDENCE = 0.60

#: The continue marker, measured on live frames: a 38x38 diamond outline centred
#: 19 px left of screen centre at y=1373 in a 2560x1440 window, pulsing in size
#: between a full diamond and a sliver without ever vanishing.
MARKER_CENTRE_DX_REF = -14.0
MARKER_CENTRE_Y_REF = 1030.0
MARKER_SIZE_REF = 28.5
MARKER_BOX_REF = (110, 40)
MARKER_HSV_LOW = (8, 90, 90)
MARKER_HSV_HIGH = (35, 255, 255)

#: Seconds a positive detection keeps counting after it stops matching. Zero:
#: any hold means pressing on after the dialogue has closed.
DETECTION_HOLD = 0.0


@dataclass
class Detection:
    """Outcome of one detection pass."""

    dialogue: bool = False
    confidence: float = 0.0
    #: True when the game is waiting for an answer to be chosen rather than for
    #: the line to be advanced. None when it could not be determined.
    choice: Optional[bool] = None
    roi: Optional[np.ndarray] = field(default=None, repr=False)


class DialogueDetector:
    """Detects whether Genshin is showing its dialogue UI.

    A ``mss`` instance is bound to the thread that creates it, so build the
    detector on the thread that will call :meth:`detect`.
    """

    def __init__(self, fallback_width: int, fallback_height: int,
                 keep_roi: bool = False, anchor: str = ANCHOR_AUTO) -> None:
        self.fallback = (0, 0, fallback_width, fallback_height)
        self.keep_roi = keep_roi
        self.anchor = anchor if anchor in ANCHORS else ANCHOR_AUTO
        self.shapes = load_shapes()
        self._disc_kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (DISC_KERNEL, DISC_KERNEL))
        self._sct = mss.MSS()
        self.rect = self.fallback
        self.auto_roi: dict = {}
        self.marker_roi: dict = {}
        self.expected_marker_size = 0.0
        self.refresh_geometry()

    # -- geometry ----------------------------------------------------------

    def refresh_geometry(self) -> bool:
        """Re-anchor onto the game window. Returns True if the rect changed."""
        rect = game_rect() or self.fallback
        if rect == self.rect and self.auto_roi:
            return False

        self.rect = rect
        left, top, width, height = rect
        scale = height / REFERENCE_HEIGHT

        x0, y0, x1, y1 = BUTTON_REF
        self.auto_roi = {
            "left": left + int(x0 * scale), "top": top + int(y0 * scale),
            "width": max(1, int((x1 - x0) * scale)),
            "height": max(1, int((y1 - y0) * scale)),
        }

        centre_x = left + width / 2 + MARKER_CENTRE_DX_REF * scale
        centre_y = top + MARKER_CENTRE_Y_REF * scale
        half_w, half_h = (value * scale for value in MARKER_BOX_REF)
        self.marker_roi = {
            "left": int(centre_x - half_w), "top": int(centre_y - half_h),
            "width": max(1, int(half_w * 2)), "height": max(1, int(half_h * 2)),
        }
        self.expected_marker_size = MARKER_SIZE_REF * scale
        return True

    def set_anchor(self, anchor: str) -> bool:
        """Switch anchor at runtime. Returns True if it changed."""
        wanted = anchor if anchor in ANCHORS else ANCHOR_AUTO
        if wanted == self.anchor:
            return False
        self.anchor = wanted
        return True

    # -- scoring -----------------------------------------------------------

    def glyph_map(self, roi: np.ndarray) -> tuple[np.ndarray, float]:
        """The glyph's shape with the scene and the opacity divided out.

        Closing with a kernel wider than the glyph's strokes fills the glyph in
        with the disc around it, so the difference isolates the glyph. That
        difference is ``alpha * (disc colour - glyph colour)`` - the scene has
        cancelled - and dividing by its own peak cancels alpha too.
        """
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        if gray.shape[:2] != (BUTTON_SIZE, BUTTON_SIZE):
            gray = cv2.resize(gray, (BUTTON_SIZE, BUTTON_SIZE),
                              interpolation=cv2.INTER_AREA)

        value = gray.astype(np.float32)
        disc = cv2.morphologyEx(value, cv2.MORPH_CLOSE, self._disc_kernel)
        x0, y0, x1, y1 = GLYPH_BOX
        inner = np.clip(disc - value, 0, None)[y0:y1, x0:x1]

        contrast = float(np.percentile(inner, 99))
        if contrast < MIN_GLYPH_CONTRAST:
            return np.zeros_like(inner), contrast
        return np.clip(inner / contrast, 0, 1), contrast

    @staticmethod
    def _correlate(a: np.ndarray, b: np.ndarray) -> float:
        a = a - a.mean()
        b = b - b.mean()
        denominator = float(np.sqrt((a * a).sum() * (b * b).sum()))
        return float((a * b).sum() / denominator) if denominator else 0.0

    def match_button(self, roi: np.ndarray) -> tuple[float, float, str]:
        """(agreement with the best shape, recovered contrast, shape name)."""
        shape, contrast = self.glyph_map(roi)
        if contrast < MIN_GLYPH_CONTRAST:
            return 0.0, contrast, ""

        best, which = -1.0, ""
        for name, reference in zip(SHAPE_NAMES, self.shapes):
            value = self._correlate(shape, reference)
            if value > best:
                best, which = value, name
        # Correlation runs from -1 to 1, and a negative one means the region is
        # the *inverse* of the shape - no more a match than no correlation at
        # all. Reporting it raw put negative numbers on the HUD.
        return max(best, 0.0), contrast, which

    def _score_marker(self, roi: np.ndarray) -> float:
        """Best match score for the orange continue diamond, 0.0 - 1.0."""
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array(MARKER_HSV_LOW, dtype=np.uint8),
                           np.array(MARKER_HSV_HIGH, dtype=np.uint8))
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)

        centre_x = roi.shape[1] / 2.0
        best = 0.0
        for i in range(1, count):
            x, _, w, h, area = stats[i]
            if w < 5 or h < 4 or area < 30:
                continue
            # It swells to a full diamond while the game waits and collapses to
            # a sliver while the line is still typing out.
            ratio = ((w + h) / 2.0) / self.expected_marker_size
            if not 0.20 <= ratio <= 1.40:
                continue
            offset = abs(x + w / 2.0 - centre_x) / centre_x
            if offset > 0.30:
                continue
            score = (1.0 - offset) * 0.55 + min(ratio, 1.0) * 0.30 + 0.15
            best = max(best, min(score, 1.0))
        return float(best)

    # -- public API --------------------------------------------------------

    def detect(self) -> Detection:
        """Run one detection pass using whichever anchor is configured."""
        roi = None
        confidence = 0.0
        choice: Optional[bool] = None

        if self.anchor in (ANCHOR_AUTO, ANCHOR_BOTH):
            roi = np.asarray(self._sct.grab(self.auto_roi))[:, :, :3]
            confidence, contrast, _ = self.match_button(roi)
            if confidence >= MIN_CONFIDENCE:
                choice = contrast < TRANSLUCENT_CONTRAST

        seen = confidence >= MIN_CONFIDENCE
        if self.anchor == ANCHOR_MARKER or (
                self.anchor == ANCHOR_BOTH and not seen):
            marker = np.asarray(self._sct.grab(self.marker_roi))[:, :, :3]
            marker_score = self._score_marker(marker)
            # Each anchor is judged against its own floor, then the stronger
            # relative result is reported.
            if marker_score >= MARKER_MIN_CONFIDENCE:
                seen = True
            confidence = max(confidence, marker_score)
            if roi is None:
                roi = marker

        confidence = float(confidence)
        return Detection(
            dialogue=bool(seen),
            confidence=confidence,
            choice=choice,
            roi=roi if self.keep_roi else None,
        )

    def close(self) -> None:
        self._sct.close()

    def __enter__(self) -> "DialogueDetector":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
