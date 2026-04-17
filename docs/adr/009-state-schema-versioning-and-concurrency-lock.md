# ADR-009: State Schema Versioning and Concurrency Lock

**Status:** Accepted
**Date:** 2026-04-17
**Deciders:** Alex, Claude Opus 4.7

## Context

A second-pass audit (Opus 4.7, 2026-04-16) identified two correctness gaps in the state-management layer:

1. **No schema version on `.roadmap_state.json` / `.context_snapshot.json`.** If the shape of either file changes in a future release — adding, renaming, or retyping a field — `read_state()` has no way to distinguish a current-format file from a newer one. A downgrade that read a newer file would silently corrupt it on the next write.

2. **No lock around the read→increment→write span in `cmd_check_stop`.** The function reads `.roadmap_state.json`, increments the iteration counter, optionally increments the per-task attempt counter, and writes back. Two concurrent Stop-hook fires can interleave the two reads and two writes so that one increment is lost. The project is documented single-operator, but "documented" is not "enforced"; a single Claude Code session running with parallel tool calls is all it takes for the race to become reachable.

Both issues are "won't bite today, could silently bite tomorrow." Either one costs a few lines of code to close.

## Decision

### Schema versioning

- Add module-level constants `STATE_SCHEMA_VERSION = 1` and `SNAPSHOT_SCHEMA_VERSION = 1` to `roadrunner.py` (Tunables section).
- `write_state()` and `write_context_snapshot()` always emit `"schema_version": <N>` as the first field of their JSON output.
- `read_state()` interprets the field with these rules:
  - **Missing** → treat as v1 (backward compatible with legacy files from before this ADR).
  - **Equal to `STATE_SCHEMA_VERSION`** → normal path.
  - **Greater than `STATE_SCHEMA_VERSION`** → `sys.exit(2)` with an operator-facing message pointing at the specific file and suggesting upgrade / manual migration. Crucially, the on-disk file is **not** overwritten, so an accidental downgrade does not destroy forward-compat state.

### Concurrency lock

- Add a `@contextmanager` helper `_exclusive_state_lock()` backed by `fcntl.flock(LOCK_EX)` on a sibling `.roadmap_state.lock` file.
- The lockfile is separate from the state file itself because `os.replace(tmp, STATE_FILE)` during `write_state` would invalidate any fd held on `STATE_FILE`.
- `cmd_check_stop` wraps the entire body after the `stop_hook_active` guard in the context manager. `SystemExit` from any `sys.exit(...)` still runs `finally` and releases the lock.
- On Windows (`fcntl` unavailable) the helper is a no-op — Windows is explicitly not a target platform per DESIGN.md, but the module must remain importable there for `pip install`-time setup.

## Alternatives considered

- **SQLite-backed state:** would give locking, schemas, and migrations for free — but introduces a real dependency and breaks the "copy three files into another project" install story. Out of proportion for the problem.
- **Lock the state file directly:** rejected because `os.replace` invalidates held locks on the original inode.
- **Migration-on-read for newer files:** deferred. Today there are no v2/v3 migrations to define. When a format change lands, the migration lives alongside the bump.
- **Schema check that returns defaults instead of exiting:** the read could warn-and-default, but the caller then writes v1 and overwrites the forward-compat file. Exiting is louder and strictly safer.

## Consequences

- Any state file or snapshot written by a post-ADR-009 roadrunner is readable by any later version that preserves backward compatibility.
- A future roadrunner that bumps `STATE_SCHEMA_VERSION = 2` can ship migration logic with confidence that older files are detectable and newer files are protected.
- Concurrent Stop-hook fires now serialize at the flock boundary instead of racing on the state JSON. Single-operator semantics are now enforced, not just documented.
- Adds `.roadmap_state.lock` to the set of session-local runtime files (gitignored).

## Test coverage

- `TestStateSchemaVersion::test_write_includes_schema_version`
- `TestStateSchemaVersion::test_legacy_state_without_version_reads_as_v1`
- `TestStateSchemaVersion::test_future_schema_version_exits_and_preserves_file`
- `TestStateSchemaVersion::test_snapshot_includes_schema_version`
- `TestCheckStopLock::test_lock_serializes_concurrent_increments` (two-thread race under `threading.Barrier`)

## References

- Schema evolution best-practices reading: oneuptime.com "How to Fix Schema Evolution Issues" (2026-01); conduktor.io "Schema Evolution Best Practices" (2026-04).
- Python `fcntl` stdlib documentation for POSIX advisory locking.
- Implementation commit: `7ea3f06`.
