<p align="center">
  <img src="docs/assets/banner.png" alt="Roadrunner CLI — Deterministic Agentic Loop for Claude Code" width="800" />
</p>

<h1 align="center">Roadrunner CLI</h1>

<p align="center">
  <b>A deterministic agentic loop for Claude Code.</b><br/>
  Python owns control. Claude owns execution. Hooks enforce completion.
</p>

<p align="center">
  <a href="https://github.com/afoxnyc3/roadrunner-cli/actions/workflows/ci.yml"><img src="https://github.com/afoxnyc3/roadrunner-cli/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <img src="https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue" alt="Python" />
  <img src="https://img.shields.io/badge/tests-102%20passing-brightgreen" alt="Tests" />
  <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey" alt="Platform" />
</p>

---

## The Problem It Solves

Large-language-model agents are good at *doing* work. They are notoriously bad at *stopping* work. Tell Claude Code to implement ten tasks and — without external structure — the session will drift, skip steps, declare success without running tests, or loop indefinitely on the same failing attempt. The surface area of "an agent that won't stop making mistakes" is the single biggest reason long-running autonomous coding loops get abandoned.

Roadrunner solves this by refusing to let the agent decide when it's done. A task is done when its `validation_commands` exit zero — not when Claude says so. Roadmap progress happens in a fixed order with explicit dependencies. Every state transition is atomic, logged, and recoverable. If the agent loses context mid-task, it resumes from the on-disk state instead of starting over. If it fails the same task five times in a row, the loop auto-blocks the task and moves on. If the roadmap is genuinely finished, a single sentinel line — `ROADMAP_COMPLETE` — halts the loop cleanly.

The result is a harness you can launch in the morning, walk away from, and come back to a completed project with a full audit trail, instead of a hallucinated half-implementation.

## How It Works

Roadrunner splits responsibility three ways. The split is the whole idea.

- **Python owns control.** A single 1,000-line file, `roadrunner.py`, is the source of truth for what happens next. It selects the next eligible task, runs validation, writes state atomically, decides whether the loop should continue. Claude never decides the order of work; Claude's only job is implementing whatever Python hands it.
- **Claude Code owns execution.** Inside the boundary of one task, Claude does what it does best: reads code, edits files, writes tests, debugs. The operating contract is narrow — stay inside the task's `files_expected`, don't touch anything outside scope, run validation before claiming completion.
- **Hooks enforce completion.** Claude Code's lifecycle hooks — Stop, SessionStart, PreCompact, PostToolUse — bridge the two worlds. The Stop hook is the critical one: after every response, it runs `roadrunner.py check-stop`, and if the roadmap isn't finished it blocks the stop and injects the next task brief. Claude can't quit the loop by accident.

The task queue itself lives in `tasks/tasks.yaml`. Each task declares its goal, acceptance criteria, validation commands, expected files, and dependencies on other tasks. The file is schema-validated on every load, written atomically with `fsync` and `os.replace`, and backed up through a rolling chain of five `.bak` files so a bad edit is always recoverable.

State that needs to survive context compaction lives in `.context_snapshot.json`. When Claude Code is about to compact the conversation, the PreCompact hook dumps the current roadmap state to disk. When the new session starts, the SessionStart hook reads that snapshot back and injects it as context. The loop can survive an arbitrary number of compactions.

## Why Use It

Roadrunner is for one specific scenario: **you want an autonomous coding agent to finish a multi-step project while you sleep, and you want to trust the result when you wake up.**

Concrete differentiators versus an unstructured Claude Code session:

