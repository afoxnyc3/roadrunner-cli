# Work Log: ROAD-006 — CONTRIBUTING.md and configuration reference
**Completed:** 2026-04-25T02:26:42.946394+00:00
**Status:** done

## Goal
Write two documents:

1. CONTRIBUTING.md at the project root covering:
   - Dev environment setup (pip install -e .[dev] or requirements.txt)
   - Running tests (pytest tests/ -v)
   - Running lint (ruff check roadrunner.py tests/ hooks/)
   - Running the full CI gate locally (just ci)
   - PR workflow: branch naming, commit style, what reviewers look for
   - How to write a new roadrunner subcommand (add to dispatch dict + argparse)
   - How to write a new hook (register in settings.json + delegate to Python)

2. docs/configuration.md covering every tunable in roadrunner.py:
   - All tunables at the top of roadrunner.py: DEFAULT_VALIDATION_TIMEOUT,
     MAX_TASK_ATTEMPTS, TASKS_BACKUP_KEEP, LOG_ROTATE_BYTES, LOG_RETAIN_DAYS,
     STATE_SCHEMA_VERSION, SNAPSHOT_SCHEMA_VERSION
   - ROADMAP_MAX_ITERATIONS env var (passed as --max-iterations to check-stop)
   - Full tasks.yaml field reference (all fields, types, required vs optional)
   - State file schemas: .roadmap_state.json and .context_snapshot.json


## Acceptance Criteria
- CONTRIBUTING.md exists at project root
- CONTRIBUTING.md has dev setup, test, lint, and new-command sections
- docs/configuration.md exists
- docs/configuration.md documents all tunables and the tasks.yaml schema
- docs/configuration.md mentions MAX_TASK_ATTEMPTS and DEFAULT_VALIDATION_TIMEOUT
- All existing tests continue to pass

## Validation (5/5 passed)

### ✅ `test -f CONTRIBUTING.md`

### ✅ `test -f docs/configuration.md`

### ✅ `grep -q "MAX_TASK_ATTEMPTS" docs/configuration.md`

### ✅ `grep -q "DEFAULT_VALIDATION_TIMEOUT" docs/configuration.md`

### ✅ `python3 -m pytest tests/ -q`
```
........................................................................ [ 50%]
.......................................................................  [100%]
143 passed in 3.37s
```

## Notes
Added CONTRIBUTING.md at project root covering dev setup (editable pip + requirements.txt), running tests/lint/CI-gate, PR workflow (branch naming, Conventional Commits, reviewer expectations), and two recipes: adding a roadrunner subcommand (argparse + dispatch) and adding a hook (bash wrapper + settings.json + Python handler). Extended docs/configuration.md with a Tunables table covering every module-level knob (DEFAULT_VALIDATION_TIMEOUT, MAX_TASK_ATTEMPTS, TASKS_BACKUP_KEEP, LOG_ROTATE_BYTES, LOG_RETAIN_DAYS, STATE_SCHEMA_VERSION, SNAPSHOT_SCHEMA_VERSION), env vars (ROADMAP_MAX_ITERATIONS, CLAUDE_PROJECT_DIR), a full tasks.yaml field reference (required vs optional, types, defaults), and both state schemas (.roadmap_state.json v2 and .context_snapshot.json v1).