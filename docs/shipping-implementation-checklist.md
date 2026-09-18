# Shipping implementation checklist

Plan: [shipping-plan-2026-09-18.md](shipping-plan-2026-09-18.md).

- [x] M0: preserve operator checkout; reconcile upstream; install dependencies; verify baseline.
- [x] M1: regressions and fixes for hook, state, lifecycle, integration, plans, and wheel assets.
- [ ] M2: authoritative serial supervisor, bounded recovery, isolated validated integration.
- [ ] M3: normalized idempotent intake and explicit remote delivery policy.
- [ ] M4: installed external-project qualification, failure injection, approved real-agent canary.

## M0 evidence

Original project remains on `main` at `b60e9e8`. Its pre-existing `logs/CHANGELOG.md` edit, untracked plan, and runtime files are untouched. Remote main checked via `ls-remote` and fetched: `2e61e26`, seven commits ahead, no divergence. Implementation branch `codex/shipping-2026-09-18` starts at that revision in an isolated worktree; all seven commits are reused intact.

An archived upstream tree in `/private/tmp/roadrunner-shipping-evidence` with a dedicated Python 3.12 environment passed **241 tests, 1 skipped**, Ruff, mypy (11 files), and ShellCheck. Existing hook tests mutate their source tree, so they ran only in this disposable archive. No real agent or remote mutation was used.

Remaining drift: operator recipes referenced removed `roadrunner.py` (fixed); dev extras omitted mypy/stubs required by `just ci` (fixed). Historical task checks and documentation still reference the former entrypoint. Upstream still has all seven reviewed correctness gaps; baseline green is not release qualification. Next: M1 regression tests before fixes.

## M1 evidence and limits

Seven subprocess regressions failed before the fixes and passed afterward. Additional regressions cover a real Git merge conflict, fresh retry allowance with preserved lifetime counters, and scaffold parity. Full suite: **251 passed, 1 skipped** (optional snapshot fixture). Hook tests now copy their projects into temporary directories instead of writing the operator checkout. Ruff, mypy, and ShellCheck pass.

A built wheel installed into `/private/tmp/rr-m1-installed` successfully initialized `/private/tmp/rr-m1-external`, including actual hook scripts and `.claude/settings.json`, outside any source checkout. Existing initialization preserves files already present.

Legacy lifecycle now rejects unstarted completion, unresolved dependencies, empty gates, missing task branches, and failed integration; branch setup fails closed. State writes preserve metadata and a new start resets only its retry allowance. These are stabilization fixes: agent-writable legacy YAML remains a trust limitation. M2 must provide frozen controller-owned specifications, attempt identity, integration revision evidence, recovery, and constrained execution before making autonomous resolution claims.
