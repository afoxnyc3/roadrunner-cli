#!/usr/bin/env python3
"""
Roadmap Loop Controller
-----------------------
Python owns: task selection, dependency resolution, validation, logging, state.
Claude Code owns: implementation inside one task boundary.
Hooks own: stop enforcement, completion gating, context snapshots.
"""

import argparse
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TypedDict, cast

import yaml

try:
    import fcntl  # POSIX advisory locking for the state file; Windows is not a target platform.
except ImportError:  # pragma: no cover - Windows fallback keeps the module importable
    fcntl = None  # type: ignore[assignment]


# ── Type aliases ─────────────────────────────────────────────────────────────
# These are structural hints only — every function still accepts plain dicts
# so callers (including tests) need no changes. They exist so editors flag
# key typos and make the implicit schema explicit.


class Task(TypedDict, total=False):
    id: str
    title: str
    status: str                # "todo" | "in_progress" | "done" | "blocked"
    depends_on: list[str]
    goal: str
    acceptance_criteria: list[str]
    validation_commands: list[str]
    validation_timeout: int
    files_expected: list[str]
    documentation_targets: list[str]
    notes: str


class RoadmapState(TypedDict, total=False):
    current_task_id: str | None
    iteration: int
    attempts_per_task: dict[str, int]
    updated_at: str
    base_branch: str


class ValidationResult(TypedDict, total=False):
    command: str
    passed: bool
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool

# ── Paths ────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).parent
TASKS_FILE = ROOT / "tasks" / "tasks.yaml"
LOGS_DIR = ROOT / "logs"
CHANGELOG = LOGS_DIR / "CHANGELOG.md"
STATE_FILE = ROOT / ".roadmap_state.json"
TRACE_LOG = LOGS_DIR / "trace.jsonl"
TASKS_BACKUP = TASKS_FILE.with_suffix(".yaml.bak")
STATE_LOCK = ROOT / ".roadmap_state.lock"  # sibling advisory lockfile; survives os.replace
LOGS_DIR.mkdir(exist_ok=True)


# ── Tunables ─────────────────────────────────────────────────────────────────
# Collected here so operators have one place to adjust retention and safety knobs.

DEFAULT_VALIDATION_TIMEOUT = 300   # seconds; per-task override via validation_timeout in tasks.yaml
MAX_TASK_ATTEMPTS = 5              # auto-block a task after this many resume cycles without completion
TASKS_BACKUP_KEEP = 5              # number of rolling tasks.yaml.bak.N copies to retain
LOG_ROTATE_BYTES = 10 * 1024 * 1024  # rotate when a log file exceeds 10 MB
LOG_RETAIN_DAYS = 7                # delete rotated/compressed logs older than this
STATE_SCHEMA_VERSION = 1           # bump when .roadmap_state.json format changes incompatibly
SNAPSHOT_SCHEMA_VERSION = 1        # bump when .context_snapshot.json format changes incompatibly

# Built from two fragments so the sentinel string never appears literally in the source
# (protects against `is_completion_signal` misfiring on the file that defines it).
_COMPLETION_SIGNAL = "ROADMAP" + "_COMPLETE"

# ── YAML helpers ─────────────────────────────────────────────────────────────


REQUIRED_TASK_FIELDS = {"id", "status", "title"}
VALID_TASK_STATUSES = {"todo", "in_progress", "done", "blocked"}
TASK_ID_RE = re.compile(r"^[A-Z]+-\d+$")


def validate_task_schema(task: dict, index: int) -> None:
    missing = REQUIRED_TASK_FIELDS - set(task.keys())
    if missing:
        task_id = task.get("id", f"<index {index}>")
        raise ValueError(
            f"Task {task_id} is missing required fields: {', '.join(sorted(missing))}"
        )
    task_id = task.get("id", "")
    if not TASK_ID_RE.match(str(task_id)):
        raise ValueError(
            f"Task {task_id!r} has invalid ID format. "
            f"Must match [A-Z]+-\\d+ (e.g., TASK-001)"
        )
    status = task.get("status")
    if status not in VALID_TASK_STATUSES:
        raise ValueError(
            f"Task {task['id']}: invalid status {status!r}. "
            f"Must be one of: {', '.join(sorted(VALID_TASK_STATUSES))}"
        )
    if not isinstance(task.get("validation_commands", []), list):
        raise ValueError(
            f"Task {task['id']}: validation_commands must be a list"
        )
    if not isinstance(task.get("depends_on", []), list):
        raise ValueError(f"Task {task['id']}: depends_on must be a list")
    timeout = task.get("validation_timeout")
    if timeout is not None and (not isinstance(timeout, (int, float)) or timeout <= 0):
        raise ValueError(f"Task {task['id']}: validation_timeout must be a positive number")


def load_tasks() -> list[Task]:
    try:
        with open(TASKS_FILE) as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"tasks file not found at {TASKS_FILE}. Create it before running any command."
        ) from exc
    except yaml.YAMLError as exc:
        # Hard stop: without a valid queue the loop cannot make decisions.
        raise ValueError(
            f"tasks file at {TASKS_FILE} is not valid YAML: {exc}. "
            f"Check tasks/tasks.yaml.bak for the last known-good version."
        ) from exc
    tasks = data.get("tasks", [])
    for i, task in enumerate(tasks):
        validate_task_schema(task, i)
    return cast(list[Task], tasks)


def load_project_config() -> dict:
    """Read top-level config keys from tasks.yaml (everything except `tasks`).

    Returns {} if the file is missing or unparseable — this helper is best-effort
    and never raises, so reads can be done defensively from any code path.
    """
    try:
        with open(TASKS_FILE) as f:
            data = yaml.safe_load(f) or {}
    except (FileNotFoundError, OSError, yaml.YAMLError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k != "tasks"}


