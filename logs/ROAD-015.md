# Work Log: ROAD-015 — Project-wide baseline validation suite
**Completed:** 2026-05-28T11:56:47.764757+00:00
**Status:** done

## Goal
Per-task validation_commands let each task drift from CI's gate. The
2026-05-28 incident (mypy src/roadrunner vs CI's mypy src tests) shipped two red
CI runs in a row because no runtime enforcement keeps the loop's gate aligned
with CI's. CLAUDE.md conventions are suggestion-only; only the code path is
deterministic.

Add an optional top-level baseline_validation list[str] field to tasks.yaml.
cmd_validate prepends those commands before each task's validation_commands,
with first-failure short-circuit and a clear distinction in the failure report
between baseline failures and task-specific failures. When baseline_validation
is absent or empty, behavior is unchanged (backward compat for v1.0 projects).

This project sets baseline_validation to the three CI commands so the loop's
validate gate is structurally equal to CI. The feature is language-agnostic by
design: a TypeScript project sets npm test, eslint, npx tsc --noEmit; the
runtime treats them as opaque shell commands.


## Acceptance Criteria
- tasks.yaml can declare a top-level baseline_validation list-of-strings field
- cmd_validate runs every baseline command before the task's validation_commands
- First baseline failure short-circuits the rest of validation (same exit semantics as per-task)
- Validation output distinguishes baseline failures from task-specific failures
- When baseline_validation is absent or empty, behavior is unchanged (backward compat)
- This project's tasks.yaml has baseline_validation set to the three CI commands (pytest, ruff, mypy)
- docs/configuration.md documents the new field with a language-agnostic note and a TypeScript example
- tests/test_roadrunner.py adds a TestBaselineValidation class covering on/off/short-circuit/error-shape
- All existing tests continue to pass
- ruff check src/ hooks/ tests/ passes
- python3 -m mypy src tests --ignore-missing-imports passes

## Validation (10/10 passed)

### ✅ `python3 -m pytest tests/ -q`
```
........................................................................ [ 30%]
........................................................................ [ 61%]
........................................................................ [ 91%]
....................                                                     [100%]
236 passed in 7.22s
```

### ✅ `ruff check src/ hooks/ tests/`
```
All checks passed!
```

### ✅ `python3 -m mypy src tests --ignore-missing-imports`
```
Success: no issues found in 11 source files
```

### ✅ `grep -q "baseline_validation" src/roadrunner/cli.py`

### ✅ `grep -q "baseline_validation" docs/configuration.md`

### ✅ `grep -q "^baseline_validation:" tasks/tasks.yaml`

### ✅ `python3 -m pytest tests/ -q -k "baseline_validation"`
```
......                                                                   [100%]
6 passed, 230 deselected in 0.07s
```

### ✅ `python3 -m pytest tests/ -q`
```
........................................................................ [ 30%]
........................................................................ [ 61%]
........................................................................ [ 91%]
....................                                                     [100%]
236 passed in 7.17s
```

### ✅ `ruff check src/ hooks/ tests/`
```
All checks passed!
```

### ✅ `python3 -m mypy src tests --ignore-missing-imports`
```
Success: no issues found in 11 source files
```

## Notes
Top-level baseline_validation list[str] in tasks.yaml gates every task before its own validation_commands; short-circuits on first failure; task phase continues-on-failure (preserves pre-ROAD-015 UX); ValidationResult gains phase field; cmd_validate renders baseline/task blocks separately; trace events carry phase and per-phase pass booleans. This project's tasks.yaml sets baseline to the three CI commands — local↔CI parity is now structural. Language-agnostic (TS example documented). 10 new tests, 236 total passing, ruff + mypy clean. Backward-compat preserved.