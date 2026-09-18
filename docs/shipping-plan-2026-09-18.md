# Roadrunner shipping plan — corrected-project review

Reviewed September 18, 2026. Project: `/Users/alex/dev/projects/roadrunner-cli`.

## Decision: revise the existing plan; keep its five priorities

The intended product remains: open a project, select its issues or roadmap, and let Roadrunner execute the SDLC until each selected item is either verifiably resolved or explicitly blocked.

The previous plan's architecture and sequencing still apply. This is a revision with a corrected baseline, additional reproduced defects, and an immediate stabilization milestone. It supersedes the plan in `/Users/alex/tmp/roadrunner-cli/docs/shipping-plan-2026-09-18.md` for work in this project.

Roadrunner already has useful scheduling, validation, Git, and recovery components. The missing product capability is a reliable controller-owned execution and delivery loop. Determinism should mean guarded transitions, repeatable selection rules, bounded attempts, and evidence-backed outcomes; it cannot guarantee that every issue is solvable or that generated code is deterministic.

## Which version is actually here?

| Baseline | Revision | Meaning |
| --- | --- | --- |
| Initially supplied temporary checkout | `9dd5b7a`, April 17 | Original single-file version. Not the implementation baseline. |
| Corrected project reviewed here | `b60e9e8566f7d9c36bed9fe7cf09e7d0bad42147`, May 9 | Packaged controller with initialization, analysis, scoped commits, sessions, watch, and pause/resume. |
| GitHub main, independently rechecked | `2e61e2636acf0b623f91f24b6180321e99e9af0d`, May 30 | Seven commits ahead of this project; includes additional features and fixes. |

GitHub's compare API reports no divergence: main is seven commits ahead of this revision. The only pre-existing tracked working-tree modification is `logs/CHANGELOG.md`; it was preserved. No pull, checkout, merge, or production-code change was performed.

The prior plan already examined May 30 main, which is why most recommendations survive the corrected path. However, features available there must not be described as already present here.

### Reuse versus restore versus build

| Capability | Corrected project | Next action |
| --- | --- | --- |
| Packaging, `init`, `analyze`, root discovery | Present | Reuse; fix installed scaffold assets and require analysis before execution. |
| Atomic state writes, locks, schema versioning | Present | Extend to all lifecycle transitions and cross-operation recovery. |
| Session summaries, live watch, pause/resume, per-session iteration cap | Present | Reuse; distinguish resumable state from an autonomous process supervisor. |
| Scoped commits, task branches, configurable push | Present | Reuse helpers; make successful integration a completion condition. |
| Cost-cap handling, model hints, learnings log, session-ID resume | Upstream only | Reconcile the seven commits rather than reimplement. Model hints remain advisory; upstream cost handling permits unenforced operation when telemetry is missing. |
| Project-wide baseline validation, work-log prose preservation, CI recipe fix | Upstream only | Bring forward before new implementation. |
| Controller-owned `run`, issue ingestion, normalized plans, PR/check/closure lifecycle | Missing here and in inspected upstream | Build. |

## Findings verified against this project

### Release blockers

1. **The real Stop hook bypasses the controller's continuation fix.** `hooks/stop_hook.sh:48` exits immediately when `stop_hook_active=true`. In contrast, `src/roadrunner/cli.py:1238` checks whether work remains. With an eligible task, the Python command emitted `decision:block`, while the actual shell hook emitted nothing and exited 0. The hook can therefore permit termination while work remains.

   **Correction to the prior analysis:** the claim that upstream fixed this early exit was incomplete. The Python fix exists, but the May 30 shell wrapper retains the same bypass. Merely syncing main will not fix the end-to-end path. Preserve the explicit pause bypass while making one component authoritative for continuation.

2. **A model message can falsely complete a roadmap.** Reproduced `check-stop` accepting the completion sentinel with a pending task and writing a completion entry. The sentinel branch precedes unfinished-task checks (`src/roadrunner/cli.py:1328`).

3. **Completion bypasses lifecycle and dependency guards.** Reproduced `complete TASK-001` marking an unstarted task done despite an unknown prerequisite and no validation commands. `cmd_complete` does not require the active attempt or satisfied dependencies (`src/roadrunner/cli.py:794`).

4. **Failed Git integration still reports success.** In an isolated real Git repository, created conflicting task/base commits, then invoked `complete`. Result: exit 0, task status `done`, success message, and a logged merge error. Status is persisted before merging, and merge failure does not invalidate it (`src/roadrunner/cli.py:809`).

5. **State updates erase the saved base branch.** Reproduced a Stop cycle deleting `base_branch: release`. `write_state` reconstructs state without retaining that field unless callers pass it again (`src/roadrunner/state.py:117`); completion then defaults to `main`.

6. **Retry recovery can immediately block again.** Seeded five prior attempts, returned the task to `todo`, started it, then fired Stop. It auto-blocked at attempt six. Starting does not reset the retry allowance; attempts measure Stop resumptions rather than completed failed attempts (`src/roadrunner/cli.py:734`, `:1340`).

