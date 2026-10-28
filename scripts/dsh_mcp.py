"""Backward-compatible DSH entry point for the shared Codex/DSH bridge."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from proteus86.bridge import *  # Preserve the initial adapter's Python imports.

if __name__ == '__main__':
    main()
