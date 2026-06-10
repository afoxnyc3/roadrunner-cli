# Fault Tolerance Architecture Review

**Date:** 2026-06-10
**Scope:** roadrunner-cli @ `2e61e26` — full repository (CLI, state, session, hooks, tests, CI)
**Reviewer role:** Senior Staff Engineer — agentic systems / reliability engineering
**Baseline at review time:** 241 tests passed, 1 skipped; ruff/mypy/shellcheck green in CI.

---

## 1. Executive Summary

**Overall reliability maturity: high for its class.** Roadrunner is unusually well-engineered
for a single-operator agentic loop controller. The fundamentals most agent harnesses get
wrong are already here: atomic state writes (tmp + fsync + `os.replace`), advisory locking
around read-modify-write windows, schema versioning with a forward-compat hard gate,
bounded retries via the per-task attempt counter, an iteration cap, a budget cap,
structured JSONL tracing, log rotation, rolling config backups, a line-anchored completion
signal, and a 240+ case test suite that covers most failure paths directly. The ADR + hotfix-log
discipline shows failures are being fed back into design.

**Biggest architectural risks, in order:**

1. **The agent is inside the trust boundary of its own gate.** `tasks.yaml` is both the
   control plane (statuses, validation commands) and writable by the agent being controlled.
   An agent can mark tasks `done`, weaken `validation_commands`, or delete dependencies —
   bypassing validation entirely. Nothing enforces the CLAUDE.md file-scope rule.
2. **The completion signal is honored without verification.** `cmd_check_stop` allows the
   session to halt on `ROADMAP_COMPLETE` without checking that tasks are actually done.
   A hallucinated (or prompt-injected) sentinel silently abandons the roadmap.
3. **Unrecoverable auto-block.** Per-task attempt counters are never reset on `start`,
   so a task that was auto-blocked and then manually unblocked is re-blocked on its
   *first* resume cycle. The recovery path for the loop's main safety valve is broken.
4. **`check-stop` crashes ungracefully on a malformed `tasks.yaml`.** Mid-loop YAML
   corruption (e.g. the agent mangles the file) raises an unhandled `ValueError` inside the
   Stop hook, killing the loop with a traceback instead of a controlled hard stop.

**Highest-ROI improvements:** (a) verify roadmap state before honoring `ROADMAP_COMPLETE`;
(b) reset `attempts_per_task[id]` in `cmd_start`; (c) wrap `load_tasks()` in `cmd_check_stop`
with a controlled hard-stop; (d) reject duplicate task IDs at load; (e) kill the whole process
group on validation timeout. All five are small, testable diffs.

**Recommended next steps:** Phase 1 backlog below (5 fixes, each with a named test), then
add the failure-injection evals in §8 to the existing suite, then promote the smoke loop
from weekly to per-PR.

---

## 2. System Map

**What it does:** drives a Claude Code session through a YAML roadmap deterministically.
Python (`roadrunner` CLI) owns task selection, validation, and state; Claude Code hooks
enforce that the session cannot stop while eligible work remains.

| Component | Files | Role |
|---|---|---|
| CLI controller | `src/roadrunner/cli.py` (2,613 LOC) | All commands: `next/start/validate/complete/block/reset/check-stop/session-start/commit/...` |
| State persistence | `src/roadrunner/state.py` | `.roadmap_state.json` read/write, flock, schema gate |
| Session summaries | `src/roadrunner/session.py` | `logs/sessions/run_*.json` rollups replayed from trace |
| Hooks | `hooks/*.sh`, `.claude/settings.json` | Stop (loop driver), SessionStart (turn-1 directive), PreCompact/PostCompact (snapshot), PostToolUse (lint feedback) |
| Task queue | `tasks/tasks.yaml` | Source of truth for tasks + `baseline_validation` + git config. **Executable configuration.** |
| State stores | `.roadmap_state.json`, `.context_snapshot.json`, `tasks.yaml`, `logs/trace.jsonl`, `logs/CHANGELOG.md`, `logs/{TASK}.md`, `logs/learnings.md`, `logs/sessions/` | All file-based, project-root anchored |
| External deps | `git` (branch/merge/push), `python3`, `ruff` (optional), Claude Code hook runtime, the shell running `validation_commands` | No network APIs except `git push` |

