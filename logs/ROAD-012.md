# Work Log: ROAD-012 — Per-task model selection
**Completed:** 2026-05-28T02:04:14.899383+00:00
**Status:** done

## Goal
Some tasks ('rename a variable across 12 files') deserve Haiku; others ('design
and implement the schema migration') deserve Opus. Today Roadrunner relies on the
operator setting 'claude --model' globally; there is no way to vary by task.

Add an optional 'model:' field (free-form string) to the tasks.yaml schema.
Validate against known model IDs at load time with a WARNING rather than an error
so the schema stays forward-compatible. Surface the chosen model in 'roadrunner
status' and in the resume / next-task brief written by the Stop hook so the agent
knows it was downshifted or upshifted. Include the field in every check_stop
trace.jsonl event for the active task so future analysis can correlate model
choice to outcome. Extend 'roadrunner analyze' to report task count by model.

This is documentation + telemetry; it does not change the runtime. Operators
who want to enforce the choice wrap 'claude' in a script that reads the field.


## Acceptance Criteria
- Optional model field added to the tasks.yaml schema in docs/configuration.md
- Field surfaced in roadrunner status and the resume / next-task brief
- trace.jsonl check_stop events include the model field on the active task
- roadrunner analyze reports task count grouped by model
- Schema validator warns (not errors) on unknown model IDs
- Unit test test_tasks_yaml_model_field covers parsing and brief rendering
- All existing tests continue to pass
- ruff check and mypy pass

## Validation (6/6 passed)

### ✅ `grep -q "^### .*model\|^| .model" docs/configuration.md || grep -q "model" docs/configuration.md`

### ✅ `python3 -m roadrunner analyze`
```
Analyzed: /Users/alex/dev/roadrunner-cli/tasks/tasks.yaml
Total tasks: 14
  done:        11
  todo:        2
  in_progress: 1
  blocked:     0
Critical path (longest dep chain): 3 tasks

✅ No issues found.
```

### ✅ `python3 -m pytest tests/ -q -k "model_field or tasks_yaml"`
```
..                                                                       [100%]
2 passed, 200 deselected in 0.04s
```

### ✅ `python3 -m pytest tests/ -q`
```
........................................................................ [ 35%]
........................................................................ [ 71%]
..........................................................               [100%]
202 passed in 6.70s
```

### ✅ `ruff check src/roadrunner tests/`
```
All checks passed!
```

### ✅ `python3 -m mypy src/roadrunner --ignore-missing-imports`
```
Success: no issues found in 5 source files
```

## Notes
Optional 'model:' field on tasks.yaml: type-strict validator with permissive value list (unknown IDs warn once, never error); surfaced in status, next, _build_task_brief, check_stop trace (null when unset), and cmd_analyze ('Tasks by model:' section, suppressed at zero). 15 new tests (test_*model_field*), 202 total passing, ruff + mypy clean. Runtime routing intentionally out of scope per acceptance criteria.