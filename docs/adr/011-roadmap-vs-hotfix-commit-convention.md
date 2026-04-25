# ADR-011: Roadmap vs Hotfix Commit Convention

**Status:** Accepted
**Date:** 2026-04-25
**Deciders:** Alex, principal_engineer

## Context

Roadrunner-cli runs two parallel streams of change:

1. **Planned roadmap work.** Tasks defined in `tasks/tasks.yaml`, executed by the loop, committed under their task ID.
2. **Observation-driven hotfixes.** Patches Alex (or a reviewer) writes by hand while watching a live run, addressing bugs surfaced by the loop itself before they show up in the plan. Examples to date: ROAD-021 (`roadrunner commit` scope-aware staging), ROAD-023/ROAD-025 (state + branch correctness), ROAD-028 (instructional SessionStart), ROAD-031 (`push_on_complete` config).

Both streams are legitimate. Hotfixes especially are a healthy dogfooding signal: when the loop reveals a problem, patching it immediately beats bureaucratically routing it through the task queue and waiting a session.

The audit on 2026-04-24 found that these five commits referenced ROAD-021/023/025/028/031, IDs that do not exist in the live `tasks.yaml`. To a future reader (or to the eventual DevOps agent), there is no way to tell from the commit subject whether a `(ROAD-NNN)` scope means "this was a planned task that shipped" or "this was a hotfix and the ID is just a label." The audit trail is ambiguous.

## Decision

Adopt a two-track commit subject convention and a hotfix log to disambiguate the streams.

### Commit subject format

- **Roadmap work** (task ID exists in `tasks/tasks.yaml` on `main`):
  `<type>(ROAD-<num>): <imperative summary>`
  Example: `feat(ROAD-001): pyproject.toml — pip-installable packaging`

- **Hotfix / observation-driven** (no roadmap task; written reactively against a live run):
  `<type>(hotfix): <imperative summary>`
  Example: `fix(hotfix): clear current_task_id on cmd_complete`
  No task ID in the scope. The date is already captured by the commit timestamp; `(hotfix)` reads more clearly at a glance in `git log --oneline` than `(obs-2026-04-23)` would.

- **Pure chore / docs / refactor** unrelated to either stream:
  `<type>: <imperative summary>` with no scope.

Conventional commit types apply: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `ci`.

### Hotfix log

Maintain `docs/hotfix-log.md` as an append-only ledger. One entry per hotfix commit. Each entry records:

- Date
- Commit SHA
- Symptom observed during the live run
- Root cause
- Fix applied
- Whether a follow-up roadmap task is warranted

Backfill the five existing observation-driven commits (ROAD-021/023/025/028/031) as the initial entries. They retain their historical subjects (rewriting public history is out of scope); the log makes the dual-track structure visible going forward.

### CI check (deferred — Phase 2 only)

A future linter could parse `(ROAD-\d+)` out of commit subjects on `main` and assert each ID resolves to a task in `tasks.yaml`. Unresolved IDs would be flagged as "probably should have been `(hotfix)`." This is a warn-only convenience, not a gate. Not implemented in this ADR; revisit if the convention proves insufficient on its own.

## Alternatives considered

- **`(obs-<date>)` scope for hotfixes.** Rejected. The date is redundant with the commit timestamp, and `(hotfix)` reads more clearly in one-line log views.
- **Reuse `(ROAD-NNN)` for hotfixes with a separate ID range** (e.g., 900+). Rejected. Mixing the ID space invites confusion: a reader cannot tell from the subject alone whether the ID resolves to a real task or to a hotfix label without consulting `tasks.yaml`.
- **No formal convention; rely on commit body to clarify.** Rejected. The audit trail needs to be readable from `git log --oneline` without expanding bodies, and the dual-track distinction has to survive into a future where DevOps owns merges.
- **Rewrite the historical hotfix subjects to match.** Rejected. The five existing commits are on `main` and on remotes; rewriting public history costs more than the log file does.

## Consequences

- New commits in either stream are unambiguous from the subject line alone.
- The hotfix log gives a permanent, append-only record of what observation-driven patches have shipped, separate from the roadmap.
- A reader (human or DevOps agent) can reconstruct "what was planned" vs "what was reactive" without grepping commit bodies.
- Existing `roadrunner commit` (from ROAD-021) does not need changes for this ADR. It already builds subjects from task IDs that live in `tasks.yaml`. The hotfix track is a hand-authored path and is unaffected by the scope-aware staging machinery.
- The hotfix log adds a small documentation discipline to each hand-authored fix. Skipping the log entry is a soft failure: the commit still lands, but the audit trail thins out.

## Test coverage

- ADR file present at `docs/adr/011-roadmap-vs-hotfix-commit-convention.md`.
- `docs/hotfix-log.md` present with backfilled entries for ROAD-021, ROAD-023, ROAD-025, ROAD-028, ROAD-031.
- README links to both files via the existing ADR index reference (count bumped from "ten" to "eleven").
- No code changes; no new test runner gates required.

## References

- Resolution plan, Issue 2: `docs/resolution-plan-2026-04-24.md` (when present in working tree).
- Backfilled hotfix commits: `81ecaf5` (ROAD-021), `afa2c60` (ROAD-023 + ROAD-025), `6328dd8` (ROAD-028), `f640fb9` (ROAD-031).
