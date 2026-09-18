# Shipping implementation checklist

Plan: [shipping-plan-2026-09-18.md](shipping-plan-2026-09-18.md).

- [x] M0: preserve operator checkout; reconcile upstream; install dependencies; verify baseline.
- [x] M1: regressions and fixes for hook, state, lifecycle, integration, plans, and wheel assets.
- [x] M2: authoritative serial supervisor, bounded recovery, isolated validated integration.
- [x] M3: normalized idempotent intake and explicit remote delivery policy.
- [x] M4: installed external-project qualification, failure injection, approved real-agent canary (local macOS scope).

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

## M4 independent qualification — canary approval pending

Candidate: **1.1.0rc1**, marked Beta rather than Production/Stable. Final full suite: **285 passed, 1 skipped**; Ruff, mypy (21 files), and ShellCheck pass. The skipped test requires an optional legacy snapshot. The subsequent command-help/initialization guidance edit was checked directly and the final wheel demonstration repeated. The clean-venv wheel test is now part of the regression suite; it verifies import provenance before exercising the installed console script outside the source tree.

Final installed demonstration: `/private/tmp/rr-installed-release-candidate-2026-09-18`. Six selected source items produce four verified local integrations, one actionable needs-input result, and one external blocker. A failed validation is repaired on attempt two; an independent task succeeds after the blocker. Repeated sync and resume are identical. Original branch, HEAD, instructions, settings, and dirty operator content are preserved. Fake usage reservations in this demonstration are accounting fixtures, not model charges.

Evidence, exact wheel hash, candidate commits, gate transcripts, source revisions, and preflight: [shipping-evidence-2026-09-18.json](shipping-evidence-2026-09-18.json). Reproduction: `python tests/qualify_installed.py /path/to/installed/bin/roadrunner /fresh/disposable/directory`.

Real-agent approval was requested for `/private/tmp/roadrunner-real-canary-2026-09-18/project`, with the exact plan/policy/command in its sibling `APPROVAL.md`: three tiny Python implementation tasks (one dependent), two expected input blockers, no remotes; $3 total, $0.50 per attempt, two attempts per executable task, 30 turns per attempt, 120 seconds per attempt, 600 seconds per run. Read-only preflight confirms Claude Code 2.1.277, available authentication, writable state storage, and working macOS sandboxing. **No real-agent invocation has occurred.** Authentication availability is not proof that the isolated adapter will authenticate successfully; the canary must establish that.

Remaining qualification: explicit approval, then the bounded real-agent run and inspection of its integrated tree, gate evidence, usage, and blockers. Real GitHub mutations are separately untested; their mocked contracts do not qualify live service behavior. Linux real-worker isolation is unsupported and fails closed. Native Claude cost-cap behavior remains provider-dependent until canary verification. Full hostile-code containment/read isolation is not claimed; the enforced boundary protects controller/Git/gate writes, validation has no network, and the worker lacks a shell tool.

Original project rechecked: still `main` at `b60e9e8`, with exactly its original changelog diff and untracked shipping plan. All implementation is in the registered `codex/shipping-2026-09-18` worktree at `/private/tmp/roadrunner-shipping-2026-09-18`. No push, release, deployment, real issue change, or remote merge was performed. M4 and the goal remain incomplete pending canary approval and evidence.

## Continuation audit — recovered evidence and frozen-plan integrity

Re-reading the actual implementation found four false-success recovery paths in persisted `integrating` state: stale gate version, missing gate results, substituted commands, and failed results. All four were reproduced by failing regressions before correction. Recovery now validates the complete command/result set, frozen gate version, current attempt identity/base, and commit ancestry before either replaying the ref update or accepting an already-integrated candidate. Remote delivery applies the same validation before any remote access. Stale-attempt evidence is rejected in both `resolved` and `integrating` states.

The audit also reproduced silent reuse of a modified frozen-plan file. Sync now writes plans atomically, rejects contents that do not match their identity, and execution checks the selected internal plan hash. Failure injection proves recovery after an interrupted registry write without duplicate history, and valid integration intent can still recover before a ref update without consuming another attempt.

Updated verification: **295 passed, 1 skipped**, Ruff, mypy (21 files), and ShellCheck passed. The updated wheel repeated the complete installed six-item demonstration at `/private/tmp/rr-installed-recovery-qualified-2026-09-18`; the linked evidence JSON now records its exact hash and attempt-bound candidate evidence. Earlier experimental run records lacking the new attempt-bound evidence fail closed; their success is not inferred or migrated automatically.

The real-Claude canary remains unapproved and unrun. Its disposable target and proposed $3/ten-minute budget are unchanged. The active goal is not complete.

## Approved real-agent canary — authentication defect reproduced and corrected

The user approved the prepared $3/ten-minute canary. Installed run `9a6ef343-9729-48e1-a372-e2aab459544a` executed in the exact disposable target and ended safely without integration. Native Claude reported `Not logged in` on four worker launches: **zero model API duration, zero input/output tokens, $0 reported cost**. Its $2 conservative reservations and consumed attempt records are preserved. Dependent work became blocked; both intentionally incomplete requirements became needs-input. See [real canary evidence](shipping-real-canary-2026-09-18.json).

Cause: replacing `CLAUDE_CONFIG_DIR` with an empty attempt directory selected a different authentication namespace. Worker environment now preserves the operator's namespace read-only; write permissions remain limited to work/scratch paths. Both `doctor` and `run` perform authentication checks inside the same worker sandbox/environment. A failed auth probe blocks all selected work before consuming attempts or reservations. Corrected read-only native preflight succeeds; this does not establish that a model implementation run succeeds.

