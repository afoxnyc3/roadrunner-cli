# Contributing to Roadrunner

Thanks for the interest. Roadrunner is a small, opinionated control loop:
Python owns task selection, validation, and state; Claude Code owns
implementation inside a single task boundary. Contributions should respect that
split — most changes land in `roadrunner.py`, a hook script, or documentation.

If you are unsure whether a change fits, open an issue before writing code.

---

## Dev environment setup

Roadrunner targets Python **3.10+** on POSIX (macOS and Linux). Windows is
not a supported platform.

### Option 1 — pip editable install (recommended)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

`-e` gives you an editable checkout; `[dev]` installs `pytest` and `ruff`.

### Option 2 — requirements.txt (runtime only)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install pytest ruff        # dev tools not pinned in requirements.txt
```

### Making the hooks executable

Fresh clones need the `.sh` bit set before the hooks will fire:

```bash
just hooks        # or: chmod +x hooks/*.sh
```

---

## Running tests

```bash
pytest tests/ -v
```

The suite is fast (~3 s, 140+ tests). Everything is in-tree; there is no
network, database, or external service. A run that touches hook scripts may
spawn `bash` subprocesses — that is expected.

Run a single file:

```bash
pytest tests/test_roadrunner.py -v
```

Run a single test:

```bash
pytest tests/test_roadrunner.py::TestStart::test_creates_branch -v
```

---

## Running lint

```bash
ruff check roadrunner.py tests/ hooks/
```

Ruff config lives in `pyproject.toml` (`[tool.ruff]`). Line length is **140**;
the rule selection is intentionally narrow (`E`, `F`, `W`). Type checking with
mypy is also configured — run `mypy roadrunner.py` if you touch a non-trivial
type boundary.

Auto-format is opt-in:

```bash
ruff format roadrunner.py tests/ hooks/
```

---

## Running the full CI gate locally

```bash
just ci
```

That shells out to `pytest tests/ -v && ruff check roadrunner.py hooks/ tests/`.
It is the same gate CI runs. If `just ci` is green, your PR is ready.

For ad-hoc combos, the justfile also has `just test`, `just lint`, `just
status`, `just health`, `just snapshot`.

---

## PR workflow

### Branch naming

Task branches are auto-created by `python3 roadrunner.py start <TASK-ID>` and
follow the pattern `roadrunner/<TASK-ID>`. For changes outside the roadmap
loop (e.g., a doc fix), use a descriptive prefix: `docs/…`, `fix/…`,
`refactor/…`, `chore/…`.

### Commit style

Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`,
`test:`). The built-in `python3 roadrunner.py commit <TASK-ID>` subcommand
generates conventional messages automatically and scopes the commit to
`files_expected` + the roadrunner overlay — use it when landing a task.

### What reviewers look for

1. **Validation commands pass.** `python3 roadrunner.py validate <TASK-ID>`
   must exit 0. A passing validator is the gate; reviewer taste is the
   sanity check layered on top.
2. **Scope discipline.** Only files in the task's `files_expected` (+ roadmap
   overlay: `logs/`, `tasks.yaml`, `.reset_*`, `.context_snapshot.json`) are
   touched. Out-of-scope drift is the #1 rejection reason.
3. **Tests before code.** New behavior has a test. Bug fixes include a
   regression test that fails on `main` and passes on the branch.
4. **No backwards-compat cruft.** Renames, deletions, and schema changes
   should be clean — no "deprecated" aliases unless the schema is versioned
   (see `STATE_SCHEMA_VERSION` contract in `docs/configuration.md`).
5. **Hooks never block the loop.** Observability hooks (`PostToolUse`,
   `PreCompact`, `PostCompact`) must exit 0 and never emit decision JSON.
   Only the Stop hook gates continuation.

---

## How to add a new roadrunner subcommand

Every subcommand is a two-step change in `roadrunner.py`:

1. **Write the handler.** Add `def cmd_<name>(args: argparse.Namespace) -> None`
   somewhere in the CLI commands section.
2. **Register it in `main()`.** Two edits:
   - Add a subparser: `sub.add_parser("<name>")` (add `add_argument` calls
     for any flags).
   - Add the handler to the `dispatch` dict: `"<name>": cmd_<name>`.

Example — a trivial `ping` subcommand:

```python
def cmd_ping(args: argparse.Namespace) -> None:
    print("pong")

# in main():
sub.add_parser("ping", help="Health check — prints 'pong'")
# ...
dispatch = {
    # ...
    "ping": cmd_ping,
}
```

Add a test in `tests/test_roadrunner.py` and (if the command mutates state or
touches disk) an integration test too.

---

## How to add a new hook

Claude Code hooks live in `hooks/*.sh` and are registered in
`.claude/settings.json` under one of the supported event names (`Stop`,
`SessionStart`, `PreCompact`, `PostCompact`, `PostToolUse`, etc.). The
convention is:

1. **Write a thin bash wrapper.** It delegates to a Python subcommand and
   never contains business logic. Example skeleton:

   ```bash
   #!/usr/bin/env bash
   # hooks/myhook.sh

   set -euo pipefail
   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
   PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

   python3 "$PROJECT_ROOT/roadrunner.py" my-subcommand
   ```

   - `set -euo pipefail` always.
   - Read stdin with `INPUT=$(cat)` if the hook receives a payload; pipe it
     through to Python, do not parse JSON in bash.
   - Informational hooks (side-effect only) should end with `|| true` and
     `exit 0` so observability failures never break the loop.

2. **Register in `.claude/settings.json`** under the appropriate event key:

   ```json
   "PostCompact": [
     {
       "hooks": [
         {
           "type": "command",
           "command": "bash \"$CLAUDE_PROJECT_DIR\"/hooks/myhook.sh",
           "timeout": 30
         }
       ]
     }
   ]
   ```

3. **Make it executable:** `chmod +x hooks/myhook.sh` (or `just hooks`).

4. **Add a handler in `roadrunner.py`** (see subcommand recipe above) and
   test both layers: unit-test the Python subcommand, integration-test the
   bash wrapper by piping a mock payload through it and asserting exit code
   + trace event.

### Hook decision contract (only Stop and friends)

The Stop hook can emit JSON to gate or halt the agent:

- `{"decision": "block", "reason": "..."}` — soft block, reason injected as
  next-turn context.
- `{"continue": false, "stopReason": "..."}` — hard halt, session
  terminates.

Every other hook is side-effect only and must exit 0 with no decision JSON.
`PostCompact` in particular does **not** support decision control per the
Claude Code hooks reference.

---

## File layout

- `roadrunner.py` — single-file control loop. Pure stdlib + PyYAML.
- `hooks/*.sh` — thin bash wrappers that delegate to Python.
- `.claude/settings.json` — hook registration + permission allowlist.
- `tasks/tasks.yaml` — the roadmap; source of truth for task ordering.
- `tests/` — `test_roadrunner.py` (unit) + `test_hooks.py` (integration).
- `docs/configuration.md` — every tunable, every schema, state file layout.
- `logs/` — work logs, trace.jsonl, rotated archives.

---

## Getting help

File an issue at <https://github.com/afoxnyc/roadrunner-cli/issues>. For
design questions, read `DESIGN.md` and `docs/WORKFLOW.md` first — most
architectural decisions are recorded there or in `docs/adr/`.
