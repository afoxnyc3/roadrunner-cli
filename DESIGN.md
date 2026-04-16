# Roadrunner CLI — Design Document

> Last updated: 2026-04-16

---

## 1. Architecture Overview

Roadrunner is a deterministic agentic loop. Python owns control flow. Claude owns implementation. Hooks enforce completion. No task advances without validation. No loop exits without an explicit signal.

```
┌───────────────────────────────────────────────────────────┐
│                    Claude Code Session                    │
│                                                           │
│  CLAUDE.md         Hook fires         Hook fires         │
│  (agent brief)         │                  │              │
│       │            Stop Hook         PreCompact          │
│       ▼                │              Hook               │
│  roadrunner.py next    │                  │              │
│  roadrunner.py start   │                  ▼              │
│  <implement task>      │          write_context_snapshot │
│  roadrunner.py validate│                                 │
│  roadrunner.py complete│                                 │
│       │                │                                 │
│       └────────────────┘                                 │
└───────────────────────────────────────────────────────────┘
```

### 1.1 Control flow, step by step

1. Claude Code starts with `CLAUDE.md` in scope. Agent reads its brief.
2. Claude runs `python3 roadrunner.py next` to identify the current task.
3. Claude runs `python3 roadrunner.py start TASK-XXX` — sets status to `in_progress`, records current task in state.
4. Claude implements the task within the scope defined in `files_expected`.
5. Claude runs `python3 roadrunner.py validate TASK-XXX` — executes all `validation_commands`, exits 0 or 1.
6. If validation fails, Claude fixes and retries.
7. Claude runs `python3 roadrunner.py complete TASK-XXX --notes "..."` — re-runs validation, sets status to `done` if passing, writes work log.
8. Claude finishes its response turn. Stop hook fires.
9. Stop hook calls `roadrunner.py check-stop` via stdin pipe.
10. `check-stop` increments the iteration counter, reads `tasks.yaml` and `.roadmap_state.json`.
11. If a task is `in_progress`: emits `{"decision": "block", "reason": "<resume brief>"}` — Claude resumes.
12. If a new `todo` task is eligible: emits `{"decision": "block", "reason": "<task brief>"}` — Claude continues.
13. If all tasks done: `check-stop` prompts Claude to emit `ROADMAP_COMPLETE`.
14. Claude emits `ROADMAP_COMPLETE` on its own line. Stop hook detects it via line-anchored regex, exits 0 (allows stop). Loop ends.
15. If iteration limit hit: hard stop with message.
16. If a task has been resumed 5+ times without completion: auto-blocked with changelog entry.

### 1.2 State files

| File | Purpose |
|---|---|
| `tasks/tasks.yaml` | Source of truth for task status and definitions. Schema-validated on every load. Written atomically via tempfile + `os.replace`. |
| `.roadmap_state.json` | Current task ID, iteration count, and per-task attempt counter |
| `.context_snapshot.json` | Written by PreCompact; survives compaction |
| `logs/CHANGELOG.md` | Append-only audit trail of status changes |
| `logs/TASK-XXX.md` | Per-task work log with validation output |
| `logs/trace.jsonl` | Structured JSON trace log — one line per lifecycle event |
| `.reset_TASK-XXX` | Boundary marker written on task completion |

---

## 2. Hook Contracts

### 2.1 Stop Hook (`hooks/stop_hook.sh`)

**Fires when:** Claude Code finishes a response turn.

**Input (stdin):** JSON object from Claude Code runtime.

```json
{
  "stop_hook_active": false,
  "last_assistant_message": "...the model's last response..."
}
```

**Output (stdout):** JSON control object.

```json
// Force continuation with task brief injected into next turn
{"decision": "block", "reason": "Continue working. Task TASK-002..."}

// Hard stop (roadmap done or max iterations)
{"continue": false, "stopReason": "Max iterations (50) reached."}
```

**Exit codes:**
- `exit 0` — allow Claude to stop (used when `stop_hook_active=true`, or completion signal detected)
- `exit 2` — legacy force-continue (deprecated; prefer JSON)

**Infinite loop guard:** If `stop_hook_active` is true in the input, exit 0 immediately. This prevents the hook from calling itself recursively.