**Critical user journeys:**
1. *Overnight loop:* SessionStart injects brief → agent `start → implement → validate → complete → reset` → Stop hook injects next brief → … → `ROADMAP_COMPLETE`.
2. *Crash recovery:* session dies mid-task → next SessionStart finalizes the orphaned session shell, emits resume brief; `resume --session-id` reattaches.
3. *Runaway containment:* iteration cap, per-task auto-block after 5 attempts, budget cap.

**Failure domains:** (1) state files on local disk; (2) the git worktree; (3) the hook
runtime contract (stdin payload shapes, exit-code semantics); (4) the LLM itself (the
least reliable dependency, and the one with write access to domains 1 and 2).

---

## 3. Critical Failure Paths

| # | Area | Failure Mode | Impact | Current Control | Gap | Severity | Recommended Fix |
|---|---|---|---|---|---|---|---|
| 1 | Trust boundary | Agent edits `tasks.yaml` to flip statuses to `done` or weaken `validation_commands` (reward hacking / prompt-injected instruction) | Validation gate bypassed; roadmap "completes" with no work done | CLAUDE.md file-scope instruction (soft); `roadrunner commit` refuses out-of-scope files *at commit time only* | No runtime enforcement; status flips and command edits take effect immediately on next load | **Critical** | PreToolUse hook denying agent Write/Edit to `tasks/tasks.yaml` (status changes must go through the CLI); optionally checksum `validation_commands` at `start` and re-verify at `complete` |
| 2 | check-stop | Agent outputs `ROADMAP_COMPLETE` while tasks remain (hallucination or injected text in a file it read) | Loop halts; roadmap silently abandoned; looks like success | Line-anchored regex (ADR-001) prevents accidental mid-sentence matches only | Signal honored without verifying task state (`cli.py:1766`) | **High** | In `cmd_check_stop`, honor the sentinel only if no active/eligible task remains; otherwise emit `decision:block` with a "premature completion signal" reason + trace event |
| 3 | Auto-block recovery | `attempts_per_task` never reset on `start`/`complete` (`cli.py:1028-1040`) | Manually unblocked task is re-auto-blocked on its first resume cycle; retry budget unrecoverable without hand-editing state JSON | `reset-iteration` resets iteration counters but **not** attempts | No reset path for attempts | **High** | `cmd_start` zeroes `attempts_per_task[task_id]`; add trace event `attempts_reset` |
| 4 | check-stop | `load_tasks()` raises on malformed YAML inside `cmd_check_stop` (`cli.py:1754`) | Unhandled traceback; `set -euo pipefail` makes hook exit 1; loop dies with no controlled stopReason; iteration was already incremented | `tasks.yaml.bak` chain exists for manual recovery | No try/except around the mid-loop load | **High** | Catch `(FileNotFoundError, ValueError)`, emit `{"continue": false, "stopReason": "tasks.yaml unreadable — restore from tasks.yaml.bak"}` + trace event |
| 5 | Schema validation | Duplicate task IDs accepted by `load_tasks()` | `get_task` returns first match; status updates hit the wrong row; `analyze`'s dep_map silently collapses duplicates | ID format regex only | No uniqueness check | **High** | Reject duplicates in `load_tasks()`; add `analyze` error too |
| 6 | Validation runner | `subprocess.run(shell=True, timeout=...)` kills only the shell on timeout; grandchildren (test servers, watchers) survive | Orphaned processes hold ports/files; subsequent validation runs fail mysteriously; "hung loop" symptoms | Timeout exists (ADR-008) and is per-task configurable | No process-group kill | **High** | `start_new_session=True` + `os.killpg(os.getpgid(p.pid), SIGKILL)` on timeout (use `Popen`/`communicate` wrapper) |
| 7 | complete → merge | `task.status="done"` saved **before** `merge_task_branch`; merge conflict or crash leaves done-but-unmerged work; `cmd_complete` prints "✅ marked done" even when merge failed | Work stranded on `roadrunner/TASK-X`; operator believes it landed | Merge abort restores clean tree; `git_merge_error` trace event | Failure not surfaced in stdout the agent reads; no reconciliation on next session | **Medium** | Print an explicit `⚠️ merge failed — branch left for manual resolution` line from `cmd_complete`; SessionStart could report unmerged `roadrunner/*` branches |
| 8 | git ops | `_git()` has no timeout; `git push` can hang on network/credential prompt | `cmd_complete` blocks forever mid-loop | `git log` in session.py has `timeout=5` (the only one) | All `_git()` calls unbounded | **Medium** | Add `timeout=` to `_git` (e.g. 60s default, 300s for push) + `GIT_TERMINAL_PROMPT=0` env |
| 9 | State concurrency | `cmd_start`/`cmd_complete` do read→write of state without `_exclusive_state_lock()` | A concurrent Stop-hook fire (crash/race) can interleave and lose attempts/iteration updates | check-stop and session-start do hold the lock | Inconsistent lock discipline | **Medium** | Wrap the read→write spans in `cmd_start`, `cmd_complete`, `cmd_block` in the lock |
| 10 | Hook env | `ROADMAP_MAX_ITERATIONS=abc` → `int()` ValueError traceback in check-stop | Loop dies ungracefully on an operator typo | `watch` validates the same var; budget var typo is silently ignored (opposite failure: guard silently off) | No validation in check-stop; budget typo is *silent* | **Medium** | Validate both: fall back to default with a one-line stderr warning |
| 11 | Atomic writes | `write_work_log`, `write_reset_marker`, `write_context_snapshot`, `CURRENT_POINTER.write_text` use plain `write_text` | Torn files on crash; PostCompact verify can fail on a half-written snapshot it just "wrote" | State/tasks/sessions writes are atomic | Discipline not applied to all writers | **Low** | Route through a shared `_atomic_write_text()` helper |
| 12 | Session rollup | `finalize_current()` replays only live `trace.jsonl`; rotation (at task boundaries) can move a session's early events into a `.gz` | Session summaries undercount tasks/iterations for long sessions | Rotation only at 10MB so rare | Replay ignores rotated archives | **Low** | Have finalize also scan `trace.jsonl.*.gz` newer than `started_at`, or rotate only when no session is open |
| 13 | Status transitions | `cmd_block` / `cmd_complete` accept any current status (can block a `done` task, complete a `todo` without `start`) | Agent confusion can corrupt roadmap state in ways the loop then reports confusingly | Eligibility is checked in `cmd_start` only | No transition guard elsewhere | **Low** | Warn (not refuse) on unusual transitions; trace event with `from_status` |

