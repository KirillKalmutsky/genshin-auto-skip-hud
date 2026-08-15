# Genshin Auto-Skip HUD

Advances Genshin Impact dialogue for you. Runs in the system tray with an
optional click-through HUD showing what it is doing.

> Using third-party software with Genshin Impact violates its Terms of Service.
> This tool never touches the game process — it reads pixels from the screen and
> synthesises keystrokes — but that does not make it sanctioned. Your account,
> your call.

---

## Quick start

Download `GenshinAutoSkip.exe` from [Releases](../../releases) and run it. It
asks for administrator rights on launch — see [Why administrator](#why-administrator).

Or build it yourself:

```
build.bat            # puts GenshinAutoSkip.exe in this folder
build.bat --onedir   # exe plus a runtime\ folder; starts faster
```

To run from source instead, `run.bat`.

## Controls

| Key | Action |
| --- | --- |
| `F8` | Start / Stop |
| `F9` | Cycle the detection anchor |
| `F10` | Answer choices automatically, or leave them to you |
| `F11` | Show/hide the HUD |
| `F12` | Exit |

`F10` is the one worth remembering. Leave answering on to blast through filler,
and press it the moment a conversation you care about starts: the skipper keeps
advancing lines but stops at each choice and hands it back to you. The HUD turns
that row red and reads `YOUR ANSWER - waiting`, so a deliberate stop is never
mistaken for a broken tool.

The tray icon mirrors the state — green when armed, amber when paused, grey when
the game is not running — and its menu covers the same actions plus the
interaction key and four speed presets, from `Fast` at 40–70 ms to `Slow` at
400–600 ms, which is slow enough to read along with. Every change is written to `.env` and takes
effect immediately; nothing needs a restart.

## Settings

`.env`, next to the executable. Editable by hand or from the tray.

| Key | Default | Meaning |
| --- | --- | --- |
| `CONFIRM_BUTTON` | `f` | In-game interaction key |
| `DETECTION_ANCHOR` | `auto` | What to key on: `auto`, `marker` or `both` |
| `AUTO_ANSWER` | `1` | Pick dialogue choices too, rather than waiting for you |
| `PRESS_MIN_MS` | `60` | Lower bound of the randomised press interval |
| `PRESS_MAX_MS` | `110` | Upper bound |
| `KEY_HOLD_MS` | `60` | How long the key stays down |
| `IDLE_POLL_MS` | `100` | How often to look at the screen when nothing is happening |
| `DETECTION_HOLD_MS` | `0` | Keep pressing this long after detection stops |
| `HUD` | `1` | Show the on-screen status panel |
| `HUD_POSITION` | `top-right` | `top-left`, `bottom-left`, `bottom-right` |
| `SPAM_MODE` | `0` | Press on a timer, ignoring detection |
| `RANDOM_BREAKS` | `0` | Occasional 3–8 s idle pauses |
| `PROFILE` | `0` | Write `loop_profile.csv` for diagnosing press rate |

`KEY_HOLD_MS` is the one to leave alone: the game samples input once per frame,
and a shorter hold risks falling between two samples.

## How it works

Everything below was measured against real captured frames rather than reasoned
about, because most of the obvious approaches turned out not to survive contact
with the game.

### Input

Keys go out through `SendInput` with hardware scan codes, held 60 ms. This is
not a stylistic choice — it was measured against the live game:

```
pyautogui.press('f')          no effect
pyautogui keyDown/Up 60ms     no effect
SendInput virtual-key 60ms    advanced the dialogue
SendInput SCANCODE  60ms      advanced the dialogue
```

`pyautogui` drives the keyboard through the legacy `keybd_event` call, which the
game ignores entirely — holding the key longer does not help. Scan codes are
preferred over virtual key codes because they address a physical key and so
survive a non-Latin keyboard layout.

### Detection

The anchor is the auto-play button in the top-left corner. It is hard to
describe and easy to recognise, which is the whole difficulty: it appears as a
play triangle or as pause bars, lit or translucent, and while translucent it
blends with whatever scenery is behind it.

Describing it by properties — bright, round, hollow, this size, this colour —
fails, because every such description also fits something else the game draws:
the quest journal's category icon, the back arrow in full-screen menus, the
Paimon menu button, markers on the minimap. Tightening the description to
exclude those excluded the real button too.

What works is algebra. The button is two layers composited over the scene, a
light disc with a dark glyph on it, so for a pixel of each:

```
disc  : I_d = a·F_d + (1−a)·B
glyph : I_g = a·F_g + (1−a)·B
─────────────────────────────
        I_d − I_g = a·(F_d − F_g)
```

The scene cancels exactly. Dividing that difference by its own peak cancels the
opacity as well, leaving the bare shape — which is then correlated against two
references, one per glyph. The disc level is estimated locally by morphological
closing with a kernel wider than the glyph's strokes.

Two things fall out of the same equation for free: the difference before
normalisation is proportional to opacity, so it doubles as a presence check
(40–163 with the button on screen, 2–22 without), and as a hint that the game
has faded the button because it is waiting for an answer.

Measured over 145 real frames covering all four appearances, the quest journal
and frames with no dialogue — **145/145 correct**:

| Frames | Confidence |
| --- | --- |
| dialogue, auto-play off | 0.897 – 0.926 |
| dialogue, auto-play on | fires on all |
| dialogue, choice waiting | 0.988 – 0.996 |
| quest journal open | 0.475 |
| no dialogue | 0.476 – 0.485 |

with the threshold at 0.63.

Approaches that were measured and rejected along the way: exact RGB comparison
(the original, breaks on any UI change), blob heuristics, a single whole-button
template (gap −0.240), masked correlation (−0.002), Canny edge matching (−0.111)
and pixel-level shape overlap (+0.018). Sampling eleven appearance templates did
work (+0.161) before the recovery approach replaced it with two (+0.291).

### Geometry

Regions are anchored to the game window rather than the primary monitor, and
scale with window **height** — Genshin scales its HUD uniformly and anchors it
to the screen edges, so on an ultrawide display the button stays the same size
and the same distance from the left edge. Scaling by width, as the original
code did, pushes the region far to the right of the button.

### Cost

While a dialogue is running the loop sleeps until the next press is actually
due rather than polling through the wait:

```
screen reads      12.8/s
reads per press   2.2
key presses       unchanged
```

`IDLE_POLL_MS` governs the only remaining poll — the delay before a new dialogue
is noticed.

## Why administrator

Genshin Impact runs elevated. Windows refuses to deliver synthetic input from a
process at a lower integrity level, silently — no error, the keys simply vanish.
The executable therefore carries a UAC manifest, and running from source
elevates through `run.bat`.

## Limitations

- **Only while the game is focused.** `SendInput` always targets the foreground
  window; pressing while alt-tabbed would type into whatever you switched to.
  No supported Windows API sends input to a background window — see
  [The Old New Thing](https://devblogs.microsoft.com/oldnewthing/20250319-00/?p=110979).
  Windows routes input per *desktop*, not per window, so the only real answer is
  a second session, which on Windows client editions needs an unsupported patch.
  Every comparable tool gates on focus for the same reason.
- **Cinematic cutscenes are not handled.** They draw neither the auto-play
  button nor option bubbles. Pressing the key there does nothing anyway.
- **Borderless or windowed, not exclusive fullscreen** — exclusive fullscreen
  breaks screen capture.
- **Windows only.**

## Diagnostics

Set `PROFILE=1` to log every loop iteration to `loop_profile.csv`: phase, how
long detection took, the confidence, and the gap since the previous press. That
is the fastest way to tell a detection problem from a timing one.

If a game update ever breaks input entirely, the thing to re-measure is which
injection method the game still accepts — see the table above for what was
measured last time.

## Layout

```
GenshinAutoSkip.exe       the built application
run.bat                   run from source instead
build.bat                 rebuild the executable
.env                      settings

src/
    main.py               entry point for the frozen build
    build.py              PyInstaller packaging
    genshin_autoskip/
        app.py            wiring: threads, hotkeys, lifecycle
        loop.py           detection loop and press scheduling
        detection.py      shape recovery and matching
        templates.py      the two reference shapes, embedded
        input_backend.py  SendInput scan-code keyboard
        hud.py            click-through on-screen panel
        tray.py           tray icon and menu
        window.py         foreground and geometry queries
        config.py         .env settings
        icons.py          runtime-generated icons

tests/                    pytest suite
```

There is no way to "just build an exe" without the Python package: an executable
*is* this code bundled together with an interpreter, and PyInstaller is what does
the bundling. Both ship together so the source stays readable.

## License

MIT — see [LICENSE](LICENSE).
