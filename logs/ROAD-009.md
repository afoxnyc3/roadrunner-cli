# Work Log: ROAD-009 — End-to-end worked example project
**Completed:** 2026-04-25T13:21:18.087454+00:00
**Status:** done

## Goal
Create a small but complete worked example in docs/examples/hello-roadrunner/
that demonstrates the full roadrunner workflow for a new user.

The example project is a trivial Python utility (e.g. a word counter CLI) with
3 tasks that a user can actually run to see the loop in action:
  DEMO-001: Create word_counter.py with a count_words(text) function
  DEMO-002: Add a CLI entry point (if __name__ == '__main__')
  DEMO-003: Add pytest tests and verify they pass

The example directory should contain:
  - tasks/tasks.yaml (the 3-task demo roadmap)
  - CLAUDE.md (minimal template showing the operating contract)
  - README.md (step-by-step: install roadrunner, copy init, run claude)

The example MUST be self-contained — someone should be able to:
  python3 roadrunner.py init docs/examples/hello-roadrunner/ (or copy manually)
  then run 'claude' from that directory and see the loop complete DEMO-001-003

The tasks.yaml in the example must pass python3 roadrunner.py analyze when
run against it.


## Acceptance Criteria
- docs/examples/hello-roadrunner/ directory exists
- docs/examples/hello-roadrunner/tasks/tasks.yaml exists with DEMO-001/002/003
- docs/examples/hello-roadrunner/CLAUDE.md exists
- docs/examples/hello-roadrunner/README.md exists
- python3 roadrunner.py analyze --tasks-file docs/examples/hello-roadrunner/tasks/tasks.yaml exits 0
- Example README explains the full workflow in under 30 lines

## Validation (5/5 passed)

### ✅ `test -d docs/examples/hello-roadrunner`

### ✅ `test -f docs/examples/hello-roadrunner/tasks/tasks.yaml`

### ✅ `test -f docs/examples/hello-roadrunner/README.md`

### ✅ `python3 roadrunner.py analyze --tasks-file docs/examples/hello-roadrunner/tasks/tasks.yaml`
```
Analyzed: /Users/alex/dev/projects/roadrunner-cli/docs/examples/hello-roadrunner/tasks/tasks.yaml
Total tasks: 3
  done:        0
  todo:        3
  in_progress: 0
  blocked:     0
Critical path (longest dep chain): 3 tasks

✅ No issues found.
```

### ✅ `python3 -m pytest tests/ -q`
```
........................................................................ [ 48%]
........................................................................ [ 96%]
......                                                                   [100%]
150 passed in 5.44s
```

## Notes
Added docs/examples/hello-roadrunner/ as a self-contained 3-task demo. tasks/tasks.yaml defines DEMO-001 (count_words function), DEMO-002 (CLI entry point depending on DEMO-001), and DEMO-003 (pytest tests depending on DEMO-002). Each demo task has real validation_commands (file existence, behavioral assertions via python3 -c, pytest) so analyze emits no warnings — passes 'No issues found'. CLAUDE.md is a minimal operating-contract template: per-cycle steps, completion sentinel, file scope, validation-as-gate. README.md walks through copy → roadrunner init → status/analyze → claude in 27 lines (under the 30-line acceptance cap). Uses the published 'pip install roadrunner-cli' + 'roadrunner init' path that ROAD-001/002/008 enable. All 5 task validators pass; full pytest suite still 150/150.