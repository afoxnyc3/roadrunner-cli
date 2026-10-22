# Review rules: Roadrunner

Read by Anthropic's Code Review on GitHub and by the `review-gate` plugin in
Claude Code. CONTRIBUTING.md describes the project; this file says what a
reviewer should flag.

## What Important means here

Report as Important only issues that would cause one of these if merged:

- **Loop control breaks.** A Stop hook path that lets Claude stop when work
  remains, blocks forever, bypasses the iteration cap, per-task auto-block, or
  `.roadrunner_paused`, or emits both `decision` and `continue: false` in one
  payload. `cmd_check_stop` in `cli.py` is the source of truth for how
  `stop_hook_active` is handled (a hint, not an early exit); where
  `docs/architecture.md` disagrees, the code wins.
- **State corruption.** A write to `.roadmap_state.json` that skips
  `STATE_LOCK` or isn't atomic. A change that makes any state, snapshot or
  `tasks.yaml` write less safe than it is today. A format change without
  bumping its version constant (`STATE_SCHEMA_VERSION` in `state.py`,
  `SNAPSHOT_SCHEMA_VERSION` in `cli.py`). The existing unlocked writes in
  `save_tasks` and `write_context_snapshot` are known; don't flag them unless
  the change touches them.
- **Git or delivery damage.** Code in `delivery.py` or `cli.py` that can push,
  merge, or delete the wrong branch or commit, skips `--match-head-commit`, or
  treats a failed push or merge as success.
- **Validation bypass.** A task can reach `done` without `roadrunner validate`
  passing, or a validation failure is swallowed.
- **Unsafe shell-out.** Task IDs, notes, branch names, or other values from
  `tasks.yaml` reach a shell without quoting, or a new code path passes
  `tasks.yaml` content to `shell=True`. The existing `validation_commands`
  runner is the one intended shell entry point; flag changes that widen what
  reaches it. Untrusted `tasks.yaml` input is in scope per SECURITY.md.
- **Non-Stop hooks that gate.** `SessionStart`, `PostToolUse`, `PreCompact` or
  `PostCompact` hooks that exit non-zero or print decision JSON. Only Stop gates
  the loop.
- **Tests that don't test.** A bug fix with no regression test, or a test that
  would pass on `main` without the change.
- **New runtime dependency.** Anything beyond the stdlib and PyYAML outside the `[dev]` extras.
- **CI gap.** Code that passes `mypy src` but fails `mypy src tests --ignore-missing-imports`.

Everything else is a Nit.

## Cap the nits

Report at most three Nits per review. Skip Nits entirely on changes under 20 lines.

## Do not report

- Formatting, import order, and line length. `ruff` owns these.
- Changes under `logs/`, `.reset_*`, `.context_snapshot.json`, or `CHANGELOG.md`.
- Missing support for Windows or Python below 3.10. Neither is supported.

## Always check

- Task work stays inside the task's `files_expected` and
  `documentation_targets`, plus the commit overlay defined by
  `_COMMIT_OVERLAY_PREFIXES` in `cli.py` (`logs/`, `tasks/tasks.yaml*`, `.reset_*`).
- New logic in hook scripts (`hooks/*.sh` and their copies in
  `src/roadrunner/scaffold/hooks/`) goes into a `roadrunner` subcommand, not
  bash. Existing shell checks such as the pause toggle are fine.
- New subcommands are registered in `main()`'s dispatch dict and have a test in
  `tests/test_roadrunner.py`.
- New `subprocess` and `git` calls handle a non-zero exit and set a timeout.
- Renames and schema changes leave no compatibility aliases unless the schema
  is versioned. Exception: `tasks.yaml` is unversioned and user-authored, so
  existing keys must keep working.
