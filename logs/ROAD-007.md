# Work Log: ROAD-007 — roadrunner watch — live run monitor
**Completed:** 2026-04-25T02:35:50.729701+00:00
**Status:** done

## Goal
Add a 'watch' subcommand that provides a live status view during an overnight run.
Behaviour:
  python3 roadrunner.py watch [--interval N]
Polls .roadmap_state.json and tasks/tasks.yaml every N seconds (default 5).
Clears terminal and prints:
  - Current iteration and max
  - Active task (if any) with attempt count
  - Task status summary (done/in_progress/todo/blocked counts)
  - Last 5 trace events from logs/trace.jsonl (event type, task_id, timestamp)
  - Time elapsed since first trace event
Exits cleanly on Ctrl-C (KeyboardInterrupt).
Does NOT require a live Claude session — reads from disk state only.
Falls back gracefully when trace.jsonl is empty or state file is missing.


## Acceptance Criteria
- python3 roadrunner.py watch --help exits 0
- python3 roadrunner.py watch --interval 1 runs for 2 seconds without crashing
- Output includes iteration count and task summary
- KeyboardInterrupt exits cleanly with exit code 0
- No new external dependencies required
- All existing tests continue to pass

## Validation (3/3 passed)

### ✅ `python3 roadrunner.py watch --help`
```
usage: roadrunner.py watch [-h] [--interval INTERVAL]

options:
  -h, --help           show this help message and exit
  --interval INTERVAL  Seconds between frames (floored at 0.5). Default: 5.
```

### ✅ `python3 -m pytest tests/ -q`
```
........................................................................ [ 48%]
........................................................................ [ 96%]
......                                                                   [100%]
150 passed in 5.44s
```

### ✅ `ruff check roadrunner.py`
```
All checks passed!
```

## Notes
Added 'roadrunner watch' subcommand: read-only live monitor that polls .roadmap_state.json, tasks/tasks.yaml, and logs/trace.jsonl on a fixed interval (default 5s, floored at 0.5s) and redraws a status frame showing session/lifetime iteration, max-iter cap (from ROADMAP_MAX_ITERATIONS), elapsed time since first trace event, active task with attempt count, next eligible, status counts, and last 5 trace events. ANSI clear (no curses), stdlib only (added 'time' and 'collections.deque'), Ctrl-C exits 0. Pure helpers _tail_trace_events / _trace_start_ts / _format_elapsed / _render_watch_frame are unit-tested; subprocess test confirms clean SIGINT exit. 7 new tests, 150 total passing.