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
  <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey" alt="Platform" />
</p>

---

## The Problem

LLM agents are good at *doing* work and bad at *stopping* work. Tell Claude Code to implement ten tasks and — without external structure — the session will drift, skip steps, declare success without running tests, or loop indefinitely on the same failure. "An agent that won't stop making mistakes" is the single biggest reason long-running autonomous coding loops get abandoned.

Roadrunner refuses to let the agent decide when it's done. A task is done when its `validation_commands` exit zero — not when Claude says so. Roadmap progress happens in a fixed order with explicit dependencies. Every state transition is atomic, logged, and recoverable. If the agent loses context mid-task, it resumes from on-disk state instead of starting over. If it fails the same task five times, the loop auto-blocks the task and moves on. If the roadmap is genuinely finished, a single sentinel line — `ROADMAP_COMPLETE` — halts the loop cleanly.

You launch it in the morning, walk away, and come back to a completed project with a full audit trail.

## How It Works

Three responsibilities, three owners. The split is the whole idea.

- **Python owns control.** `roadrunner.cli`, `roadrunner.state`, `roadrunner.session` are the source of truth for what happens next: select the eligible task, run validation, write state atomically, decide whether the loop continues. Claude never decides task order.
- **Claude Code owns execution.** Inside a task, Claude reads code, edits files, writes tests, debugs. The contract is narrow: stay inside `files_expected`, run validation before claiming completion.
- **Hooks enforce completion.** Claude Code's lifecycle hooks — Stop, SessionStart, PreCompact, PostCompact, PostToolUse — bridge the two worlds. The Stop hook is the critical one: after every response it runs `roadrunner check-stop`, and if the roadmap isn't finished it blocks the stop and injects the next brief.

Tasks live in `tasks/tasks.yaml` (schema-validated, atomic writes, rolling backups). After compaction, Claude Code's own conversation continuity carries the loop forward — and `.context_snapshot.json`, written by PreCompact and verified by PostCompact, gives a cold-resume foothold if the session crashes mid-task. SessionStart reads `tasks.yaml` live each time so a stale snapshot can't poison the next directive.

## Why Use It

For one specific scenario: **you want an autonomous coding agent to finish a multi-step project while you sleep, and you want to trust the result when you wake up.**

- **Validation is the gate, not the agent's assessment.** A task isn't "done" until `pytest tests/foo.py && ruff check src/` exits zero. Claude cannot self-certify.
- **Every run is resumable.** Crash the process, kill the terminal, sleep the machine — the next hook fire reads state from disk and picks up where it left off.
- **Retry storms are capped.** After five failed resume attempts on the same task, the task is auto-blocked and the loop moves on instead of burning tokens.
- **Three-layer observability.** `logs/trace.jsonl` (machine-readable), `logs/CHANGELOG.md` (human-readable audit trail), `logs/TASK-XXX.md` (per-task work log with full validation output).
- **No framework tax.** One runtime dep (PyYAML); pytest and ruff are dev-only. No LangChain, no CrewAI, no vector store. Three Python files plus a few shell hook shims — readable in an afternoon.

Roadrunner is not an agent *framework* — it's a *harness* that makes Claude Code deterministic. If you're building a general-purpose multi-agent system from scratch, look elsewhere.

## Getting Started

```bash
# 1. Install
pip install roadrunner-cli

# 2. Scaffold a project (writes tasks/tasks.yaml, hooks/, .claude/, CLAUDE.md)
roadrunner init my-project
cd my-project

# 3. Sanity check
roadrunner health

# 4. Edit tasks/tasks.yaml to describe your work, then launch Claude
ROADMAP_MAX_ITERATIONS=100 claude
```

The loop halts when (a) Claude outputs `ROADMAP_COMPLETE` on its own line because every task is done, (b) the iteration cap is reached, or (c) you hit Ctrl-C. For a complete worked example, see [`docs/examples/hello-roadrunner/`](docs/examples/hello-roadrunner/).

### From source

```bash
git clone https://github.com/afoxnyc3/roadrunner-cli.git
cd roadrunner-cli
pip install -e '.[dev]'
just hooks                 # chmod +x hooks/*.sh
roadrunner health
```

## Describing Work

