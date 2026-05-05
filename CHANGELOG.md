# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> The internal per-task audit trail lives in [`logs/CHANGELOG.md`](logs/CHANGELOG.md);
> this file is the release-facing summary.

## [Unreleased]

### Removed

- **`requirements.txt`** — deleted the four-line backward-compat shim
  (`-e .[dev]`). All install instructions now point directly to
  `pip install -e .[dev]` (full dev setup) or `pip install -e .` (runtime
  only). CI workflows updated to use `cache-dependency-path: pyproject.toml`.

### Changed

- **Documentation cleanup for v1.0 ship** — `README.md` 358→173 lines,
  `CONTRIBUTING.md` 239→108, `docs/architecture.md` 449→159 by linking
  out to `docs/` for deep-dive content instead of duplicating it. The
  `architecture.md` April-15 risk register (all items "FIXED") removed —
  current risks track via ADRs and `docs/hotfix-log.md`. The stale "copy-in
  vs external runner" embedding guidance and resolved open questions also
  dropped from `architecture.md` (pip install + `roadrunner init` is the
  shipping path). The PostCompact hook contract added to `architecture.md`
  §2.4 (hook shipped in ROAD-005 but was undocumented).
- **Frozen historical reviews moved to `docs/history/`** —
  `code-review-audit.md` and `architecture-review-2026-04-15.md` now live
  under `docs/history/` with a "historical snapshot" banner so readers
  don't mistake them for current design docs. Their internal `DESIGN.md`
  references are preserved as part of the original record.
- **Documentation layout** — `DESIGN.md` moved to `docs/architecture.md`.
  Reduces the root file count and groups architectural reference
  material with the rest of the design docs (ADRs, configuration,
  workflow). Active links in `README.md`, `CONTRIBUTING.md`,
  `docs/WORKFLOW.md`, and `hooks/README.md` updated.

### Fixed

- Stale references to `docs/resolution-plan-2026-04-24.md` (file no
  longer in the working tree) scrubbed from
  `.github/workflows/weekly-smoke.yml` and `src/roadrunner/session.py`
  module docstring. ADR-011's reference is left intact — it already
  hedges with "when present in working tree" and ADRs are append-only.
- **Package layout** — moved the flat-module trio (`roadrunner.py`,
  `rr_state.py`, `rr_session.py`) into a proper `src/roadrunner/` package
  (`cli.py`, `state.py`, `session.py`) with `__init__.py` and
  `__main__.py`. The `roadrunner` console script and `python -m roadrunner`
  are the canonical entry points; the file-based fallback the hooks used
  to honour (`python3 $PROJECT_ROOT/roadrunner.py`) is gone. `import
  roadrunner; roadrunner.foo` and `monkeypatch.setattr(roadrunner, ...)`
  continue to work via a `sys.modules` alias to the cli module so legacy
  callers and tests are unaffected.
- Path resolution — `ROOT` and `STATE_FILE`/`STATE_LOCK` now resolve from
  `CLAUDE_PROJECT_DIR` (set by the hooks) with a `cwd()` fallback,
  replacing the old `Path(__file__).parent` anchor that worked only when
  the file lived at the project root.

## [1.0.0] - 2026-04-25

### Added

- **`roadrunner watch`** — read-only live monitor that polls disk state on a
  configurable interval and renders a status frame (iteration, active task,
  task counts, last 5 trace events, elapsed time). Stdlib only; clean Ctrl-C
  exit. (ROAD-007)
- **PostCompact hook** — fires after Claude Code completes context compaction;
  verifies `.context_snapshot.json` survived and logs a `post_compact_verify`
  trace event with trigger and compact summary. (ROAD-005)
- **PyPI publish workflow** — `.github/workflows/publish.yml` triggers on
  `v*` tag pushes (and via `workflow_dispatch` for rehearsal). Uses OIDC
  Trusted Publishing through `pypa/gh-action-pypi-publish` — no API tokens
  in repo secrets. See [`docs/release.md`](docs/release.md) for setup.
  (ROAD-008)
- **`docs/examples/hello-roadrunner/`** — end-to-end three-task worked
  example (word-counter CLI) so new users can copy → `roadrunner init` →
  `claude` and watch the loop complete a real demo. (ROAD-009)
- **`CONTRIBUTING.md`** at the repo root — dev setup, tests/lint/CI gate, PR
  workflow, and recipes for adding subcommands and hooks. (ROAD-006)
- **`docs/configuration.md`** extended — full tunables table, env vars,
  `tasks.yaml` field reference, and on-disk schemas for both state files.
  (ROAD-006)
- **Per-session iteration counter** (`session_iteration`) with reset on every
  `SessionStart` hook fire; gates the runaway-protection cap so long-lived
  projects don't accumulate iterations across sessions. State schema bumped
  to v2 with backward-compatible `setdefault` migration. (ROAD-010)
- **`build>=1.0`** added to dev dependencies for local release rehearsal.
- **Top-level `LICENSE` file** (MIT, matching `pyproject.toml`).
- **Top-level `CHANGELOG.md`** (this file).

### Changed

- README operator-commands list refreshed to include `init`, `analyze`,
  `commit`, `reset-iteration`, `watch`, and `post-compact`.
- README architecture block now lists `PostCompact` alongside the other
  hooks.
- README install/usage docs reference the published `pip install
  roadrunner-cli` + `roadrunner` console-script entry point.

### Fixed

- Repo URLs corrected to match the actual GitHub remote
  `afoxnyc3/roadrunner-cli` (pyproject.toml previously had a typo'd
  `afoxnyc/...`; README, CONTRIBUTING.md, and docs/release.md aligned).
- `.gitignore` now covers `build/`, `dist/`, `*.egg-info/`, `.mypy_cache/`,
  and `.ruff_cache/`.

## [0.0.1] — pre-release

Initial development. See `git log` for full history before the changelog
was started.

[Unreleased]: https://github.com/afoxnyc3/roadrunner-cli/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/afoxnyc3/roadrunner-cli/releases/tag/v1.0.0
