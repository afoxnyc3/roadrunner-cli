# Hotfix Log

Append-only ledger of observation-driven hotfix commits. See [ADR-011](adr/011-roadmap-vs-hotfix-commit-convention.md) for the dual-track convention separating roadmap work from hotfixes.

Each entry records the symptom that surfaced during a live run, the root cause, the fix, and whether a follow-up roadmap task is warranted. Newest first.

---

## 2026-04-23 — `6328dd8` — instructional SessionStart that auto-resumes

**Original subject:** `feat: instructional SessionStart that auto-resumes (ROAD-028)`

- **Symptom.** SessionStart hook emitted ambient status text ("Current task: X"), so the agent treated it as background context and did not act on turn one. Operators had to type "Begin" or similar to kick the loop forward.
- **Root cause.** `cmd_session_start` injected status, not instruction. The agent had no directive to start work, and the snapshot it read could lag the live state (especially after the ROAD-023 fix cleared `current_task_id`).
- **Fix.** Rewrote `cmd_session_start` to read `tasks.yaml` directly (not the snapshot) and emit instructional `additionalContext` of the form "Your first action: `roadrunner start <ID>`" plus the task brief. Added a decision tree: missing tasks file → silent; in_progress task → resume brief; eligible next → start directive; blocked-only → blocked list; all done → ROADMAP_COMPLETE prompt.
- **Tests.** +5 (replacing 3 obsolete), 124 passing total. Covers absent file, eligible next, in_progress, all done, blocked.
- **Follow-up roadmap task warranted?** No. The fix is self-contained. Behavior is already covered by direct unit tests.

---

## 2026-04-23 — `f640fb9` — auto-push after merge via `push_on_complete` config

**Original subject:** `feat: auto-push after merge via push_on_complete config (ROAD-031)`

- **Symptom.** After successful task-branch merges, nothing was pushed to origin. Operators had to manually `git push` between sessions, defeating the "trust the result when you wake up" pitch.
- **Root cause.** No push step existed in the merge path. The decision had previously been deferred under the assumption a DevOps agent would own remote operations.
- **Fix.** Added top-level `push_on_complete` key in `tasks.yaml` with four modes: `base` (push base branch only — new init default), `task` (push task branch before deletion), `both`, `none` (legacy default for existing projects without the key). Push failures are non-fatal: trace event + stderr warning, but the task stays marked done locally so transient network issues don't invalidate work that passed validation.
- **Tests.** +5, 122 passing. Real bare-repo origin in fixtures, not mocks. Covers default unset, each of the four modes, and push failure with no remote.
- **Follow-up roadmap task warranted?** No. The capability is contained and the contract (non-fatal failure) is documented in `_INIT_TASKS_TEMPLATE`.

---

## 2026-04-23 — `81ecaf5` — scope-aware `roadrunner commit` command

**Original subject:** `feat(commit): scope-aware commit command (ROAD-021)`

- **Symptom.** Observed in `entra-triage` commit `b21c768`: a `git add -A && git commit` swept unrelated README and ROADMAP edits into ENTRA-001's commit alongside the entity work. The "one commit per task" contract was broken in a way that's almost impossible to spot in review.
- **Root cause.** The original commit path used `git add -A`, which is unscoped by definition. Any dirty file in the worktree at commit time gets included, regardless of which task it belongs to.
- **Fix.** New `roadrunner commit TASK-ID [--notes] [--type]` subcommand. Stages only files in the task's `files_expected` or in the roadrunner overlay (`logs/`, `tasks/tasks.yaml*`, `.reset_*`). Refuses with a named-file error if any out-of-scope dirty file is present, and lists three resolution paths (add to `files_expected`, stash, discard). Auto-generates the commit subject as `{type}({task_id}): {task.title}`. Default `--type feat`; conventional types only.
- **Tests.** +7, 117 passing. Covers in-scope happy path, out-of-scope refusal with named offender, empty-tree no-op, `--type refactor`, invalid type, `--notes` body, unknown task ID.
- **Follow-up roadmap task warranted?** No. Replaces the unsafe pattern entirely; CLAUDE.md init template was updated in the same commit to teach the new contract.

---

## 2026-04-23 — `afa2c60` — state + branch correctness (two bugs in one commit)

**Original subject:** `fix: state + branch correctness (ROAD-023 + ROAD-025)`

This commit batched two pilot-surfaced bugs that were both worth shipping the same night.

### ROAD-023 — `cmd_complete` did not clear `current_task_id`

- **Symptom.** After completing a task, `state.current_task_id` kept pointing at the just-completed ID. SessionStart and `check-stop` then read that stale value and emitted "resume this done task" briefs on subsequent fires, leading to confused loop restarts.
- **Root cause.** `cmd_complete` did not write `current_task_id=None` when finalizing.
- **Fix.** `cmd_complete` now writes state with `current_task_id=None` while preserving `iteration`, `attempts_per_task`, and `base_branch`.
- **Tests.** `TestCompleteClearsState` — verifies state.current_task_id is None after cmd_complete while iteration and attempts survive.

### ROAD-025 — task branches forked from HEAD, not project_base

- **Symptom.** Observed in `entra-triage`: after ENTRA-010 merged to main, ENTRA-011..040 chained on each other instead of each forking from main, producing a 6-branch stack that requires manual unstacking to get to origin/main.
- **Root cause.** `cmd_start` used `_current_branch()` as the branch base, so calling `start` while HEAD was still on a previous task branch stacked the new branch on top of the old one.
- **Fix.** New `load_project_config()` and `get_project_base()` helpers. `get_project_base()` returns the configured `project_base` (top-level key in `tasks.yaml`), falling back to `_current_branch()` or `"main"` for back-compat. `cmd_start` calls it and passes the result to `create_task_branch(base_branch=...)`. `create_task_branch` checks out the base before forking, guaranteeing fan-out instead of stacking. Init template scaffolds `project_base: main` so new projects get the correct behavior by default.
- **Tests.** `TestProjectBase` — verifies `get_project_base` reads the key, falls back cleanly without it, and that `create_task_branch` with an explicit base forks from that base rather than from current HEAD.

**Combined tests.** +4, 110 passing total.

**Follow-up roadmap task warranted?** No for either. Both are straight bugfixes covered by direct unit tests. The 6-branch stack in entra-triage is a separate cleanup item owned downstream.

---

## Conventions

- One section per hotfix commit (or per logical hotfix when batched).
- Original subject quoted verbatim so `git log` and the log are correlatable.
- Symptom / Root cause / Fix / Tests / Follow-up fields, in that order.
- Newest entries on top.
- No edits to existing entries — append only. Corrections go in a new entry referencing the original SHA.
