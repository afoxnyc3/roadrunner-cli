# ADR-005: Absolute Hook Paths via $CLAUDE_PROJECT_DIR

**Status:** Accepted
**Date:** 2026-04-16
**Deciders:** Alex, Claude Opus 4.6

## Context

Hook commands in `.claude/settings.json` used relative paths (`bash hooks/stop_hook.sh`). Claude Code hook documentation states that hook commands execute in the current working directory, which can change during a session. If Claude `cd`s into a subdirectory (e.g., `tasks/`, `logs/`), the relative path resolves from the wrong directory and the hook silently fails to execute.

## Decision

Use the `$CLAUDE_PROJECT_DIR` environment variable (provided by Claude Code at hook invocation time) to root all hook paths:

```json
"command": "bash \"$CLAUDE_PROJECT_DIR\"/hooks/stop_hook.sh"
```

This is the pattern recommended in the official Claude Code hooks documentation.

## Consequences

- **Fixed:** Hooks execute correctly regardless of Claude's current working directory.
- **Dependency:** Requires Claude Code to set `$CLAUDE_PROJECT_DIR`. If the variable is unset, the command resolves to `/hooks/...` which will fail — but this would indicate a Claude Code runtime issue, not a roadrunner configuration error.
- **Verified:** Tested by running the stop hook from `cwd=/tmp` with `CLAUDE_PROJECT_DIR` set to the project root.