def get_project_base() -> str:
    """Resolve the base branch task branches should fork from.

    Priority:
      1. `project_base` key in tasks.yaml (top-level) — explicit config, preferred
      2. Current git branch at the moment of call — legacy behavior pre-ROAD-025
      3. "main" — final fallback

    Setting `project_base` in tasks.yaml is how users opt out of the stacking
    pattern where task branches fork from whatever previous task branch was HEAD.
    """
    configured = load_project_config().get("project_base")
    if isinstance(configured, str) and configured:
        return configured
    return _current_branch() or "main"


def _rotate_task_backups() -> None:
    """Shift rolling backups: .bak.N-1 → .bak.N, overwriting the oldest atomically.

    Order (newest → oldest): tasks.yaml.bak, tasks.yaml.bak.1, ..., tasks.yaml.bak.N.
    Uses ``Path.replace`` so each rename atomically evicts the slot it lands in — no
    unconditional ``unlink`` of the oldest, which would create a window where the
    oldest snapshot is gone with nothing to replace it.
    """
    for i in range(TASKS_BACKUP_KEEP - 1, 0, -1):
        src = TASKS_FILE.with_suffix(f".yaml.bak.{i}")
        dst = TASKS_FILE.with_suffix(f".yaml.bak.{i + 1}")
        if src.exists():
            src.replace(dst)
    if TASKS_BACKUP.exists():
        TASKS_BACKUP.replace(TASKS_FILE.with_suffix(".yaml.bak.1"))


def save_tasks(tasks: list[Task]) -> None:
    # Tolerate an empty or transiently-missing 'tasks:' section by defaulting
    # to a fresh wrapper dict; re-loading existing top-level keys preserves
    # any other fields in tasks.yaml the operator may have added.
    with open(TASKS_FILE) as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        data = {}
    data["tasks"] = tasks

    # Stage the new content first. If serialization fails, nothing above the
    # temp file is disturbed — backups retain whatever they had.
    tmp_path = TASKS_FILE.with_suffix(TASKS_FILE.suffix + ".tmp")
    with open(tmp_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        f.flush()
        os.fsync(f.fileno())

    # Only rotate the backup chain once we know the new content is on disk
    # and ready to replace. This keeps the rolling chain crash-safe against
    # any failure in the dump/fsync step above.
    if TASKS_FILE.exists():
        _rotate_task_backups()
        shutil.copy2(TASKS_FILE, TASKS_BACKUP)
    os.replace(tmp_path, TASKS_FILE)


def get_task(tasks: list[Task], task_id: str) -> Task | None:
    return next((t for t in tasks if t["id"] == task_id), None)


# ── Eligibility ───────────────────────────────────────────────────────────────


def is_eligible(task: Task, tasks: list[Task]) -> bool:
    if task.get("status") != "todo":
        return False
    for dep_id in task.get("depends_on", []):
        dep = get_task(tasks, dep_id)
        if not dep or dep.get("status") != "done":
            return False
    return True


def next_eligible_task(tasks: list[Task]) -> Task | None:
    return next((t for t in tasks if is_eligible(t, tasks)), None)


def active_task(tasks: list[Task]) -> Task | None:
    return next((t for t in tasks if t.get("status") == "in_progress"), None)


ROADMAP_COMPLETE_RE = re.compile(r"^\s*ROADMAP_COMPLETE\s*$")


def is_completion_signal(last_msg: str) -> bool:
    """True only if the last non-empty line of last_msg is ROADMAP_COMPLETE."""
    if not last_msg:
        return False
    for line in reversed(last_msg.splitlines()):
        if line.strip():
            return bool(ROADMAP_COMPLETE_RE.match(line))
    return False


# ── Git helpers (partial-work recovery) ──────────────────────────────────────


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=check,
    )


def _is_git_repo() -> bool:
    return _git("rev-parse", "--is-inside-work-tree", check=False).returncode == 0


