"""Entry point for the frozen build.

PyInstaller analyses its target as a plain script, so a module using relative
imports (``genshin_autoskip/__main__.py``) resolves to nothing and produces a
bundle with none of the dependencies in it. This shim imports absolutely.
"""
import sys

from genshin_autoskip.app import cli

if __name__ == "__main__":
    sys.exit(cli())