**Logic (delegated to `roadrunner.py check-stop`):**
1. `stop_hook_active` → exit 0
2. Increment iteration counter, check against max
3. `ROADMAP_COMPLETE` on last non-empty line of last message → exit 0
4. In-progress task exists → emit resume brief (increment attempt counter; auto-block if >= max attempts)
5. Eligible todo task → emit task brief
6. Blocked tasks exist → report with unblock instruction
7. Non-done tasks remain → report anomaly
8. All done → prompt for `ROADMAP_COMPLETE`

---

### 2.2 SessionStart Hook (`hooks/session_start_hook.sh`)

**Fires when:** Claude Code session begins or resumes (including after compaction restarts).

**Input (stdin):** JSON object from Claude Code runtime (common fields only).

**Output (stdout):** JSON with `additionalContext` containing roadmap state summary (if `.context_snapshot.json` exists).

```json
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "Roadmap snapshot: Current task: TASK-003 | Iteration: 7 | Status: TASK-001=done, TASK-002=done, TASK-003=in_progress"
  }
}
```

**Exit codes:**
- `exit 0` always — informational, never blocks.

**Logic:**
1. Check if `.context_snapshot.json` exists. If not, exit 0 silently.
2. Parse snapshot, build a summary string from `current_task`, `next_eligible`, `iteration`, and `status_summary`.
3. Emit JSON with `additionalContext` so Claude starts the session with roadmap awareness.

**Note:** `additionalContext` is a supported output field for `SessionStart` hooks per Claude Code docs. This replaces the previous approach of emitting `additionalContext` from the PreCompact hook (which does not support that field).

---

### 2.3 PreCompact Hook (`hooks/precompact_hook.sh`)

**Fires when:** Claude Code is about to compact the conversation.

**Input (stdin):** JSON with `trigger` (`manual` or `auto`) and `custom_instructions`.

**Output:** None. PreCompact supports only `decision: "block"` — it does **not** support `additionalContext`.

**Side effect:** Writes `.context_snapshot.json` to disk. The SessionStart hook (§2.2) reads this file to inject state into the next session.

**`.context_snapshot.json` schema:**
```json
{
  "snapshot_at": "2026-04-15T09:00:00Z",
  "current_task": "TASK-003",
  "iteration": 7,
  "next_eligible": "TASK-004",
  "status_summary": {
    "TASK-001": "done",
    "TASK-002": "done",
    "TASK-003": "done",
    "TASK-004": "todo"
  }
}
```

---

### 2.4 PostToolUse Hook (`hooks/post_write_hook.sh`)

**Fires when:** Claude uses Write, Edit, or MultiEdit tools (async).

**Input (stdin):** JSON object with `tool_input.file_path`.

**Output:** Lint feedback passed back to Claude on next turn.

**Logic:**
- `.py` files → `ruff check` (failures suppressed with `|| true`)
- `.yaml`/`.yml` files → `python3 -c 'import sys, yaml; yaml.safe_load(open(sys.argv[1]))' "$FILE_PATH"` (path passed via argv, not interpolated)

**Behavior:** Claude continues immediately. This hook is informational, not blocking.

---

## 3. Risk Areas and Mitigations

### Status Legend

- ✅ **FIXED** — addressed in the hardening pass (2026-04-16)
- ⚠️ **MITIGATED** — risk reduced but not fully eliminated
- 🔶 **OPEN** — known limitation, accepted for current scope

---

### ✅ FIXED: Hook path mismatch (was CRITICAL)

**Original risk:** `settings.json` used relative paths (`bash hooks/stop_hook.sh`) that break if Claude changes working directory.

**Fix:** All hook commands now use `"$CLAUDE_PROJECT_DIR"/hooks/<name>.sh` (ADR-005). Verified working from arbitrary cwd.

---

### ✅ FIXED: ROADMAP_COMPLETE substring match (was HIGH)

**Original risk:** Any assistant message containing the literal string triggered loop termination.

**Fix:** Line-anchored regex on the last non-empty line only (ADR-001). Task brief no longer emits the sentinel as a matchable line. 9 test cases cover edge cases.

---

### ✅ FIXED: check-stop treated in-progress as "all done" (was CRITICAL)

**Original risk:** After `cmd_start`, the active task became invisible to `next_eligible_task()`. If Claude responded before calling `complete`, the hook declared all work finished.

