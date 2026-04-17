# Roadrunner CLI

Deterministic agentic loop for Claude Code. Python owns control. Claude owns execution. Hooks enforce completion.

## Architecture

```
tasks/tasks.yaml          <- the queue (schema-validated, atomically written)
roadrunner.py             <- controller: validation, logging, state, stop-check
.claude/settings.json     <- hooks: Stop, SessionStart, PreCompact, PostToolUse
hooks/stop_hook.sh        <- loop enforcement: block or allow Claude Code to stop
hooks/session_start_hook.sh <- context injection: injects roadmap snapshot on start
hooks/precompact_hook.sh  <- context snapshot: persists state before compaction
hooks/post_write_hook.sh  <- lint feedback: ruff on .py, yaml parse on .yaml
CLAUDE.md                 <- agent brief: operating contract for Claude Code
```

## Quick Start

```bash
# 1. Clone the repository
git clone <repo-url> roadrunner-cli
cd roadrunner-cli

# 2. Install dependencies
pip3 install -r requirements.txt

# 3. Make hooks executable
chmod +x hooks/*.sh

# 4. Verify setup
python3 roadrunner.py health

# 5. Check what's next
python3 roadrunner.py status

# 6. Launch Claude Code — the loop takes over
claude
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
limit is hit. Tasks that fail validation 5 times are auto-blocked.

## Operator Commands

```bash
python3 roadrunner.py status           # see all task states
python3 roadrunner.py next             # see what runs next
python3 roadrunner.py start TASK-001   # mark in_progress
python3 roadrunner.py validate TASK-001  # run validation commands
python3 roadrunner.py complete TASK-001 --notes "did the thing"
python3 roadrunner.py block TASK-001 --notes "why it's stuck"
python3 roadrunner.py reset TASK-001 --summary "boundary marker"
python3 roadrunner.py health           # system check
python3 roadrunner.py snapshot         # write context snapshot manually
python3 roadrunner.py session-start    # emit SessionStart hook JSON (called by the hook)
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
  validation_timeout: 300          # seconds per command (default: 300)
  documentation_targets:
    - "CHANGELOG.md"
    - "logs/TASK-001.md"
  files_expected:
    - "src/feature.py"
  notes: "Operator annotations"
```

Tasks are schema-validated on load — missing `id`, `status`, or `title` fields raise an error immediately. Task IDs must match `[A-Z]+-\d+` (e.g., `TASK-001`).

## How the Stop Hook Works

```
Claude finishes responding
        |
Stop hook fires -> reads stop_hook_active
        |
stop_hook_active=true? -> exit 0 (allow stop, prevents infinite loop)
        |
Iteration limit reached? -> hard stop with message
        |
ROADMAP_COMPLETE on last line? -> exit 0 (all done)
        |
Task in_progress? -> resume brief (auto-block after 5 attempts)
        |
Next eligible todo? -> task brief
        |
Tasks blocked? -> block with investigation prompt
        |
All done? -> prompt Claude to output ROADMAP_COMPLETE
```

## Logs and Observability

Every task produces:
- `logs/TASK-XXX.md` — work log with validation results
- `logs/CHANGELOG.md` — project-level audit trail
- `logs/trace.jsonl` — structured JSON trace log (one line per lifecycle event)
- `.roadmap_state.json` — current task, iteration count, per-task attempt counter
- `.context_snapshot.json` — roadmap state for context recovery after compaction
- `.reset_TASK-XXX` — boundary marker per completed task

### Log retention

`trace.jsonl` and `CHANGELOG.md` are rotated at the task boundary (each `reset`):
when either exceeds 10 MB, it is renamed with a UTC timestamp suffix and gzipped
in place. Rotated archives older than 7 days are deleted automatically. Per-task
work logs (`logs/TASK-XXX.md`) are not rotated — they are authoritative per-task
history and expected to stay small.

Tune by editing `LOG_ROTATE_BYTES` and `LOG_RETAIN_DAYS` in `roadrunner.py`.

## Tests

```bash
python3 -m pytest tests/ -v
```

Unit and subprocess-level integration tests across `tests/test_roadrunner.py`
and `tests/test_hooks.py` covering:

- Schema validation (task ID format, validation timeout)
- Eligibility (including circular-dependency behaviour)
- Completion signal detection
- State management, atomic saves, rolling task backups
- Validation execution including subprocess timeout
- `check-stop` logic (resume, auto-block, iteration cap)
- Trace logging, log rotation, log retention
- Task-brief generation
- Error handling (corrupt YAML, unreadable state, failed log writes)
- Git branching (clean merge, merge-conflict abort, missing branch)
- Crash-recovery mid-task (start → kill → resume via on-disk state)
- Hook integration (Stop, SessionStart, PreCompact, PostToolUse) including a
  shell-injection canary.

## Using in Another Project

Copy `roadrunner.py`, the `hooks/` directory, and `.claude/settings.json` into your target project. Create your own `tasks/tasks.yaml` and `CLAUDE.md`. See [DESIGN.md](DESIGN.md) for full setup instructions and architecture details.

## Trust Boundary

`tasks.yaml` is executable configuration — `validation_commands` run via `shell=True` with your full privileges. Treat it like a Makefile. See [DESIGN.md](DESIGN.md) for details.

## Troubleshooting

### Hooks appear to misbehave / JSON parse errors

Claude Code hooks read structured JSON from stdin. If your `~/.zshrc` or
`~/.bashrc` prints output unconditionally — for example, an `echo` that runs on
every shell start, or a tool like `direnv`/`nvm` that reports activity — that
output is prepended to the JSON payload the hook sees, and hook parsing breaks.

Wrap any such output in an interactive-shell guard so it only runs for a human
terminal, not for hook subshells:

```bash
# in ~/.zshrc or ~/.bashrc
if [[ $- == *i* ]]; then
  echo "hello developer"   # only runs for interactive sessions
fi
```

Signs you are hitting this: the Stop hook silently allows the loop to end, or
`logs/trace.jsonl` stops receiving `check_stop` events.

### Tests

```bash
just test          # pytest
just lint          # ruff
just ci            # both (same command CI runs)
```
