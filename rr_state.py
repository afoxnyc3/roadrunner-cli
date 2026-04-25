"""Roadrunner state persistence — extracted from ``roadrunner.py``.

Owns the read/modify/write window around the on-disk roadmap state file.
The highest-risk section of the codebase: a bug here silently corrupts the
control loop. Kept narrow on purpose so the blast radius is bounded.

Public surface (re-exported from ``roadrunner.py`` for backward compat):

- ``RoadmapState`` (TypedDict)
- ``STATE_SCHEMA_VERSION`` (int)
- ``STATE_FILE`` / ``STATE_LOCK`` (Path)
- ``write_state(...)``, ``read_state()``, ``increment_attempts(state, task_id)``
- ``_exclusive_state_lock()`` context manager

Locking, atomic writes, schema-version gating, and corrupt-file fallbacks
are bit-identical to the pre-extraction implementation. This module is a
pure refactor, not a redesign — see ``docs/resolution-plan-2026-04-24.md``
Issue 5. The state module deliberately does not import from
``roadrunner.py`` to avoid an import cycle.
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict, cast

try:
    import fcntl  # POSIX advisory locking; Windows is not a target platform.
except ImportError:  # pragma: no cover - Windows fallback keeps the module importable
    fcntl = None  # type: ignore[assignment]


# ── Type alias ──────────────────────────────────────────────────────────────


class RoadmapState(TypedDict, total=False):
    current_task_id: str | None
    iteration: int              # lifetime-cumulative counter (audit trail)
    session_iteration: int      # per-session counter; reset on SessionStart; gates the iteration cap (ROAD-010)
    attempts_per_task: dict[str, int]
    updated_at: str
    base_branch: str


# ── Paths and version ──────────────────────────────────────────────────────
# Defined at the project root, mirroring the original layout in ``roadrunner.py``.
# Tests rebind these module-level names (see ``tests/test_roadrunner.py::tmp_project``)
# to redirect state I/O into ``tmp_path``; that pattern is preserved.

_PROJECT_ROOT = Path(__file__).parent
STATE_FILE: Path = _PROJECT_ROOT / ".roadmap_state.json"
STATE_LOCK: Path = _PROJECT_ROOT / ".roadmap_state.lock"  # sibling lockfile; survives os.replace

STATE_SCHEMA_VERSION = 2  # bump when .roadmap_state.json format changes incompatibly
                          # v2 (ROAD-010): added session_iteration field; backward-compat via setdefault


# ── Internal helpers ────────────────────────────────────────────────────────


def _now() -> str:
    """UTC ISO timestamp. Local copy so this module has no roadrunner dependency."""
    return datetime.now(timezone.utc).isoformat()


# ── Public API ──────────────────────────────────────────────────────────────


def write_state(
    current_task_id: str | None,
    iteration: int,
    attempts: dict | None = None,
    extra: dict | None = None,
    session_iteration: int | None = None,
) -> None:
    """Atomically write the roadmap state file. Caller is expected to hold
    ``_exclusive_state_lock()`` if concurrent Stop-hook fires are possible.

    Uses the temp-file + ``os.replace`` dance to guarantee that observers
    never see a torn write: either the previous file or the new file is
    visible, never a half-written one. ``f.flush()`` + ``os.fsync()`` ensure
    bytes hit the disk before the rename.

    ROAD-010: ``session_iteration`` is the per-session counter. When None,
    preserve the value already on disk (or default to 0 for a fresh state
    file). When set explicitly, overwrite. Keeps existing call sites
    correct without threading the field through every signature — only the
    call sites that mutate the session counter (cmd_check_stop,
    cmd_session_start) need to know about it.
    """
    if session_iteration is None:
        existing = 0
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text())
                if isinstance(data, dict):
                    existing = int(data.get("session_iteration", 0))
            except (OSError, json.JSONDecodeError, ValueError, TypeError):
                existing = 0
        effective_session_iter = existing
    else:
        effective_session_iter = session_iteration

    state = {
        "schema_version": STATE_SCHEMA_VERSION,
        "current_task_id": current_task_id,
        "iteration": iteration,
        "session_iteration": effective_session_iter,
        "attempts_per_task": attempts or {},
        "updated_at": _now(),
    }
    if extra:
        state.update(extra)
    tmp_path = STATE_FILE.with_suffix(".json.tmp")
    with open(tmp_path, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, STATE_FILE)


def read_state() -> RoadmapState:
    """Read the on-disk state, returning safe defaults if missing/corrupt.

    Schema gating:
    - missing version -> assume legacy v1 (back-compat)
    - version > STATE_SCHEMA_VERSION -> exit(2) so we never overwrite a forward-
      compat state file with a backward-incompatible payload.
    - missing optional keys -> filled with defaults via setdefault.
    """
    default: RoadmapState = {
        "current_task_id": None,
        "iteration": 0,
        "session_iteration": 0,
        "attempts_per_task": {},
    }
    if not STATE_FILE.exists():
        return default
    try:
        data = json.loads(STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        # Corrupt or unreadable state must not wedge the loop; reconverge from defaults.
        print(
            f"[roadrunner] state file unreadable ({exc}); falling back to defaults.",
            file=sys.stderr,
        )
        return default
    if not isinstance(data, dict):
        print(
            "[roadrunner] state file is not a JSON object; falling back to defaults.",
            file=sys.stderr,
        )
        return default
    version = data.get("schema_version", 1)
    if not isinstance(version, int) or version > STATE_SCHEMA_VERSION:
        print(
            f"[roadrunner] state file has unknown schema_version={version!r}; "
            f"this version of roadrunner only understands up to {STATE_SCHEMA_VERSION}. "
            f"Upgrade roadrunner or manually migrate {STATE_FILE.name} before continuing.",
            file=sys.stderr,
        )
        sys.exit(2)
    data.setdefault("attempts_per_task", {})
    data.setdefault("current_task_id", None)
    data.setdefault("iteration", 0)
    # ROAD-010 (schema v2): older state files lack this field. Treat as 0 so
    # the first Stop-hook fire after upgrade starts a fresh session window.
    data.setdefault("session_iteration", 0)
    return cast(RoadmapState, data)


def increment_attempts(state: RoadmapState, task_id: str) -> int:
    """Bump per-task attempt counter in-place; return the new count."""
    attempts = state.get("attempts_per_task", {})
    attempts[task_id] = attempts.get(task_id, 0) + 1
    state["attempts_per_task"] = attempts
    return attempts[task_id]


@contextmanager
def _exclusive_state_lock():
    """POSIX advisory lock around the state file's read->modify->write window.

    Uses a sibling lockfile so the lock object is not wiped by ``os.replace``
    of the state file itself. On Windows (where ``fcntl`` is unavailable)
    this degrades to a no-op since the project only supports POSIX;
    multi-operator concurrency is a documented non-goal but a single flock
    closes the accidental-concurrency hole.
    """
    if fcntl is None:
        yield
        return
    STATE_LOCK.touch(exist_ok=True)
    with open(STATE_LOCK, "r+") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
