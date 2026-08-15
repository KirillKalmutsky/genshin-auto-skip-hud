"""Always-on-top status panel drawn over the game.

Built on tkinter so it needs no extra dependency. The window is made
click-through (``WS_EX_TRANSPARENT``) and non-activating (``WS_EX_NOACTIVATE``)
so that it never swallows a click meant for the game and never steals focus -
which would pause the skipper, since it only acts while Genshin is in front.

Placement note: the panel is captured by the screen grab like anything else, so
it must not sit on a region detection reads. `config.HUD_POSITIONS` excludes the
top-left corner for that reason.

Tkinter must own the main thread, so :meth:`Overlay.run` blocks; the detection
loop belongs on a worker thread.
"""
import ctypes
import tkinter as tk
from ctypes import wintypes

from .state import SkipperState

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
SPI_GETWORKAREA = 0x0030

BG = "#0d1220"
LINE = "#1e2a44"
TEXT = "#e6edf7"
MUTED = "#8b9bb4"
FAINT = "#5a6a86"
GREEN = "#4ade80"
AMBER = "#fbbf24"
BLUE = "#54c7fc"
RED = "#fb7185"

#: Anchor names as the tray menu words them, so panel and menu agree.
ANCHOR_LABELS = {
    "auto": "auto-play button",
    "marker": "orange marker",
    "both": "either",
}


