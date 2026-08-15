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
the skipper, since it only acts while Genshin is in front. Click-through is
lifted while the panel is being moved.

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
        self._widgets: dict[str, tk.Widget] = {}
        self._visible = True
        self._movable = False
        self._height = 0
        self._drag: tuple[int, int] | None = None

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

        activity = tk.Label(body, text="", bg=INK, fg=DIM, anchor="w",
                            justify="left", font=BODY,
                            wraplength=WIDTH - RAIL - 32)
        activity.pack(fill="x", pady=(6, 0))

        settings = tk.Label(body, text="", bg=INK, fg=FAINT, anchor="w",
                            justify="left", font=UTILITY,
                            wraplength=WIDTH - RAIL - 32)
        settings.pack(fill="x", pady=(9, 0))

        tk.Frame(body, bg=EDGE, height=1).pack(fill="x", pady=(10, 8))

        keys = tk.Label(body, text="", bg=INK, fg=FAINT, anchor="w",
                        justify="left", font=UTILITY,
                        wraplength=WIDTH - RAIL - 32)
        keys.pack(fill="x")

        self._widgets = {"rail": rail, "title": title,
                         "activity": activity, "settings": settings,
                         "keys": keys}

        root.geometry(f"{WIDTH}x1")
        root.update_idletasks()
        root.geometry(f"{WIDTH}x{root.winfo_reqheight()}")
        root.update_idletasks()
        self._height = root.winfo_height()
        self._place(root)
        self._set_click_through(True)

        # Every descendant, not just the frames: the labels cover almost the
        # whole panel, and Tk delivers a click to the innermost widget under
        # the pointer without passing it up to the parent - so binding the
        # frames alone meant the panel could never actually be picked up.
        self._bind_drag(root)

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
            x = min(max(self.point[0], left), right - w)
            y = min(max(self.point[1], top), bottom - h)
        else:
            m = self.margin
            x, y = {
                "top-right": (right - w - m, top + m),
                "bottom-right": (right - w - m, bottom - h - m),
                "bottom-left": (left + m, bottom - h - m),
            }.get(self.position, (left + m, bottom - h - m))
        root.geometry(f"{w}x{h}+{int(x)}+{int(y)}")

    def _set_click_through(self, through: bool) -> None:
        root = self.root
        if root is None:
            return
        user32 = ctypes.windll.user32
        user32.GetWindowLongPtrW.restype = ctypes.c_longlong
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetWindowLongPtrW.restype = ctypes.c_longlong
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int,
                                             ctypes.c_longlong]

        hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
        style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        style |= WS_EX_LAYERED | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
        style = style | WS_EX_TRANSPARENT if through else style & ~WS_EX_TRANSPARENT
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)

    # -- dragging ----------------------------------------------------------

    def _bind_drag(self, widget: tk.Misc) -> None:
        widget.bind("<Button-1>", self._grab)
        widget.bind("<B1-Motion>", self._drag_to)
        widget.bind("<ButtonRelease-1>", self._drop)
        for child in widget.winfo_children():
            self._bind_drag(child)

    def _grab(self, event: "tk.Event") -> None:
        if self._movable:
            self._drag = (event.x_root - self.root.winfo_x(),
                          event.y_root - self.root.winfo_y())

    def _drag_to(self, event: "tk.Event") -> None:
        if self._movable and self._drag:
            self.root.geometry(f"+{event.x_root - self._drag[0]}"
                               f"+{event.y_root - self._drag[1]}")

    def _drop(self, _event: "tk.Event") -> None:
        if self._movable and self._drag and self.on_move:
            self.on_move(self.root.winfo_x(), self.root.winfo_y())
        self._drag = None

    # -- what the panel says -----------------------------------------------

    def _headline(self) -> tuple[str, str]:
        """States what is true now, not merely what is switched on.

        The colour is the whole point of the rail, so it has to mean one thing:
        red nothing is happening, amber something is expected of you or of the
        game, green working.
        """
        s = self.state
        if self._movable:
            return "MOVE", WORK
        if not s.running:
            return "STOPPED", STOP
        if s.choice and not s.auto_answer:
            return "YOUR TURN", WORK
        if not s.game_running:
            return "NO GAME", HOLD
        if not s.game_focused:
            return "NO FOCUS", HOLD
        return ("SKIPPING", GO) if s.dialogue else ("READY", GO)

    def _activity(self) -> tuple[str, str]:
        """One sentence for the situation, most urgent case first."""
        s = self.state
        if self._movable:
            return "Drag the panel where you want it", WORK
        if s.note:
            return s.note, STOP
        if not s.running:
            return "Press F8 to start", DIM
        if not s.game_running:
            return "Start Genshin and it will pick up", DIM
        if not s.game_focused:
            return (f"Waiting — {_shorten(s.foreground)} has focus"
                    if s.foreground else "Waiting for Genshin to be in front"), DIM
        if s.choice and not s.auto_answer:
            return "Pick an answer — it is yours to make", WORK
        if s.dialogue:
            return "Skipping dialogue", TEXT
        return "Watching for dialogue", DIM

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

        if s.hud_movable != self._movable:
            self._movable = s.hud_movable
            self._set_click_through(not self._movable)

        if s.hud_visible != self._visible:
            self._visible = s.hud_visible
            root.deiconify() if s.hud_visible else root.withdraw()

        title, colour = self._headline()
        self._widgets["title"].config(text=title, fg=colour)
        self._widgets["rail"].config(bg=colour)

        text, tone = self._activity()
        self._widgets["activity"].config(text=text, fg=tone)
        self._widgets["settings"].config(text=self._settings_line())
        self._widgets["keys"].config(text=self._keys_line())

        # Wrapped text can change the height; keep the panel anchored to its
        # corner rather than letting it grow off the edge.
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
