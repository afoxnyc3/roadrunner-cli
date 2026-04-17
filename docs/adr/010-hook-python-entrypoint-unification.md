# ADR-010: Hook → Python Entry Point Unification

**Status:** Accepted
**Date:** 2026-04-17
**Deciders:** Alex, Claude Opus 4.7

## Context

The project historically grew two different patterns for how a bash hook delegated to Python:

- **`hooks/precompact_hook.sh`** called `python3 "$PROJECT_ROOT/roadrunner.py" snapshot` — one subcommand dispatched from the main CLI module.
- **`hooks/session_start_hook.sh`** called a small dedicated helper, `hooks/_session_start.py`, which read `.context_snapshot.json` and emitted the `hookSpecificOutput` JSON.

Both patterns worked. The second-pass audit (Opus 4.7, 2026-04-16) flagged the inconsistency as a nit (N4) — two ways to do the same thing makes the codebase harder to learn than necessary. Every new reader has to figure out *why* one hook reaches into `roadrunner.py` and the other reaches into a sibling file.

Other operational differences between the two patterns:

- The dedicated helper had its own import path and exception-handling discipline that could drift from `roadrunner.py`'s (e.g. `ensure_ascii=False` had to be fixed in two places during M4).
- The helper was not covered by the module-level TypedDicts or Tunables block, so any schema change to the snapshot had to be propagated twice.
- Testing wanted both files copied into tmp projects, doubling the surface area of the integration tests.

## Decision

Promote the helper's logic into a `cmd_session_start` subcommand on `roadrunner.py` and delete `hooks/_session_start.py`.

- New subcommand `python3 roadrunner.py session-start` reads `.context_snapshot.json` and emits the same `hookSpecificOutput` JSON as before. Silent no-op when the snapshot is missing or corrupt.
- `hooks/session_start_hook.sh` becomes a one-liner that mirrors `precompact_hook.sh`: derive `PROJECT_ROOT` from `BASH_SOURCE`, call `python3 "$PROJECT_ROOT/roadrunner.py" session-start`.
- `hooks/_session_start.py` is removed from the repo.

## Alternatives considered

- **Move `cmd_snapshot`'s logic out of `roadrunner.py` into a new `hooks/_precompact.py`** — inverse of the chosen direction. Rejected because it would scatter Python logic across multiple files and prevent reuse of `load_tasks`, `read_state`, `write_context_snapshot` without re-importing `roadrunner` anyway.
- **Leave the two patterns alone.** Documented as intentional at the time — but re-examined: the helper had no real justification beyond historical accident. Unifying costs ~30 lines and removes one file.
- **Extract a shared `hooks/_common.py`.** Overkill for the amount of logic involved.

## Consequences

- All Python logic invoked by hooks now lives in `roadrunner.py`. One file to read, one import graph to maintain, one set of Tunables and TypedDicts to keep current.
- The `session-start` subcommand is operator-invokable (`python3 roadrunner.py session-start`) for debugging — same ergonomics as `snapshot`, `health`, `status`.
- Existing `tests/test_hooks.py::TestSessionStartHook` keeps working with the new pattern; test staging now copies `roadrunner.py` into the tmp root instead of `_session_start.py`.
- New direct tests in `tests/test_roadrunner.py::TestSessionStart` cover the three paths (no snapshot, valid snapshot, corrupt snapshot) without needing a bash subprocess.

## Test coverage

- `TestSessionStart::test_session_start_without_snapshot_is_silent`
- `TestSessionStart::test_session_start_with_snapshot_emits_additional_context`
- `TestSessionStart::test_session_start_with_corrupt_snapshot_is_silent`
- `TestSessionStartHook::test_with_snapshot` (existing, unchanged)
- `TestSessionStartHook::test_without_snapshot` (updated to stage `roadrunner.py` into tmp)

## References

- Claude Code hooks reference: <https://code.claude.com/docs/en/hooks.md>
- Implementation commit: this ADR.
