# ADR-004: Atomic File Writes for State Integrity

**Status:** Accepted
**Date:** 2026-04-16
**Deciders:** Alex, Claude Opus 4.6

## Context

`save_tasks()` opened `tasks.yaml` for writing (truncating it), then wrote the new YAML content. A `SIGINT` or crash between truncation and write completion would leave the file empty or partially written, corrupting the task queue with no recovery path. For overnight unattended runs, this is an unacceptable data loss risk.

## Decision

Write to a temporary file (`tasks.yaml.tmp`), `fsync` the file descriptor, then atomically replace the original via `os.replace()`. On POSIX systems, `os.replace` is an atomic rename — the file is either fully old or fully new, never partial.

```python
tmp_path = TASKS_FILE.with_suffix(TASKS_FILE.suffix + ".tmp")
with open(tmp_path, "w") as f:
    yaml.dump(data, f, ...)
    f.flush()
    os.fsync(f.fileno())
os.replace(tmp_path, TASKS_FILE)
```

## Consequences

- **Fixed:** SIGINT mid-write can no longer corrupt the task queue.
- **Trade-off:** Slightly more disk I/O (write + rename vs. write in place). Negligible for a file under 10KB.
- **Not addressed:** `.roadmap_state.json` still uses `write_text()` directly. Acceptable because state is reconstructible (re-read tasks.yaml + infer iteration), whereas tasks.yaml is the source of truth and not reconstructible.
