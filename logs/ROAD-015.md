# Work Log: ROAD-015 — Project-wide baseline validation suite

## Why this lands

Per-task `validation_commands` let each task drift from CI's gate. The 2026-05-28
incident (`mypy src/roadrunner` locally vs CI's `mypy src tests`) shipped two
consecutive red CI runs because no runtime enforcement keeps the loop's gate
aligned with CI's. CLAUDE.md conventions are read-once-then-drift —
suggestion-only — so the gap could only be closed in code.

ROAD-015 moves "local equals CI" from convention into the validator itself.

## Design decisions

- **Two-phase model.** Baseline runs first, short-circuits on first failure;
  task phase runs only if baseline passed, but continues on failure within
  itself (preserves pre-ROAD-015 "see every task issue at once" UX).
- **`phase` field on `ValidationResult`.** Lets renderers and trace consumers
  attribute failures correctly. Cheap, structural, two-value enum.
- **Language-agnostic by construction.** The runtime treats commands as opaque
  shell invocations. Nothing in `run_validation` assumes Python. A TypeScript
  project sets `npm test` / `eslint` / `tsc --noEmit` and the same machinery
  works. This is the right altitude — roadrunner orchestrates, doesn't assume.
- **No escape hatch.** No `skip_baseline: true` task field. Each opt-out is a
  drift surface; the whole point of the feature is deterministic enforcement.
  Add the field later if a real use case shows up.

## Implementation

- `tasks.yaml` schema: optional top-level `baseline_validation: list[str]`.
- `get_baseline_validation()` reads it via the existing `load_project_config()`
  helper. Defensive parsing — non-list / non-string / empty entries return `[]`
  so a typo degrades to "fewer baseline checks," never a wedged loop.
- `run_validation` rewritten to two-phase with short-circuit + phase tagging.
- `cmd_validate` output renders `── baseline ──` and `── task ──` blocks
  separately; prints "Baseline failed — task-specific commands were not run."
  between them when applicable.
- Trace events: `validation_command` carries `phase`; `validation_complete`
  carries `baseline_passed` + `task_passed` booleans for attribution.
- This project's `tasks.yaml` now sets `baseline_validation` to the three CI
  commands. Loop ⇔ CI parity is structural going forward.

## Dogfood

`roadrunner validate ROAD-015` ran 3 baseline + 7 task = 10 ✅ — proves the
feature is live and the task's own `validation_commands` stand alone even
before the baseline mechanism was wired up (the task is self-validating
either way).

## Backward compatibility

Absent / empty / malformed `baseline_validation` → `get_baseline_validation()`
returns `[]` and `run_validation` behaves as pre-ROAD-015. Existing v1.0
projects pick this up with zero migration effort.

## Tests

`TestBaselineValidation` covers: backward compat (absent/non-list/malformed),
happy path (list passes through), defensive parsing, baseline-runs-before-task
ordering, short-circuit on first baseline failure, task continue-on-failure
preserved, empty/empty → no-op, baseline-only configuration, trace `phase` +
per-phase pass booleans. 10 cases.

## Follow-ups

- The auto-generated work log was overwriting hand-authored prose (this log
  was one of the casualties). Fixed in a follow-up commit on `main` —
  `write_work_log` now preserves content above a `WORK_LOG_MARKER` and only
  replaces the auto-generated section below it, idempotently across repeated
  `complete`/`block` invocations.
