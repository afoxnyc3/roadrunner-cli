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
  <img src="https://img.shields.io/badge/tests-passing-brightgreen" alt="Tests" />
  <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey" alt="Platform" />
</p>

---

## The Problem It Solves

Large-language-model agents are good at *doing* work. They are notoriously bad at *stopping* work. Tell Claude Code to implement ten tasks and — without external structure — the session will drift, skip steps, declare success without running tests, or loop indefinitely on the same failing attempt. The surface area of "an agent that won't stop making mistakes" is the single biggest reason long-running autonomous coding loops get abandoned.

Roadrunner solves this by refusing to let the agent decide when it's done. A task is done when its `validation_commands` exit zero — not when Claude says so. Roadmap progress happens in a fixed order with explicit dependencies. Every state transition is atomic, logged, and recoverable. If the agent loses context mid-task, it resumes from the on-disk state instead of starting over. If it fails the same task five times in a row, the loop auto-blocks the task and moves on. If the roadmap is genuinely finished, a single sentinel line — `ROADMAP_COMPLETE` — halts the loop cleanly.

The result is a harness you can launch in the morning, walk away from, and come back to a completed project with a full audit trail, instead of a hallucinated half-implementation.

## How It Works

Roadrunner splits responsibility three ways. The split is the whole idea.

- **Python owns control.** A small Python package — `roadrunner.cli`, `roadrunner.state`, `roadrunner.session` — is the source of truth for what happens next. It selects the next eligible task, runs validation, writes state atomically, decides whether the loop should continue. Claude never decides the order of work; Claude's only job is implementing whatever Python hands it.
- **Claude Code owns execution.** Inside the boundary of one task, Claude does what it does best: reads code, edits files, writes tests, debugs. The operating contract is narrow — stay inside the task's `files_expected`, don't touch anything outside scope, run validation before claiming completion.
- **Hooks enforce completion.** Claude Code's lifecycle hooks — Stop, SessionStart, PreCompact, PostToolUse — bridge the two worlds. The Stop hook is the critical one: after every response, it runs `roadrunner check-stop`, and if the roadmap isn't finished it blocks the stop and injects the next task brief. Claude can't quit the loop by accident.

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
- **No framework tax.** One runtime dependency (PyYAML); pytest and ruff are dev-only. No LangChain, no CrewAI, no vector database. The whole package is three Python files (`cli`, `state`, `session`) plus a few shell hook shims — readable in an afternoon, modifiable without ceremony.

Versus alternatives — LangGraph, CrewAI, AutoGen — Roadrunner is not an agent *framework*. It is a *harness* that makes an existing agent (Claude Code) deterministic. If you already love Claude Code and want the loop to be boring and reliable, Roadrunner fits. If you're building a general-purpose multi-agent system from scratch, look elsewhere.

## A Practical Use Case

You've decided to port a Python service to TypeScript. The work breaks down into roughly fifteen discrete migrations — models, API handlers, tests, configuration, deploy scripts — each of which has a clear acceptance test (the corresponding Node test suite passes) and clear dependencies (you can't port the handlers until the models are done).

Without Roadrunner: you either do the fifteen tasks by hand over two weeks, or you ask Claude Code to "port the service" and spend the next session steering it back on track every time it wanders into an adjacent refactor.

With Roadrunner: you write `tasks/tasks.yaml` with fifteen entries, each declaring its files, acceptance criteria, and validation commands. You run `claude` once. Roadrunner feeds Claude TASK-001, waits for validation to pass, feeds TASK-002, and so on. You go to bed. When you wake up, you have a completed migration, a per-task work log, a trace of every decision, and a git branch per task for review. Tasks that genuinely got stuck are marked `blocked` with their error output captured — those are the only ones that need your attention.

The same pattern applies to any sequential project that can be decomposed into validatable steps: a documentation rewrite with tests that check for broken links, a dependency bump with compatibility tests, a security hardening pass with lint rules as the acceptance criteria, a multi-service refactor with an integration test suite as the validation gate.

## Getting Started

The fastest path is `pip install` + `roadrunner init` in your target directory:

```bash
# 1. Install
pip install roadrunner-cli

# 2. Scaffold a new project (writes tasks/tasks.yaml, hooks/, .claude/, CLAUDE.md)
roadrunner init my-project
cd my-project

# 3. Sanity check
roadrunner health
```

You'll see something like `healthy — 1/1 done, 0 eligible, 0 blocked` against
the bootstrap demo task. To run a real project, edit `tasks/tasks.yaml` to
describe your work and tailor `CLAUDE.md` to the operating contract you want.

For a complete worked example, see [`docs/examples/hello-roadrunner/`](docs/examples/hello-roadrunner/) —
a three-task demo (function → CLI → tests) you can copy and run end-to-end.

### From source

```bash
git clone https://github.com/afoxnyc3/roadrunner-cli.git
cd roadrunner-cli
pip install -e '.[dev]'    # editable install + pytest + ruff + build
just hooks                 # chmod +x hooks/*.sh
roadrunner health
```

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

The SessionStart hook injects any stored snapshot. The Stop hook — which runs after every Claude response — consults `roadrunner check-stop`, which answers "is the roadmap done?" If not, it injects the next task brief as `additionalContext` and Claude keeps working.

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

