"""The auto-play button's two glyph shapes, background and opacity removed.

The button is two layers composited over the scene: a light disc with a dark
glyph drawn on it. For a pixel of each:

    disc  : I_d = a*F_d + (1-a)*B
    glyph : I_g = a*F_g + (1-a)*B
    I_d - I_g = a * (F_d - F_g)

The scene cancels exactly. Dividing that difference by its own maximum cancels
the opacity as well, which is why only two references are needed rather than one
per appearance - and why neither the background nor the button's transparency
has to be dealt with by sampling more examples.

Two consequences worth keeping in mind:

* Inside the disc the glyph is always the darker of the two, whatever lies
  behind the button. Comparing it against the *scene* instead is what made
  simple thresholding pick the wrong side.
* The difference before normalisation is proportional to the opacity, so it
  doubles as a presence check: measured, 40-163 with the button on screen
  against 2-22 without it.

Measured over 143 real frames: dialogue 0.776..1.000, no dialogue 0.000..0.485.
"""
import base64
import io

import numpy as np

#: Button box in 1080-reference pixels, measured from the window's top-left.
BUTTON_REF = (42, 20, 120, 98)
#: The button region is resized to this before anything else, which makes the
#: whole measurement resolution independent.
BUTTON_SIZE = 104
#: The glyph's box inside that region.
GLYPH_BOX = (28, 28, 78, 78)
#: Wider than the glyph's strokes, so closing fills the glyph in with the disc.
DISC_KERNEL = 15

_PAYLOAD = (
    "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"
)

SHAPE_NAMES = ("triangle", "bars")


def load_shapes() -> np.ndarray:
    """The reference shapes as floats in [0, 1], shape (2, h, w)."""
    with np.load(io.BytesIO(base64.b64decode(_PAYLOAD))) as data:
        return data["shapes"].astype(np.float32) / 255.0
