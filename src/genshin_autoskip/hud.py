"""Always-on-top status panel drawn over the game.

Designed to be *glanced* at rather than read: the left edge carries a full
height rail in the state's colour, so the state registers in peripheral vision
without focusing on the panel at all. Everything else is deliberately quiet.

Two things learned by photographing it over real game frames:

* At 0.88 opacity the scene behind showed through and the grey secondary text
  landed on top of game detail. The ground is now near-opaque, because a status
  panel that is sometimes unreadable is worse than one that hides a little
  scenery.
* The window auto-sized to its text, while its position was computed once from
  the width it had at startup - so a longer line pushed it off the screen edge
  and the right-hand side was cut off. The width is fixed now, long text wraps,
  and the panel re-places itself if its height changes anyway.

Built on tkinter so it needs no extra dependency. The window is click-through
(``WS_EX_TRANSPARENT``) and non-activating (``WS_EX_NOACTIVATE``) so it never
swallows a click meant for the game and never steals focus - which would pause
the skipper, since it only acts while Genshin is in front.

That click-through style is why the panel cannot simply be picked up with the
mouse: Windows leaves the whole window out of hit-testing, so no handler inside
it ever sees the click, however many widgets the binding covers. The drag handle
is therefore a *second, tiny window* without that style, parked over the panel's
top-right corner - the only part of the overlay that answers the mouse.

Placement note: the panel is captured by the screen grab like anything else, so
it must not sit on a region detection reads; `config.HUD_POSITIONS` excludes the
top-left corner for that reason.

Tkinter must own the main thread, so :meth:`Overlay.run` blocks; the detection
loop belongs on a worker thread.
"""
import ctypes
import tkinter as tk
from ctypes import wintypes
from typing import Callable, Optional

from .state import SkipperState

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
SPI_GETWORKAREA = 0x0030
GA_ROOT = 2

#: Deep desaturated navy rather than black: black reads as a hole punched in
#: the game, this reads as an instrument sitting on top of it.
INK = "#070b14"
EDGE = "#243250"
TEXT = "#eef3fb"
DIM = "#93a3be"
FAINT = "#6b7c99"

GO = "#3ddc84"      # working
HOLD = "#ffb020"    # waiting on something - focus, or the game being open
WORK = "#4cc2ff"    # your move
STOP = "#ff5c7a"    # not running at all

WIDTH = 330
RAIL = 4

#: The drag handle: small enough to be hard to hit by accident over the game,
#: big enough to grab without aiming.
GRIP_W, GRIP_H = 26, 22
GRIP_INSET = 5


def grip_origin(x: int, y: int, width: int = WIDTH) -> tuple[int, int]:
    """Where the handle sits given the panel's top-left corner."""
    return x + width - GRIP_W - GRIP_INSET, y + GRIP_INSET


def clamp(area: tuple[int, int, int, int], x: int, y: int,
          w: int, h: int) -> tuple[int, int]:
    """Keep a `w`x`h` window inside `area`.

    Applied while dragging as well as on restore, so a position that was
    reachable with the mouse is always a position the panel comes back to.
    """
    left, top, right, bottom = area
    return (int(min(max(x, left), max(right - w, left))),
            int(min(max(y, top), max(bottom - h, top))))

#: Condensed and geometric - narrow enough to keep the panel small, and not the
#: interface font every other Windows tool defaults to.
DISPLAY = ("Bahnschrift SemiBold Condensed", 16)
BODY = ("Segoe UI", 11)
UTILITY = ("Cascadia Mono", 9)

#: Anchor names as the tray menu words them, so panel and menu agree.
ANCHOR_LABELS = {
    "auto": "auto-play button",
    "marker": "orange marker",
    "both": "either",
}


#: Notes the loop sets, turned into states of their own. A note explains a tool
#: that looks like it is working and is not, so it has to reach the headline -
#: it is the state, not a footnote to one.
NOTE_STATES = (
    ("not elevated", "NO ADMIN", "keys are ignored"),
    ("input error", "KEY FAILED", ""),
    ("break", "BREAK", ""),
)


def note_state(note: str) -> tuple[str, str, str] | None:
    """Split a note into a headline, its detail, and nothing if it is routine.

    The detail falls back to whatever the note says after its prefix, so an
    unrecognised note still reaches the panel rather than being swallowed.
    """
    text = note.strip()
    for prefix, word, detail in NOTE_STATES:
        if text.lower().startswith(prefix):
            tail = text[len(prefix):].lstrip(" -:")
            return word, detail or tail, HOLD if word == "BREAK" else STOP
    return ("PROBLEM", text, STOP) if text else None


