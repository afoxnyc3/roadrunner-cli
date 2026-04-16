# ADR-002: Check-Stop In-Progress Task Awareness

**Status:** Accepted
**Date:** 2026-04-16
**Deciders:** Alex, Claude Opus 4.6

## Context

`cmd_check_stop` determined whether work remained by calling `next_eligible_task()`, which only returns tasks with `status == "todo"`. After `cmd_start`, the active task transitions to `in_progress` — making it invisible to the eligibility check. If Claude responded before calling `complete` (e.g., to ask a question, or on context overflow), `check-stop` would declare "All tasks complete" and prompt for `ROADMAP_COMPLETE`, even though a task was mid-flight.

This was the highest-severity finding in the code review reconciliation.

## Decision

`cmd_check_stop` now checks for in-progress tasks before checking for eligible tasks:

1. `active_task(tasks)` returns the first `in_progress` task.
2. If found, emit a `RESUME IN-PROGRESS TASK` brief instead of the "all complete" message.
3. Only declare completion when no `todo`, `in_progress`, or `blocked` tasks remain.

The priority order in check-stop is now:
1. `stop_hook_active` → allow stop (infinite loop guard)
2. Iteration cap → hard stop
3. `ROADMAP_COMPLETE` signal → allow stop
4. **In-progress task → resume brief** (new)
5. Eligible todo task → task brief
6. Blocked tasks → report blocked
7. Non-done tasks → report anomaly
8. All done → prompt for completion signal

## Consequences

- **Fixed:** Claude can now respond mid-task without the loop incorrectly terminating.
- **New behavior:** The `RESUME IN-PROGRESS TASK` header in the brief distinguishes a resumption from a fresh task start.
- **Test coverage:** `TestCheckStop::test_resumes_in_progress` verifies this path.
