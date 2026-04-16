# Roadrunner CLI — Comprehensive Code & Architecture Review

> Reviewed: 2026-04-15 | Files read: roadrunner.py, all hooks/*, tests/test_roadrunner.py, tasks/tasks.yaml, DESIGN.md, CLAUDE.md, README.md, all ADRs, settings.json, state files
> Research: EXA searches on agentic loop best practices (SitePoint 2026, Atlan 2026, Mindra 2026, LangGraph/CrewAI/AutoGen comparisons)

---

## Project Overview

Roadrunner is a **deterministic agentic loop harness** for Claude Code. It is not an agent framework — it is the *control plane around an agent*. Python (`roadrunner.py`, 620 lines) owns task state, validation gating, and loop control. Claude Code owns implementation. Bash hooks (Stop, SessionStart, PreCompact, PostToolUse) wire Python's decisions into Claude Code's lifecycle events. The task queue lives in `tasks/tasks.yaml`; state persists to JSON sidecars; observability flows to JSONL traces, markdown changelogs, and per-task work logs.

**Architectural style:** Procedural single-file controller + shell hook glue + YAML task queue. No classes, no frameworks, no async. Deliberately minimal — two runtime dependencies (PyYAML, ruff).

---

## Numerical Rating: 7.5 / 10

This is a well-designed, purpose-built tool that solves a real problem (making Claude Code loops deterministic and observable) with remarkable economy. The 620-line controller is clean, idempotent, and well-tested (42 tests). The hook lifecycle is thoughtfully designed with safety valves (iteration caps, auto-block, recursion guards). Seven ADRs document real bugs found and fixed — evidence of genuine hardening.

The deductions: shell=True in validation is a documented-but-unresolved trust boundary issue; state file writes are not atomic (contrast with the atomic task file writes); test coverage has meaningful gaps around error paths and integration scenarios; and the single-file architecture will hit a complexity ceiling if the project grows. But for its stated scope — a single-operator deterministic loop — this is solid, honest engineering.

---

## SWOT Analysis

### Strengths

**S1. Atomic task file writes** (`roadrunner.py:61-70`)
The `save_tasks()` function uses write-to-temp → `fsync` → `os.replace()` — the correct POSIX pattern for crash-safe file updates. This is the single most important data integrity measure in the system, and it's done right. Many projects at this scale skip this entirely.

**S2. Validation-gated completion** (`roadrunner.py:366-386`)
`cmd_complete` re-runs validation before marking a task done. The agent cannot self-certify — the validation commands are the source of truth. This is the key correctness invariant, and it's enforced at the code level, not just the prompt level.

**S3. Comprehensive observability for a 620-line tool**
Three observability layers: `logs/trace.jsonl` (structured, machine-readable), `logs/CHANGELOG.md` (human-readable audit trail), `logs/TASK-XXX.md` (per-task work logs with stdout/stderr). This is unusually thorough for a tool this size and makes post-mortem analysis practical.

**S4. Idempotent check-stop design** (`roadrunner.py:424-530`)
`cmd_check_stop` re-reads all state from disk on every invocation. No in-memory state carries across hook calls. This means retries, crashes, and restarts are inherently safe — the system reconverges from disk state every iteration.

**S5. Context survival across compaction**
The PreCompact → snapshot → SessionStart → inject cycle is a clever solution to Claude Code's context window limits. The `.context_snapshot.json` persists task state to disk before compaction destroys conversation history, and the SessionStart hook injects it back. This enables genuinely long-running loops.

**S6. Seven ADRs documenting real bugs found and fixed**
ADR-001 (line-anchored completion signal), ADR-003 (retry storm prevention), ADR-004 (atomic writes), ADR-007 (shell injection in post_write_hook). These aren't speculative — they document real defects discovered during use and the specific fixes applied. This is production-grade rigor.

**S7. Clean procedural design**
Small functions (10-30 lines), single responsibility, `cmd_*` dispatch convention, consistent `_now()` helper, ASCII section banners. The code reads top-to-bottom without needing to chase class hierarchies or inheritance chains. Appropriate for the problem size.

### Weaknesses

**W1. `shell=True` in `run_validation`** (`roadrunner.py:128-134`)
Validation commands execute via `subprocess.run(cmd, shell=True)`. The README and DESIGN.md acknowledge this ("Treat it like a Makefile"), and for a single-operator tool this is a pragmatic choice. However:
- No timeout on subprocess execution — a hanging command blocks the loop forever
- No resource limits (memory, CPU)
- `shlex.split()` + `shell=False` would eliminate shell injection while preserving most use cases

**W2. Non-atomic state file writes** (`roadrunner.py:172-183`)
`write_state()` uses `Path.write_text()` directly — no temp file, no fsync. Compare with `save_tasks()` which does this correctly. A crash during state write could corrupt `.roadmap_state.json`. The system is designed to tolerate this (check-stop re-reads and reconverges), but the inconsistency is a code smell — if atomic writes matter for tasks.yaml, they matter here too.

**W3. No subprocess timeout**
`run_validation()` has no `timeout` parameter on `subprocess.run()`. A validation command that hangs (e.g., waiting for network, deadlocked process) will block the entire loop indefinitely with no recovery path. This is the single most likely production failure mode.

**W4. Incomplete type hints**
Core logic functions are typed (`-> tuple[bool, list[dict]]`), but CLI handlers lack parameter types (`cmd_status(args)` should be `cmd_status(args: argparse.Namespace)`). Return type on `main()` is missing. Coverage is ~60% — enough to be useful but not enough for mypy strict mode.

**W5. Test coverage gaps**
42 tests cover happy paths well, but significant gaps exist:
- No tests for subprocess timeout/hanging commands
- No tests for corrupt YAML/JSON files
- No circular dependency detection (or tests for it)
- No concurrent access testing
- `TestCheckStop` has an unused `_run_check_stop` helper that references undefined `self._last_stdout`
- No integration tests that exercise the full hook → Python → hook cycle

**W6. No input sanitization on task IDs**
`get_task()` accepts any string as `task_id`. While task IDs come from `tasks.yaml` (operator-controlled), the reset marker writes to `.reset_{task_id}` — a task ID containing `../` could write outside the project directory. Low risk for single-operator use, but a latent path traversal.

### Opportunities

**O1. Add subprocess timeouts** (Low effort, high impact)
Add a `timeout` parameter to `subprocess.run()` in `run_validation()`. A sensible default (300s) with per-command override in `tasks.yaml` would eliminate the hanging-command failure mode. This is the single highest-ROI improvement.

```python
# Current
result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=ROOT)
# Improved
timeout = task.get("validation_timeout", 300)
result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=ROOT, timeout=timeout)
```

**O2. Adopt structured state with Pydantic or dataclasses** (Medium effort)
Current state is `dict` everywhere — `task: dict`, `state: dict`, `results: list[dict]`. Using `@dataclass` or `TypedDict` would:
- Catch key typos at definition time
- Enable IDE autocomplete
- Make the implicit schema explicit
- Cost zero runtime dependencies (stdlib dataclasses)

Per current best practices (SitePoint 2026, LangGraph patterns): "typed state via TypedDict, conditional edges for loop control, and explicit termination" — Roadrunner already has the control flow right, but the state typing would bring it to parity.

**O3. Circuit breaker for repeated validation failures** (Low effort)
The auto-block mechanism (5 attempts) is good, but it operates at the task level. A validation command that fails the same way 3 times in a row is unlikely to succeed on attempt 4. A per-command circuit breaker would save tokens and time. Per Mindra (2026): "classify failures into transient vs. permanent, and only retry the transient ones."

**O4. Structured error taxonomy** (Medium effort)
Current error handling is binary: exit 0 or exit 1, with stderr/stdout capture. Categorizing failures (transient vs. permanent, infra vs. logic, timeout vs. assertion) would enable smarter retry logic. Per Atlan (2026): "Execution failures (~25%) are runtime defects... Tier 2 execution failures are at least visible: they usually throw errors."

**O5. Integration test harness** (Medium effort)
The 42 unit tests are solid, but no test exercises the full loop: hook fires → Python check-stop → JSON output → hook interprets → next iteration. A small integration test using `subprocess.run` to simulate the hook lifecycle would catch contract mismatches between bash and Python.

**O6. Checkpoint/resume for multi-command validation** (Low effort)
If a task has 5 validation commands and #4 fails, all 5 re-run on retry. Checkpointing passed commands and resuming from the first failure would reduce wasted compute. Per Mindra (2026): "Retrying expensive operations without checkpointing. If your agent completed steps 1 through 7 of a ten-step workflow..."

### Threats

**T1. Single-file scaling ceiling**
At 620 lines, `roadrunner.py` is manageable. At 1200+ lines, it won't be. The flat procedural style works now but has no natural extension points. If features like parallel task execution, remote state backends, or multi-agent coordination are ever needed, the single-file design will need to be refactored. This is not urgent — it's a known tradeoff.

**T2. Shell hook fragility**
The system depends on bash hooks parsing JSON from stdin and calling Python correctly. This works but is:
- Hard to test automatically (no hook integration tests exist)
- Sensitive to shell quoting issues
- Platform-dependent (bash on macOS may differ from Linux)
- Invisible when it breaks (a broken hook silently stops the loop)

**T3. No validation command sandboxing**
Validation commands run with the operator's full privileges. A typo in `tasks.yaml` (`rm -rf /` instead of `rm -rf ./build`) is catastrophic. This is the accepted trust model, but as the tool is shared or templated, the blast radius grows.

**T4. Context window dependency**
The system's correctness depends on Claude Code correctly reading CLAUDE.md, following the task brief, and outputting ROADMAP_COMPLETE at the right time. If Claude Code's behavior changes (prompt interpretation, hook contracts, stop behavior), the system could break silently. The hook-based architecture is tightly coupled to Claude Code's current lifecycle API.

**T5. No crash recovery for partial task completion**
If Claude Code crashes mid-task (after `start` but before `complete`), the task stays `in_progress`. The auto-block mechanism (5 resume attempts) handles this, but a task that was 90% complete will be re-attempted from scratch — there's no partial progress checkpointing.

---

## Code Quality Assessment

| Dimension | Rating | Notes |
|---|---|---|
| **Readability** | 8/10 | Clean procedural code, good naming, ASCII section headers. Easy to follow top-to-bottom. |
| **Error handling** | 6/10 | JSON parse failures handled gracefully; file I/O errors not caught (will raise); no subprocess timeouts; no recovery from corrupt YAML. |
| **Type hints** | 6/10 | Present on core functions, absent on CLI handlers. No mypy config. Union types use modern `X \| None` syntax (3.10+). |
| **Logging/observability** | 9/10 | Excellent for project size. Three-layer system (trace, changelog, work logs). All lifecycle events traced. |
| **Test coverage** | 7/10 | 42 tests cover core logic well. Gaps in error paths, integration scenarios, and edge cases (circular deps, corrupt files, timeouts). |
| **Python conventions** | 8/10 | PEP 8 compliant (ruff enforced). Pathlib throughout (no os.path). UTC timestamps. Modern syntax (3.10+). |
| **Security** | 6/10 | shell=True is documented but unmitigated. Post-write hook injection fixed (ADR-007). No task ID sanitization. No subprocess resource limits. |

---

## Architecture Assessment

| Dimension | Rating | Notes |
|---|---|---|
| **Loop design** | 9/10 | Deterministic, idempotent, well-guarded. Iteration caps, auto-block, recursion prevention. Best-in-class for the scope. |
| **State management** | 7/10 | Tasks file atomic, state file not. Dict-based (no typed schema). Idempotent reconvergence compensates for most failure modes. |
| **Tool integration** | 7/10 | Clean subprocess interface. No timeouts, no sandboxing, no structured error taxonomy. |
| **Context management** | 8/10 | Snapshot/restore cycle for compaction is well-designed. CLAUDE.md brief is clear and actionable. |
| **Retry/failure handling** | 7/10 | Auto-block after N attempts is good. No distinction between transient/permanent failures. No per-command circuit breaker. |
| **Separation of concerns** | 9/10 | Python owns state/control, Claude owns implementation, hooks own lifecycle wiring. Clean boundaries. |

**Comparison to leading frameworks:**
Roadrunner is not competing with LangGraph/CrewAI/AutoGen — those are *agent frameworks* that help you build agents. Roadrunner is a *harness* that makes an existing agent (Claude Code) deterministic. The closest analogy is LangGraph's checkpointing and state graph, but Roadrunner achieves similar guarantees (typed state, deterministic transitions, persistence, resumability) with ~600 lines of Python and zero framework dependencies. The tradeoff is that it's purpose-built for Claude Code's specific hook API rather than being general-purpose.

---

## Prioritized Recommendations

### Priority 1: Add subprocess timeouts (Low effort, Critical impact)
**What:** Add `timeout=300` (configurable) to `subprocess.run()` in `run_validation()`. Catch `subprocess.TimeoutExpired` and log it as a validation failure.
**Why:** A hanging validation command is the most likely production failure mode. Every fault-tolerance guide (Mindra 2026, Atlan 2026) lists unbounded execution as a top anti-pattern. This is a one-line fix with outsized impact.
**File:** `roadrunner.py:128-134`

### Priority 2: Make state writes atomic (Low effort, Medium impact)
**What:** Apply the same temp-file + fsync + os.replace pattern from `save_tasks()` to `write_state()`.
**Why:** Internal consistency — if atomic writes matter for tasks.yaml (ADR-004), they matter for state. A corrupted state file during auto-block could lose the attempt counter, causing retry storms.
**File:** `roadrunner.py:172-183`

### Priority 3: Sanitize task IDs (Low effort, Low-Medium impact)
**What:** Add a regex check in `validate_task_schema()`: task IDs must match `^[A-Z]+-\d+$` (or similar). Reject IDs containing `/`, `..`, or shell metacharacters.
**Why:** Prevents path traversal via `.reset_{task_id}` and `logs/{task_id}.md`. Defense in depth.
**File:** `roadrunner.py:37-49`

### Priority 4: Add integration tests for hook lifecycle (Medium effort, High impact)
**What:** A test that simulates: stdin JSON → `cmd_check_stop` → stdout JSON → verify decision. Then a second test that runs `stop_hook.sh` via subprocess and verifies the full bash→Python→JSON cycle.
**Why:** The hook contract (bash parses JSON, calls Python, interprets output) is the system's most fragile boundary and has zero automated tests. Every ADR except ADR-006 was a bug at this boundary.
**File:** New test class in `tests/test_roadrunner.py`

### Priority 5: Type the state with dataclasses (Medium effort, Medium impact)
**What:** Replace `task: dict` / `state: dict` with `@dataclass` or `TypedDict`. Define `Task`, `RoadmapState`, `ValidationResult` as explicit types.
**Why:** Catches key typos, enables IDE support, makes the implicit schema explicit. Aligns with LangGraph's "typed state" pattern (the current best practice for deterministic agents). Zero new dependencies.
**File:** `roadrunner.py` (top of file)

### Priority 6: Add per-command circuit breaker (Low effort, Low impact)
**What:** Track validation command failure history in state. If the same command fails 3 consecutive times with the same stderr, skip it and mark the task as blocked with a "permanent failure" note.
**Why:** Saves tokens and time on non-transient failures. Current auto-block operates at task granularity only.
**File:** `roadrunner.py:114-163`, `.roadmap_state.json` schema extension

---

## Validation of This Review

- **Source files read:** roadrunner.py (full), all 4 hooks + _session_start.py, tests/test_roadrunner.py (full), tasks/tasks.yaml, DESIGN.md, README.md, CLAUDE.md, settings.json, .roadmap_state.json, .context_snapshot.json, all 7 ADRs listed
- **Research grounded in:** EXA searches on agentic loop best practices (SitePoint 2026 definitive guide, Atlan 2026 anti-patterns taxonomy, Mindra 2026 fault-tolerance patterns, LangGraph/CrewAI/AutoGen comparisons from DataCamp, Medium, Latenode), Anthropic's MCP code execution patterns
- **Insufficient context to assess:** Runtime performance under real Claude Code sessions (would require observing a live loop); hook behavior differences across macOS/Linux bash versions; actual token cost of the snapshot/restore cycle