**Fix:** `cmd_check_stop` now checks for `in_progress` tasks first and emits a resume brief (ADR-002). Only declares completion when no `todo`, `in_progress`, or `blocked` tasks remain.

---

### ✅ FIXED: Shell injection in post_write_hook.sh (was HIGH)

**Original risk:** `$FILE_PATH` interpolated into a single-quoted Python string. A path containing `'` could execute arbitrary Python.

**Fix:** Path passed via `sys.argv[1]` instead of f-string interpolation. Verified with injection canary test.

---

### ✅ FIXED: Iteration counter only incremented on start (was MEDIUM)

**Original risk:** If Claude skipped `start`, the iteration counter never advanced and the max-iterations cap was disabled.

**Fix:** Iteration counter now increments in `cmd_check_stop`, which fires every turn regardless of whether `start` was called.

---

### ✅ FIXED: Non-atomic save_tasks (was MEDIUM)

**Original risk:** SIGINT mid-write could corrupt `tasks.yaml`.

**Fix:** Writes to `.tmp` file, `fsync`, then `os.replace` (ADR-004).

---

### ✅ FIXED: python vs python3 mismatch (was MEDIUM)

**Original risk:** `justfile` used `python`, hooks used `python3`.

**Fix:** All invocations standardized on `python3` across justfile, CLAUDE.md, and hooks.

---

### ✅ FIXED: cmd_block silent exit (was LOW)

**Original risk:** `cmd_block` exited with code 1 but no error message on missing task.

**Fix:** Now prints `Task {id} not found.` before exiting.

---

### ✅ FIXED: TaskCompleted hook was dead code (was HIGH)

**Original risk:** Hook tried to extract roadmap task IDs from the `TaskCompleted` payload, but the payload uses Claude's internal `task_id`, not roadmap IDs.

**Root cause (verified against docs):** `TaskCompleted` only fires on `TaskUpdate` tool calls (agent teams feature) or when a teammate finishes its turn. Roadrunner uses neither — it uses `roadrunner.py complete`. The hook never fired.

**Fix:** Removed the hook entirely (ADR-007). Validation gating is already handled by `cmd_complete` in Python, which re-runs `run_validation` before flipping status. Replaced with a `SessionStart` hook for context injection.

---

### ⚠️ MITIGATED: Retry storms (was UNADDRESSED)

**Mitigation:** Per-task attempt counter with auto-block after 5 attempts (ADR-003). Configurable via `--max-attempts`.

**Remaining risk:** A task that legitimately needs many iterations will be auto-blocked. Operator must manually unblock and retry.

---

### 🔶 OPEN: No automated tests for hooks (bash scripts)

The pytest suite covers `roadrunner.py` controller logic (48 tests). The bash hooks are tested manually only. Hook-level integration tests (mocked Claude Code payloads piped through bash scripts) would close this gap.

---

### 🔶 OPEN: Single-author, single-machine assumptions

File locking, concurrent invocations, and multi-project parallel runs are not supported. Acceptable for the current single-operator scope.

---

### Trust Boundary: tasks.yaml and validation_commands

`tasks.yaml` is a **trust boundary**. The `validation_commands` list is executed via `subprocess.run(cmd, shell=True)` — any command defined there runs with the operator's full privileges. This is by design for a single-operator tool: the operator authors the tasks, the operator trusts the commands.

**Implications:**

- A malicious or careless `validation_commands` entry (e.g., `rm -rf /`) will execute without sandboxing.
- If this project is ever shared or used in a multi-tenant context, `tasks.yaml` must be treated as executable configuration — review it the way you'd review a Makefile or CI pipeline.
- The same applies to `acceptance_criteria` or `goal` fields: they don't execute, but they shape Claude's behavior via the task brief. Prompt injection through task definitions is a theoretical concern in shared environments.

**Single-operator assumption:** Roadrunner assumes the person writing `tasks.yaml` is the same person running it. No access control, no sandboxing, no approval flow. This is appropriate for local development and overnight single-machine runs. It is not appropriate for shared infrastructure.

---

## 4. Setup for a New Project

### 4.1 Copy-in procedure