- **Validation is the gate, not the agent's assessment.** A task is not "done" until `pytest tests/foo.py && ruff check src/` exits zero. Claude cannot self-certify.
- **Every run is resumable.** Crash the process mid-task, kill the terminal, let the machine sleep — the next hook fire reads state from disk and picks up exactly where it left off.
- **Retry storms are capped.** After five failed resume attempts on the same task, the task is auto-blocked and the loop moves on instead of burning tokens on a broken premise.
- **Three-layer observability.** `logs/trace.jsonl` gives you machine-readable per-event telemetry. `logs/CHANGELOG.md` is a human-readable audit trail. `logs/TASK-XXX.md` is a per-task work log with full validation output. Post-mortem analysis is always possible.
- **Loss-resistant state.** Tasks file has rolling backups. State file has atomic writes and a `fcntl` advisory lock so concurrent hook fires can't corrupt the iteration counter. The snapshot format is versioned for forward-compat safety.
- **No framework tax.** Two runtime dependencies (PyYAML, pytest). No LangChain, no CrewAI, no vector database. If you can read a 1,000-line Python file, you can read and modify this tool.

Versus alternatives — LangGraph, CrewAI, AutoGen — Roadrunner is not an agent *framework*. It is a *harness* that makes an existing agent (Claude Code) deterministic. If you already love Claude Code and want the loop to be boring and reliable, Roadrunner fits. If you're building a general-purpose multi-agent system from scratch, look elsewhere.

## A Practical Use Case

You've decided to port a Python service to TypeScript. The work breaks down into roughly fifteen discrete migrations — models, API handlers, tests, configuration, deploy scripts — each of which has a clear acceptance test (the corresponding Node test suite passes) and clear dependencies (you can't port the handlers until the models are done).

Without Roadrunner: you either do the fifteen tasks by hand over two weeks, or you ask Claude Code to "port the service" and spend the next session steering it back on track every time it wanders into an adjacent refactor.

With Roadrunner: you write `tasks/tasks.yaml` with fifteen entries, each declaring its files, acceptance criteria, and validation commands. You run `claude` once. Roadrunner feeds Claude TASK-001, waits for validation to pass, feeds TASK-002, and so on. You go to bed. When you wake up, you have a completed migration, a per-task work log, a trace of every decision, and a git branch per task for review. Tasks that genuinely got stuck are marked `blocked` with their error output captured — those are the only ones that need your attention.

The same pattern applies to any sequential project that can be decomposed into validatable steps: a documentation rewrite with tests that check for broken links, a dependency bump with compatibility tests, a security hardening pass with lint rules as the acceptance criteria, a multi-service refactor with an integration test suite as the validation gate.

## Getting Started

```bash
# 1. Clone
git clone https://github.com/afoxnyc3/roadrunner-cli.git
cd roadrunner-cli

# 2. Install the two runtime dependencies
pip3 install -r requirements.txt

# 3. Make the hooks executable
chmod +x hooks/*.sh

# 4. Sanity check
python3 roadrunner.py health
```

You'll see something like `healthy — 6/6 done, 0 eligible, 0 blocked` if you're starting from the shipped demo roadmap. To start your own project, edit `tasks/tasks.yaml` to describe your work and write a fresh `CLAUDE.md` with the operating contract for your project.

## How To Use It End-to-End

> See [docs/WORKFLOW.md](docs/WORKFLOW.md) for end-to-end workflow diagrams covering the five stages, per-task cycle, Stop hook decision tree, and a worked example task DAG.

**Step 1. Describe the work.** Each task in `tasks/tasks.yaml` looks like this:

```yaml
- id: TASK-001
  title: "Port the user model to TypeScript"
  status: todo
  depends_on: []
  goal: "src/models/user.ts exports the same schema as py/models/user.py"
  acceptance_criteria:
    - "src/models/user.ts exists"
    - "npm test -- user.test.ts passes"
  validation_commands:
    - "test -f src/models/user.ts"
    - "npm test -- user.test.ts"
  validation_timeout: 300
  files_expected:
    - "src/models/user.ts"
    - "src/models/user.test.ts"
```

Task IDs must match `[A-Z]+-\d+`. Missing required fields cause a clear load-time error.

**Step 2. Launch Claude Code.** From the project root:

```bash
claude
```

The SessionStart hook injects any stored snapshot. The Stop hook — which runs after every Claude response — consults `roadrunner.py check-stop`, which answers "is the roadmap done?" If not, it injects the next task brief as `additionalContext` and Claude keeps working.

