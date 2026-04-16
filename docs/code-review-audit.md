# Roadrunner CLI — Code Review Audit & Remediation Status

> Audited: 2026-04-15 against commit `e83a337`
> Sources: Code Review #2 (external), Codex Adversarial Review (external), authoritative Claude Code hooks reference (https://docs.claude.com/en/docs/claude-code/hooks)

---

## Summary

Commit `e83a337` ("fix: harden controller against review-identified correctness and security defects") resolved 12 of 16 actionable findings from the two reviews. The remaining 4 items are: the TaskCompleted hook is wired to the wrong Claude Code event, the PostToolUse matcher includes a non-existent tool name, the PreCompact hook emits dead-code JSON, and DESIGN.md is stale.

| Category | Fixed | Outstanding |
|---|---|---|
| P0 correctness | 2/2 | 0 |
| P1 docs alignment | 1/4 | 3 |
| P2 security/hooks | 1/1 | 0 |
| P3 reliability | 4/4 | 0 |
| P4 test coverage | 1/1 | 0 |
| **Total** | **9/12 review items + 3 bonus** | **4 outstanding** |

---

## Resolved Items

### 1. Stop hook treats in-progress task as roadmap complete
**Source:** Codex Review [critical], roadrunner.py:355-363
**Status: FIXED** at `roadrunner.py:482-508`

Before: `cmd_check_stop` only called `next_eligible_task()`, which returns None for any non-`todo` task. After `cmd_start` flips to `in_progress`, the hook emitted "All tasks complete" mid-task.

After: New `active_task()` function (line 94-95) checks for `in_progress` tasks first. `cmd_check_stop:482-508` emits a `RESUME IN-PROGRESS TASK` brief when one is found. The "all done" path (line 526-537) now scans for *any* non-done status, not just eligible tasks. Additionally, a per-task attempt counter (line 484-505) auto-blocks after 5 failed attempts — this was an "opportunity" item the reviews suggested but didn't demand.

**Test coverage:** `TestCheckStop.test_resumes_in_progress` (line 351), `test_auto_block_after_max_attempts` (line 381).

### 2. ROADMAP_COMPLETE substring match
**Source:** Both reviews, roadrunner.py:347
**Status: FIXED** at `roadrunner.py:98-108`

Before: `if "ROADMAP_COMPLETE" in last_msg` — triggers on any quoted occurrence.

After: `is_completion_signal()` uses a compiled regex `^\s*ROADMAP_COMPLETE\s*$` and checks only the *last non-empty line* of the message. Additionally, `_build_task_brief` (line 556) splits the sentinel string as `"ROADMAP" "_COMPLETE"` to avoid embedding a matchable literal in the brief itself.

**Test coverage:** `TestCompletionSignal` class — 9 cases including `test_substring_no_match`, `test_mid_message_no_match`, `test_no_bare_sentinel_line` on the brief.

### 3. Relative hook commands in settings.json
**Source:** Codex Review [high], .claude/settings.json
**Status: FIXED** at `.claude/settings.json:8,19,30,42`

Before: `bash hooks/stop_hook.sh` (bare relative path).
After: `bash "$CLAUDE_PROJECT_DIR"/hooks/stop_hook.sh` — matches the recommended pattern in the official Claude Code hooks reference under "Reference scripts by path."

### 4. Shell injection in post_write_hook.sh
**Source:** Code Review #2, hooks/post_write_hook.sh:40
**Status: FIXED** at `hooks/post_write_hook.sh:40`

Before: `python3 -c "import yaml; yaml.safe_load(open('$FILE_PATH'))"` — path with `'` breaks out.
After: `python3 -c 'import sys, yaml; yaml.safe_load(open(sys.argv[1]))' "$FILE_PATH"` — path passed via argv.

### 5. Non-atomic save_tasks
**Source:** Code Review #2, roadrunner.py:37-42
**Status: FIXED** at `roadrunner.py:61-70`

Now writes to `.yaml.tmp`, calls `f.flush()` + `os.fsync(f.fileno())`, then `os.replace()`. Standard atomic write pattern confirmed by multiple 2025-2026 Python references.

**Test coverage:** `TestAtomicSave.test_save_roundtrip`, `test_no_tmp_left`.

### 6. Iteration counter only increments on start
**Source:** Both reviews, roadrunner.py:242 / DESIGN.md §3
**Status: FIXED** at `roadrunner.py:446`

Increment moved from `cmd_start` (which now only records `current_task_id`) into `cmd_check_stop:446` — increments once per Stop-hook invocation after the `stop_hook_active` short-circuit.