```bash
# From target project root
cp /path/to/roadrunner-cli/roadrunner.py .
cp -r /path/to/roadrunner-cli/hooks ./hooks
cp -r /path/to/roadrunner-cli/.claude ./.claude
mkdir -p tasks logs
# Create your tasks/tasks.yaml
# Create your CLAUDE.md (use roadrunner-cli/CLAUDE.md as template)
pip3 install -r requirements.txt
python3 roadrunner.py health
```

### 4.2 Smoke test hooks before first live run

```bash
# Stop hook — should return {"decision": "block", "reason": "..."} or allow stop
echo '{"stop_hook_active": false, "last_assistant_message": "some text"}' | bash "$CLAUDE_PROJECT_DIR"/hooks/stop_hook.sh

# Infinite loop guard — should exit 0 silently
echo '{"stop_hook_active": true}' | bash "$CLAUDE_PROJECT_DIR"/hooks/stop_hook.sh; echo "exit: $?"

# ROADMAP_COMPLETE detection (must be last line)
printf '%s' '{"stop_hook_active": false, "last_assistant_message": "done\n\nROADMAP_COMPLETE"}' | bash "$CLAUDE_PROJECT_DIR"/hooks/stop_hook.sh; echo "exit: $?"

# Snapshot
python3 roadrunner.py snapshot && cat .context_snapshot.json

# Health
python3 roadrunner.py health
```

### 4.3 Post-first-run verification

After the first real Claude Code session with hooks active:

1. Check `logs/.taskcompleted_payloads.log` for the actual `TaskCompleted` payload schema.
2. Confirm the `TASK-###` regex extraction worked (or adjust field probing if needed).
3. Remove the debug log line from `hooks/task_completed_hook.sh` once confirmed.
4. Review `logs/trace.jsonl` to verify structured logging is capturing events.

---

## 5. Embedding Model: Copy-In vs External Runner

**Recommendation: Copy-in, versioned.**

### Option A: External runner (symlink/PATH reference)

Claude Code in a target project calls roadrunner.py from a shared location. Each target project has its own `tasks.yaml`.

Pros: single source of truth for roadrunner.py.
Cons: absolute path in CLAUDE.md and settings.json means portability breaks. If the runner is updated, all active projects get the change immediately — risky during a live run. PATH setup required.

### Option B: Copy-in (recommended)

Copy `roadrunner.py`, the `hooks/` directory, and `.claude/settings.json` into the target project. Target project provides its own `tasks.yaml`.

Pros: fully self-contained, no external dependencies, no version skew risk mid-run, works offline.
Cons: roadrunner.py changes need to be propagated manually to each project.

### Future: pip installable

When roadrunner stabilizes, package as `roadrunner-cli` on PyPI. Target projects `pip install roadrunner-cli` and call via `roadrunner <command>`. Hooks remain in the target repo. Runner logic is versioned and shared; task definitions and hooks are per-project.

---

## 6. Architecture Decision Records

| ADR | Title | Status |
|---|---|---|
| [ADR-001](docs/adr/001-line-anchored-completion-signal.md) | Line-Anchored Completion Signal | Accepted |
| [ADR-002](docs/adr/002-check-stop-in-progress-awareness.md) | Check-Stop In-Progress Task Awareness | Accepted |
| [ADR-003](docs/adr/003-retry-storm-prevention.md) | Per-Task Attempt Counter and Auto-Block | Accepted |
| [ADR-004](docs/adr/004-atomic-writes-and-data-integrity.md) | Atomic File Writes for State Integrity | Accepted |
| [ADR-005](docs/adr/005-absolute-hook-paths.md) | Absolute Hook Paths via $CLAUDE_PROJECT_DIR | Accepted |
| [ADR-006](docs/adr/006-structured-trace-logging.md) | Structured JSON Trace Logging | Accepted |
| [ADR-007](docs/adr/007-dead-hook-cleanup.md) | Dead Hook Cleanup (TaskCompleted, MultiEdit, PreCompact additionalContext) | Accepted |

---

## 7. Open Questions

1. Does the `SessionStart` hook's `additionalContext` reliably appear in Claude's context on session resume? (Verify by observing Claude's behavior after a compaction or session restart)
2. Does the `PostCompact` event's `compact_summary` field contain useful information for roadmap continuity? (Could supplement the snapshot approach)
