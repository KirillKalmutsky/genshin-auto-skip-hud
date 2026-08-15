"""Tray and application icons, drawn at runtime.

Generating them avoids shipping binary assets and keeps the tray icon in sync
with the state it represents: the ring changes colour, so a glance at the tray
tells you whether the skipper is armed.
"""
from PIL import Image, ImageDraw

RUNNING = (74, 222, 128)   # green
PAUSED = (251, 191, 36)    # amber
STOPPED = (100, 116, 139)  # slate
BACKDROP = (11, 16, 32)


def make_icon(colour: tuple[int, int, int], size: int = 64) -> Image.Image:
    """A rounded dark tile with a coloured ring and a play glyph inside."""
    scale = 4  # draw large, downsample: cheap anti-aliasing
    big = size * scale
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle([0, 0, big - 1, big - 1], radius=big // 5,
                           fill=BACKDROP + (255,))

    margin = big // 6
    draw.ellipse([margin, margin, big - margin, big - margin],
                 outline=colour + (255,), width=max(2, big // 16))

    # Play triangle, nudged right so it looks optically centred.
    cx, cy = big // 2, big // 2
    r = big // 7
    draw.polygon([(cx - r // 2 + r // 6, cy - r),
                  (cx - r // 2 + r // 6, cy + r),
                  (cx + r, cy)], fill=colour + (255,))

    return image.resize((size, size), Image.LANCZOS)


def icon_for(running: bool, game_running: bool) -> Image.Image:
    if not game_running:
        return make_icon(STOPPED)
    return make_icon(RUNNING if running else PAUSED)


def write_ico(path: str, sizes: tuple[int, ...] = (16, 24, 32, 48, 64, 256)) -> None:
    """Write a multi-resolution .ico for the executable itself."""
    base = make_icon(RUNNING, 256)
    base.save(path, format="ICO",
              sizes=[(size, size) for size in sizes])