**Step 3. Watch it or walk away.** Set the iteration cap if you want headroom:

```bash
ROADMAP_MAX_ITERATIONS=100 claude
```

The loop halts when (a) Claude outputs `ROADMAP_COMPLETE` on its own line because every task is done, (b) the iteration cap is reached, or (c) you hit Ctrl-C.

**Step 4. Review the output.** Every task produces a work log:

```
logs/CHANGELOG.md             # project-level audit trail
logs/TASK-001.md              # per-task work log with validation output
logs/trace.jsonl              # structured JSON trace, one line per event
```

Tasks that auto-blocked show up in `python3 roadrunner.py status` with a `blocked` status and a note explaining why. Unblock by fixing the underlying issue and setting the status back to `todo`.

## How To Test It Safely

Before pointing Roadrunner at a real project, exercise the shipped demo to get a feel for the loop:

```bash
# Run the full test suite (102 tests, ~1.3 seconds)
python3 -m pytest tests/ -v

# Dry-run validation on one of the demo tasks
python3 roadrunner.py status
python3 roadrunner.py validate TASK-001

# Inspect what the Stop hook would say at this moment
echo '{}' | python3 roadrunner.py check-stop --max-iterations 50 | jq .

# Write a context snapshot and preview what the SessionStart hook emits
python3 roadrunner.py snapshot
python3 roadrunner.py session-start
```

The test suite covers 102 scenarios including state-file corruption, concurrent hook fires, merge-conflict recovery, log rotation, schema version skew, UTF-8 round-tripping, and a shell-injection canary. CI runs the matrix across Python 3.10 / 3.11 / 3.12 on every push.

## Running Overnight

Once the demo is understood, pointing at your own roadmap is the same flow:

```bash
export ROADMAP_MAX_ITERATIONS=100
claude
```

Claude works through the roadmap, validating each task before marking it done, writing logs, and continuing until `ROADMAP_COMPLETE` is output or the iteration cap is hit. Tasks that fail validation five times in a row are auto-blocked.

## Architecture

```
tasks/tasks.yaml              <- the queue (schema-validated, atomically written, rolling .bak)
roadrunner.py                 <- controller: validation, logging, state, stop-check, snapshot, session-start
.claude/settings.json         <- hook registrations: Stop, SessionStart, PreCompact, PostToolUse
hooks/stop_hook.sh            <- loop enforcement: block or allow Claude to stop
hooks/session_start_hook.sh   <- context injection: delegates to `roadrunner.py session-start`
hooks/precompact_hook.sh      <- context snapshot: delegates to `roadrunner.py snapshot`
hooks/post_write_hook.sh      <- lint feedback: ruff on .py, yaml parse on .yaml
CLAUDE.md                     <- agent brief: operating contract for Claude Code
DESIGN.md                     <- full design + ADR index
docs/adr/                     <- 11 ADRs documenting real decisions and fixes
docs/hotfix-log.md            <- append-only ledger of observation-driven hotfixes
```

## Operator Commands

```bash
python3 roadrunner.py status           # see all task states
python3 roadrunner.py next             # see what runs next
python3 roadrunner.py start TASK-001   # mark in_progress
python3 roadrunner.py validate TASK-001 # run validation commands
python3 roadrunner.py complete TASK-001 --notes "did the thing"
python3 roadrunner.py block TASK-001 --notes "why it's stuck"
python3 roadrunner.py reset TASK-001 --summary "boundary marker"
python3 roadrunner.py health           # system check
python3 roadrunner.py snapshot         # write context snapshot manually
python3 roadrunner.py session-start    # emit SessionStart hook JSON (called by the hook)
```

Or via `just`:

```bash
just ci      # full local gate: pytest + ruff
just test    # pytest only
just lint    # ruff only
just status  # roadmap status
just health  # system check
```

## Task Anatomy

