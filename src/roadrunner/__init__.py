"""Roadrunner CLI — deterministic agentic loop controller for Claude Code.

The package surface deliberately mirrors the cli module. Historically this was
one flat ``roadrunner.py`` at the project root; tests, hooks, and external
callers do ``import roadrunner; roadrunner.foo`` and ``monkeypatch.setattr(
roadrunner, "ROOT", ...)`` against the cli namespace directly. Splitting the
file into a package without preserving that single-namespace contract would
break every existing call site, so we alias ``sys.modules['roadrunner']`` to
the cli module — attribute access and runtime mutation stay coherent with
cli's own internal lookups.
"""

import sys as _sys
from importlib.metadata import PackageNotFoundError as _PackageNotFoundError
from importlib.metadata import version as _pkg_version

from . import cli as _cli
from . import session as _session
from . import state as _state

# Capture before the alias so ``python -m roadrunner`` can still walk the
# package path to find __main__.py.
_pkg_path = list(_sys.modules[__name__].__path__)

try:
    _cli.__version__ = _pkg_version("roadrunner-cli")  # type: ignore[attr-defined]
except _PackageNotFoundError:  # source checkout without metadata available
    _cli.__version__ = "0.0.0+local"  # type: ignore[attr-defined]
_cli.session = _session  # type: ignore[attr-defined]
_cli.state = _state  # type: ignore[attr-defined]
_cli.cli = _cli  # type: ignore[attr-defined]
_cli.__path__ = _pkg_path

_sys.modules[__name__] = _cli
