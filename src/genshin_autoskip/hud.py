"""Always-on-top status HUD drawn over the game.

Built on tkinter so it needs no extra dependency. The window is made
click-through (``WS_EX_TRANSPARENT``) and non-activating
(``WS_EX_NOACTIVATE``) so that it never swallows a click meant for the game and
never steals focus - which would pause the skipper, since the skipper only acts
while Genshin is the foreground window.

Placement note: the HUD is captured by the screen grab like anything else, so it
must not sit on top of a detection ROI or it would corrupt the very signal it is
reporting. The default corner is chosen to stay clear of the auto-play button
region that :mod:`detector` samples.

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

BG = "#0b1020"
FG_DIM = "#94a3b8"
FG = "#e2e8f0"
GREEN = "#4ade80"
AMBER = "#fbbf24"
BLUE = "#38bdf8"
GREY = "#64748b"
RED = "#f87171"

#: Anchor names as the tray menu words them, so the HUD and the menu agree.
ANCHOR_LABELS = {
    "auto": "auto-play button",
    "marker": "orange marker",
    "both": "either",
}


class Overlay:
    def __init__(self, state: SkipperState, position: str = "top-right",
                 margin: int = 28, alpha: float = 0.85,
                 hotkeys: str = ("[F8] start/stop  [F9] mode  [F10] answers\n"
                                 "[F11] hud  [F12] exit")
                 ) -> None:
        self.state = state
        self.position = position
        self.margin = margin
        self.alpha = alpha
        self.hotkeys = hotkeys
        self.root: tk.Tk | None = None
        self._dots: dict[str, tk.Label] = {}
        self._labels: dict[str, tk.Label] = {}
        self._visible = True

    # -- construction ------------------------------------------------------

    def _row(self, parent: tk.Widget, key: str, text: str,
             font: tuple[str, int, str]) -> None:
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", anchor="w")
        dot = tk.Label(row, text="●", bg=BG, fg=GREY, font=("Consolas", 11))
        dot.pack(side="left", padx=(0, 8))
        label = tk.Label(row, text=text, bg=BG, fg=FG, font=font, anchor="w")
        label.pack(side="left")
        self._dots[key] = dot
        self._labels[key] = label

    def _build(self) -> None:
        root = tk.Tk()
        self.root = root
        root.title("autoskip-hud")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", self.alpha)
        root.configure(bg=BG)

        outer = tk.Frame(root, bg=BG, padx=16, pady=12,
                         highlightbackground="#1e293b", highlightthickness=1)
        outer.pack(fill="both", expand=True)

        self._row(outer, "status", "STOPPED", ("Consolas", 12, "bold"))
        self._row(outer, "game", "Genshin: not focused", ("Consolas", 10, "normal"))
        self._row(outer, "dialogue", "dialogue: --", ("Consolas", 10, "normal"))
        self._row(outer, "mode", "detect: auto-play button",
                  ("Consolas", 10, "normal"))
        self._row(outer, "answer", "answers: auto", ("Consolas", 10, "normal"))
        self._row(outer, "stats", "presses: 0", ("Consolas", 10, "normal"))

        tk.Label(outer, text=self.hotkeys, bg=BG, fg="#475569",
                 font=("Consolas", 9)).pack(anchor="w", pady=(8, 0))

        root.update_idletasks()
        self._place(root)
        self._apply_click_through(root)

    def _place(self, root: tk.Tk) -> None:
        w, h = root.winfo_width(), root.winfo_height()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        m = self.margin
        x, y = {
            "top-right": (sw - w - m, m),
            "top-left": (m, m),
            "bottom-right": (sw - w - m, sh - h - m * 2),
            "bottom-left": (m, sh - h - m * 2),
        }.get(self.position, (sw - w - m, m))
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
        # asks Windows to bring it forward, and doing that ten times a second
        # fights the game for the foreground.
        if s.hud_visible != self._visible:
            self._visible = s.hud_visible
            if s.hud_visible:
                root.deiconify()
            else:
                root.withdraw()

        self._labels["status"].config(text="RUNNING" if s.running else "STOPPED",
                                      fg=GREEN if s.running else AMBER)
        self._dots["status"].config(fg=GREEN if s.running else AMBER)

        if s.game_focused:
            game_text = "Genshin: focused"
        elif s.foreground:
            # Naming the window that took the foreground turns "it does not
            # work" into "this window stole the focus".
            game_text = f"focus: {s.foreground[:22]}"
        else:
            game_text = "Genshin: not focused"
        self._labels["game"].config(
            text=game_text, fg=FG if s.game_focused else FG_DIM)
        self._dots["game"].config(fg=GREEN if s.game_focused else RED)

        if s.dialogue and s.holding:
            # Still pressing, but only because of the hysteresis window - say so
            # rather than showing DETECTED next to a confidence of 0.00.
            self._labels["dialogue"].config(
                text=f"dialogue: holding   {s.confidence:.2f}", fg=AMBER)
            self._dots["dialogue"].config(fg=AMBER)
        elif s.dialogue:
            self._labels["dialogue"].config(
                text=f"dialogue: DETECTED  {s.confidence:.2f}", fg=BLUE)
            self._dots["dialogue"].config(fg=BLUE)
        else:
            self._labels["dialogue"].config(
                text=f"dialogue: --        {s.confidence:.2f}", fg=FG_DIM)
            self._dots["dialogue"].config(fg=GREY)

        self._labels["mode"].config(
            text="detect: " + ANCHOR_LABELS.get(s.anchor, s.anchor) + "  (F9)",
            fg=FG_DIM)
        self._dots["mode"].config(fg=GREY)

        if not s.auto_answer and s.choice:
            # The most important thing the HUD can say: it is deliberately
            # standing still and the choice is yours.
            self._labels["answer"].config(text="YOUR ANSWER - waiting", fg=RED)
            self._dots["answer"].config(fg=RED)
        elif not s.auto_answer:
            self._labels["answer"].config(text="answers: manual", fg=AMBER)
            self._dots["answer"].config(fg=AMBER)
        else:
            self._labels["answer"].config(text="answers: auto", fg=FG_DIM)
            self._dots["answer"].config(fg=GREY)

        stats = f"presses: {s.presses}   {s.rate:.1f}/s"
        if s.note:
            stats += f"   {s.note}"
        self._labels["stats"].config(text=stats, fg=FG_DIM)
        self._dots["stats"].config(fg=GREY)

        root.after(100, self._tick)

    # -- lifecycle ---------------------------------------------------------

    def run(self) -> None:
        """Build and drive the HUD. Blocks until the state asks to exit."""
        self._build()
        assert self.root is not None
        self.root.after(100, self._tick)
        self.root.mainloop()
        try:
            self.root.destroy()
        except tk.TclError:
            pass
