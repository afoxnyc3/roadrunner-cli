"""Pytest setup: make the ``roadrunner`` package importable in non-installed runs.

CI and developers typically run ``pip install -e .[dev]`` before pytest, in which
case ``import roadrunner`` resolves through the installed entry. This shim
covers the source-checkout-without-install case so a fresh clone followed by
``python -m pytest`` still works.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