Tasks that auto-blocked show up in `roadrunner status` with a `blocked` status and a note explaining why. Unblock by fixing the underlying issue and setting the status back to `todo`.

## How To Test It Safely

Before pointing Roadrunner at a real project, exercise the shipped demo to get a feel for the loop:

```bash
# Run the full test suite (a few seconds)
python3 -m pytest tests/ -v

# Dry-run validation on one of the demo tasks
roadrunner status
roadrunner validate TASK-001

# Inspect what the Stop hook would say at this moment
echo '{}' | roadrunner check-stop --max-iterations 50 | jq .

# Write a context snapshot and preview what the SessionStart hook emits
roadrunner snapshot
roadrunner session-start
```

The test suite covers state-file corruption, concurrent hook fires, merge-conflict recovery, log rotation, schema version skew, UTF-8 round-tripping, and a shell-injection canary. CI runs the matrix across Python 3.10 / 3.11 / 3.12 on every push, plus ruff, mypy, and shellcheck on the hooks.

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
src/roadrunner/cli.py         <- controller: validation, logging, stop-check, snapshot, session-start
src/roadrunner/state.py       <- atomic state I/O with advisory locking and schema versioning
src/roadrunner/session.py     <- per-session summary observability
.claude/settings.json         <- hook registrations: Stop, SessionStart, PreCompact, PostCompact, PostToolUse
hooks/stop_hook.sh            <- loop enforcement: block or allow Claude to stop
hooks/session_start_hook.sh   <- context injection: delegates to `roadrunner session-start`
hooks/precompact_hook.sh      <- context snapshot: delegates to `roadrunner snapshot`
hooks/postcompact_hook.sh     <- snapshot verification: delegates to `roadrunner post-compact`
hooks/post_write_hook.sh      <- lint feedback: ruff on .py, yaml parse on .yaml
CLAUDE.md                     <- agent brief: operating contract for Claude Code
DESIGN.md                     <- full design + ADR index
CONTRIBUTING.md               <- dev setup, PR workflow, recipes for new commands and hooks
CHANGELOG.md                  <- release-facing changelog (per-task audit trail in logs/CHANGELOG.md)
docs/configuration.md         <- every tunable, every schema, env vars, state file layout
docs/release.md               <- PyPI Trusted Publishing setup + per-release checklist
docs/examples/                <- hello-roadrunner end-to-end worked example
docs/adr/                     <- 11 ADRs documenting real decisions and fixes
docs/hotfix-log.md            <- append-only ledger of observation-driven hotfixes
```

## Operator Commands

After `pip install roadrunner-cli` the `roadrunner` console script is on
your PATH. From a source checkout without an install, swap `roadrunner`
for `python -m roadrunner` (or run `pip install -e .` first and use the
console script).

```bash
# Project lifecycle
roadrunner init <dir>            # scaffold a new project (tasks/, hooks/, .claude/, CLAUDE.md)
roadrunner analyze               # validate tasks.yaml: cycles, missing deps, critical path

# Task lifecycle
roadrunner status                # see all task states
roadrunner next                  # see what runs next
roadrunner start TASK-001        # mark in_progress, create roadrunner/TASK-001 branch
roadrunner validate TASK-001     # run validation commands
roadrunner complete TASK-001 --notes "did the thing"
roadrunner commit TASK-001       # scope-aware commit (only files in files_expected + overlay)
roadrunner block TASK-001 --notes "why it's stuck"
roadrunner reset TASK-001 --summary "boundary marker"

# Observability + control
roadrunner watch [--interval N]  # live read-only monitor; redraws every N seconds
roadrunner health                # system check
roadrunner reset-iteration       # reset the session iteration counter (--soft default, --hard nukes lifetime)

# Hook entry points (called by Claude Code; you rarely run these by hand)
roadrunner snapshot              # PreCompact hook — write .context_snapshot.json
roadrunner post-compact          # PostCompact hook — verify the snapshot survived
roadrunner session-start         # SessionStart hook — emit additionalContext JSON
roadrunner check-stop            # Stop hook — decide whether the loop continues
```

Or via `just`:

```bash
just ci      # full local gate: pytest + ruff
just test    # pytest only
just lint    # ruff only
just status  # roadmap status
just health  # system check
just hooks   # chmod +x hooks/*.sh
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

`trace.jsonl` and `CHANGELOG.md` are rotated at the task boundary (on `reset`): over 10 MB they rename with a microsecond-precision UTC stamp and gzip in place. Rotated archives older than 7 days are deleted. Per-task work logs (`logs/TASK-XXX.md`) are not rotated — they are authoritative history and stay small. Tune via `LOG_ROTATE_BYTES` and `LOG_RETAIN_DAYS` in `src/roadrunner/cli.py`.

## Using In Another Project

```bash
pip install roadrunner-cli
roadrunner init my-other-project
```

That writes `tasks/tasks.yaml`, `hooks/`, `.claude/settings.json`, and a
starter `CLAUDE.md` into `my-other-project/`. Edit the tasks file to
describe your work and you're ready to launch `claude`. See
[`docs/examples/hello-roadrunner/`](docs/examples/hello-roadrunner/) for
a complete worked example, [DESIGN.md](DESIGN.md) for architecture and the
ADR index, and [docs/configuration.md](docs/configuration.md) for every
tunable.

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