Each task in `tasks/tasks.yaml`:

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

Task IDs must match `[A-Z]+-\d+`. Missing required fields fail at load time. Full schema reference: [`docs/configuration.md`](docs/configuration.md).

## Operator Commands

After `pip install roadrunner-cli` the `roadrunner` console script is on your PATH.

```bash
# Project lifecycle
roadrunner init <dir>            # scaffold a new project
roadrunner analyze               # validate tasks.yaml: cycles, missing deps, critical path

# Task lifecycle
roadrunner status                # see all task states
roadrunner next                  # see what runs next
roadrunner start TASK-001        # mark in_progress, create roadrunner/TASK-001 branch
roadrunner validate TASK-001     # run validation commands
roadrunner complete TASK-001 --notes "did the thing"
roadrunner commit TASK-001       # scope-aware commit (only files in files_expected)
roadrunner block TASK-001 --notes "why it's stuck"
roadrunner reset TASK-001 --summary "boundary marker"

# Observability + control
roadrunner watch [--interval N]  # live read-only monitor
roadrunner health                # system check
roadrunner reset-iteration       # reset session counter (--soft default, --hard nukes lifetime)

# Hook entry points (called by Claude Code; rarely run by hand)
roadrunner snapshot              # PreCompact — write .context_snapshot.json
roadrunner post-compact          # PostCompact — verify the snapshot survived
roadrunner session-start         # SessionStart — emit additionalContext JSON
roadrunner check-stop            # Stop — decide whether the loop continues
```

For the full Stop-hook decision tree and end-to-end workflow diagrams, see [`docs/WORKFLOW.md`](docs/WORKFLOW.md).

## Observability

Per-task artifacts:

- `logs/TASK-XXX.md` — per-task work log with validation output
- `logs/CHANGELOG.md` — project-level audit trail
- `logs/trace.jsonl` — structured per-event trace, one JSON line per event

Cross-session state:

- `.roadmap_state.json` — current task, iteration count, attempt counters
- `.context_snapshot.json` — written by PreCompact, verified by PostCompact; cold-resume state for crash recovery

Retention, rotation thresholds, and tunable env vars: [`docs/configuration.md`](docs/configuration.md).

## Trust Boundary

`tasks.yaml` is executable configuration — `validation_commands` run via `shell=True` with your full privileges. Treat it like a Makefile: only commit tasks whose shell commands you would type yourself. Subprocess timeouts (default 300 s, tunable per task) cap the hanging-command failure mode. Full trust model: [`docs/architecture.md`](docs/architecture.md#3-trust-boundary).

## Troubleshooting

**Hooks misbehave / JSON parse errors.** Claude Code hooks read structured JSON from stdin. If `~/.zshrc` or `~/.bashrc` prints output unconditionally — an `echo`, a `direnv` or `nvm` activation banner — that output is prepended to the JSON the hook sees, and parsing breaks. Wrap shell-init output in an interactive-shell guard:

```bash
if [[ $- == *i* ]]; then
  echo "hello developer"   # only runs for interactive sessions
fi
```

Symptoms: the Stop hook silently allows the loop to end, or `logs/trace.jsonl` stops receiving `check_stop` events.

**Claude Code refuses pytest / ruff in auto mode.** Auto mode routes every Bash command through a safety classifier; when the classifier is unavailable the commands block. The fix that ships in `.claude/settings.json` allowlists the specific commands this project runs (pytest, ruff, `just ci`, etc.).

## Design & Decisions

- [`docs/architecture.md`](docs/architecture.md) — control flow, hook contracts, trust model, ADR index.
- [`docs/WORKFLOW.md`](docs/WORKFLOW.md) — end-to-end workflow diagrams.
- [`docs/configuration.md`](docs/configuration.md) — every tunable, schema, env var, state-file layout.
- [`docs/adr/`](docs/adr/) — eleven ADRs documenting real defects and fixes.
- [`docs/hotfix-log.md`](docs/hotfix-log.md) — append-only ledger of observation-driven hotfixes (see [ADR-011](docs/adr/011-roadmap-vs-hotfix-commit-convention.md)).
- [`docs/release.md`](docs/release.md) — PyPI Trusted Publishing setup + release checklist.