def _current_branch() -> str | None:
    result = _git("rev-parse", "--abbrev-ref", "HEAD", check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def _branch_exists(branch: str) -> bool:
    return _git("rev-parse", "--verify", branch, check=False).returncode == 0


def task_branch_name(task_id: str) -> str:
    return f"roadrunner/{task_id}"


def create_task_branch(task_id: str, base_branch: str | None = None) -> bool:
    """Create a task branch. Returns True if created (or already exists), False on git errors.

    If base_branch is provided and exists, checks it out BEFORE creating the task
    branch — this prevents stacking. Without this, calling start on a new task while
    HEAD is still on a previous task branch would create the new branch atop the old,
    producing a stack instead of a fan-out from the project base.
    """
    if not _is_git_repo():
        return False
    branch = task_branch_name(task_id)
    if _branch_exists(branch):
        return True
    if base_branch and _branch_exists(base_branch):
        checkout = _git("checkout", base_branch, check=False)
        if checkout.returncode != 0:
            trace_event(
                "git_base_checkout_error",
                task_id=task_id,
                extra={"base": base_branch, "stderr": checkout.stderr.strip()[:200]},
            )
            # Fall through — we'll still try to branch from whatever HEAD is.
    result = _git("checkout", "-b", branch, check=False)
    if result.returncode != 0:
        trace_event("git_branch_error", task_id=task_id, extra={"stderr": result.stderr.strip()[:200]})
        return False
    trace_event("git_branch_create", task_id=task_id, extra={"branch": branch, "base": base_branch})
    return True


def merge_task_branch(task_id: str, base_branch: str) -> bool:
    """Merge task branch back to base and delete it. Returns True on success.

    On merge failure (e.g. conflict), runs `git merge --abort` so the repo is
    returned to a clean state. The task branch is left intact for manual
    resolution.
    """
    if not _is_git_repo():
        return False
    branch = task_branch_name(task_id)
    if not _branch_exists(branch):
        return True
    current = _current_branch()
    if current == branch:
        _git("checkout", base_branch, check=False)
    result = _git("merge", branch, "--no-edit", check=False)
    if result.returncode != 0:
        # Abort the in-flight merge so callers can inspect/retry cleanly.
        abort = _git("merge", "--abort", check=False)
        trace_event(
            "git_merge_error",
            task_id=task_id,
            extra={
                "stderr": result.stderr.strip()[:200],
                "branch": branch,
                "base": base_branch,
            },
        )
        # Record the abort independently so a double-failure (abort itself
        # errored, e.g. no merge was actually in progress) is visible in the trace.
        trace_event(
            "git_merge_abort",
            task_id=task_id,
            extra={
                "returncode": abort.returncode,
                "stderr": abort.stderr.strip()[:200],
                "branch": branch,
            },
        )
        return False
    _git("branch", "-d", branch, check=False)
    trace_event("git_branch_merge", task_id=task_id, extra={"branch": branch, "into": base_branch})
    return True


# ── Validation ────────────────────────────────────────────────────────────────


def run_validation(task: Task) -> tuple[bool, list[ValidationResult]]:
    """Run all validation_commands for a task. Returns (passed, results)."""
    import time

    commands = task.get("validation_commands", [])
    if not commands:
        return True, []

    results: list[ValidationResult] = []
    all_passed = True
    state = read_state()
    timeout = task.get("validation_timeout", DEFAULT_VALIDATION_TIMEOUT)

    for cmd in commands:
        t0 = time.monotonic()
        timed_out = False
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                cwd=ROOT,
                timeout=timeout,
            )
            passed = result.returncode == 0
            stdout = result.stdout.strip()[:500]
            stderr = result.stderr.strip()[:500]
            returncode = result.returncode
        except subprocess.TimeoutExpired as exc:
            passed = False
            timed_out = True
            stdout = (exc.stdout or b"").decode(errors="replace").strip()[:500]
            stderr = (exc.stderr or b"").decode(errors="replace").strip()[:500]
            returncode = -1
        elapsed = (time.monotonic() - t0) * 1000
        if not passed:
            all_passed = False
        entry: ValidationResult = {
            "command": cmd,
            "passed": passed,
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
        }
        if timed_out:
            entry["timed_out"] = True
        results.append(entry)
        trace_event(
            "validation_command",
            task_id=task["id"],
            iteration=state.get("iteration"),
            command=cmd,
            exit_code=returncode,
            duration_ms=elapsed,
        )

    trace_event(
        "validation_complete",
        task_id=task["id"],
        iteration=state.get("iteration"),
        extra={"passed": all_passed, "total": len(results)},
    )
    return all_passed, results


# ── State management ──────────────────────────────────────────────────────────