```yaml
- id: TASK-001
  title: "Human-readable name"
  status: todo                    # todo | in_progress | done | blocked
  depends_on: []                  # task IDs that must be done first
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

Task IDs must match `[A-Z]+-\d+`. Tasks are schema-validated on load — missing required fields raise an error immediately and the loop refuses to proceed.

## How the Stop Hook Decides

```
Claude finishes responding
        ↓
Stop hook fires → reads stop_hook_active
        ↓
stop_hook_active=true? ────→ exit 0 (allow stop; prevents infinite loop)
        ↓
Iteration limit reached? ──→ hard stop with message
        ↓
ROADMAP_COMPLETE on last line? ─→ exit 0 (all done, audit trail closed)
        ↓
Task in_progress?   ────────→ resume brief (auto-block after 5 attempts)
        ↓
Next eligible todo? ────────→ task brief
        ↓
Tasks blocked?     ─────────→ investigation prompt
        ↓
All done?          ─────────→ prompt Claude to output ROADMAP_COMPLETE
```

## Observability

Every task produces:

- `logs/TASK-XXX.md` — per-task work log with validation output
- `logs/CHANGELOG.md` — project-level audit trail
- `logs/trace.jsonl` — structured JSON trace, one line per lifecycle event
- `.roadmap_state.json` — current task, iteration count, per-task attempt counter, schema version
- `.context_snapshot.json` — roadmap state for context recovery after compaction
- `.reset_TASK-XXX` — boundary marker per completed task

### Retention

`trace.jsonl` and `CHANGELOG.md` are rotated at the task boundary (on `reset`): over 10 MB they rename with a microsecond-precision UTC stamp and gzip in place. Rotated archives older than 7 days are deleted. Per-task work logs (`logs/TASK-XXX.md`) are not rotated — they are authoritative history and stay small. Tune via `LOG_ROTATE_BYTES` and `LOG_RETAIN_DAYS` in `roadrunner.py`.

## Using In Another Project

Copy `roadrunner.py`, the `hooks/` directory, and `.claude/settings.json` into your target project. Create your own `tasks/tasks.yaml` and `CLAUDE.md`. See [DESIGN.md](DESIGN.md) for full setup instructions, data-file schema, and the ADR index.

## Trust Boundary

`tasks.yaml` is executable configuration — `validation_commands` run via `shell=True` with your full privileges. Treat it like a Makefile: only commit tasks whose shell commands you would type yourself. Subprocess timeouts (default 300 s, tunable per task) remove the hanging-command failure mode. The full trust model is documented in [DESIGN.md](DESIGN.md).

## Troubleshooting

### Hooks appear to misbehave / JSON parse errors

Claude Code hooks read structured JSON from stdin. If your `~/.zshrc` or `~/.bashrc` prints output unconditionally — for example, an `echo` that runs on every shell start, or a tool like `direnv` / `nvm` that reports activity — that output is prepended to the JSON payload the hook sees, and hook parsing breaks.

Wrap any such output in an interactive-shell guard so it only runs for a human terminal, not for hook subshells:

```bash
# in ~/.zshrc or ~/.bashrc
if [[ $- == *i* ]]; then
  echo "hello developer"   # only runs for interactive sessions
fi
```

Signs you're hitting this: the Stop hook silently allows the loop to end, or `logs/trace.jsonl` stops receiving `check_stop` events.

### Claude Code refuses pytest / ruff in auto mode

`auto mode` routes every Bash command through a safety classifier. When the classifier is unavailable the commands block. The fix that ships in `.claude/settings.json` adds an allowlist for the specific commands this project runs (pytest, ruff, `just ci`, etc.) so they bypass the classifier entirely.

## Design & Decisions

- [DESIGN.md](DESIGN.md) — full architecture, data-file schema, hook contracts, risk areas.
- [docs/adr/](docs/adr/) — eleven ADRs documenting real defects found and fixes applied, from the line-anchored completion signal through the roadmap-vs-hotfix commit convention.
- [docs/hotfix-log.md](docs/hotfix-log.md) — append-only ledger of observation-driven hotfixes (see [ADR-011](docs/adr/011-roadmap-vs-hotfix-commit-convention.md) for the convention).
