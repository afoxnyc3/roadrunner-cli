# Roadrunner Configuration

This document covers the tunables that govern Roadrunner's control loop: iteration
counters, the runaway-protection cap, the state schema, and the migration contract
for downstream consumers that vendor `roadrunner.py`.

## Iteration Counters

Roadrunner tracks two iteration counters in `.roadmap_state.json`. They exist so
the runaway-protection cap does not accidentally become a lifetime ceiling on the
project as a whole.

| Counter             | Purpose                                           | Reset on                                  |
| ------------------- | ------------------------------------------------- | ----------------------------------------- |
| `iteration`         | Lifetime audit counter. Never gates behavior.     | `reset-iteration --hard` only             |
| `session_iteration` | Per-session runaway guard. Gates the Stop-hook cap. | Every `SessionStart` hook fire, plus `reset-iteration` (soft or hard) |

Both counters are incremented on every `check-stop` invocation (i.e., every time
Claude finishes a turn and the Stop hook fires). The cap is compared against
`session_iteration` only.

### Why Two Counters?

Before 2026-04-24, Roadrunner kept a single `iteration` counter and the cap fired
when that counter hit `max_iter`. Because the counter persisted across every
`claude` invocation for the same project, long-running projects (e.g., entra-triage
running periodically against production data) would accumulate iterations across
many sessions and eventually trip the cap even though no single run looped. The
split preserves the audit trail (`iteration`) while making the runaway guard
per-session (`session_iteration`). See `logs/ROAD-010.md` for the full history.

## Runaway-Protection Cap

The Stop hook enforces a maximum number of Claude turns per session.

**Default:** 100.

**Override (env var, per invocation):**

```bash
export ROADMAP_MAX_ITERATIONS=50   # tighter cap for a short run
```

The env var is read by `hooks/stop_hook.sh` and passed as `--max-iterations` to
`roadrunner.py check-stop`. The CLI itself defaults to 100 if the flag is absent.

**When the cap fires:** `check-stop` emits a hard halt with `stopReason` explaining
the cap was hit. The session terminates; Alex's next `claude` invocation starts
fresh at session iteration 0 (because `SessionStart` resets it).

## Resetting Iteration Counters

The `reset-iteration` subcommand provides manual control.

```bash
# Reset session counter only. Lifetime counter preserved.
python3 roadrunner.py reset-iteration --soft   # default if no flag

# Reset both counters. Destructive; loses lifetime audit trail.
python3 roadrunner.py reset-iteration --hard
```

Trace events (`reset_iteration`) record the mode and the prior lifetime counter
for every invocation, so `--hard` is recoverable via the trace log if needed.

## State Schema

`.roadmap_state.json` is versioned via `STATE_SCHEMA_VERSION`. Roadrunner's
forward-compat contract:

- **Older Roadrunner reading newer state:** refuses to run (`version > current`
  exits with an upgrade-required message). Prevents data loss from writes that
  drop fields the newer version added.
- **Newer Roadrunner reading older state:** migrates transparently. Missing fields
  are filled in via `setdefault` during `read_state`, then written back in the
  new schema on the next `write_state`.

### Schema v1 → v2 (ROAD-010, 2026-04-24)

Adds `session_iteration: int` field. Default for legacy state files: `0`. No
manual migration required; first load auto-fills.

## Downstream Consumers

`entra-triage` vendors `roadrunner.py` in-tree and syncs periodically. Because the
v1 → v2 migration is setdefault-based (not a hard schema check), vendored copies
pick up the new schema without coordination: the state file on disk migrates the
first time a post-sync `roadrunner.py` invocation runs.

If you fork or vendor this file elsewhere, follow the same contract:

1. Bump `STATE_SCHEMA_VERSION` when adding new state fields.
2. In `read_state`, put `data.setdefault(new_field, default)` after the JSON load
   so older state files migrate cleanly.
3. Keep the forward-compat gate (`version > STATE_SCHEMA_VERSION → exit`) intact
   so older binaries can't silently corrupt newer state.