def write_state(
    current_task_id: str | None,
    iteration: int,
    attempts: dict | None = None,
    extra: dict | None = None,
) -> None:
    state = {
        "schema_version": STATE_SCHEMA_VERSION,
        "current_task_id": current_task_id,
        "iteration": iteration,
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
    default: RoadmapState = {"current_task_id": None, "iteration": 0, "attempts_per_task": {}}
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
    # Schema gate: missing version → legacy v1 (backward compatible). Newer version
    # than we understand → exit immediately so the caller never overwrites the
    # forward-compat state file. Operator fix: upgrade this tool or migrate state.
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
    return cast(RoadmapState, data)


def increment_attempts(state: RoadmapState, task_id: str) -> int:
    attempts = state.get("attempts_per_task", {})
    attempts[task_id] = attempts.get(task_id, 0) + 1
    state["attempts_per_task"] = attempts
    return attempts[task_id]


@contextmanager
def _exclusive_state_lock():
    """POSIX advisory lock around the state file's read→modify→write window.

    Uses a sibling lockfile so the lock object is not wiped by `os.replace` of the
    state file itself. On Windows (where `fcntl` is unavailable) this degrades to
    a no-op since the project only supports POSIX; multi-operator concurrency is
    a documented non-goal but a single flock closes the accidental-concurrency hole.
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


# ── Logging ───────────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_changelog(task_id: str, status: str, notes: str = "") -> None:
    entry = f"## {_now()} | {task_id} → {status}\n{notes}\n\n"
    try:
        with open(CHANGELOG, "a") as f:
            f.write(entry)
    except OSError as exc:
        # Audit trail must never break the control loop.
        print(f"[roadrunner] changelog append failed: {exc}", file=sys.stderr)


def trace_event(
    event_type: str,
    task_id: str | None = None,
    iteration: int | None = None,
    command: str | None = None,
    exit_code: int | None = None,
    duration_ms: float | None = None,
    extra: dict | None = None,
) -> None:
    record: dict[str, Any] = {
        "ts": _now(),
        "event": event_type,
        "task_id": task_id,
        "iteration": iteration,
    }
    if command is not None:
        record["command"] = command
    if exit_code is not None:
        record["exit_code"] = exit_code
    if duration_ms is not None:
        record["duration_ms"] = round(duration_ms, 1)
    if extra:
        record.update(extra)
    try:
        with open(TRACE_LOG, "a") as f:
            f.write(json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n")
    except OSError as exc:
        # Observability must never break the control loop.
        print(f"[roadrunner] trace_event failed: {exc}", file=sys.stderr)


# ── Log rotation ──────────────────────────────────────────────────────────────


def _rotate_one(path: Path) -> None:
    """Rotate a single log file by renaming with a UTC timestamp suffix and gzipping.

    The suffix includes microseconds and falls back to a counter on collision so two
    rotations within the same microsecond never clobber each other's archives.
    """
    if not path.exists() or path.stat().st_size < LOG_ROTATE_BYTES:
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    rotated = path.with_name(f"{path.name}.{stamp}")
    # Collision safety: if the rotated name or its .gz twin already exists
    # (same-microsecond rotations on a clock with coarser-than-μs resolution),
    # append a monotonic counter.
    counter = 1
    while rotated.exists() or Path(str(rotated) + ".gz").exists():
        rotated = path.with_name(f"{path.name}.{stamp}.{counter}")
        counter += 1
    path.rename(rotated)
    # Avoid ``Path.with_suffix`` here: the timestamp segment looks like a suffix
    # to pathlib and would be clobbered rather than preserved.
    gz_path = Path(str(rotated) + ".gz")
    with open(rotated, "rb") as src, gzip.open(gz_path, "wb") as dst:
        shutil.copyfileobj(src, dst)
    rotated.unlink()


def _prune_old_rotations(directory: Path, stem: str) -> None:
    """Delete rotated files matching {stem}.* older than LOG_RETAIN_DAYS."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOG_RETAIN_DAYS)
    for p in directory.glob(f"{stem}.*"):
        # Skip the live log itself (no timestamp suffix) and *.tmp partials.
        if p.name == stem or p.name.endswith(".tmp"):
            continue
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if mtime < cutoff:
            try:
                p.unlink()
            except OSError as exc:
                print(f"[roadrunner] prune failed for {p}: {exc}", file=sys.stderr)


def rotate_logs() -> None:
    """Rotate oversized logs and prune old rotations. Called at task boundaries."""
    try:
        for path in (TRACE_LOG, CHANGELOG):
            _rotate_one(path)
        _prune_old_rotations(LOGS_DIR, TRACE_LOG.name)
        _prune_old_rotations(LOGS_DIR, CHANGELOG.name)
    except Exception as exc:
        # Rotation failures must never break the loop.
        print(f"[roadrunner] rotate_logs failed: {exc}", file=sys.stderr)


def write_work_log(task: Task, validation_results: list[ValidationResult], notes: str = "") -> None:
    log_path = LOGS_DIR / f"{task['id']}.md"
    passed_count = sum(1 for r in validation_results if r["passed"])
    total = len(validation_results)

    lines = [
        f"# Work Log: {task['id']} — {task.get('title', '')}",
        f"**Completed:** {_now()}",
        f"**Status:** {task.get('status')}",
        "",
        f"## Goal\n{task.get('goal', 'N/A')}",
        "",
        "## Acceptance Criteria",
    ]
    for ac in task.get("acceptance_criteria", []):
        lines.append(f"- {ac}")

    lines += [
        "",
        f"## Validation ({passed_count}/{total} passed)",
    ]
    for r in validation_results:
        icon = "✅" if r["passed"] else "❌"
        lines.append(f"\n### {icon} `{r['command']}`")
        if r["stdout"]:
            lines.append(f"```\n{r['stdout']}\n```")
        if r["stderr"] and not r["passed"]:
            lines.append(f"**stderr:**\n```\n{r['stderr']}\n```")

    if notes:
        lines += ["", f"## Notes\n{notes}"]

    log_path.write_text("\n".join(lines))


def write_reset_marker(task_id: str, summary: str) -> None:
    marker = ROOT / f".reset_{task_id}"
    marker.write_text(
        json.dumps(
            {"task_id": task_id, "summary": summary, "at": _now()},
            indent=2,
            ensure_ascii=False,
        )
    )


def write_context_snapshot() -> None:
    """Called by PreCompact hook — persist enough state for cold resume."""
    tasks = load_tasks()
    state = read_state()
    next_task = next_eligible_task(tasks)

    snapshot = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "snapshot_at": _now(),
        "current_task": state.get("current_task_id"),
        "iteration": state.get("iteration", 0),
        "next_eligible": next_task["id"] if next_task else None,
        "status_summary": {t["id"]: t["status"] for t in tasks},
    }
    (ROOT / ".context_snapshot.json").write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False)
    )


# ── CLI commands ──────────────────────────────────────────────────────────────


def cmd_status(args: argparse.Namespace) -> None:
    tasks = load_tasks()
    print(f"\n{'ID':<14} {'STATUS':<12} {'TITLE'}")
    print("─" * 60)
    for t in tasks:
        marker = "→" if t.get("status") == "in_progress" else " "
        print(
            f"{marker} {t['id']:<13} {t.get('status', 'todo'):<12} {t.get('title', '')}"
        )
    next_t = next_eligible_task(tasks)
    print(f"\nNext eligible: {next_t['id'] if next_t else 'None'}")


def cmd_next(args: argparse.Namespace) -> None:
    tasks = load_tasks()
    task = next_eligible_task(tasks)
    if not task:
        print("No eligible tasks.")
        return
    print(f"\nNext: {task['id']} — {task.get('title')}")
    print(f"Goal: {task.get('goal', 'N/A')}")
    print("Acceptance criteria:")
    for ac in task.get("acceptance_criteria", []):
        print(f"  - {ac}")


def cmd_start(args: argparse.Namespace) -> None:
    tasks = load_tasks()
    task = get_task(tasks, args.task_id)
    if not task:
        print(f"Task {args.task_id} not found.")
        sys.exit(1)
    if not is_eligible(task, tasks):
        print(
            f"Task {args.task_id} is not eligible (status={task.get('status')}, check deps)."
        )
        sys.exit(1)

    state = read_state()
    # Record base branch before creating task branch. Prefer the configured
    # project_base from tasks.yaml over _current_branch() to avoid stacking
    # task branches on top of previous task branches (ROAD-025).
    base_branch = get_project_base()
    task["status"] = "in_progress"
    save_tasks(tasks)
    write_state(
        args.task_id,
        state.get("iteration", 0),
        state.get("attempts_per_task"),
        extra={"base_branch": base_branch},
    )
    append_changelog(args.task_id, "in_progress")
    branched = create_task_branch(args.task_id, base_branch=base_branch)
    trace_event(
        "task_start",
        task_id=args.task_id,
        iteration=state.get("iteration", 0),
        extra={"base_branch": base_branch, "branched": branched},
    )
    branch_msg = f" (branch: {task_branch_name(args.task_id)})" if branched else ""
    print(f"Started {args.task_id}. Iteration {state.get('iteration', 0)}.{branch_msg}")