**Test coverage:** `TestCheckStop.test_iteration_increments_on_check_stop` (line 396), `test_iteration_cap` (line 373).

### 7. cmd_block silent exit on missing task
**Source:** Code Review #2, roadrunner.py:288-289
**Status: FIXED** at `roadrunner.py:399-401`

Now prints `f"Task {args.task_id} not found."` before `sys.exit(1)`.

### 8. justfile uses python, hooks use python3
**Source:** Both reviews, DESIGN.md §3
**Status: FIXED** in `justfile` — all commands now use `python3`.

### 9. Debug log at /tmp/rr_tc_debug.log
**Source:** Code Review #2, task_completed_hook.sh:21
**Status: PARTIALLY FIXED** at `hooks/task_completed_hook.sh:21-24`

Moved from world-readable `/tmp/rr_tc_debug.log` to project-local `logs/.taskcompleted_payloads.log`. Still logging payloads — intentionally, to verify the TaskCompleted payload schema. Acceptable as a temporary diagnostic; should be removed once the schema is confirmed (see Outstanding #1).

### 10. Schema validation on tasks.yaml load (bonus)
**Source:** Code Review #2 Opportunities, not a required fix
**Status: IMPLEMENTED** at `roadrunner.py:34-58`

`validate_task_schema()` checks for required fields (`id`, `status`, `title`) and validates `validation_commands` and `depends_on` are lists. Not jsonschema/Pydantic — lightweight and appropriate.

### 11. Structured trace logging (bonus)
**Source:** Code Review #2 Opportunities #8
**Status: IMPLEMENTED** at `roadrunner.py:214-238`

`trace_event()` writes JSONL to `logs/trace.jsonl` with `ts`, `event`, `task_id`, `iteration`, optional `command`, `exit_code`, `duration_ms`. Called from `run_validation`, `cmd_start`, `cmd_complete`, `cmd_block`, `cmd_check_stop`.

### 12. Per-task attempt counter + auto-block (bonus)
**Source:** Code Review #2 Opportunities #9
**Status: IMPLEMENTED** at `roadrunner.py:169-198, 484-505`

`increment_attempts()` tracks per-task attempts in `.roadmap_state.json`. `cmd_check_stop` auto-blocks after `MAX_TASK_ATTEMPTS` (5) failed stop-hook cycles. Mitigates the retry-storm pattern.

---

## Outstanding Items

### O1. TaskCompleted hook is wired to the wrong Claude Code event
**Source:** Codex Review [high], Code Review #2 (TaskCompleted payload unverified)
**Severity: Medium** (not load-bearing, but misleading)
**Files:** `hooks/task_completed_hook.sh`, `.claude/settings.json:14-23`, `DESIGN.md §2.2`

Per the authoritative Claude Code hooks reference:

> `TaskCompleted` — "Runs when a task is being marked as completed. This fires in two situations: when any agent explicitly marks a task as completed through the TaskUpdate tool, or when an agent team teammate finishes its turn with in-progress tasks."

The payload schema is:
```json
{
  "task_id": "task-001",        // Claude's internal ID, NOT roadmap's TASK-001
  "task_subject": "Implement user authentication",
  "task_description": "Add login and signup endpoints",
  "teammate_name": "implementer",
  "team_name": "my-project"
}
```

This event fires when the Claude Code `TaskUpdate` tool marks an internal agent-team task as complete — NOT when `python3 roadrunner.py complete TASK-XXX` runs. Roadrunner's actual validation gate is `cmd_complete:380` (`run_validation`), which works correctly.

The commit improved the hook to scan for `TASK-\d{3,}` via regex, which could theoretically match if Claude mentions "TASK-002" in a `task_subject` or `task_description`. But this is fragile and accidental coupling.

**Options:**
- **Delete the hook** (recommended): Remove from settings.json and delete the file. Document in DESIGN.md that validation happens in `cmd_complete`, not a hook. This is the cleanest path.
- **Repurpose it**: If you plan to use Claude Code agent-teams mode with roadrunner, redesign the hook to map `task_subject` → roadmap ID explicitly.

### O2. PostToolUse matcher includes `MultiEdit` (non-existent tool)
**Source:** New finding (not in either review)
**Severity: Low** (harmless — `MultiEdit` never matches, `Write|Edit` still work)
**File:** `.claude/settings.json:38`

Current: `"matcher": "Write|Edit|MultiEdit"`
The current Claude Code tool set (per official docs) lists `Bash`, `Edit`, `Write`, `Read`, `Glob`, `Grep`, `Agent`, `WebFetch`, `WebSearch`, `AskUserQuestion`, `ExitPlanMode`. `MultiEdit` is not present.

**Fix:** Change to `"matcher": "Write|Edit"`.

### O3. PreCompact `additionalContext` JSON output is dead code
**Source:** New finding (not in either review)
**Severity: Low** (dead code, not a bug)
**File:** `roadrunner.py:297-303`

`write_context_snapshot()` prints:
```python
print(json.dumps({"additionalContext": f"Roadmap state snapshot..."}))
```

Per the official docs, **PreCompact has no `additionalContext` output field**. The events that support `additionalContext` in their output are: `SessionStart`, `UserPromptSubmit`, `PostToolUse`, `PostToolUseFailure`, `SubagentStart`, and `Notification`. PreCompact only supports `decision: "block"` / exit code 2 to block compaction.

The file write (`.context_snapshot.json`, line 296) still works and is the actual load-bearing mechanism — CLAUDE.md references it and `InstructionsLoaded` fires on compact with `load_reason: "compact"`.

**Fix:** Remove the `print(json.dumps(...))` call. Keep the file write.

### O4. DESIGN.md is stale after the hardening commit
**Source:** Cross-referencing current docs against code
**Severity: Low** (documentation drift)
**File:** `DESIGN.md`

Specific items:
- **§1.1 step 3** (line 33): Says `python roadrunner.py` — should be `python3`.
- **§2.1 bullet 1** (line 91): Says "ROADMAP_COMPLETE in last message" — should describe the regex line-anchored match.
- **§2.2** (lines 99-122): Describes TaskCompleted with an incorrect payload example (`{"task_id": "TASK-003"}`). The actual payload from Claude Code uses lowercase `task_id` like `"task-001"` with separate `task_subject`, `task_description` etc. fields. See O1 above.
- **§2.3** (line 132): Claims PreCompact outputs `additionalContext` — this is dead code per O3.
- **§3 "Known Risk Areas"** (lines 176-260): Several items are now resolved (iteration counter, non-atomic writes, python vs python3) but still listed as open risks.
- **§4 "Recommended Fixes Before First Run"**: References old file paths and contains fixes that have been applied.
- **§6 "Open Questions"** (lines 388-392): Questions 1 and 3 are answered.

**Fix:** Update DESIGN.md to reflect the current state of the code and the verified Claude Code hook schemas.

---

## Items From Reviews That Were Correctly Assessed and Do Not Need Action

| Claim | Assessment |
|---|---|
| `shell=True` over YAML-defined commands (CR#2) | Correct: trust boundary, not a bug. Now documented in DESIGN.md §3 "Trust Boundary" section. |
| Stop-hook loop guard correct (CR#2) | Confirmed: `stop_hook_active` check at roadrunner.py:442. |
| Validation as gate (CR#2) | Confirmed: `cmd_complete:380` re-runs `run_validation`. |
| Per-task audit trail (CR#2) | Confirmed: logs/TASK-XXX.md + CHANGELOG + trace.jsonl. |
| Zero automated tests (CR#2) | Now resolved: `tests/test_roadrunner.py` (~468 LOC). |
| No ruff config (CR#2) | True but acceptable: `ruff` in requirements.txt, code happens to be clean. No CI to run it. |

---

## Scorecard: Review Accuracy

### Code Review #2 (7.5/10 rating)
- **11 weakness claims**: 10 verified accurate, 1 partially accurate (TaskCompleted described as "silently inoperative" — actually wired to wrong event entirely)
- **7 opportunity claims**: 4 implemented in the hardening commit (schema validation, trace logging, attempt counter, line-anchored ROADMAP_COMPLETE)
- **Strengths**: All verified accurate.
- **Rating fairness**: 7.5 was appropriate pre-commit. Post-commit `e83a337`, the project is closer to 8.5-9. Outstanding items are all low-severity.

### Codex Adversarial Review (3/10 rating, "no-ship")
- **Finding 1 (critical: in-progress treated as complete)**: Verified accurate. Now fixed.
- **Finding 2 (high: relative hook paths)**: Verified accurate. Now fixed.
- **Finding 3 (high: ROADMAP_COMPLETE substring)**: Verified accurate (duplicate of CR#2). Now fixed.
- **Finding 4 (high: TaskCompleted wired to wrong event)**: Verified accurate — and more correct than CR#2's characterization. Still outstanding.
- **3/10 rating**: Was arguably harsh but defensible given finding #1 was a genuine correctness bug in the core loop. Post-fix, the same review would likely rate 6-7/10 with only O1-O4 remaining.