class Overlay:
    def __init__(self, state: SkipperState, position: str = "bottom-left",
                 margin: int = 24, alpha: float = 0.88) -> None:
        self.state = state
        self.position = position
        self.margin = margin
        self.alpha = alpha
        self.root: tk.Tk | None = None
        self._widgets: dict[str, tk.Widget] = {}
        self._visible = True

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        root = tk.Tk()
        self.root = root
        root.title("autoskip-hud")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", self.alpha)
        root.configure(bg=BG)

        outer = tk.Frame(root, bg=BG, padx=18, pady=14,
                         highlightbackground=LINE, highlightthickness=1)
        outer.pack(fill="both", expand=True)

        # Header: the one thing worth reading from across the room.
        header = tk.Frame(outer, bg=BG)
        header.pack(fill="x")
        dot = tk.Label(header, text="●", bg=BG, fg=GREEN,
                       font=("Segoe UI", 13))
        dot.pack(side="left", padx=(0, 8))
        title = tk.Label(header, text="SKIPPING", bg=BG, fg=GREEN,
                         font=("Segoe UI Semibold", 14))
        title.pack(side="left")
        rate = tk.Label(header, text="", bg=BG, fg=FAINT,
                        font=("Consolas", 10))
        rate.pack(side="right")

        # What is happening right now, in words rather than numbers.
        activity = tk.Label(outer, text="", bg=BG, fg=MUTED, anchor="w",
                            justify="left", font=("Segoe UI", 11))
        activity.pack(fill="x", pady=(8, 0))

        settings = tk.Label(outer, text="", bg=BG, fg=FAINT, anchor="w",
                            font=("Segoe UI", 9))
        settings.pack(fill="x", pady=(10, 0))

        tk.Frame(outer, bg=LINE, height=1).pack(fill="x", pady=(10, 8))

        keys = tk.Label(outer, text="", bg=BG, fg=FAINT, anchor="w",
                        justify="left", font=("Consolas", 9))
        keys.pack(fill="x")

        self._widgets = {"dot": dot, "title": title, "rate": rate,
                         "activity": activity, "settings": settings,
                         "keys": keys}

        root.update_idletasks()
        self._place(root)
        self._apply_click_through(root)

    @staticmethod
    def _work_area(root: tk.Tk) -> tuple[int, int, int, int]:
        """The desktop minus the taskbar, so the bottom corners clear it."""
        rect = wintypes.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0,
                                                      ctypes.byref(rect), 0):
            return rect.left, rect.top, rect.right, rect.bottom
        return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()

    def _place(self, root: tk.Tk) -> None:
        w, h = root.winfo_width(), root.winfo_height()
        left, top, right, bottom = self._work_area(root)
        m = self.margin
        x, y = {
            "top-right": (right - w - m, top + m),
            "bottom-right": (right - w - m, bottom - h - m),
            "bottom-left": (left + m, bottom - h - m),
        }.get(self.position, (left + m, bottom - h - m))
        root.geometry(f"+{int(x)}+{int(y)}")

    @staticmethod
    def _apply_click_through(root: tk.Tk) -> None:
        user32 = ctypes.windll.user32
        user32.GetWindowLongPtrW.restype = ctypes.c_longlong
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetWindowLongPtrW.restype = ctypes.c_longlong
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int,
                                             ctypes.c_longlong]

        hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
        style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongPtrW(
            hwnd, GWL_EXSTYLE,
            style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE
            | WS_EX_TOOLWINDOW,
        )

    # -- what the panel says -----------------------------------------------

    def _headline(self) -> tuple[str, str]:
        """The headline states what is true now, not merely what is switched on.

        Reporting "SKIPPING" whenever the tool was armed contradicted the line
        below it - the panel would claim to be skipping while also saying the
        game was closed.
        """
        s = self.state
        if not s.running:
            return "STOPPED", AMBER
        if s.choice and not s.auto_answer:
            return "WAITING", RED
        if s.game_focused and s.dialogue:
            return "SKIPPING", GREEN
        return "READY", GREEN

    def _activity(self) -> tuple[str, str]:
        """One sentence for the situation, most urgent case first."""
        s = self.state
        if s.note:
            return s.note, RED
        if not s.running:
            return "Press F8 to start", MUTED
        if not s.game_running:
            return "Genshin is not running", MUTED
        if not s.game_focused:
            where = f" — {s.foreground[:20]} has focus" if s.foreground else ""
            return f"Paused{where}", MUTED
        if s.choice and not s.auto_answer:
            # The most important thing the panel can say: it is deliberately
            # standing still, and the choice is yours.
            return "Your answer — waiting for you", RED
        if s.dialogue:
            return "Skipping dialogue", BLUE
        return "Watching for dialogue", MUTED

    def _settings_line(self) -> str:
        anchor = ANCHOR_LABELS.get(self.state.anchor, self.state.anchor)
        answers = "answers automatically" if self.state.auto_answer \
            else "leaves answers to you"
        return f"{anchor}  ·  {answers}"

    def _keys_line(self) -> str:
        first = "F8 stop" if self.state.running else "F8 start"
        answers = "F10 manual" if self.state.auto_answer else "F10 auto"
        return (f"{first}   F9 mode   {answers}\n"
                f"F11 hide   F12 quit")

    # -- refresh -----------------------------------------------------------

    def _tick(self) -> None:
        root = self.root
        if root is None:
            return
        s = self.state

        if s.should_exit:
            root.quit()
            return

        # Only on an actual change: deiconify() on an already-visible window
        # asks Windows to bring it forward.
        if s.hud_visible != self._visible:
            self._visible = s.hud_visible
            root.deiconify() if s.hud_visible else root.withdraw()

        title, colour = self._headline()
        self._widgets["title"].config(text=title, fg=colour)
        self._widgets["dot"].config(fg=colour)

        active = s.running and s.game_focused and s.dialogue
        self._widgets["rate"].config(
            text=f"{s.presses}  ·  {s.rate:.1f}/s" if active
            else f"{s.presses} presses" if s.presses else "")

        text, tone = self._activity()
        self._widgets["activity"].config(text=text, fg=tone)
        self._widgets["settings"].config(text=self._settings_line())
        self._widgets["keys"].config(text=self._keys_line())

        root.after(100, self._tick)

    # -- lifecycle ---------------------------------------------------------

    def run(self) -> None:
        """Build and drive the panel. Blocks until the state asks to exit."""
        self._build()
        assert self.root is not None
        self.root.after(100, self._tick)
        self.root.mainloop()
        try:
            self.root.destroy()
        except tk.TclError:
            pass