def cmd_validate(args: argparse.Namespace) -> None:
    tasks = load_tasks()
    task = get_task(tasks, args.task_id)
    if not task:
        print(f"Task {args.task_id} not found.")
        sys.exit(1)

    trace_event("validate_start", task_id=args.task_id)
    passed, results = run_validation(task)
    trace_event(
        "validate_end",
        task_id=args.task_id,
        extra={"passed": passed, "total": len(results)},
    )
    for r in results:
        icon = "✅" if r["passed"] else "❌"
        print(f"{icon} {r['command']}")
        if not r["passed"] and r["stderr"]:
            print(f"   {r['stderr'][:200]}")

    sys.exit(0 if passed else 1)


def cmd_complete(args: argparse.Namespace) -> None:
    tasks = load_tasks()
    task = get_task(tasks, args.task_id)
    if not task:
        print(f"Task {args.task_id} not found.")
        sys.exit(1)

    passed, results = run_validation(task)
    if not passed:
        print(f"Validation failed. Task {args.task_id} NOT marked done.")
        write_work_log(task, results, notes=args.notes or "")
        sys.exit(1)

    task["status"] = "done"
    save_tasks(tasks)
    write_work_log(task, results, notes=args.notes or "")
    append_changelog(args.task_id, "done", notes=args.notes or "")
    write_reset_marker(args.task_id, summary=args.notes or "Completed.")
    state = read_state()
    # Merge task branch back to base if it exists
    base_branch = state.get("base_branch", "main")
    merged = merge_task_branch(args.task_id, base_branch)
    # Clear current_task_id so SessionStart / check_stop don't read a stale
    # "resume this done task" pointer on the next fire. Preserve iteration,
    # attempts, and base_branch for continuity.
    write_state(
        None,
        state.get("iteration", 0),
        state.get("attempts_per_task", {}),
        extra={"base_branch": base_branch} if base_branch else None,
    )
    trace_event(
        "task_complete",
        task_id=args.task_id,
        iteration=state.get("iteration"),
        extra={"merged": merged},
    )
    print(f"✅ {args.task_id} marked done.")


def cmd_block(args: argparse.Namespace) -> None:
    tasks = load_tasks()
    task = get_task(tasks, args.task_id)
    if not task:
        print(f"Task {args.task_id} not found.")
        sys.exit(1)

    task["status"] = "blocked"
    save_tasks(tasks)
    append_changelog(args.task_id, "blocked", notes=args.notes or "")
    write_work_log(task, [], notes=args.notes or "")
    state = read_state()
    trace_event(
        "task_block", task_id=args.task_id, iteration=state.get("iteration"),
        extra={"notes": args.notes or ""},
    )
    print(f"🚫 {args.task_id} marked blocked.")


def cmd_reset(args: argparse.Namespace) -> None:
    write_reset_marker(args.task_id, summary=args.summary or "")
    write_context_snapshot()
    rotate_logs()
    print(f"Reset marker written for {args.task_id}.")


def cmd_health(args: argparse.Namespace) -> None:
    tasks = load_tasks()
    eligible = [t for t in tasks if is_eligible(t, tasks)]
    done = [t for t in tasks if t.get("status") == "done"]
    blocked = [t for t in tasks if t.get("status") == "blocked"]
    print(
        f"healthy — {len(done)}/{len(tasks)} done, {len(eligible)} eligible, {len(blocked)} blocked"
    )


