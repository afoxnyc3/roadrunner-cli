# Work Log: ROAD-003 — roadrunner analyze — tasks.yaml analysis and validation
**Completed:** 2026-04-23T13:14:41.481598+00:00
**Status:** done

## Goal
Add a new 'analyze' subcommand to roadrunner.py that reads tasks/tasks.yaml and
reports a health summary. Behaviour:
  python3 roadrunner.py analyze [--tasks-file PATH]
Reports:
  - Total tasks, done/todo/in_progress/blocked counts
  - Circular dependency detection (A depends on B depends on A)
  - Unreachable tasks (dependencies reference tasks that don't exist)
  - Tasks with no validation_commands (validation-free warning)
  - Estimated minimum linear path (critical path length)
Exits 1 if any critical errors found (circular deps, missing deps).
Exits 0 with warnings for non-critical issues (no validation commands).
--tasks-file PATH allows analyzing a tasks.yaml other than the default.


## Acceptance Criteria
- python3 roadrunner.py analyze exits 0 on the current tasks.yaml
- Circular dependency detected and reported as error (exit 1)
- Missing dependency reference detected and reported as error (exit 1)
- Tasks with no validation_commands reported as warnings (exit 0)
- --tasks-file flag accepts a custom path
- All existing tests continue to pass

## Validation (4/4 passed)

### ✅ `python3 roadrunner.py analyze --help`
```
usage: roadrunner.py analyze [-h] [--tasks-file TASKS_FILE]

options:
  -h, --help            show this help message and exit
  --tasks-file TASKS_FILE
                        Path to a tasks.yaml file (defaults to the project
                        tasks/tasks.yaml)
```

### ✅ `python3 roadrunner.py analyze`
```
Analyzed: /Users/alex/dev/projects/roadrunner-cli/tasks/tasks.yaml
Total tasks: 9
  done:        2
  todo:        6
  in_progress: 1
  blocked:     0
Critical path (longest dep chain): 3 tasks

✅ No issues found.
```

### ✅ `python3 -m pytest tests/ -q`
```
........................................................................ [ 70%]
..............................                                           [100%]
102 passed in 1.26s
```

### ✅ `ruff check roadrunner.py`
```
All checks passed!
```

## Notes
Added 'analyze' subcommand. Loads tasks.yaml (default TASKS_FILE or --tasks-file PATH) and reports: total + per-status counts (done/todo/in_progress/blocked/other), missing-dep references, circular deps via 3-color DFS (dedupes on sorted vertex set), validation_commands-free warnings, and longest dependency chain (critical path, computed only if acyclic). Exits 1 on any error (missing deps, cycles); exits 0 with warnings otherwise. Smoke-tested on current tasks.yaml (0 issues) plus synthetic fixtures for cycle, missing-dep, and no-validation cases — each branch took the expected path and exit code.