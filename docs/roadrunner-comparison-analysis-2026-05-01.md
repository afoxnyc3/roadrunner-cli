# Project vs. Roadrunner Analysis (2026-05-01)

## Executive summary
This repository is already a deterministic workflow harness intentionally designed to solve many Roadrunner pain points: Python-owned control flow, validation-gated completion, disk-backed resumability, hook-driven continuation, and auditable lifecycle logs. Relative to a less deterministic "classic" Roadrunner loop, this implementation is materially more opinionated about completion invariants and progression gates.

The strongest reusable pattern for Roadrunner evolution is the explicit split:
1) planner/selector in Python,
2) executor in the model session,
3) external stop gate that cannot be bypassed by model self-reporting.

For a target state of "Python repeatedly advancing features/issues/phases/roadmap items until completion," the main gap is abstraction level: this project is task-centric today, not first-class feature/issue/phase-centric, and uses mostly imperative command flow rather than a formal deterministic state machine with typed transitions.

## Key architectural differences from Roadrunner

### 1) Control-plane ownership and stop semantics
- This project enforces a hard boundary: Python decides whether work continues (`check-stop`), while the model only executes the current brief. The Stop hook blocks normal session termination until control logic says otherwise.
- The completion signal is line-anchored and explicitly guarded, reducing accidental loop termination.
- Iteration accounting happens inside stop checks, not only task-start paths, preventing silent bypass.

**Difference from typical Roadrunner deployments:** less reliance on agent self-assessment; more reliance on external deterministic continuation logic.

### 2) State and persistence discipline
- `tasks/tasks.yaml` is schema-validated and atomically written with backup rotation.
- `.roadmap_state.json` is lock-guarded and schema-versioned.
- Context continuity is explicit via snapshot write/read across compaction boundaries.

**Difference:** stronger crash/restart resilience and replayability than ad hoc in-memory orchestration loops.

### 3) Retry and failure governance
- In-progress resume attempts are counted; repeated failures auto-block after a cap.
- Blocked tasks do not deadlock the entire loop; they are surfaced as actionable anomalies.

**Difference:** explicit retry-storm prevention and bounded failure behavior.

### 4) Observability model
- Three layers: structured trace (`trace.jsonl`), project changelog, and per-task logs.

**Difference:** deterministic postmortem path and machine-readable event history for later policy tuning.

### 5) Planning vs execution separation
- Selection/dependency resolution happens in CLI control commands; implementation is delegated to the model.
- Validation gate is treated as source of truth, not narrative completion.

**Difference:** cleaner planner/executor split than prompt-only autonomous loops.

## Features or patterns worth adopting in Roadrunner

1. **External stop-gate contract**
   - Keep stop decisions outside the model response loop; model cannot declare done unless controller verifies state and validations.

2. **Deterministic decision order in continuation checks**
   - Fixed sequence: iteration cap → completion sentinel check → in-progress resume → next eligible → blocked reporting → anomaly → all-done prompt.

3. **Atomic + versioned state strategy**
   - Use schema versions, atomic writes, and lock files for all mutable control-plane artifacts.

4. **Attempt counters and auto-block policy**
   - Apply per-work-item attempt tracking with bounded retries to prevent infinite loops.

5. **Snapshot-injection for context loss recovery**
   - Persist minimal orchestrator state before compaction; rehydrate at session start with deterministic summary.

6. **Structured trace telemetry for control tuning**
   - Emit per-transition events to support later analysis of bottlenecks, stuck states, and policy regressions.

7. **Validation-as-gate invariant**
   - Enforce mandatory re-validation at completion transition (not just at mid-task checkpoints).

## Risks, tradeoffs, or incompatibilities

1. **Hook coupling risk**
   - Heavy dependence on host hook contracts can break if runtime APIs change.

2. **Task-centric schema mismatch**
   - Current primitives are `TASK-*`; your target needs native `feature/issue/phase/roadmap` entities with hierarchical progression.

3. **Sequential throughput tradeoff**
   - Determinism improves reliability but may reduce throughput vs speculative parallelism.

4. **Shell-command trust boundary**
   - Validation commands remain an execution-safety boundary and need governance/sandbox policy in broader deployments.

5. **Policy rigidity**
   - Strict gates can over-block on transient infra noise unless error taxonomy distinguishes transient vs permanent failures.

## Specific recommendations for evolving Roadrunner toward a deterministic Python-controlled workflow

1. **Introduce a typed orchestration graph in Python**
   - Add first-class entities: `Roadmap`, `Phase`, `Feature`, `Issue`, `Task`.
   - Encode allowed transitions in code (explicit state machine), not implicit command ordering.

2. **Refactor `check-stop` into a pure decision engine**
   - Implement `decide_next(state, roadmap) -> Decision` as a side-effect-free function.
   - Keep side effects (state writes, logs, hook payload formatting) in adapters.

3. **Add hierarchical progress accounting**
   - Roll task completion up to issue/feature/phase readiness.
   - Require deterministic closure criteria at each level (validation sets, dependency closure, required evidence).

4. **Separate planning and execution artifacts**
   - Maintain `plan_state` (decomposition/prioritization) distinct from `exec_state` (attempts, current node, runtime outcomes).
   - Permit re-planning only at explicit checkpoints with audit entries.

5. **Implement failure taxonomy + policy table**
   - Classify failures: `transient_infra`, `deterministic_test_fail`, `missing_dependency`, `policy_violation`, `timeout`.
   - Map each type to retry budget, backoff, escalation route, and block conditions.

6. **Make loop idempotent per transition**
   - Persist transition intents with monotonic sequence IDs.
   - On restart, replay/skip duplicate transitions safely.

7. **Add deterministic decomposer stage**
   - Prior to execution, run a Python decomposition pass that normalizes roadmap items into executable units with dependency DAG and phase tags.

8. **Promote roadmap-level SLAs and watchdogs**
   - Add per-phase max turns/time budgets and stagnation detectors.
   - Auto-escalate if no net closure occurs over N iterations.

## Prioritized implementation list

### P0 (immediate)
1. Build a pure Python `DecisionEngine` module with deterministic decision ordering and exhaustive decision enums.
2. Introduce typed state models and schema migration for hierarchical entities.
3. Add transition journal (`events.log`) with idempotency keys and monotonic counters.

### P1 (next)
4. Implement hierarchical roll-up logic (`task -> issue -> feature -> phase -> roadmap`).
5. Add failure taxonomy + retry/backoff policy table.
6. Extend stop-hook payloads to include explicit `next_action` types and machine-readable rationale codes.

### P2 (then)
7. Add planner checkpoint loop (re-decompose unresolved roadmap items at controlled intervals).
8. Introduce stagnation analytics from trace logs (no-progress windows, repeat-failure motifs).
9. Add optional parallel branches only where dependency graph permits, while preserving deterministic merge gates.

### P3 (hardening)
10. Add integration tests for full hook/controller loop contracts.
11. Add chaos tests for crash/restart during each transition boundary.
12. Add policy tests that prove deterministic outcomes from identical initial state + inputs.