def cmd_check_stop(args: argparse.Namespace) -> None:
    """
    Called by Stop hook. Outputs JSON to control whether Claude Code halts.
    Reads stop_hook_active from stdin to prevent infinite loops.
    """
    try:
        stdin_data = json.loads(sys.stdin.read())
    except Exception:
        stdin_data = {}

    # stop_hook_active is Claude Code's signal that a previous hook invocation
    # in this session already blocked-and-continued. Historically we early-exited
    # on this to avoid infinite loops, but that killed legitimate multi-task
    # runs the moment the flag flipped true — the loop would stop after the
    # first task boundary and the user would have to restart the session to
    # move on. Treat the flag as a hint: only allow stop if the roadmap is
    # genuinely finished (no active task, no eligible next task). Otherwise
    # fall through to normal decision logic — the iteration cap and per-task
    # auto-block (5 attempts) are the real safety nets against runaway loops.
    hook_looping = bool(stdin_data.get("stop_hook_active"))

    # Serialize concurrent Stop-hook fires so the read→increment→write span in the
    # body below is atomic. SystemExit from any sys.exit() still releases the lock
    # via the context manager's finally.
    with _exclusive_state_lock():
        state = read_state()
        iteration = state.get("iteration", 0) + 1
        attempts = state.get("attempts_per_task", {})
        max_iter = int(args.max_iterations) if args.max_iterations else 50
        max_attempts = int(args.max_attempts) if args.max_attempts else MAX_TASK_ATTEMPTS
        write_state(state.get("current_task_id"), iteration, attempts)
        trace_event(
            "check_stop",
            task_id=state.get("current_task_id"),
            iteration=iteration,
            extra={"max_iter": max_iter},
        )

        if iteration >= max_iter:
            print(
                json.dumps(
                    {
                        "continue": False,
                        "stopReason": f"Max iterations ({max_iter}) reached. Roadmap loop halted.",
                    },
                    ensure_ascii=False,
                )
            )
            sys.exit(0)

        tasks = load_tasks()
        last_msg = stdin_data.get("last_assistant_message", "")

        # If Claude Code flagged this fire as a potential hook loop AND there is
        # genuinely nothing left to do (no active task, no eligible next task),
        # allow the stop. Otherwise we ignore the flag and keep driving — stalled
        # sessions still get caught by the iteration cap below.
        if hook_looping and not active_task(tasks) and not next_eligible_task(tasks):
            sys.exit(0)

        # Completion signal: Claude outputs ROADMAP_COMPLETE as the last non-empty line
        if is_completion_signal(last_msg):
            append_changelog(
                "ALL",
                "complete",
                notes="Roadmap finished — ROADMAP_COMPLETE signal received.",
            )
            sys.exit(0)

        # Resume in-progress task if Claude responded mid-task
        in_flight = active_task(tasks)
        if in_flight:
            task_attempts = increment_attempts(state, in_flight["id"])
            write_state(in_flight["id"], iteration, state["attempts_per_task"])
            if task_attempts >= max_attempts:
                in_flight["status"] = "blocked"
                save_tasks(tasks)
                append_changelog(
                    in_flight["id"],
                    "blocked",
                    notes=f"Auto-blocked after {task_attempts} attempts without completion.",
                )
                trace_event(
                    "auto_block",
                    task_id=in_flight["id"],
                    iteration=iteration,
                    extra={"attempts": task_attempts, "max_attempts": max_attempts},
                )
                msg = (
                    f"Task {in_flight['id']} auto-blocked after {task_attempts} attempts. "
                    f"Move to the next task or output ROADMAP_COMPLETE on its own line."
                )
                print(json.dumps({"decision": "block", "reason": msg}, ensure_ascii=False))
                sys.exit(0)
            brief = _build_task_brief(in_flight, iteration, max_iter, resume=True)
            print(json.dumps({"decision": "block", "reason": brief}, ensure_ascii=False))
            sys.exit(0)

        next_task = next_eligible_task(tasks)
        if next_task:
            brief = _build_task_brief(next_task, iteration, max_iter)
            print(json.dumps({"decision": "block", "reason": brief}, ensure_ascii=False))
            sys.exit(0)

        # No active or eligible task — check for blocked before declaring done
        blocked = [t["id"] for t in tasks if t.get("status") == "blocked"]
        if blocked:
            msg = (
                f"No eligible tasks. Blocked: {blocked}. Investigate and unblock, "
                "or output ROADMAP_COMPLETE on its own line to halt."
            )
            print(json.dumps({"decision": "block", "reason": msg}, ensure_ascii=False))
            sys.exit(0)

        remaining = [t["id"] for t in tasks if t.get("status") not in ("done",)]
        if remaining:
            msg = (
                f"No eligible tasks, but these are not done: {remaining}. "
                "Check dependencies and status. Output ROADMAP_COMPLETE on its own line only if roadmap is truly finished."
            )
            print(json.dumps({"decision": "block", "reason": msg}, ensure_ascii=False))
            sys.exit(0)

        msg = "All tasks complete. Output ROADMAP_COMPLETE on its own line to signal completion."
        print(json.dumps({"decision": "block", "reason": msg}, ensure_ascii=False))
        sys.exit(0)


def cmd_snapshot(args: argparse.Namespace) -> None:
    write_context_snapshot()


_INIT_TASKS_TEMPLATE = """\
# project_base: branch that task branches fork from (prevents stacking).
# Task branches auto-merge back into this on `roadrunner complete`.
project_base: main

tasks:
  - id: TASK-001
    title: "First task — replace me"
    status: todo
    depends_on: []
    goal: |
      Describe what this task accomplishes. Keep the scope to a single
      boundary — one task per cycle, no side quests.
    acceptance_criteria:
      - "Describe a concrete, observable outcome"
    validation_commands:
      - "echo 'replace with a real check (test, lint, build)'"
    files_expected: []
"""

_INIT_CLAUDE_MD_TEMPLATE = """\
# CLAUDE.md — Roadmap Loop Agent Brief

You are executing a deterministic roadmap. Python owns control. You own implementation.
One task per cycle. No side quests. No skipping ahead.

## Each cycle
1. `python3 roadrunner.py next`
2. `python3 roadrunner.py start TASK-XXX`
3. Implement inside the task boundary
4. `python3 roadrunner.py validate TASK-XXX`
5. `python3 roadrunner.py complete TASK-XXX --notes "..."`
6. `python3 roadrunner.py reset TASK-XXX --summary "..."`

When every task is `done` and nothing is eligible, output the sentinel
`ROADMAP_COMPLETE` on its own line as the last line of your message.
"""


def _init_plan(target: Path, source: Path) -> list[tuple[str, Path, Path | None, str | None]]:
    """Return the list of scaffold actions as (kind, dest, src_or_none, content_or_none).

    kind is one of: 'mkdir', 'write', 'copy'. For 'write', content is the string to
    emit; for 'copy', src is the source path on disk.
    """
    plan: list[tuple[str, Path, Path | None, str | None]] = [
        ("mkdir", target / "tasks", None, None),
        ("write", target / "tasks" / "tasks.yaml", None, _INIT_TASKS_TEMPLATE),
        ("mkdir", target / "logs", None, None),
        ("write", target / "logs" / ".gitkeep", None, ""),
        ("write", target / "CLAUDE.md", None, _INIT_CLAUDE_MD_TEMPLATE),
    ]
    settings_src = source / ".claude" / "settings.json"
    if settings_src.is_file():
        plan.append(("mkdir", target / ".claude", None, None))
        plan.append(("copy", target / ".claude" / "settings.json", settings_src, None))
    hooks_src = source / "hooks"
    if hooks_src.is_dir():
        plan.append(("mkdir", target / "hooks", None, None))
        for hook_file in sorted(hooks_src.iterdir()):
            if hook_file.is_file():
                plan.append(("copy", target / "hooks" / hook_file.name, hook_file, None))
    return plan


