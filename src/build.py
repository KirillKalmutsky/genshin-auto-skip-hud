"""Freeze the app into a Windows executable dropped in the repository root.

    build.bat              single GenshinAutoSkipHUD.exe in the root
    build.bat --onedir     exe plus a runtime folder; starts noticeably faster

There is no "just make an exe" shortcut that skips the Python package: an
executable *is* this code bundled together with an interpreter, and PyInstaller
is the thing that does the bundling. The package under src/ is the program; the
exe is a wrapper around it.

The build embeds a UAC manifest, because the game runs elevated and Windows
discards synthetic input aimed at an elevated window from a process that is not.
"""
import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent
WORK = ROOT / "build"
ICON = SRC / "genshin_autoskip" / "resources" / "icon.ico"
NAME = "GenshinAutoSkipHUD"

# Pulled in dynamically by pystray/PIL/pynput, so PyInstaller cannot see them.
HIDDEN_IMPORTS = [
    "pystray._win32",
    "PIL._tkinter_finder",
    "pynput.keyboard._win32",
    "pynput.mouse._win32",
]

# None of this is used at runtime; excluding it saves tens of megabytes.
EXCLUDES = [
    "matplotlib", "scipy", "pandas", "pytest", "setuptools", "pip",
    "PySide6", "PyQt5", "PyQt6", "notebook", "IPython",
]


def remove_tree(path: Path, attempts: int = 6) -> bool:
    """Delete a build directory, waiting out transient locks.

    A freshly written bundle is routinely still held by an antivirus scan, and
    PyInstaller's own cleanup aborts the whole build when that happens.
    """
    for attempt in range(attempts):
        if not path.exists():
            return True
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return True
        time.sleep(0.5 * (attempt + 1))
    print(f"  [WARN] cannot remove {path.name}: another process is holding it "
          f"(antivirus?). Close anything using it and retry.")
    return False


def make_icon() -> None:
    ICON.parent.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(SRC))
    from genshin_autoskip.icons import write_ico

    write_ico(str(ICON))
    print(f"  icon  -> {ICON.relative_to(ROOT)}")


def verify(target: Path, onefile: bool) -> list[str]:
    """Confirm the dependencies really landed in the bundle.

    An analysis that silently resolved nothing still reports success, so this
    guards against shipping an exe that dies on its first import. Packages with
    compiled extensions are laid out as directories; pure-Python ones go into
    the PYZ archive appended to the exe and leave no file of their own.
    """
    missing: list[str] = []
    if not onefile:
        contents = target.parent / "runtime"
        present = ({item.name.lower() for item in contents.iterdir()}
                   if contents.is_dir() else set())
        missing += [name for name in ("cv2", "numpy", "pil")
                    if name not in present]

    blob = target.read_bytes()
    missing += [name for name in ("pystray", "mss", "pynput", "genshin_autoskip")
                if name.encode() not in blob]
    return missing


def build(onefile: bool, clean: bool) -> int:
    dist = ROOT if onefile else ROOT / "dist"
    if clean:
        # Only clear what this mode actually writes. A leftover dist/ from an
        # earlier --onedir build is irrelevant to a single-file build, and
        # failing on a lock we do not care about would be pure obstruction.
        if not remove_tree(WORK):
            return 1
        if onefile:
            try:
                (ROOT / f"{NAME}.exe").unlink(missing_ok=True)
            except OSError:
                print(f"  [ERROR] {NAME}.exe is in use - close it and retry.")
                return 1
        elif not remove_tree(dist):
            return 1

    make_icon()

    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--windowed",            # the tray icon and HUD are the interface
        "--uac-admin",           # the game is elevated, so we must be too
        "--name", NAME,
        "--icon", str(ICON),
        "--distpath", str(dist),
        "--workpath", str(WORK),
        "--specpath", str(WORK),
        "--onefile" if onefile else "--onedir",
    ]
    if not onefile:
        # Keep the bundled interpreter out of sight next to the exe.
        command += ["--contents-directory", "runtime"]
    for module in HIDDEN_IMPORTS:
        command += ["--hidden-import", module]
    for module in EXCLUDES:
        command += ["--exclude-module", module]
    command += ["--paths", str(SRC), str(SRC / "main.py")]

    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        return result.returncode

    target = (ROOT / f"{NAME}.exe") if onefile else (dist / NAME / f"{NAME}.exe")
    if not target.exists():
        print(f"\n  [ERROR] expected artefact missing at {target}")
        return 1

    missing = verify(target, onefile)
    if missing:
        print(f"\n  [ERROR] not bundled: {', '.join(missing)}")
        return 1

    size = target.stat().st_size / (1024 * 1024)
    print(f"\n  built -> {target.relative_to(ROOT)}  ({size:.0f} MB)")
    print("  dependencies verified")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onedir", action="store_true",
                        help="exe plus a runtime/ folder; starts much faster")
    parser.add_argument("--no-clean", action="store_true",
                        help="keep previous build artefacts")
    args = parser.parse_args()
    raise SystemExit(build(onefile=not args.onedir, clean=not args.no_clean))
