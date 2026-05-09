# Contributing to Roadrunner

Roadrunner is a small, opinionated control loop: Python owns task selection, validation, and state; Claude Code owns implementation inside a single task boundary. Most changes land in `src/roadrunner/cli.py`, a hook script, or documentation.

If you're unsure whether a change fits, open an issue before writing code.

---

## Dev environment

Roadrunner targets Python **3.10+** on POSIX (macOS and Linux). Windows is not supported.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
just hooks                       # chmod +x hooks/*.sh
```

`-e` gives an editable checkout; `[dev]` adds pytest, ruff, and build.

---

## Local CI gate

```bash
just ci                          # pytest + ruff — same gate CI runs
```

If `just ci` is green, the PR is ready. Ad-hoc runners: `just test`, `just lint`, `pytest tests/test_roadrunner.py::TestStart::test_creates_branch -v`. Auto-format with `ruff format src/ tests/ hooks/` (opt-in). `mypy src` for type-boundary changes.

---

## PR workflow

**Branch naming.** Task branches are auto-created by `roadrunner start <TASK-ID>` as `roadrunner/<TASK-ID>`. For changes outside the roadmap loop, use `docs/…`, `fix/…`, `refactor/…`, `chore/…`.

**Commits.** Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`). For task work, `roadrunner commit <TASK-ID>` generates the message and scopes the commit to `files_expected` + the roadmap overlay.

**Reviewers look for:**

1. **Validation passes.** `roadrunner validate <TASK-ID>` exits 0. The validator is the gate; reviewer taste is the layer on top.
2. **Scope discipline.** Only files in `files_expected` (+ overlay: `logs/`, `tasks.yaml`, `.reset_*`, `.context_snapshot.json`). Out-of-scope drift is the #1 rejection reason.
3. **Tests before code.** New behavior has a test. Bug fixes include a regression test that fails on `main` and passes on the branch.
4. **No backwards-compat cruft.** Renames, deletions, and schema changes should be clean. Aliases only when the schema is versioned (see `STATE_SCHEMA_VERSION`).
5. **Only Stop gates the loop.** `PostToolUse`, `PreCompact`, `PostCompact` are observability hooks — they must exit 0 with no decision JSON.

---

## Adding a subcommand

Two-step change in `src/roadrunner/cli.py`:

1. **Write the handler.** `def cmd_<name>(args: argparse.Namespace) -> None`.
2. **Register in `main()`.** Add `sub.add_parser("<name>")` (with any `add_argument` calls) and `"<name>": cmd_<name>` in the dispatch dict.

```python
def cmd_ping(args: argparse.Namespace) -> None:
    print("pong")

# in main():
sub.add_parser("ping", help="Health check — prints 'pong'")
dispatch = {..., "ping": cmd_ping}
```

Add a unit test in `tests/test_roadrunner.py`. If the command mutates state or touches disk, add an integration test too.

---

## Adding a hook

Hooks live in `hooks/*.sh` and are registered in `.claude/settings.json` under a supported event name (`Stop`, `SessionStart`, `PreCompact`, `PostCompact`, `PostToolUse`). The convention is a thin bash wrapper that delegates to a `roadrunner` subcommand — never business logic in bash.

```bash
#!/usr/bin/env bash
set -euo pipefail
roadrunner my-subcommand
```

Then register in `.claude/settings.json`:

```json
"PostCompact": [{
  "hooks": [{
    "type": "command",
    "command": "bash \"$CLAUDE_PROJECT_DIR\"/hooks/myhook.sh",
    "timeout": 30
  }]
}]
```

`chmod +x hooks/myhook.sh` (or `just hooks`). See [`hooks/postcompact_hook.sh`](hooks/postcompact_hook.sh) as a worked example. Hook decision contracts are documented in [`docs/architecture.md`](docs/architecture.md#2-hook-contracts).

---

## File layout

- `src/roadrunner/` — `cli.py` (commands), `state.py` (atomic state I/O), `session.py` (session summaries). Stdlib + PyYAML only.
- `hooks/*.sh` — thin bash wrappers.
- `.claude/settings.json` — hook registration + permission allowlist.
- `tasks/tasks.yaml` — the roadmap; source of truth for task ordering.
- `tests/` — `test_roadrunner.py` (unit) + `test_hooks.py` (integration) + `tests/smoke/` (cross-session).
- `docs/` — design, workflow, configuration, ADRs, hotfix log.

---

## Getting help

File an issue at <https://github.com/afoxnyc3/roadrunner-cli/issues>. For design questions, read [`docs/architecture.md`](docs/architecture.md) and [`docs/WORKFLOW.md`](docs/WORKFLOW.md) first.
