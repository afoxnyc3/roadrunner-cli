# Review rules: Roadrunner

Read by Anthropic's Code Review on GitHub and by the `review-gate` plugin in
Claude Code. CONTRIBUTING.md describes the project; this file says what a
reviewer should flag.

## What Important means here

Report as Important only issues that would cause one of these if merged:

- **Loop control breaks.** A Stop hook path that lets Claude stop when work
  remains, blocks forever, ignores `stop_hook_active`, the iteration cap, or
  `.roadrunner_paused`, or emits decision JSON that doesn't match the contract
  in `docs/architecture.md`.
- **State corruption.** Writes to `.roadmap_state.json`, `.context_snapshot.json`
  or `tasks/tasks.yaml` that aren't atomic, skip the lock, or change the schema
  without bumping `STATE_SCHEMA_VERSION`.
- **Git or delivery damage.** Code in `delivery.py` or `cli.py` that can push,
  merge, or delete the wrong branch or commit, skips `--match-head-commit`, or
  treats a failed push or merge as success.
- **Validation bypass.** A task can reach `done` without `roadrunner validate`
  passing, or a validation failure is swallowed.
- **Unsafe shell-out.** Task IDs, notes, branch names, or other values from
  `tasks.yaml` reach a shell without quoting. Exception: `validation_commands`
  run with `shell=True` by design (operator-authored, see SECURITY.md).
- **Observability hooks that gate.** `PostToolUse`, `PreCompact` or `PostCompact`
  hooks that exit non-zero or print decision JSON.
- **Tests that don't test.** A bug fix with no regression test, or a test that
  would pass on `main` without the change.
- **New runtime dependency.** Anything beyond the stdlib and PyYAML outside the `[dev]` extras.
- **CI gap.** Code that passes `mypy src` but fails `mypy src tests --ignore-missing-imports`.

Everything else is a Nit.

## Cap the nits

Report at most three Nits per review. Skip Nits entirely on changes under 20 lines.

## Do not report

- Formatting, import order, and line length. `ruff` owns these.
- Business logic in `hooks/*.sh` wrappers that only call a `roadrunner` subcommand.
- Changes under `logs/`, `.reset_*`, `.context_snapshot.json`, or `CHANGELOG.md`.
- Missing support for Windows or Python below 3.10. Neither is supported.

## Always check

- Task work stays inside the task's `files_expected` plus the roadmap overlay
  (`logs/`, `tasks.yaml`, `.reset_*`, `.context_snapshot.json`).
- New subcommands are registered in `main()`'s dispatch dict and have a test in
  `tests/test_roadrunner.py`.
- New `subprocess` and `git` calls handle a non-zero exit and set a timeout.
- Renames and schema changes leave no compatibility aliases unless the schema is versioned.