def _shorten(title: str, limit: int = 26) -> str:
    """Trim a window title on a word boundary rather than mid-word.

    Slicing by character produced things like "Google Chrome - a rather has
    focus", which reads as a bug in the panel rather than a long title.
    """
    title = title.strip()
    if len(title) <= limit:
        return title
    cut = title[:limit].rsplit(" ", 1)[0]
    return f"{cut or title[:limit]}…"


class Overlay:
    def __init__(self, state: SkipperState, position: str = "top-right",
                 margin: int = 24, alpha: float = 1.0,
                 on_move: Optional[Callable[[int, int], None]] = None,
                 point: Optional[tuple[int, int]] = None) -> None:
        self.state = state
        self.position = position
        self.margin = margin
        self.alpha = alpha
        self.on_move = on_move
        self.point = point
        self.root: tk.Tk | None = None
        self._grip: tk.Toplevel | None = None
        self._dots: list[int] = []
        self._canvas: tk.Canvas | None = None
        self._widgets: dict[str, tk.Widget] = {}
        self._visible = True
        self._height = 0
        self._drag: tuple[int, int] | None = None
        self._moved_to: tuple[int, int] | None = None

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        root = tk.Tk()
        self.root = root
        root.title("autoskip-hud")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", self.alpha)
        root.configure(bg=INK)

        shell = tk.Frame(root, bg=EDGE)
        shell.pack(fill="both", expand=True)

        # The signature: a full-height rail carrying the state colour, so the
        # state is legible from the corner of the eye.
        rail = tk.Frame(shell, bg=GO, width=RAIL)
        rail.pack(side="left", fill="y")
        rail.pack_propagate(False)

        body = tk.Frame(shell, bg=INK, padx=16, pady=12)
        body.pack(side="left", fill="both", expand=True)

        # No pack_propagate here: the window already fixes the width, and
        # switching propagation off without also setting a height collapsed the
        # row and clipped the headline.
        head = tk.Frame(body, bg=INK)
        head.pack(fill="x")
        title = tk.Label(head, text="READY", bg=INK, fg=GO, font=DISPLAY,
                         anchor="w")
        title.pack(side="left")

        # The one thing the state word cannot say on its own: *which* window
        # took the focus. It rides alongside the headline rather than on a line
        # of its own, which is what the panel used to spend a whole sentence on.
        detail = tk.Label(head, text="", bg=INK, fg=DIM, font=UTILITY,
                          anchor="e")
        # Kept clear of the drag handle, which sits in this same corner.
        detail.pack(side="right", pady=(6, 0), padx=(0, GRIP_W - GRIP_INSET))

        settings = tk.Label(body, text="", bg=INK, fg=FAINT, anchor="w",
                            justify="left", font=UTILITY,
                            wraplength=WIDTH - RAIL - 32)
        settings.pack(fill="x", pady=(10, 0))

        tk.Frame(body, bg=EDGE, height=1).pack(fill="x", pady=(10, 8))

        keys = tk.Label(body, text="", bg=INK, fg=FAINT, anchor="w",
                        justify="left", font=UTILITY,
                        wraplength=WIDTH - RAIL - 32)
        keys.pack(fill="x")

        self._widgets = {"rail": rail, "title": title, "detail": detail,
                         "settings": settings, "keys": keys}

        root.geometry(f"{WIDTH}x1")
        root.update_idletasks()
        root.geometry(f"{WIDTH}x{root.winfo_reqheight()}")
        root.update_idletasks()
        self._height = root.winfo_height()
        self._place(root)
        self._apply_style(root, click_through=True)
        self._build_grip(root)

    def _build_grip(self, root: tk.Tk) -> None:
        """The one part of the overlay that answers the mouse.

        Six dots in two columns - the shape every window manager and list
        editor uses for "pick this up", so it needs no label to be understood.
        """
        grip = tk.Toplevel(root)
        self._grip = grip
        grip.overrideredirect(True)
        grip.attributes("-topmost", True)
        grip.attributes("-alpha", self.alpha)
        grip.configure(bg=INK)

        canvas = tk.Canvas(grip, width=GRIP_W, height=GRIP_H, bg=INK,
                           highlightthickness=0, cursor="fleur")
        canvas.pack()
        self._canvas = canvas
        # Squares rather than circles: at three pixels across, an oval is drawn
        # as a plus sign, which reads as a cluster of little crosses.
        for col in range(2):
            for row in range(3):
                x = GRIP_W // 2 - 4 + col * 6
                y = GRIP_H // 2 - 7 + row * 6
                self._dots.append(canvas.create_rectangle(
                    x, y, x + 2, y + 2, fill=FAINT, outline=""))

        canvas.bind("<Enter>", lambda _e: self._tint(TEXT))
        canvas.bind("<Leave>", lambda _e: self._tint(FAINT))
        canvas.bind("<Button-1>", self._grab)
        canvas.bind("<B1-Motion>", self._drag_to)
        canvas.bind("<ButtonRelease-1>", self._drop)

        # Layered and non-activating like the panel, but deliberately *not*
        # click-through - that is the whole point of it.
        self._apply_style(grip, click_through=False)
        self._place_grip()
        grip.lift()

    def _tint(self, colour: str) -> None:
        if self._canvas is not None:
            for dot in self._dots:
                self._canvas.itemconfig(dot, fill=colour)

    def _place_grip(self, at: tuple[int, int] | None = None) -> None:
        """Park the handle on the panel's top-right corner.

        `at` is the panel position the caller just asked for. It has to be
        passed in rather than read back: `geometry()` only queues the move, so
        immediately afterwards the panel still reports where it used to be -
        which left the handle behind at its starting corner during a drag.
        """
        root, grip = self.root, self._grip
        if root is None or grip is None:
            return
        px, py = at if at is not None else (root.winfo_x(), root.winfo_y())
        x, y = grip_origin(px, py)
        grip.geometry(f"{GRIP_W}x{GRIP_H}+{x}+{y}")

    # -- placement ---------------------------------------------------------

    @staticmethod
    def _work_area(root: tk.Tk) -> tuple[int, int, int, int]:
        """The desktop minus the taskbar, so the bottom corners clear it."""
        rect = wintypes.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0,
                                                      ctypes.byref(rect), 0):
            return rect.left, rect.top, rect.right, rect.bottom
        return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()

    def _place(self, root: tk.Tk) -> None:
        # The requested height, not the current one: the window is told its
        # width, so its height has to follow the content it ends up wrapping to.
        w, h = WIDTH, max(root.winfo_reqheight(), root.winfo_height())
        left, top, right, bottom = self._work_area(root)

        if self.point is not None:
            # A position the user dragged to, clamped so it cannot be lost off
            # screen if the display arrangement changes.
            x, y = clamp((left, top, right, bottom),
                         int(self.point[0]), int(self.point[1]), w, h)
        else:
            m = self.margin
            x, y = {
                "top-right": (right - w - m, top + m),
                "bottom-right": (right - w - m, bottom - h - m),
                "bottom-left": (left + m, bottom - h - m),
            }.get(self.position, (left + m, bottom - h - m))
        root.geometry(f"{w}x{h}+{int(x)}+{int(y)}")
        self._place_grip((int(x), int(y)))

    @staticmethod
    def _apply_style(window: tk.Misc, click_through: bool) -> None:
        user32 = ctypes.windll.user32
        user32.GetWindowLongPtrW.restype = ctypes.c_longlong
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetWindowLongPtrW.restype = ctypes.c_longlong
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int,
                                             ctypes.c_longlong]

        # GA_ROOT rather than GetParent: Tk wraps its windows, so the id it
        # hands out is a child of the real frame - but a Toplevel is *owned* by
        # the main window, and GetParent would climb to that and restyle the
        # panel instead of the handle. GA_ROOT stops at the top-level window.
        hwnd = user32.GetAncestor(window.winfo_id(), GA_ROOT) or window.winfo_id()
        style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        style |= WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
        if click_through:
            style |= WS_EX_LAYERED | WS_EX_TRANSPARENT
        else:
            # No WS_EX_LAYERED here. Setting it without also setting the layer's
            # attributes leaves the window composited from nothing - it stops
            # being drawn entirely, which is exactly how the handle first came
            # out invisible. Tk adds the style itself when opacity is below 1,
            # and configures it properly when it does.
            style &= ~WS_EX_TRANSPARENT
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)

    # -- dragging ----------------------------------------------------------

    def _grab(self, event: "tk.Event") -> None:
        """Remember where inside the panel the handle was taken hold of."""
        self._drag = (event.x_root - self.root.winfo_x(),
                      event.y_root - self.root.winfo_y())

    def _drag_to(self, event: "tk.Event") -> None:
        root = self.root
        if root is None or self._drag is None:
            return
        x, y = clamp(self._work_area(root),
                     event.x_root - self._drag[0], event.y_root - self._drag[1],
                     WIDTH, self._height)
        root.geometry(f"+{x}+{y}")
        self._place_grip((x, y))
        self._moved_to = (x, y)

    def _drop(self, _event: "tk.Event") -> None:
        """Remember where it was let go - the same coordinates that were asked
        for, not what the window reports before the move has been processed."""
        if self._drag is not None and self._moved_to and self.on_move:
            self.on_move(*self._moved_to)
        self._drag = None

    # -- what the panel says -----------------------------------------------

    def _headline(self) -> tuple[str, str]:
        """States what is true now, not merely what is switched on.

        The colour is the whole point of the rail, so it has to mean one thing:
        red nothing is happening, amber something is expected of you or of the
        game, green working.
        """
        s = self.state
        # Stopped first, so F8 always visibly does something. A warning would
        # otherwise sit there permanently - "not elevated" is set once at
        # startup and never clears - and swallow that feedback.
        if not s.running:
            return "STOPPED", STOP
        if (warning := note_state(s.note)) is not None:
            return warning[0], warning[2]
        if s.choice and not s.auto_answer:
            return "YOUR TURN", WORK
        if not s.game_running:
            return "NO GAME", HOLD
        if not s.game_focused:
            return "NO FOCUS", HOLD
        return ("SKIPPING", GO) if s.dialogue else ("READY", GO)

    def _detail(self) -> tuple[str, str]:
        """What the state word leaves out - nothing, most of the time.

        The sentence that used to sit here restated the headline: "SKIPPING"
        over "Skipping dialogue". Two cases carried something new, and only
        those still say anything: which window stole the focus, and what a
        warning is about.
        """
        s = self.state
        if s.running and (warning := note_state(s.note)) is not None:
            # Capped: an input error carries whatever Windows reported, and a
            # long one would run past the panel rather than wrap.
            return _shorten(warning[1], 22), warning[2]
        if s.running and s.game_running and not s.game_focused and s.foreground:
            return _shorten(s.foreground, 20), DIM
        return "", DIM

    def _settings_line(self) -> str:
        """Two settings, two lines, labels aligned.

        Side by side they read as one run-on phrase; stacked and padded to the
        same width they read as a small table, which is what they are.
        """
        anchor = ANCHOR_LABELS.get(self.state.anchor, self.state.anchor)
        answers = "auto" if self.state.auto_answer else "manual"
        return f"mode      {anchor}\nanswers   {answers}"

    def _keys_line(self) -> str:
        """Each key is labelled with what it controls, not with its next value.

        "F10 manual" read as a status while every other entry read as an
        action, and the current setting is already on the line above.
        """
        first = "F8 stop" if self.state.running else "F8 start"
        # Two deliberate lines rather than one that wraps wherever it lands.
        return f"{first}   F9 mode   F10 answers\nF11 hide   F12 quit"

    # -- refresh -----------------------------------------------------------

    def _tick(self) -> None:
        root = self.root
        if root is None:
            return
        s = self.state

        if s.should_exit:
            root.quit()
            return

        if s.hud_visible != self._visible:
            self._visible = s.hud_visible
            # The handle is its own window, so it has to be hidden with the
            # panel - otherwise F11 leaves six dots floating over the game.
            for window in (root, self._grip):
                if window is None:
                    continue
                window.deiconify() if s.hud_visible else window.withdraw()
            if s.hud_visible and self._grip is not None:
                self._place_grip()
                self._grip.lift()

        title, colour = self._headline()
        self._widgets["title"].config(text=title, fg=colour)
        self._widgets["rail"].config(bg=colour)

        detail, tone = self._detail()
        self._widgets["detail"].config(text=detail, fg=tone)
        self._widgets["settings"].config(text=self._settings_line())
        self._widgets["keys"].config(text=self._keys_line())

        # Every row is a fixed number of lines, so this should never fire - it
        # is here so an unexpected change re-anchors the panel to its corner
        # instead of letting it grow off the screen edge.
        root.update_idletasks()
        wanted = root.winfo_reqheight()
        if wanted != self._height:
            self._height = wanted
            if self._drag is None:
                self._place(root)

        root.after(120, self._tick)

    # -- lifecycle ---------------------------------------------------------

    def run(self) -> None:
        """Build and drive the panel. Blocks until the state asks to exit."""
        self._build()
        assert self.root is not None
        self.root.after(120, self._tick)
        self.root.mainloop()
        try:
            self.root.destroy()
        except tk.TclError:
            pass