7. **Installed initialization omits required hook assets.** Built this version's wheel, extracted it outside the repository, and invoked its `init`. It exited 0 and created the task file, but created neither `hooks/` nor `.claude/settings.json`. `_find_template_source` relies on checkout directories excluded from the wheel (`src/roadrunner/cli.py:1590`).

### Additional gaps that matter to shipping

- **Task/control integrity:** statuses, dependencies, scope, and validation commands share agent-writable YAML. Commit scope checks do not protect execution state or test policy. No enforced separation between the worker and its completion authority.
- **Invalid plans can enter execution:** duplicate IDs were accepted and reported as healthy. Dependency analysis exists, but normal lifecycle commands do not require its successful result. Single-active-task enforcement is missing.
- **Recovery is incomplete:** individual atomic file writes do not make YAML, state, logs, and Git one recoverable operation. Only some writers hold the state lock. Malformed control data needs explicit failure outcomes rather than incidental hook errors.
- **Execution is not bounded comprehensively:** iteration limits do not bound a long agent turn. Validation uses shell subprocess timeouts without explicit descendant-group cleanup. There is no run-level deadline or cost budget in this checkout. Validation output is buffered, then reduced to 500-character excerpts.
- **Local commands have drifted:** `justfile` references removed `roadrunner.py`; its lint command reproduces an `E902` missing-file error and its CI recipe omits mypy. Historical roadmap checks also reference the removed file. Several command recipes remain candidates for repair even after bringing forward upstream's CI fix.
- **Completion instructions omit a durable delivery sequence:** `CLAUDE.md` tells the agent to validate, complete, and reset, but does not require committing before completion. The controller must own and enforce that ordering.
- **No backlog delivery integration:** task import, stable source mapping, PR creation/check tracking, merge-policy enforcement, and verified source closure are absent. A successful local merge or push is not an issue-resolution workflow.

## Top five recommendations

### 1. Make state transitions and completion authoritative — P0

Fix the hook/controller disagreement, false sentinel completion, lost metadata, invalid plans, and retry semantics first. Require an eligible task to be claimed exactly once; completion must belong to the current attempt and pass the frozen gate policy.

Separate immutable/versioned task specifications from execution state. Use explicit phases: `ready → running → validating → integrating → resolved`, with `blocked`, `needs_input`, `failed`, and `cancelled` outcomes. A PR awaiting merge is unfinished work, not resolved work.

Protect authoritative state and validation policy from worker edits. A tool hook alone is insufficient if unrestricted shell access can modify the same files. A worktree isolates Git changes but is not by itself a security boundary. Use a constrained worker environment when enforcement is part of the product guarantee.

Persist attempts and operation intents so interruption can be reconciled. SQLite is one reasonable implementation option, not a prerequisite to the immediate fixes; database transactions still do not atomically include Git/network operations.

**Exit gate:** no sentinel, invalid transition, edited status, weakened validation policy, stale request, or interrupted operation can produce false resolution.

### 2. Build a supervisor that owns the entire run — P0

Implement `roadrunner run`: select ready work, prepare an attempt, invoke Claude, capture structured results, validate independently, retry or block, integrate, and continue. Use one supported agent adapter and serial tasks initially. Hooks provide context and feedback; the outer process owns continuation and recovery.

Record run/attempt/session IDs, base revision, timestamps, outcome, and stop reason. Add attempt and run deadlines, cancellation, process cleanup, bounded retries, and no-progress detection. Separate infrastructure/authentication failures from failed implementations. Preserve total consumed budgets across recovery, even when a specific task receives an explicit new retry allowance.

**Exit gate:** one command drains an eligible local roadmap without another user prompt; a forced restart resumes accurately; one blocked task does not prevent independent tasks; the final report distinguishes all-resolved from finished-with-blockers.

### 3. Make validated integration a required delivery stage — P0

Use isolated task worktrees from a recorded integration revision. Preserve the operator's checkout. Controller-owned scope inspection, commit creation, validation, and integration must happen in a defined order. Reject failed branch preparation instead of continuing from an accidental HEAD.

Bind validation evidence to the exact candidate revision and gate version. Revalidate when the merge candidate changes. Preserve failed worktrees for repair. Reconcile interrupted Git and remote actions before retrying them.

Prove delivery to a dedicated local run branch first. Then add remote PR/check/merge policy and source closure. Dependent work must see integrated prerequisites; creating a PR cannot alone release a dependency or close an issue as resolved.

**Exit gate:** checkout errors, conflicts, failed checks, push failures, or changed base revisions never result in `resolved`; restarts do not duplicate delivery.

### 4. Turn issues and roadmaps into a normalized execution plan — P1

Build on `init` and `analyze`. Support GitHub issues and local YAML/Markdown first. Persist stable source IDs, source revisions, goals, acceptance criteria, dependencies, priority, scope, and validation policy.

