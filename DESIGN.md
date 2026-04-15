# Roadrunner CLI — Design Document

> Last updated: 2026-04-15

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
2. Claude runs `python roadrunner.py next` to identify the current task.
3. Claude runs `python roadrunner.py start TASK-XXX` — sets status to `in_progress`, increments iteration counter.
4. Claude implements the task within the scope defined in `files_expected`.
5. Claude runs `python roadrunner.py validate TASK-XXX` — executes all `validation_commands`, exits 0 or 1.
6. If validation fails, Claude fixes and retries.
7. Claude runs `python roadrunner.py complete TASK-XXX --notes "..."` — re-runs validation, sets status to `done` if passing, writes work log.
8. Claude finishes its response turn. Stop hook fires.
9. Stop hook calls `roadrunner.py check-stop` via stdin pipe.
10. `check-stop` reads `tasks.yaml` and `.roadmap_state.json`, determines next eligible task.
11. If tasks remain: emits `{"decision": "block", "reason": "<task brief>"}` — Claude receives this as injected context and continues.
12. If all tasks done: `check-stop` prompts Claude to emit `ROADMAP_COMPLETE`.
13. Claude emits `ROADMAP_COMPLETE`. Stop hook detects it, exits 0 (allows stop). Loop ends.
14. If iteration limit hit: hard stop with message.

### 1.2 State files

| File | Purpose |
|---|---|
| `tasks/tasks.yaml` | Source of truth for task status and definitions |
| `.roadmap_state.json` | Current task ID and iteration count |
| `.context_snapshot.json` | Written by PreCompact; survives compaction |
| `logs/CHANGELOG.md` | Append-only audit trail of status changes |
| `logs/TASK-XXX.md` | Per-task work log with validation output |
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
- `exit 0` — allow Claude to stop (used when `stop_hook_active=true`)
- `exit 2` — legacy force-continue (deprecated; prefer JSON)

**Infinite loop guard:** If `stop_hook_active` is true in the input, exit 0 immediately. This prevents the hook from calling itself recursively.

**Logic (delegated to `roadrunner.py check-stop`):**
1. `ROADMAP_COMPLETE` in last message → exit 0
2. Iteration >= max → output `{"continue": false, ...}`
3. Eligible tasks exist → output `{"decision": "block", "reason": <task brief>}`
4. No eligible tasks, some blocked → output block with unblock instruction
5. All done → prompt Claude to emit `ROADMAP_COMPLETE`

---

### 2.2 TaskCompleted Hook (`hooks/task_completed_hook.sh`)

**Fires when:** Claude Code agent marks a todo task complete.

**Input (stdin):** JSON object from Claude Code runtime.

```json
{
  "task_id": "TASK-003"
}
```

**Output:** None required. Feedback goes to stderr on failure.

**Exit codes:**
- `exit 0` — allow completion
- `exit 2` — block completion; stderr fed back to model

**Logic:**
1. Extract `task_id` from payload. If absent, pass through (not a managed task).
2. Run `roadrunner.py validate <task_id>`. If exit != 0, echo error to stderr and exit 2.
3. On pass, exit 0.

**Note on payload format:** This hook assumes the Claude Code `TaskCompleted` event includes a `task_id` field matching roadrunner task IDs. Verify the actual Claude Code hook payload schema before relying on this. If the field name differs, the hook silently passes through (empty TASK_ID check exits 0).

---

### 2.3 PreCompact Hook (`hooks/precompact_hook.sh`)

**Fires when:** Claude Code is about to compact the conversation.

**Input (stdin):** None significant.

**Output (stdout):** JSON `additionalContext` block injected into the compacted context.

```json
{
  "additionalContext": "Roadmap state snapshot written. Next task: TASK-004. Iteration: 7"
}
```

**Side effect:** Writes `.context_snapshot.json` to disk.

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
- `.yaml`/`.yml` files → `python3 -c "import yaml; yaml.safe_load(...)"` (failures suppressed)

**Behavior:** Claude continues immediately. This hook is informational, not blocking.

---

## 3. Known Risk Areas for First Run

### CRITICAL: Hook path mismatch

**Severity: Showstopper**