---

## 4. Function / Service Review

### `cli.py` — control loop core

- **Purpose:** all command logic; the Stop-hook decision tree (`cmd_check_stop`) is the heart of the loop.
- **Key files:** `src/roadrunner/cli.py`.
- **Failure risks:** items 2, 3, 4, 5, 6, 7, 8, 10 above. Also: `save_tasks()` re-reads
  `tasks.yaml` (TOCTOU between `load_tasks` and `save_tasks` — benign for a single operator,
  but a second concurrent writer loses data); `validate_task_schema` does not verify
  `depends_on` references exist (a typo'd dep makes a task permanently ineligible — caught
  only if the operator runs `analyze`).
- **Current controls:** schema validation on every load; task-ID regex blocks path traversal
  into `logs/{id}.md` / branch names; rolling `.bak` chain with crash-safe rotation; baseline
  validation gate (ROAD-015) makes "local equals CI" structural; budget/iteration caps; the
  sentinel is built from two string fragments so the controller's own source can't trip it.
- **Gaps:** completion-signal trust; attempts reset; check-stop YAML crash; duplicate IDs;
  dangling dep refs not validated at load.
- **Recommended fixes:** §3 rows 2–6, 10; validate `depends_on` refs in `load_tasks()` (warn,
  don't fail, to avoid bricking mid-flight roadmaps).
- **Suggested tests:** `test_completion_signal_ignored_when_tasks_remain`,
  `test_start_resets_attempt_counter`, `test_check_stop_malformed_yaml_emits_hard_stop`,
  `test_duplicate_task_ids_rejected`, `test_dangling_dependency_warns`.

### `state.py` — persistence

- **Purpose:** atomic state file I/O, locking, schema gating.
- **Failure risks:** `write_state` reads the existing file for preserve-semantics fields
  *outside* any lock when the caller doesn't hold one (callers: `cmd_start`, `cmd_complete`);
  corrupt state falls back to defaults — which silently zeroes `iteration`/`attempts`
  (correct trade-off, but the reconvergence is only visible on stderr, not in trace).
- **Current controls:** tmp+fsync+replace; flock on a sibling lockfile (survives
  `os.replace`); forward-compat version gate `exit(2)`; corrupt-file fallback to defaults.
  This module is the strongest in the codebase.
- **Gaps:** lock discipline is caller-optional; state-corruption fallback not traced.
- **Recommended fixes:** §3 row 9; add a `state_corrupt_fallback` trace event in `read_state`.
- **Suggested tests:** concurrency test spawning two processes doing
  `check-stop` + `start` simultaneously against one state file (assert no lost update).

### `session.py` — session summaries

- **Purpose:** per-session observability rollups replayed from trace.
- **Failure risks:** §3 row 12 (rotation blind spot); `CURRENT_POINTER.write_text` is
  non-atomic; `_events_after` lexicographic ISO compare is correct only while all
  timestamps come from the same UTC `isoformat()` writer (currently true).
- **Current controls:** atomic JSON writes; orphaned-session finalization on next
  `open_session()` (good crash recovery); torn-tail-line tolerance in trace reads;
  `git log` has the codebase's only subprocess timeout.
- **Gaps:** as above; also `finalize_current()` attributes *any* git commit in the time
  window to the session (concurrent human commits get counted).
- **Suggested tests:** finalize after simulated rotation; pointer file torn-write test.

### `hooks/*.sh` — runtime glue

- **Purpose:** delegate hook fires to the CLI with a 3-tier resolver (installed script →
  `python3 -m` → PYTHONPATH source).
- **Failure risks:** `stop_hook.sh` runs `set -euo pipefail`, so any CLI traceback turns
  into hook exit 1 (Claude Code then allows stop — fail-open for the loop). SessionStart
  has a 10s timeout: `session-start` does `finalize_current()` (full trace read) + git log +
  state write; on a slow disk a timeout here means the per-session iteration counter never
  resets → premature cap firing, with no signal as to why.
- **Current controls:** guards (stop_hook_active, pause marker) run *before* the resolver so
  a broken install can't hijack the session; shellcheck in CI; `post-compact || true`.
- **Gaps:** no `|| `-fallback on the check-stop delegation (deliberate fail-open — worth a
  comment); SessionStart timeout budget untested against a 10MB trace.
- **Suggested tests:** hook-level test feeding malformed stdin (exists), plus one with a
  deliberately oversized trace to time `session-start`.

---

## 5. Agentic Workflow Review

### Roadmap execution loop (the only agent workflow)

- **Trigger:** operator launches `claude`; SessionStart hook injects the turn-1 directive.
- **Steps:** `next → start → implement → validate → complete → reset`, repeated; Stop hook re-injects briefs between turns.
- **Tools used (by the agent):** Bash (`roadrunner *`, git), Write/Edit (implementation files), guided by CLAUDE.md.
- **State used:** `tasks.yaml`, `.roadmap_state.json`, `logs/*`, git branches.
- **Failure modes:**
  - *Hallucinated completion* — §3 row 2.
  - *Reward hacking via tasks.yaml* — §3 row 1. The validation gate is only as strong as
    the agent's inability to edit the gate. Today it can.
  - *Prompt injection:* task briefs embed operator-authored YAML (trusted), but the agent
    also reads arbitrary repo files during implementation; injected text telling it to emit
    `ROADMAP_COMPLETE` or edit `tasks.yaml` is currently effective because of rows 1–2.
  - *Scope creep:* `files_expected` enforced only at `roadrunner commit` time, and only if
    the agent uses `roadrunner commit` rather than raw `git commit`.
  - *Stalls:* covered well — attempt cap, iteration cap, budget cap.
  - *Partial completion:* done-but-unmerged branches (§3 row 7).
- **Recovery strategy:** strong — resume briefs from live `tasks.yaml`, orphaned-session
  finalization, `resume --session-id`, snapshot + PostCompact verification, auto-block.
- **Human approval points:** none at runtime by design (single-operator overnight tool).
  The pause marker (`roadrunner pause`) is the manual override, and the hook checks it
  before anything else — good.
- **Recommended changes:** rows 1–3 in §3; have `cmd_check_stop` cross-check
  `last_assistant_message` claims against state (the sentinel check is the only message
  parsing today, which is the right minimalism — just verify it).
- **Evals to add:** golden-path loop sim (exists as `tests/smoke/`); premature-sentinel
  injection; tasks.yaml-tamper detection; auto-block→unblock→retry lifecycle.

---

## 6. Tool Call Reliability Review

| Tool/API | Used By | Failure Risks | Validation Needed | Retry Policy | Timeout | Idempotency Needed | Eval Coverage |
|---|---|---|---|---|---|---|---|
| `validation_commands` (shell) | `run_validation` | hang (grandchild leak), nonzero, garbage output | none (operator-trusted by design) | none — correct: retries belong to the agent loop | ✅ 300s default, per-task override; ❌ no pgroup kill | yes — commands re-run on `validate`+`complete`; must be re-runnable | ✅ strong (timeouts, phases, short-circuit) |
| `git checkout/branch/merge` | `create_task_branch`, `merge_task_branch` | dirty-tree checkout failure → silent stacking; merge conflict | exit-code checked, traced | none (correct) | ❌ none | merge is effectively idempotent (branch deleted after) | ✅ good (bare-repo fixtures) |
| `git push` | `_push_branch` | hang, auth prompt, network | exit-code checked, non-fatal | ❌ none — a transient network blip silently skips the push until next merge | ❌ none | push is idempotent | ✅ failure-path tested |
| `git log` | `session._git_commits_in_window` | hang, not-a-repo | returncode checked | none | ✅ 5s | n/a | ✅ |
| Stop-hook stdin payload | `cmd_check_stop` | malformed JSON, missing fields, unstable cost schema | ✅ try/except→`{}`; nested-tolerant cost extraction | n/a | n/a | n/a | ✅ |
| SessionStart stdin | `cmd_session_start` | missing/malformed/tty | ✅ tolerant, preserve-on-fail | n/a | n/a | session-id capture idempotent | ✅ |
| `ruff` (PostToolUse) | `post_write_hook.sh` | missing binary | ✅ `command -v` guard | n/a | hook 30s | n/a | ✅ hook tests |

Recommended: add `timeout=` to `_git()`; bounded retry (2 attempts, short backoff) **only**
for `git push` — the one genuinely transient-failure-prone call; leave everything else
single-shot since the agent loop is itself the retry mechanism.

---

## 7. Observability Review

**Strong:** structured JSONL trace with stable event vocabulary (`task_start`,
`validation_command`, `check_stop`, `auto_block`, `budget_exceeded`, `git_*`,
`post_compact_verify`…), durations and exit codes on validation events, model hint
correlated into `check_stop` events, session rollups, `watch` live monitor, `sessions`
pretty-printer, append-only CHANGELOG, per-task work logs with validation transcripts,
rotation + retention. Observability failures never break the loop (correct posture).

**Gaps:**

1. **No correlation ID on trace events.** `last_session_id` is captured into state but not
   stamped onto trace records, so interleaved sessions in one trace file must be split by
   timestamp heuristics. → Add `session_id` to every `trace_event` record (read once at
   process start; cheap).
2. **Silent guard degradation isn't traced:** state-corruption fallback, budget-typo
   disable, base-checkout fallthrough (traced but not surfaced to operator), missing cost
   data (stderr only, and the once-per-process dedup is ineffective since each fire is a
   new process). → trace events for each; `health` should report them.
3. **`roadrunner health` doesn't check invariants** it easily could: unmerged
   `roadrunner/*` branches, `.reset_*` markers without matching done status, attempts ≥ max
   on a todo task, `tasks.yaml` vs `.roadmap_state.json` disagreement on current task.
4. **Per agent run / tool call, log:** (already mostly done) — recommend adding: session_id
   (gap 1), `from_status`/`to_status` on every transition, and a `loop_decision` event
   recording which branch of the check-stop decision tree fired (today you must infer it
   from the absence/presence of other events).

No dashboards/alerts needed at this scale; `watch` + `sessions` + `health` are the right
operator surface. Make `health` the invariant checker and it doubles as the morning-after
triage tool.

---

## 8. Evaluation Plan

Existing coverage is genuinely good: 207 unit tests (schema, eligibility, signal parsing,
state, backups, validation phases, budget, auto-block progression), 15 hook-script tests,
14 session tests, 6 smoke tests simulating SessionStart→Stop boundaries. CI gates pytest ×
3 Python versions + ruff + mypy + shellcheck on every PR; smoke runs weekly.

| Eval Name | Type | Scenario | Expected Behavior | Files/Fixtures Needed | CI Gate? |
|---|---|---|---|---|---|
| `test_completion_signal_ignored_when_tasks_remain` | Failure injection | check-stop stdin has sentinel as last line, 1 todo task eligible | `decision:block` with premature-signal reason; trace `premature_complete_signal` | extend `tests/test_roadrunner.py::TestCheckStop` | **Merge-blocking** |
| `test_start_resets_attempt_counter` | Regression | task auto-blocked at 5 attempts → operator sets todo → `start` → first check-stop resume | attempts == 1, no auto-block | unit | **Merge-blocking** |
| `test_check_stop_malformed_yaml_hard_stops` | Failure injection | corrupt `tasks.yaml` mid-loop, fire check-stop | `{"continue": false}` JSON with restore-from-backup stopReason, exit 0 | tmp_project fixture | **Merge-blocking** |
| `test_duplicate_task_ids_rejected` | Schema | two tasks share `TASK-001` | `load_tasks` raises ValueError naming the ID | unit | **Merge-blocking** |
| `test_validation_timeout_kills_process_group` | Failure injection | validation cmd spawns `sleep 600 &` child then hangs | after timeout, no surviving descendant (poll pgid) | unit, marked slow | **Merge-blocking** |
| `test_complete_surfaces_merge_failure` | Failure injection | seed merge conflict on task branch | stdout contains explicit merge-failure warning; task still done; branch intact | bare-repo fixture (pattern exists) | **Merge-blocking** |
| `test_git_push_timeout_bounded` | Failure injection | push against a hanging remote (fifo trick or `GIT_SSH_COMMAND=sleep`) | returns False within timeout, task completes | smoke | Nightly/weekly |
| `test_tasks_yaml_tamper_detected` | Safety | `validation_commands` hash recorded at `start` differs at `complete` | warning/refusal per chosen policy; trace event | unit (after fix 1) | **Merge-blocking** once shipped |
| `test_sentinel_injection_via_reason_roundtrip` | Safety/regression | task goal text contains `ROADMAP_COMPLETE` on its own line inside the brief | brief never emits sentinel line-anchored (current `sentinel_hint` design holds) | unit | **Merge-blocking** |
| `test_session_start_under_10s_with_10mb_trace` | Performance | 10MB trace.jsonl, run `session-start` | completes < 5s (half the hook timeout) | smoke fixture generator | Weekly |
| `test_finalize_spans_rotation` | Failure injection | rotate trace mid-session, finalize | summary includes pre-rotation events (after fix) | session tests | Weekly |
| `test_unblock_retry_golden_path` | Golden path | block → unblock → start → complete full lifecycle via smoke harness | clean completion, attempts sane | `tests/smoke/` | Weekly |
| Smoke loop on PR | Golden path | existing `tests/smoke/` | green | none | **Promote to merge-blocking** (5.84s suite cost is trivial) |

LLM-as-judge is **not** appropriate here — the controller is deterministic and every
behavior is assertable. Keep it that way; the determinism is the product.

**CI/CD gates:** merge-blocking = unit + hooks + smoke + lint + mypy + shellcheck.
Weekly = slow/failure-injection extras above. Release (`publish.yml`) should run the full
weekly set before tagging.

---

## 9. Recommended Implementation Backlog

### Phase 1 — Immediate Reliability Fixes (Critical/High)

1. **Verify before honoring `ROADMAP_COMPLETE`** (`cmd_check_stop`, ~6 lines + test).
2. **Reset `attempts_per_task[task_id]` in `cmd_start`** (~3 lines + test).
3. **Controlled hard-stop when `load_tasks()` fails in `cmd_check_stop`** (~8 lines + test).
4. **Reject duplicate task IDs in `load_tasks()`** (~5 lines + test).
5. **Process-group kill on validation timeout** (replace `subprocess.run` with a small
   `Popen` wrapper in `run_validation._run_one`; ~15 lines + test).
6. **Guardrail for tasks.yaml self-modification** (the Critical item; design decision
   required): minimum viable = record a hash of each task's `validation_commands` +
   `status` at `start`, verify at `complete`, refuse with a loud message on mismatch.
   Stronger = PreToolUse hook matcher on `Write|Edit` denying `tasks/tasks.yaml`.

### Phase 2 — Verification Loop

7. Add the merge-blocking evals from §8; promote `tests/smoke/` into `ci.yml`.
8. Wrap `cmd_start`/`cmd_complete`/`cmd_block` state windows in `_exclusive_state_lock()`
   + a two-process concurrency test.
9. Validate `ROADMAP_MAX_ITERATIONS` and warn on unparseable `ROADMAP_MAX_BUDGET_USD`
   instead of silently disabling the guard.
10. Validate `depends_on` references at load (warn) + duplicate-dep `analyze` errors.

### Phase 3 — Operational Hardening

11. `session_id` on every trace event; `loop_decision` event in check-stop.
12. `roadrunner health` invariant checks: unmerged task branches, stale attempts,
    state/tasks disagreement, guard-degradation events in last session.
13. `_atomic_write_text()` helper; route work logs, reset markers, snapshot, session
    pointer through it.
14. `_git()` timeout + `GIT_TERMINAL_PROMPT=0`; bounded retry on push only.
15. Surface merge failure in `cmd_complete` stdout; SessionStart reports leftover
    `roadrunner/*` branches.
16. Finalize-across-rotation fix (or defer rotation while a session is open — simpler).

---

## 10. Concrete Code Change Suggestions

**Fix 1 — sentinel verification** (`cli.py`, in `cmd_check_stop` around line 1766):

```python
if is_completion_signal(last_msg):
    if active_task(tasks) or next_eligible_task(tasks):
        trace_event("premature_complete_signal", task_id=state.get("current_task_id"),
                    iteration=iteration)
        msg = ("ROADMAP_COMPLETE was output but eligible/in-progress tasks remain. "
               "The signal was ignored. Continue with the current task.")
        print(json.dumps({"decision": "block", "reason": msg}, ensure_ascii=False))
        sys.exit(0)
    append_changelog("ALL", "complete", notes="Roadmap finished — signal received.")
    _finalize_session_quiet()
    sys.exit(0)
```

**Fix 2 — attempts reset** (`cmd_start`, after eligibility check):

```python
attempts = dict(state.get("attempts_per_task") or {})
if attempts.pop(args.task_id, None) is not None:
    trace_event("attempts_reset", task_id=args.task_id)
write_state(args.task_id, state.get("iteration", 0), attempts,
            extra={"base_branch": base_branch})
```

**Fix 3 — check-stop YAML guard** (`cmd_check_stop`):

```python
try:
    tasks = load_tasks()
except (FileNotFoundError, ValueError) as exc:
    trace_event("tasks_unreadable", iteration=iteration, extra={"error": str(exc)[:200]})
    print(json.dumps({"continue": False, "stopReason":
        f"tasks.yaml unreadable mid-loop: {exc}. Restore from tasks/tasks.yaml.bak "
        f"and restart."}, ensure_ascii=False))
    sys.exit(0)
```

**Fix 5 — process-group kill** (`run_validation._run_one`):

```python
proc = subprocess.Popen(cmd, shell=True, cwd=ROOT, text=True,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        start_new_session=True)
try:
    stdout, stderr = proc.communicate(timeout=timeout)
except subprocess.TimeoutExpired:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    stdout, stderr = proc.communicate()
    timed_out = True
```

**Fix 6 (minimum viable) — gate integrity hash:** at `cmd_start`, store
`hashlib.sha256(json.dumps(task["validation_commands"]).encode()).hexdigest()` in state
(`extra={"validation_hash": ...}`); at `cmd_complete`, recompute and refuse with a named
diff if changed, with `--allow-gate-change` as the explicit operator override.

**Test files to create/extend:** all fixes land in `tests/test_roadrunner.py` (patterns
already exist for every fixture needed — tmp_project, bare-repo origin, check-stop stdin
harness). New fixture needed only for the process-group test (a `sleep`-spawning script).

---

*Net assessment: this codebase already practices most of what a fault-tolerance review
usually has to ask for. The remaining work concentrates on one theme — the controller
currently trusts the agent in three places (sentinel, tasks.yaml writes, attempt-counter
hygiene) where the system's own design philosophy says it shouldn't. Close those, and the
"Python owns control" claim becomes structurally true rather than behaviorally true.*
