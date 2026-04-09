# Roadmap Loop

Deterministic agentic loop for Claude Code. Python owns control. Claude owns execution. Hooks enforce completion.

## Architecture

```
tasks/tasks.yaml          ← the queue
roadmap_loop.py           ← controller: validation, logging, state, stop-check
.claude/settings.json     ← hooks: Stop, TaskCompleted, PreCompact, PostToolUse
hooks/stop_hook.sh        ← loop enforcement: block or allow Claude Code to stop
hooks/task_completed_hook.sh  ← validation gate: must pass before task is done
hooks/precompact_hook.sh  ← context snapshot: survives memory wipes
CLAUDE.md                 ← agent brief: operating contract for Claude Code
```

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Make hooks executable
chmod +x hooks/*.sh

# 3. Copy hooks where settings.json expects them
mkdir -p .claude/hooks
cp hooks/*.sh .claude/hooks/

# 4. Verify setup
python roadmap_loop.py health

# 5. Check what's next
python roadmap_loop.py status

# 6. Launch Claude Code — the loop takes over
claude --dangerously-skip-permissions  # or with your normal permission level
```

## Running Overnight

The Stop hook handles everything automatically once Claude Code is running.
Set `ROADMAP_MAX_ITERATIONS` to control max cycles (default: 50).

```bash
export ROADMAP_MAX_ITERATIONS=100
claude
```

Claude will work through the roadmap, validating each task before marking done,
writing logs, and continuing until `ROADMAP_COMPLETE` is output or the iteration
limit is hit.

## Operator Commands

```bash
python roadmap_loop.py status           # see all task states
python roadmap_loop.py next             # see what runs next
python roadmap_loop.py start TASK-001  # mark in_progress
python roadmap_loop.py validate TASK-001  # run validation commands
python roadmap_loop.py complete TASK-001 --notes "did the thing"
python roadmap_loop.py block TASK-001 --notes "why it's stuck"
python roadmap_loop.py health           # system check
```

## Task Anatomy

```yaml
- id: TASK-001
  title: "Human-readable name"
  status: todo                    # todo | in_progress | done | blocked
  depends_on: []                  # list of task IDs that must be done first
  goal: "What success looks like"
  acceptance_criteria:
    - "Specific, testable condition"
  validation_commands:
    - "pytest tests/test_feature.py"
    - "ruff check src/"
  documentation_targets:
    - "CHANGELOG.md"
    - "logs/TASK-001.md"
  files_expected:
    - "src/feature.py"
  notes: "Operator annotations"
```

## How the Stop Hook Works

```
Claude finishes responding
        ↓
Stop hook fires → reads stop_hook_active
        ↓
stop_hook_active=true? → exit 0 (allow stop, prevents infinite loop)
        ↓
ROADMAP_COMPLETE in last message? → exit 0 (all done)
        ↓
Iteration limit reached? → {"continue": false, "stopReason": "..."}
        ↓
Next eligible task exists? → {"decision": "block", "reason": "<task brief>"}
        ↓
No eligible tasks, some blocked? → block with investigation prompt
        ↓
All done? → prompt Claude to output ROADMAP_COMPLETE
```

## Logs

Every task produces:
- `logs/TASK-XXX.md` — work log with validation results
- `logs/CHANGELOG.md` — project-level audit trail
- `.roadmap_state.json` — current task + iteration count
- `.context_snapshot.json` — roadmap state for context recovery
- `.reset_TASK-XXX` — boundary marker per completed task
