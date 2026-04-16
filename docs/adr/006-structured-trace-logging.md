# ADR-006: Structured JSON Trace Logging

**Status:** Accepted
**Date:** 2026-04-16
**Deciders:** Alex, Claude Opus 4.6

## Context

Roadrunner's only logging was markdown-for-humans: `logs/CHANGELOG.md` and per-task `logs/TASK-XXX.md`. Reconstructing what happened during an overnight run required reading multiple markdown files in order. There was no machine-parseable record of which iteration ran which command with which exit code and how long it took.

This matches the "no observability" anti-pattern identified in agentic loop failure-mode literature.

## Decision

Add a JSON Lines trace log at `logs/trace.jsonl`. One line per event, compact JSON (no pretty-print). Events are emitted from key lifecycle points:

| Event | Emitted from | Fields |
|---|---|---|
| `check_stop` | `cmd_check_stop` | `task_id`, `iteration`, `max_iter` |
| `task_start` | `cmd_start` | `task_id`, `iteration` |
| `task_complete` | `cmd_complete` | `task_id`, `iteration` |
| `task_block` | `cmd_block` | `task_id`, `iteration`, `notes` |
| `auto_block` | `cmd_check_stop` | `task_id`, `iteration`, `attempts`, `max_attempts` |
| `validation_command` | `run_validation` | `task_id`, `iteration`, `command`, `exit_code`, `duration_ms` |
| `validation_complete` | `run_validation` | `task_id`, `iteration`, `passed`, `total` |

Every record includes `ts` (ISO 8601 UTC timestamp).

## Consequences

- **Enables:** `jq` queries over overnight runs (e.g., `jq 'select(.event=="auto_block")' logs/trace.jsonl`).
- **Coexists:** Markdown logs remain for human readability. Trace log is the machine-parseable complement.
- **Growth:** Trace log grows linearly with iterations. A 50-iteration run with 3 validation commands per task produces ~200 lines (~40KB). Acceptable without rotation.
- **Not addressed:** No log rotation, no remote shipping, no metrics counters. These are future concerns if roadrunner moves to multi-project or team use.