def cmd_init(args: argparse.Namespace) -> None:
    raw_target = args.target_dir
    target = Path.cwd() if raw_target == "." else Path(raw_target).expanduser().resolve()
    source = ROOT
    dry_run = bool(getattr(args, "dry_run", False))

    prefix = "[dry-run] " if dry_run else ""
    print(f"{prefix}Scaffolding roadrunner project at: {target}")

    if raw_target != "." and not target.exists() and not dry_run:
        target.mkdir(parents=True)

    plan = _init_plan(target, source)
    created: list[str] = []
    skipped: list[str] = []
    for kind, dest, src, content in plan:
        rel = dest.relative_to(target) if dest.is_relative_to(target) else dest
        if kind == "mkdir":
            if dest.exists():
                if not dest.is_dir():
                    skipped.append(f"{rel} (exists, not a directory)")
                continue
            if dry_run:
                print(f"{prefix}mkdir  {rel}/")
            else:
                dest.mkdir(parents=True, exist_ok=True)
                print(f"mkdir  {rel}/")
            created.append(f"{rel}/")
        elif kind == "write":
            if dest.exists():
                print(f"skip   {rel} (already exists)")
                skipped.append(str(rel))
                continue
            if dry_run:
                print(f"{prefix}write  {rel}")
            else:
                dest.write_text(content or "", encoding="utf-8")
                print(f"write  {rel}")
            created.append(str(rel))
        elif kind == "copy":
            assert src is not None, "copy plan entries always carry a source path"
            if dest.exists():
                print(f"skip   {rel} (already exists)")
                skipped.append(str(rel))
                continue
            if dry_run:
                print(f"{prefix}copy   {rel}  <-  {src}")
            else:
                shutil.copy2(src, dest)
                if dest.suffix == ".sh":
                    dest.chmod(dest.stat().st_mode | 0o111)
                print(f"copy   {rel}  <-  {src}")
            created.append(str(rel))

    print()
    print("Next steps:")
    print("  1. Edit tasks/tasks.yaml — replace TASK-001 with your real first task.")
    print("  2. Review CLAUDE.md and tailor the agent brief to your project.")
    print("  3. Confirm .claude/settings.json wires up the hooks you want to run.")
    print("  4. Run `python3 roadrunner.py status` to confirm the roadmap parses.")
    print("  5. Start the loop with `python3 roadrunner.py next`.")
    if skipped:
        print()
        print(f"Skipped {len(skipped)} existing path(s); they were left untouched.")


def _load_tasks_from(path: Path) -> list[dict]:
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return list(data.get("tasks") or [])


