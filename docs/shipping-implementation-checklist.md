# Shipping implementation checklist

Plan: [shipping-plan-2026-09-18.md](shipping-plan-2026-09-18.md).

- [x] M0: preserve operator checkout; reconcile upstream; install dependencies; verify baseline.
- [x] M1: regressions and fixes for hook, state, lifecycle, integration, plans, and wheel assets.
- [x] M2: authoritative serial supervisor, bounded recovery, isolated validated integration.
- [x] M3: normalized idempotent intake and explicit remote delivery policy.
- [ ] M4: installed external-project qualification, failure injection, approved real-agent canary.

## M0 evidence

Original project remains on `main` at `b60e9e8`. Its pre-existing `logs/CHANGELOG.md` edit, untracked plan, and runtime files are untouched. Remote main checked via `ls-remote` and fetched: `2e61e26`, seven commits ahead, no divergence. Implementation branch `codex/shipping-2026-09-18` starts at that revision in an isolated worktree; all seven commits are reused intact.

An archived upstream tree in `/private/tmp/roadrunner-shipping-evidence` with a dedicated Python 3.12 environment passed **241 tests, 1 skipped**, Ruff, mypy (11 files), and ShellCheck. Existing hook tests mutate their source tree, so they ran only in this disposable archive. No real agent or remote mutation was used.

Remaining drift: operator recipes referenced removed `roadrunner.py` (fixed); dev extras omitted mypy/stubs required by `just ci` (fixed). Historical task checks and documentation still reference the former entrypoint. Upstream still has all seven reviewed correctness gaps; baseline green is not release qualification. Next: M1 regression tests before fixes.

## M1 evidence and limits

Seven subprocess regressions failed before the fixes and passed afterward. Additional regressions cover a real Git merge conflict, fresh retry allowance with preserved lifetime counters, and scaffold parity. Full suite: **251 passed, 1 skipped** (optional snapshot fixture). Hook tests now copy their projects into temporary directories instead of writing the operator checkout. Ruff, mypy, and ShellCheck pass.

A built wheel installed into `/private/tmp/rr-m1-installed` successfully initialized `/private/tmp/rr-m1-external`, including actual hook scripts and `.claude/settings.json`, outside any source checkout. Existing initialization preserves files already present.

Legacy lifecycle now rejects unstarted completion, unresolved dependencies, empty gates, missing task branches, and failed integration; branch setup fails closed. State writes preserve metadata and a new start resets only its retry allowance. These are stabilization fixes: agent-writable legacy YAML remains a trust limitation. M2 must provide frozen controller-owned specifications, attempt identity, integration revision evidence, recovery, and constrained execution before making autonomous resolution claims.

## M2 evidence and supported boundary

`roadrunner run --project ... --plan ... --policy ...` drains a serial frozen plan into a dedicated local integration ref, preserving the operator checkout. `--resume UUID` reconciles persisted integration intent and retains consumed attempts, reserved cost allowance, and the original run deadline. Completion requires exact candidate commit validation followed by a compare-and-swap ref update. Logs retain full worker and gate output. No model sentinel or legacy YAML status releases dependencies.

**264 passed, 1 skipped**, including real subprocess tests for dependent tasks, validation repair, independent work after ambiguity, policy/gate tampering, invalid transitions, timeout, cancellation, SIGKILL recovery, interrupted integration reconciliation, changed integration refs, and operator dirty-file preservation. The macOS sandbox test proves denied writes to controller data and gate files, and an external-project fake-agent run succeeds under that sandbox. A pipe watchdog kills the worker process group if the controller dies.

Current supported real-worker host: macOS with working `sandbox-exec`. Unsupported hosts fail closed. The fixture adapter is explicitly marked in reports and only for trusted disposable tests. Claude's tool set excludes shell execution; controller-owned validation runs shell commands under the write sandbox. Agent cost is bounded by per-attempt native caps with conservative non-refundable reservations across retries/restarts. Real-Claude compatibility/authentication and usage enforcement remain unqualified pending the approved M4 canary. Adapter flags were checked against installed Claude 2.1.277 help and the official CLI reference. Next: normalized source intake and remote delivery policy.

## M3 evidence and remote qualification limits

`sync` supports local YAML, Markdown with one fenced YAML task block, and read-only GitHub issue selection by number/label/milestone. Stable source IDs and revision hashes produce idempotent frozen plans. Edits/reopens require explicit revision approval; external closure never becomes controller resolution. Issue text cannot supply executable gates. Missing acceptance/scope becomes actionable `needs_input`.

`deliver` prepares by default. Execution requires separate explicit push/PR/merge/closure capabilities. It rediscovers PRs on retry, binds checks to exact head/base, requires remote merge ancestry and an identical validated tree, and verifies source revision and closure. Local resolution and remote delivery phases remain separate.

Full suite: **278 passed, 1 skipped**. Fourteen new intake/delivery contracts cover repeated/edited/reopened sources, Markdown IDs, frozen execution, no-mutation preparation, push failure, missing/failing/duplicate checks, PR-only non-resolution, rediscovery, and verified merge. GitHub contracts use mocks; no real push, PR, merge, or issue mutation has been performed. Production remote qualification remains untested and requires explicit authorization. A preflight `doctor` is also available; M4 will qualify the installed journey and document supported limits.
