# ADR-003: Per-Task Attempt Counter and Auto-Block

**Status:** Accepted
**Date:** 2026-04-16
**Deciders:** Alex, Claude Opus 4.6

## Context

If Claude repeatedly fails validation on a task, the loop retries indefinitely — each iteration costs tokens with no progress. Research on agentic loop failure modes (Tianpan 2026) documents 200x cost amplification from unbounded retry loops. Roadrunner had no mechanism to detect or break this pattern; the only escape was the global iteration cap (which may be set high for legitimate long roadmaps).

## Decision

Extend `.roadmap_state.json` with an `attempts_per_task` dictionary. Each time `cmd_check_stop` resumes an in-progress task, the counter for that task increments. When a task reaches `MAX_TASK_ATTEMPTS` (default 5, configurable via `--max-attempts`), the task is automatically set to `blocked` with a changelog entry explaining why.

```json
{
  "current_task_id": "TASK-003",
  "iteration": 12,
  "attempts_per_task": {
    "TASK-001": 1,
    "TASK-002": 1,
    "TASK-003": 4
  }
}
```

## Alternatives Considered

- **Validation-result hashing:** Only count attempts where validation fails identically. More precise but adds complexity; deferred.
- **Exponential backoff:** Delay between retries. Not applicable — Claude Code doesn't support sleep between iterations.
- **Global-only cap:** Rely on `--max-iterations`. Too coarse — a 50-task roadmap with a 50-iteration cap leaves no room for retries.

## Consequences

- **Prevents:** Unbounded cost on stuck tasks.
- **Trade-off:** A task that needs 6 legitimate attempts will be auto-blocked. Operator can unblock manually and the counter resets on re-start.
- **Trace logging:** Auto-block events are recorded in `logs/trace.jsonl` with the attempt count.
- **Test coverage:** `TestCheckStop::test_auto_block_after_max_attempts` verifies the path.
