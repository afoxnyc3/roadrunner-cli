# Work Log: ROAD-010 — Per-session iteration counter with reset on SessionStart
**Completed:** 2026-04-24T16:37:05.409843+00:00
**Status:** done

## Goal
Split the iteration counter into two values so the runaway-protection cap becomes
per-session instead of lifetime-cumulative. Bug observed 2026-04-24: iteration hit
92 against max_iter=50 because every Stop-hook fire incremented and persisted the
counter across all `claude` invocations, making the cap a lifetime ceiling rather
than a per-run runaway guard.

Changes:
- Keep `iteration` in `.roadmap_state.json` as the lifetime audit counter (preserves
  existing traces and backward compat).
- Add `session_iteration` (int, default 0) to `RoadmapState` TypedDict. Reset to 0 in
  `cmd_session_start`.
- Gate the max-iterations check in `cmd_check_stop` on `session_iteration`, not
  `iteration`. Raise DEFAULT session cap from 50 → 100.
- Add `reset-iteration [--soft|--hard]` subcommand. `--soft` resets `session_iteration`;
  `--hard` zeros both.
- Surface both counters in `cmd_status` output and in `_build_task_brief`.
- Bump `STATE_SCHEMA_VERSION` and add a migration that defaults `session_iteration=0`
  for state files written by older versions.

## Acceptance Criteria
- RoadmapState TypedDict has both `iteration` and `session_iteration` fields
- `cmd_session_start` resets `session_iteration` to 0 while preserving `iteration`
- `cmd_check_stop` compares `session_iteration` (not `iteration`) against `max_iter`
- Default `max_iter` passed by check_stop hook is 100 (was 50)
- `reset-iteration --soft` resets `session_iteration` only
- `reset-iteration --hard` resets both counters
- `cmd_status` output shows both counters with clear labels
- State files without `session_iteration` load cleanly (treated as 0)
- `STATE_SCHEMA_VERSION` bumped
- All existing tests continue to pass
- `ruff check` and `mypy` pass

## Validation (5/5 passed)

### ✅ `python3 roadrunner.py reset-iteration --help`
```
usage: roadrunner.py reset-iteration [-h] [--soft | --hard]

options:
  -h, --help  show this help message and exit
  --soft      Reset session_iteration only; preserve lifetime counter
              (default).
  --hard      Reset both session_iteration and lifetime iteration.
              Destructive.
```

### ✅ `python3 -m pytest tests/ -q`
```
........................................................................ [ 50%]
.......................................................................  [100%]
143 passed in 3.10s
```

### ✅ `ruff check roadrunner.py tests/ hooks/`
```
All checks passed!
```

### ✅ `python3 -m mypy roadrunner.py --ignore-missing-imports`
```
Success: no issues found in 1 source file
```

### ✅ `grep -q "session_iteration" roadrunner.py`
(29 occurrences across the module — TypedDict field, read/write_state, check_stop,
session_start, reset_iteration, status, trace events.)

## Notes
Implementation landed as hand-over-hand code (Branch B in the recommendation tree)
rather than running through the loop itself, because the loop's runaway-guard bug
was the thing being fixed. Running the bugged loop to fix itself would have been a
bootstrap hazard.

Structural split:

1. **State schema (v1 → v2).** `RoadmapState` TypedDict gains `session_iteration: int`.
   `STATE_SCHEMA_VERSION` bumped to 2. `read_state` sets `session_iteration=0` on
   the default dict *and* calls `data.setdefault("session_iteration", 0)` on loaded
   state, so any v1 file (including entra-triage's vendored copy) migrates
   transparently on first load. Forward-compat guard (`version > current → exit 2`)
   is unchanged.

2. **`write_state` preservation.** New kwarg `session_iteration: int | None = None`.
   When callers pass `None` (the default for cmd_start/cmd_complete/cmd_block/cmd_reset,
   which don't own the runaway counter), `write_state` re-reads the on-disk value and
   preserves it. Explicit callers — cmd_check_stop, cmd_session_start,
   cmd_reset_iteration — pass the intended value. This kept the change surface local;
   unrelated callers did not need to thread the new field through.

3. **Cap moved to session counter.** `cmd_check_stop` now increments both
   `iteration` (lifetime audit) and `session_iteration` (runaway guard), persists
   both, and gates the cap check on `session_iteration`. Default `max_iter` raised
   50 → 100 at both layers: the `argparse` default in roadrunner.py and the
   `ROADMAP_MAX_ITERATIONS:-100` fallback in `hooks/stop_hook.sh`. `_build_task_brief`
   now receives `session_iteration` in the "iteration N/M" line because that is the
   counter the loop cares about operationally; lifetime is audit-only.

4. **SessionStart resets.** `cmd_session_start` opens an exclusive state lock, reads
   current state, writes it back with `session_iteration=0` (lifetime preserved),
   and emits a `session_start_reset` trace event. This happens on every
   SessionStart hook fire, so each fresh `claude` invocation starts at 0/100.

5. **reset-iteration subcommand.** Mutually exclusive `--soft` / `--hard` group.
   Default is `--soft` (reset session only). `--hard` zeros both. Trace events
   include the mode and prior lifetime counter for audit. Useful when an operator
   wants to reset manually without firing a full SessionStart.

6. **Status.** `cmd_status` now prints `Iteration (session): N` and
   `Iteration (lifetime): M` as two separate lines so Alex can tell at a glance
   whether a runaway is imminent vs. whether the project has just accrued a lot
   of cycles.

Tests: 143 passing. Added a new `TestSessionIteration` class (~18 cases) covering
schema v2, TypedDict shape, default values, legacy v1 load, write/read preservation,
cap-on-session-not-lifetime, default-100 behavior, SessionStart reset preserving
lifetime, reset-iteration soft/hard modes, trace event emission, status output,
and the hooks/stop_hook.sh default. Two pre-existing tests
(`test_read_state_invalid_json`, `test_read_state_not_a_dict_falls_back`) updated
because they asserted exact-shape default dicts — now include `session_iteration: 0`.
The runaway-cap test was updated to seed `session_iteration=49` (was `iteration=49`).

Entra-triage coordination: none required. entra-triage vendors roadrunner.py and
syncs on its own cadence; because `read_state` uses setdefault on load, the v1
state file on disk there will migrate silently on the next `claude` invocation after
sync. Documented in docs/configuration.md.

Not touched: entra-triage itself, pyproject packaging, CI workflow (existing mypy +
ruff + pytest jobs cover this change without modification).
