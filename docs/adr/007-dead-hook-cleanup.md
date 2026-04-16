# ADR-007: Dead Hook Cleanup

**Status:** Accepted
**Date:** 2026-04-16
**Deciders:** Alex, Claude Opus 4.6

## Context

An independent analysis flagged three pieces of dead configuration in the hook system. All three were verified against the official Claude Code hooks documentation (https://docs.claude.com/en/docs/claude-code/hooks) using Ref and Exa MCP tools.

### Finding 1: TaskCompleted hook never fires

The `TaskCompleted` event fires only in two situations:
1. When any agent explicitly marks a task as completed through the **TaskUpdate** tool.
2. When an **agent team teammate** finishes its turn with in-progress tasks.

Roadrunner uses neither `TaskUpdate` nor agent teams. It completes tasks via `roadrunner.py complete`, which is a subprocess call — invisible to Claude Code's hook system. The hook was dead code that never fired during any session.

The `task_id` in the TaskCompleted payload is Claude's internal task identifier (e.g., `"task-001"`), not roadmap IDs like `"TASK-001"`. Even if the hook fired, the ID namespace mismatch would prevent correct routing.

### Finding 2: MultiEdit matcher is dead config

The PostToolUse hook matcher was `"Write|Edit|MultiEdit"`. There is no `MultiEdit` tool in Claude Code — only `Write` and `Edit`. The `MultiEdit` branch never matches.

### Finding 3: PreCompact does not support additionalContext

The `write_context_snapshot()` function printed `{"additionalContext": "..."}` to stdout, expecting PreCompact to inject it into the compacted context. Per the docs, PreCompact supports only `decision: "block"` for output. The `additionalContext` field is supported by SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Notification, and SubagentStart — but not PreCompact or PostCompact. The print was silently ignored.

## Decision

1. **Delete the TaskCompleted hook** — remove from `settings.json` and delete `hooks/task_completed_hook.sh`. Validation gating is already handled by `cmd_complete` in Python.
2. **Fix the PostToolUse matcher** — change to `"Write|Edit"`.
3. **Remove the dead `print()` from `write_context_snapshot()`** — keep only the file write.
4. **Add a SessionStart hook** — reads `.context_snapshot.json` and emits `additionalContext` (which IS supported by SessionStart). This provides the context injection that PreCompact was incorrectly attempting.

## Consequences

- **Removed:** ~60 lines of dead hook code and config.
- **Added:** `hooks/session_start_hook.sh` (~50 lines) that correctly injects roadmap state on session start/resume.
- **Net effect:** Roadmap state now actually reaches Claude's context after compaction (via SessionStart), whereas before it was silently discarded (via PreCompact).
- **Validation gate unchanged:** `cmd_complete` in `roadrunner.py` re-runs `run_validation` before flipping status — this was always the real gate, not the TaskCompleted hook.