def _find_cycles(ids: list[str], dep_map: dict[str, list[str]]) -> list[list[str]]:
    """DFS-based cycle detection. Returns each unique cycle as a list of task IDs."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {tid: WHITE for tid in ids}
    cycles: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()

    def walk(node: str, stack: list[str]) -> None:
        color[node] = GRAY
        for dep in dep_map.get(node, []):
            if dep not in color:
                continue
            if color[dep] == GRAY and dep in stack:
                cycle = stack[stack.index(dep):] + [dep]
                key = tuple(sorted(set(cycle)))
                if key not in seen:
                    seen.add(key)
                    cycles.append(cycle)
            elif color[dep] == WHITE:
                walk(dep, stack + [dep])
        color[node] = BLACK

    for tid in ids:
        if color[tid] == WHITE:
            walk(tid, [tid])
    return cycles


def _longest_chain(ids: list[str], dep_map: dict[str, list[str]]) -> int:
    """Length of the longest dependency chain in task count. Caller must ensure the graph is acyclic."""
    memo: dict[str, int] = {}

    def depth(tid: str) -> int:
        if tid in memo:
            return memo[tid]
        deps = [d for d in dep_map.get(tid, []) if d in dep_map]
        memo[tid] = 1 + max((depth(d) for d in deps), default=0)
        return memo[tid]

    return max((depth(t) for t in ids), default=0)


def cmd_analyze(args: argparse.Namespace) -> None:
    path = Path(args.tasks_file).expanduser().resolve() if args.tasks_file else TASKS_FILE
    try:
        tasks = _load_tasks_from(path)
    except FileNotFoundError:
        print(f"error: tasks file not found at {path}", file=sys.stderr)
        sys.exit(1)
    except yaml.YAMLError as exc:
        print(f"error: invalid YAML in {path}: {exc}", file=sys.stderr)
        sys.exit(1)

    total = len(tasks)
    counts = {"done": 0, "todo": 0, "in_progress": 0, "blocked": 0, "other": 0}
    for t in tasks:
        status = t.get("status", "todo")
        counts[status if status in counts else "other"] += 1

    ids = [t["id"] for t in tasks if t.get("id")]
    id_set = set(ids)
    dep_map: dict[str, list[str]] = {
        t["id"]: list(t.get("depends_on") or []) for t in tasks if t.get("id")
    }

    errors: list[str] = []
    warnings: list[str] = []

    for tid, deps in dep_map.items():
        for dep in deps:
            if dep not in id_set:
                errors.append(f"task {tid} depends on unknown task {dep!r}")

    cycles = _find_cycles(ids, dep_map)
    for cycle in cycles:
        errors.append(f"circular dependency: {' -> '.join(cycle)}")

    for t in tasks:
        if not (t.get("validation_commands") or []):
            warnings.append(f"task {t.get('id', '<no-id>')} has no validation_commands")

    critical_path = _longest_chain(ids, dep_map) if not cycles else 0

    print(f"Analyzed: {path}")
    print(f"Total tasks: {total}")
    print(f"  done:        {counts['done']}")
    print(f"  todo:        {counts['todo']}")
    print(f"  in_progress: {counts['in_progress']}")
    print(f"  blocked:     {counts['blocked']}")
    if counts["other"]:
        print(f"  other:       {counts['other']}")
    if critical_path:
        print(f"Critical path (longest dep chain): {critical_path} tasks")

    if errors:
        print()
        print(f"Errors ({len(errors)}):")
        for e in errors:
            print(f"  ❌ {e}")
    if warnings:
        print()
        print(f"Warnings ({len(warnings)}):")
        for w in warnings:
            print(f"  ⚠️  {w}")

    if not errors and not warnings:
        print()
        print("✅ No issues found.")

    sys.exit(1 if errors else 0)


def cmd_session_start(args: argparse.Namespace) -> None:
    """Called by the SessionStart hook. If `.context_snapshot.json` exists,
    emit a SessionStart `hookSpecificOutput` JSON so the next session starts
    with roadmap context. Silent no-op when no snapshot is present.

    This mirrors the cmd_snapshot pattern so that both SessionStart and
    PreCompact hooks have one Python entry point — no separate helper script.
    """
    snap_path = ROOT / ".context_snapshot.json"
    if not snap_path.exists():
        return
    try:
        snap = json.loads(snap_path.read_text())
    except (OSError, json.JSONDecodeError):
        return

    parts = []
    if snap.get("current_task"):
        parts.append(f"Current task: {snap['current_task']}")
    if snap.get("next_eligible"):
        parts.append(f"Next eligible: {snap['next_eligible']}")
    if snap.get("iteration"):
        parts.append(f"Iteration: {snap['iteration']}")
    if snap.get("status_summary"):
        summary = ", ".join(f"{k}={v}" for k, v in snap["status_summary"].items())
        parts.append(f"Status: {summary}")

    if not parts:
        return

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": "Roadmap snapshot: " + " | ".join(parts),
                }
            },
            ensure_ascii=False,
        )
    )


def _build_task_brief(
    task: Task, iteration: int, max_iter: int, resume: bool = False
) -> str:
    criteria = "\n".join(f"  - {ac}" for ac in task.get("acceptance_criteria", []))
    validation = "\n".join(f"  - {v}" for v in task.get("validation_commands", []))
    files = "\n".join(f"  - {f}" for f in task.get("files_expected", []))
    header = (
        f"RESUME IN-PROGRESS TASK. Iteration {iteration}/{max_iter}."
        if resume
        else f"Continue working. Iteration {iteration}/{max_iter}."
    )
    # Avoid embedding the completion sentinel as a bare line — describe it instead.
    sentinel_hint = f"output the completion sentinel (the word {_COMPLETION_SIGNAL}) on its own line"
    return (
        f"{header}\n\n"
        f"CURRENT TASK: {task['id']} — {task.get('title')}\n"
        f"Goal: {task.get('goal', 'N/A')}\n\n"
        f"Acceptance criteria:\n{criteria or '  (none specified)'}\n\n"
        f"Validation commands (must pass before complete):\n{validation or '  (none)'}\n\n"
        f"Expected files:\n{files or '  (none)'}\n\n"
        f"When done: run `python3 roadrunner.py complete {task['id']} --notes '...'`\n"
        f"To signal full roadmap done: {sentinel_hint}."
    )


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Roadmap Loop Controller")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status")
    sub.add_parser("next")
    sub.add_parser("health")
    sub.add_parser("snapshot")
    sub.add_parser("session-start")

    p_start = sub.add_parser("start")
    p_start.add_argument("task_id")

    p_validate = sub.add_parser("validate")
    p_validate.add_argument("task_id")

    p_complete = sub.add_parser("complete")
    p_complete.add_argument("task_id")
    p_complete.add_argument("--notes", default="")

    p_block = sub.add_parser("block")
    p_block.add_argument("task_id")
    p_block.add_argument("--notes", default="")

    p_reset = sub.add_parser("reset")
    p_reset.add_argument("task_id")
    p_reset.add_argument("--summary", default="")

    p_stop = sub.add_parser("check-stop")
    p_stop.add_argument("--max-iterations", default="50")
    p_stop.add_argument("--max-attempts", default=str(MAX_TASK_ATTEMPTS))

    p_init = sub.add_parser("init", help="Scaffold a new roadrunner project directory")
    p_init.add_argument("target_dir", help="Target directory (use '.' for current working directory)")
    p_init.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be created without touching the filesystem",
    )

    p_analyze = sub.add_parser("analyze", help="Analyze tasks.yaml for cycles, missing deps, and coverage")
    p_analyze.add_argument(
        "--tasks-file",
        default=None,
        help="Path to a tasks.yaml file (defaults to the project tasks/tasks.yaml)",
    )

    args = parser.parse_args()

    dispatch = {
        "status": cmd_status,
        "next": cmd_next,
        "start": cmd_start,
        "validate": cmd_validate,
        "complete": cmd_complete,
        "block": cmd_block,
        "reset": cmd_reset,
        "health": cmd_health,
        "check-stop": cmd_check_stop,
        "snapshot": cmd_snapshot,
        "session-start": cmd_session_start,
        "init": cmd_init,
        "analyze": cmd_analyze,
    }

    if args.command not in dispatch:
        parser.print_help()
        sys.exit(1)

    dispatch[args.command](args)


if __name__ == "__main__":
    main()
