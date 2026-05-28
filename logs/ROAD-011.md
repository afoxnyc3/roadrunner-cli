# Work Log: ROAD-011 — Token / cost budget halt — ROADMAP_MAX_BUDGET_USD
**Completed:** 2026-05-28T01:08:12.073887+00:00
**Status:** done

## Goal
Roadrunner caps session iterations but not session cost; two tasks that each take
50 iterations can differ 10x in dollars depending on tool-use density and model
choice. Operators running overnight loops have no upper bound on cost.

Add a ROADMAP_MAX_BUDGET_USD env var (and matching --max-budget-usd flag on
'roadrunner check-stop'). Track per-session cost in .roadmap_state.json (new
field session_cost_usd, schema bump v2 -> v3). cmd_check_stop evaluates the
budget alongside the iteration cap and emits the same hard-halt JSON shape on
overrun. Surface current spend + budget in 'roadrunner status' and 'roadrunner
health'. Record a 'budget_exceeded' trace event on halt.

Cost data comes from Claude Code's per-turn session metadata; if the data isn't
surfaced reliably, gate the feature behind a config flag that defaults off and
emits a one-time warning rather than breaking the loop.


## Acceptance Criteria
- ROADMAP_MAX_BUDGET_USD env var honored by check-stop
- --max-budget-usd flag on check-stop overrides the env var
- .roadmap_state.json schema bumped to v3 with session_cost_usd field
- Schema migration v2 -> v3 fills session_cost_usd with 0.0 for existing state files
- Budget overrun returns {"continue": false, "stopReason": "..."} — same hard-halt shape as the iteration cap
- roadrunner status and roadrunner health surface current spend + budget
- Trace event budget_exceeded recorded on halt
- If per-turn cost data is unavailable, feature gracefully no-ops with a one-time warning
- tests/test_roadrunner.py::TestCheckStop covers the budget-halt path
- docs/configuration.md documents the new env var and state field
- All existing tests continue to pass
- ruff check and mypy pass

## Validation (8/8 passed)

### ✅ `python3 -m roadrunner check-stop --help`
```
usage: __main__.py check-stop [-h] [--max-iterations MAX_ITERATIONS]
                              [--max-attempts MAX_ATTEMPTS]
                              [--max-budget-usd MAX_BUDGET_USD]

options:
  -h, --help            show this help message and exit
  --max-iterations MAX_ITERATIONS
  --max-attempts MAX_ATTEMPTS
  --max-budget-usd MAX_BUDGET_USD
                        Per-session USD budget cap. Halts the loop with a hard
                        stop when the running session cost meets
```

### ✅ `grep -qE "ROADMAP_MAX_BUDGET_USD|max_budget_usd" src/roadrunner/cli.py src/roadrunner/state.py`

### ✅ `grep -q "session_cost_usd" src/roadrunner/state.py`

### ✅ `grep -q "STATE_SCHEMA_VERSION = 3" src/roadrunner/state.py`

### ✅ `grep -q "ROADMAP_MAX_BUDGET_USD" docs/configuration.md`

### ✅ `python3 -m pytest tests/ -q`
```
........................................................................ [ 38%]
........................................................................ [ 77%]
...........................................                              [100%]
187 passed in 6.55s
```

### ✅ `ruff check src/roadrunner tests/ hooks/`
```
All checks passed!
```

### ✅ `python3 -m mypy src/roadrunner --ignore-missing-imports`
```
Success: no issues found in 5 source files
```

## Notes
Schema v3 with session_cost_usd; --max-budget-usd flag + ROADMAP_MAX_BUDGET_USD env var with flag precedence; budget_exceeded trace + hard-halt JSON shape; one-time stderr warning when payload lacks cost; session_cost reset on SessionStart and reset-iteration; status/health surface spend; 9 new tests, 187 total passing, ruff + mypy clean.