`settings.json` references `.claude/hooks/stop_hook.sh` but the hook scripts live at `hooks/stop_hook.sh`.

```json
// Current (broken)
"command": "bash .claude/hooks/stop_hook.sh"

// Should be
"command": "bash hooks/stop_hook.sh"
```

This affects all four hooks. On first run, every hook will fail with "file not found" and Claude will exit freely after each response. The agentic loop will not run.

**Fix:** Update `settings.json` (see Section 4.1).

---

### HIGH: Hook SCRIPT_DIR/PROJECT_ROOT calculation

The hook scripts compute `PROJECT_ROOT` as:
```bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
```

This assumes hooks are exactly one directory below the project root (i.e., at `hooks/stop_hook.sh`). If they were at `.claude/hooks/`, `PROJECT_ROOT` would resolve to `.claude/` and `python3 "$PROJECT_ROOT/roadrunner.py"` would fail.

The path calculation is correct for `hooks/` placement. Confirm this is stable once the settings.json is fixed.

---

### HIGH: TaskCompleted hook payload field name

The hook extracts `task_id` from the Claude Code hook payload. The actual field name in the Claude Code `TaskCompleted` event payload may differ (e.g. `title`, `taskId`, or `content`). If it does, the hook silently exits 0 for all task completions — meaning validation is never run, and the gate is inoperative.

**Mitigation:** On first run, observe what Claude Code actually sends to this hook by adding temporary logging: `echo "$INPUT" >> /tmp/tc_hook_debug.log`.

---

### MEDIUM: `python roadrunner.py` vs `python3`

`settings.json` hook commands call `python3`. `CLAUDE.md` instructs Claude to call `python roadrunner.py`. If the system `python` is Python 2 or absent, Claude's direct calls will fail. The hooks are safe (use `python3`). The agent-facing commands may not be.

**Fix:** Standardize on `python3` in `CLAUDE.md` command examples, or ensure `python` → `python3` in the runtime environment.

---

### MEDIUM: `pyyaml` dependency not enforced

`roadrunner.py` imports `yaml` at the top level. If `pyyaml` is not installed in the active Python environment, every command fails with an ImportError. `requirements.txt` does not exist yet (TASK-001 creates it, but the tool needs yaml to even start TASK-001).

**Fix:** Install `pyyaml` manually before first run: `pip3 install pyyaml`. After TASK-001, `requirements.txt` will capture this.

---

### MEDIUM: Iteration counter only increments on `start`

`check-stop` reads the iteration count from `.roadmap_state.json`. The counter only increments when Claude calls `python roadrunner.py start TASK-XXX`. If Claude skips calling `start` and jumps straight to implementation, the counter never advances, the max_iterations guard never triggers, and a runaway session can loop indefinitely.

**Mitigation:** The Stop hook also checks for eligible tasks and the ROADMAP_COMPLETE signal, so it won't loop truly forever. But the iteration cap fails silently.

---

### MEDIUM: tasks.yaml write is not atomic

`save_tasks()` reads the full file, replaces the tasks list, and overwrites. If interrupted mid-write, the YAML is corrupted and all subsequent commands fail. No backup is created.

**Low-risk for a local tool with short writes. Acceptable for MVP. Document as known limitation.**

---

### LOW: `set -euo pipefail` in hooks + python3 failures

All hooks use `set -euo pipefail`. If `python3` is unavailable or the script has a non-zero exit for any incidental reason, the hook exits non-zero. For the Stop hook, a non-zero exit (not 0 or 2) is ambiguous — Claude Code may treat it as an error rather than a clean allow-stop. Test with `echo '{}' | bash hooks/stop_hook.sh` before first run.

---

### LOW: PostToolUse lint output not visible

`post_write_hook.sh` uses `|| true` on all lint commands. Ruff failures are silently swallowed. The hook always exits 0. Claude never sees lint feedback from this hook. If the intent is feedback-on-next-turn, the output needs to be emitted without suppression and without causing a non-zero exit.

---

## 4. Recommended Fixes Before First Run

### 4.1 Fix settings.json hook paths (REQUIRED)

Replace `.claude/hooks/` with `hooks/` in all four hook commands:

```json
{
  "hooks": {
    "Stop": [{"hooks": [{"type": "command", "command": "bash hooks/stop_hook.sh", "timeout": 30}]}],
    "TaskCompleted": [{"hooks": [{"type": "command", "command": "bash hooks/task_completed_hook.sh", "timeout": 60}]}],
    "PreCompact": [{"hooks": [{"type": "command", "command": "bash hooks/precompact_hook.sh", "timeout": 30}]}],
    "PostToolUse": [{"matcher": "Write|Edit|MultiEdit", "hooks": [{"type": "command", "command": "bash hooks/post_write_hook.sh", "timeout": 30}]}]
  }
}
```

### 4.2 Pre-install pyyaml (REQUIRED)

```bash
pip3 install pyyaml
```

Or create a minimal `requirements.txt` by hand before running:
```
pyyaml>=6.0
```

Then `pip3 install -r requirements.txt`.

### 4.3 Debug the TaskCompleted hook payload

Add a debug log line before the `TASK_ID` extraction to capture what Claude Code actually sends:

```bash
echo "$INPUT" >> /tmp/rr_tc_debug.log
```

Remove after confirming the field name. Do this before the first real overnight run.

### 4.4 Smoke test hooks before first live run

```bash
# Stop hook — should return {"decision": "block", "reason": "..."} or allow stop
echo '{"stop_hook_active": false, "last_assistant_message": "some text"}' | bash hooks/stop_hook.sh

# Infinite loop guard — should exit 0 silently
echo '{"stop_hook_active": true}' | bash hooks/stop_hook.sh; echo "exit: $?"

# ROADMAP_COMPLETE detection
echo '{"stop_hook_active": false, "last_assistant_message": "ROADMAP_COMPLETE"}' | bash hooks/stop_hook.sh; echo "exit: $?"

# Snapshot
python3 roadrunner.py snapshot && cat .context_snapshot.json

# Health
python3 roadrunner.py health
```

### 4.5 Standardize Python invocation in CLAUDE.md

Update command examples to use `python3`:
```bash
python3 roadrunner.py status
python3 roadrunner.py next
python3 roadrunner.py start TASK-XXX
...
```

---

## 5. Embedding Model: Copy-In vs External Runner

**Recommendation: Copy-in, versioned.**

### Option A: External runner (symlink/PATH reference)

Claude Code in a target project calls roadrunner.py from a shared location (e.g. `~/dev/projects/roadrunner-cli/roadrunner.py`). Each target project has its own `tasks.yaml`.

Pros: single source of truth for roadrunner.py.
Cons: absolute path in CLAUDE.md and settings.json means portability breaks. If the runner is updated, all active projects get the change immediately — risky during a live run. PATH setup required.

### Option B: Copy-in (recommended)

Copy `roadrunner.py`, the `hooks/` directory, and `.claude/settings.json` into the target project. Target project provides its own `tasks.yaml`.

Pros: fully self-contained, no external dependencies, no version skew risk mid-run, works offline, hooks resolve via relative paths which are stable.
Cons: roadrunner.py changes need to be propagated manually to each project.

### Copy-in procedure for a new project

```bash
# From target project root
cp /path/to/roadrunner-cli/roadrunner.py .
cp -r /path/to/roadrunner-cli/hooks ./hooks
cp /path/to/roadrunner-cli/.claude/settings.json .claude/settings.json
mkdir -p tasks logs
# Create your tasks/tasks.yaml
# Create your CLAUDE.md (use roadrunner-cli/CLAUDE.md as template)
pip3 install pyyaml
python3 roadrunner.py health
```

### Future: pip installable

When roadrunner stabilizes, package it as `roadrunner-cli` on PyPI. Target projects `pip install roadrunner-cli` and call it via `roadrunner <command>`. Hooks remain in the target repo (they need to be local to Claude Code's working directory). This gives a clean separation: runner logic is versioned and shared, task definitions and hooks are per-project.

---

## 6. Open Questions

1. Does Claude Code's `TaskCompleted` hook payload include a field named `task_id`? Or something else? (See risk 3.2)
2. Should `post_write_hook.sh` emit lint results non-fatally? Currently suppressed entirely.
3. Is `python` or `python3` the right invocation in the target environment? Standardize before first run.