Verification after the fix: **297 passed, 1 skipped**, Ruff, mypy, ShellCheck, and the updated installed six-item fake-agent demonstration pass. Fixture regressions cover namespace preservation, no-budget/no-attempt auth failure, and structured adapter output through the new probe.

The prepared retry uses the same target and plan, **one additional attempt per executable task, $0.33 per attempt, $0.99 total, 540 seconds**. Aggregate reservations including the failed run would be $2.99, below the original $3. Because task attempt allowances were exhausted, this retry requires an explicit new allowance; none was silently reset. Exact policy and command: `/private/tmp/roadrunner-real-canary-2026-09-18/APPROVAL-RETRY.md`. M4 remains incomplete. No real remote mutations have occurred.

## Approved retry — protected worktree placement corrected

Retry `a2807fe1-d0a5-4d1b-83bf-65798c455783` authenticated and made real API calls, reporting **$0.1891715** usage across two attempts ($0.66 reserved). Both Write calls were denied for task paths beneath `.git`; neither task produced changes or integration. The dependent item was blocked and the two incomplete requirements remained needs-input. Prior records and allowances are unchanged.

[Claude protected-path documentation](https://code.claude.com/docs/en/permission-modes#protected-paths) confirms these writes cannot be auto-approved with the existing permission mode. New runs now allocate private task worktrees outside Git metadata, persist their location, and reuse it during retries/recovery. Controller state, Git writes, and validation gates retain their existing sandbox protections. Native permission denials become specific actionable blockers in the final report. Historical runs retain their original workspace paths; they are not silently relocated or reopened.

The adapter placement regression failed before the correction and passes afterward. **298 passed, 1 skipped**, Ruff, mypy (21 files), and ShellCheck pass. The rebuilt wheel passed the complete six-item installed fake-agent demonstration at `/private/tmp/rr-installed-worktree-qualified-2026-09-18`, including repair, dependency integration, blockers, and idempotent resume/sync. This is not yet proof of native Write success. Temporary task directories must be retained for recovery; their location is recorded in `run.json`.

M0–M3 remain implemented; M4 remains incomplete. Next proposed real canary: same exact disposable project/plan, three new attempts maximum (one per executable task), $0.33 each/$0.99 total, 120 seconds each/540 seconds total, 30 turns each. This requires explicit approval because the approved task-attempt limits are exhausted and aggregate conservative reservations would rise from $2.66 to $3.65. Actual reported usage to date is $0.1891715. See `/private/tmp/roadrunner-real-canary-2026-09-18/APPROVAL-WORKTREE-RETRY.md`. No release, push, remote PR, issue mutation, or deployment has occurred. Original checkout/changelog remain unchanged.

## M4 complete — installed native local workflow qualified

Approved installed-wheel run `38652973-ecd2-4776-b5ec-fc6a26d1919e` completed in **39.79 seconds** with **three verified resolutions and two expected needs-input outcomes**. Native Claude Code 2.1.277 created the normalization function, a dependent slug function importing it, and an independent greeting function. Each used one attempt with no native permission denials. Reported usage was **$0.1849415**, below the approved $0.99 reservation. Across all three approved runs, reported usage is **$0.374113** and conservative reservations total **$3.65**. Failed historical runs and allowances remain intact.

Qualified implementation commit: `d1242d9`. Wheel SHA-256: `e908a54e55d53f960d2f5d6d205e5f9d236794bdefa669a86afe535ef9de1607`. Each resolved item has passing frozen gates bound to its current attempt and candidate. Independent inspection verified merge parents, ancestry, sequential dependency bases, unchanged gate contents, and all three implementation files in final integration commit `1ad14067a397c15174969b485076ff6070e8f13e`. A separate detached checkout passed the final gate plus explicit imports/assertions for every implementation. Resume returned an identical report and byte-identical controller state without additional attempts. Operator branch/HEAD/tree were unchanged; the target has no remotes.

The full current implementation suite remains **298 passed, 1 skipped**, with Ruff, mypy, ShellCheck, and the installed six-item fixture demonstration passing. Only documentation/evidence changed after this verified implementation. The fixture demonstration covers repair on retry and independent work after an external blocker; crash/recovery, cancellation, conflicts, invalid transitions, gate tampering, actual shell hooks, and repeated synchronization are covered by isolated regression contracts. The native canary covers successful real file operations and integration; it does not substitute for those deliberate failure injections.

Evidence: [real canary](shipping-real-canary-2026-09-18.json), [installed qualification](shipping-evidence-2026-09-18.json). Raw logs, all run states, and the final verification checkout are retained beneath `/private/tmp/roadrunner-real-canary-2026-09-18`; native task worktrees are at the recorded `task_work_root`.

M0–M4 are complete for the authorized local macOS release-candidate scope. Remaining limitations: live GitHub push/PR/check/merge/closure behavior has mocked coverage only; Linux real-worker isolation is unsupported; general worker shell execution and hostile-code read isolation are not claimed; provider hard-cap behavior at exhaustion was not exercised by this below-budget canary. No release, deployment, push, real issue mutation, or remote PR merge occurred. Publishing and live remote qualification require separate authorization. Original project/changelog remain preserved. Next: review the focused local commits and evidence before any separately authorized release action.