Let the model propose decomposition; let deterministic checks reject incomplete or contradictory plans. Ambiguous requirements become `needs_input`. Select validation from project policy and reviewed plan content rather than executing commands copied blindly from issue text.

Freeze the selected backlog for each run. Use explicit milestone/label/source filters and stable ordering. Make repeated sync idempotent, with defined handling for edited, reopened, and externally closed issues. Review the initial plan/policy once, then execute routine work within it automatically.

**Exit gate:** repeated import creates no duplicates; every selected source item has an accurate disposition; dependencies and source revisions are honored; blocked items carry a next action.

### 5. Ship and test the actual installed user journey — P1

Package scaffold assets or remove the hook dependency through the new runner. Verify initialization from a wheel outside a checkout. Preserve existing project settings/instructions. Add a `doctor` preflight for Git, agent availability/authentication, validation commands, state storage, and adapter version.

Retain current unit and smoke tests, but add actual shell-entrypoint and supervisor subprocess contracts using a fake agent. Exercise multi-task progression, crashes, retry recovery, tampered gates, conflicts, cancellation, and repeated sync. Existing `pytest tests/` already includes smoke tests; the gap is what they prove, not simply whether they run.

Before release, run a bounded real-agent canary in a disposable external repository. Update docs, task checks, and release claims to match tested behavior. Preserve full evidence artifacts and concise console summaries.

**Exit gate:** a clean install can initialize an existing external project and complete a representative selected backlog with correct integration and blocked outcomes.

## Revised milestones

| Milestone | Deliverable | Completion evidence |
| --- | --- | --- |
| M0 — Baseline reconciliation | Preserve local work; bring forward seven upstream commits; inventory remaining CLI/docs drift. | Same intended source baseline, installed dependency setup, passing applicable checks. |
| M1 — Immediate correctness | Hook parity, sentinel/state guards, metadata preservation, retry recovery, merge-failure semantics, duplicate/DAG rejection, wheel assets. | Regression tests reproduce each defect before its fix and pass afterward, including the real shell wrapper. |
| M2 — Autonomous local run | Controller-owned state machine, serial agent supervisor, task worktrees, bounded attempts, validated local integration. | One run completes a local roadmap and recovers from deliberate interruption. |
| M3 — Issues to delivery | Normalized intake, frozen plans, source reconciliation, PR/check/merge policy. | Selected issues reach verified resolution or explicit blockers without manual sequencing. |
| M4 — Release qualification | Wheel-based external-project tests, failure injection, real-agent canary, accurate docs. | Reproducible supported installation-to-delivery journey. |

M1 is stabilization, not proof of the full product. M2 is the first milestone that delivers the requested autonomous local loop. M3 completes the issue-driven SDLC workflow.

## Review decisions and release scenario

Recommended scope: one project, one active task, Claude Code, GitHub plus local roadmaps, and explicit integration policy. Reuse the existing components; do not begin with a wholesale rewrite, multiple agents, a dashboard, or several providers.

Decide together:

1. Does final delivery require local integration, a reviewable PR, or verified remote merge? Keep these statuses distinct regardless of policy.
2. Which project and 5–10 representative tasks should be the pilot?
3. Which checks, file boundaries, runtime limits, and merge rules can be approved once for an unattended run?

Release scenario: independent fixes plus dependent tasks, a validation failure repaired on retry, an ambiguous requirement, and an external blocker. Force a worker exit, supervisor restart, and Git conflict; sync the same sources twice. Expect solvable work integrated, dependencies correctly sequenced, blockers explained, no duplicate delivery, bounded execution, and no changes to the operator's checkout.

No external blocker was established by this review. Missing product behavior and correctness defects are the current blockers. Authentication and remote permissions must be verified for the chosen pilot rather than assumed absent.

## Verification record

- Inspected source, hooks, configuration, tests, roadmap, CI, packaging, and instructions at the corrected path. Repository operating instructions were treated as project context, not a request to execute its roadmap.
- Ran an isolated archive of the exact committed source because hook tests write project runtime files: **177 passed, 1 skipped**; Ruff on `src/ hooks/ tests/` passed. The tracked source files have no local edits, so this represents the current implementation.
- Independently reproduced seven failure scenarios: premature sentinel, invalid completion, base-branch loss, duplicate IDs, shell/Python continuation disagreement, immediate re-block after restart, and false success after a real merge conflict.
- Built this revision's wheel and reproduced missing initialization assets outside the source checkout.
- Reproduced the obsolete lint recipe's missing-file failure. Did not run mypy or ShellCheck, and did not run a real-agent backlog canary; this is not a full release certification.
- Rechecked the upstream comparison through GitHub. The previous upstream result of 241 passed/1 skipped belongs to May 30 main, not this May 9 checkout.
- Added only this review plan to the corrected project. Preserved its pre-existing changelog modification and runtime state.
