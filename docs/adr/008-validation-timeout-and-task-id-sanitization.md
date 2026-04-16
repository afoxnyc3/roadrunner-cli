# ADR-008: Validation Timeout and Task ID Sanitization

**Status:** Accepted
**Date:** 2026-04-16
**Deciders:** Alex, Claude Opus 4.6

## Context

An architecture review (2026-04-15) identified two open risks in `roadrunner.py`:

1. **No subprocess timeout.** `run_validation()` called `subprocess.run()` without a `timeout` parameter. A hanging validation command (network wait, deadlock, infinite loop) would block the entire roadmap loop indefinitely with no recovery path. Every fault-tolerance guide for agentic systems lists unbounded execution as a top anti-pattern.

2. **No task ID sanitization.** Task IDs flowed unsanitized into file paths (`ROOT / f".reset_{task_id}"`, `LOGS_DIR / f"{task['id']}.md"`) and git branch names (`f"roadrunner/{task_id}"`). A task ID containing `../` could write files outside the project directory. Low risk for single-operator use, but a latent path traversal vulnerability.

## Decision

### Subprocess timeout

Add `timeout` parameter to `subprocess.run()` in `run_validation()`:

- Default: 300 seconds (`DEFAULT_VALIDATION_TIMEOUT`)
- Per-task override: `validation_timeout` field in `tasks.yaml`
- On `TimeoutExpired`: catch the exception, report as a validation failure with `returncode: -1` and `timed_out: True` in the result dict
- `TimeoutExpired.stdout`/`.stderr` are `bytes | None` even with `text=True` (exception fires before text decoding) — decode with `errors="replace"`

```python
try:
    result = subprocess.run(cmd, shell=True, ..., timeout=timeout)
except subprocess.TimeoutExpired as exc:
    passed = False
    stdout = (exc.stdout or b"").decode(errors="replace").strip()[:500]
    stderr = (exc.stderr or b"").decode(errors="replace").strip()[:500]
    returncode = -1
```

### Task ID sanitization

Add regex validation in `validate_task_schema()`:

- Pattern: `^[A-Z]+-\d+$` (matches `TASK-001`, `FEAT-12`, `BUG-1`, etc.)
- Rejects: `../etc`, empty strings, lowercase, spaces, shell metacharacters
- Fires on every `load_tasks()` call (schema validation runs per-task)

Also validate `validation_timeout` if present: must be a positive number.

### Empty YAML guard

`yaml.safe_load()` returns `None` for empty files. Added `or {}` guard in `load_tasks()` to prevent `AttributeError`.

## Consequences

- **Fixed:** Hanging validation commands now fail after timeout instead of blocking forever.
- **Fixed:** Path traversal via malicious task IDs is no longer possible.
- **Fixed:** Empty `tasks.yaml` returns an empty task list instead of crashing.
- **Trade-off:** The 300s default timeout may be too short for very long test suites. Operators can override per-task with `validation_timeout`.
- **Trade-off:** The `^[A-Z]+-\d+$` regex is strict — task IDs like `my-task` or `task_1` are rejected. This matches the established convention (`TASK-001` through `TASK-006`) and prevents the entire class of injection attacks.
- **Test coverage:** 14 new tests cover timeout handling (including None output edge case), task ID validation (path traversal, empty, spaces, lowercase), corrupt input (invalid YAML, invalid JSON, empty YAML), and circular dependency behavior.
