# Roadrunner Configuration

This document covers every knob Roadrunner exposes: module-level tunables,
environment variables, the `tasks.yaml` schema, and the two on-disk state
files (`.roadmap_state.json` and `.context_snapshot.json`).

## Tunables

All tunables live at the top of `roadrunner.py` so operators have a single
place to adjust retention and safety knobs. Change them in source — there is
no runtime override for these (use the env var path documented below for the
iteration cap).

| Constant                     | Default         | Purpose                                                                                                               |
| ---------------------------- | --------------- | --------------------------------------------------------------------------------------------------------------------- |
| `DEFAULT_VALIDATION_TIMEOUT` | `300` seconds   | Per-validation-command timeout. Overridable per task via the `validation_timeout` field in `tasks.yaml`.              |
| `MAX_TASK_ATTEMPTS`          | `5`             | Auto-block threshold. If the Stop hook observes the same task `in_progress` across this many resume cycles without a `complete`, the task is flipped to `blocked` and the loop moves on. |
| `TASKS_BACKUP_KEEP`          | `5`             | Rolling `tasks.yaml.bak.N` copies retained on every `save_tasks` write. Oldest is evicted atomically via `Path.replace`. |
| `LOG_ROTATE_BYTES`           | `10 * 1024²`    | Trigger threshold (10 MiB) for rotating `logs/trace.jsonl` and `logs/CHANGELOG.md`. Rotation runs at every task boundary. |
| `LOG_RETAIN_DAYS`            | `7`             | Rotated/compressed logs older than this are deleted at the next rotation pass.                                        |
| `STATE_SCHEMA_VERSION`       | `2`             | On-disk schema for `.roadmap_state.json`. Bump when the format changes incompatibly. See the migration contract below. |
| `SNAPSHOT_SCHEMA_VERSION`    | `1`             | On-disk schema for `.context_snapshot.json`. Bump when the PreCompact snapshot format changes incompatibly.           |

### Per-task validation timeout

`DEFAULT_VALIDATION_TIMEOUT` is the fallback. Individual tasks override it by
setting `validation_timeout: <seconds>` on the task:

```yaml
- id: ROAD-099
  title: "Long-running integration test"
  validation_timeout: 900     # 15 minutes for this task only
  validation_commands:
    - ./scripts/slow-e2e.sh
```

The override must be a positive number; `validate_task_schema` rejects
anything else at load time.

### Environment variables

| Variable                 | Consumer                      | Effect                                                                           |
| ------------------------ | ----------------------------- | -------------------------------------------------------------------------------- |
| `ROADMAP_MAX_ITERATIONS` | `hooks/stop_hook.sh`          | Overrides the per-session iteration cap; passed to `roadrunner.py check-stop` as `--max-iterations`. Defaults to `100`. See "Runaway-Protection Cap" below. |
| `CLAUDE_PROJECT_DIR`     | every hook script             | Set by Claude Code itself; hooks use it to locate `roadrunner.py`. You do not set this manually. |

## Iteration Counters

Roadrunner tracks two iteration counters in `.roadmap_state.json`. They exist so
the runaway-protection cap does not accidentally become a lifetime ceiling on the
project as a whole.

| Counter             | Purpose                                           | Reset on                                  |
| ------------------- | ------------------------------------------------- | ----------------------------------------- |
| `iteration`         | Lifetime audit counter. Never gates behavior.     | `reset-iteration --hard` only             |
| `session_iteration` | Per-session runaway guard. Gates the Stop-hook cap. | Every `SessionStart` hook fire, plus `reset-iteration` (soft or hard) |

Both counters are incremented on every `check-stop` invocation (i.e., every time
Claude finishes a turn and the Stop hook fires). The cap is compared against
`session_iteration` only.

### Why Two Counters?

Before 2026-04-24, Roadrunner kept a single `iteration` counter and the cap fired
when that counter hit `max_iter`. Because the counter persisted across every
`claude` invocation for the same project, long-running projects (e.g., entra-triage
running periodically against production data) would accumulate iterations across
many sessions and eventually trip the cap even though no single run looped. The
split preserves the audit trail (`iteration`) while making the runaway guard
per-session (`session_iteration`). See `logs/ROAD-010.md` for the full history.

## Runaway-Protection Cap

The Stop hook enforces a maximum number of Claude turns per session.

**Default:** 100.

**Override (env var, per invocation):**

```bash
export ROADMAP_MAX_ITERATIONS=50   # tighter cap for a short run
```

The env var is read by `hooks/stop_hook.sh` and passed as `--max-iterations` to
`roadrunner.py check-stop`. The CLI itself defaults to 100 if the flag is absent.

**When the cap fires:** `check-stop` emits a hard halt with `stopReason` explaining
the cap was hit. The session terminates; Alex's next `claude` invocation starts
fresh at session iteration 0 (because `SessionStart` resets it).

## Resetting Iteration Counters

The `reset-iteration` subcommand provides manual control.

```bash
# Reset session counter only. Lifetime counter preserved.
python3 roadrunner.py reset-iteration --soft   # default if no flag

# Reset both counters. Destructive; loses lifetime audit trail.
python3 roadrunner.py reset-iteration --hard
```

Trace events (`reset_iteration`) record the mode and the prior lifetime counter
for every invocation, so `--hard` is recoverable via the trace log if needed.

## State Schema

`.roadmap_state.json` is versioned via `STATE_SCHEMA_VERSION`. Roadrunner's
forward-compat contract:

- **Older Roadrunner reading newer state:** refuses to run (`version > current`
  exits with an upgrade-required message). Prevents data loss from writes that
  drop fields the newer version added.
- **Newer Roadrunner reading older state:** migrates transparently. Missing fields
  are filled in via `setdefault` during `read_state`, then written back in the
  new schema on the next `write_state`.

### Schema v1 → v2 (ROAD-010, 2026-04-24)

Adds `session_iteration: int` field. Default for legacy state files: `0`. No
manual migration required; first load auto-fills.

## `tasks.yaml` reference

`tasks/tasks.yaml` is the roadmap — the source of truth for task ordering,
dependencies, and validation contracts. It has two kinds of entries:
**top-level project config** and the **`tasks:` list**.

### Top-level keys

```yaml
project_base: main          # required-ish; falls back to current git branch, then 'main'
push_on_complete: base      # optional; default 'none'
tasks:                      # required; the ordered task list
  - id: ROAD-001
    # ...
```

| Key                | Type                     | Required? | Purpose                                                                                                           |
| ------------------ | ------------------------ | --------- | ----------------------------------------------------------------------------------------------------------------- |
| `project_base`     | string                   | optional  | Branch that `roadrunner/<TASK-ID>` branches fork from. Prevents stacking. Falls back to current branch, then `main`. |
| `push_on_complete` | `"base"` / `"task"` / `"both"` / `"none"` | optional | What to push after a successful merge on `complete`. Default `"none"` (local only). |
| `tasks`            | list                     | required  | Ordered task list. See field reference below.                                                                     |

### Per-task fields

Required on every task:

| Field    | Type   | Notes                                                       |
| -------- | ------ | ----------------------------------------------------------- |
| `id`     | string | Must match `^[A-Z]+-\d+$` (e.g., `ROAD-001`, `TASK-042`).   |
| `title`  | string | Short, human-readable title. Used in briefs and status output. |
| `status` | string | One of `todo`, `in_progress`, `done`, `blocked`.             |

Optional on every task:

| Field                   | Type           | Default       | Notes                                                                                                  |
| ----------------------- | -------------- | ------------- | ------------------------------------------------------------------------------------------------------ |
| `depends_on`            | list[string]   | `[]`          | Task IDs that must be `done` before this task becomes eligible. Must be a list; cycles are rejected by `roadrunner analyze`. |
| `goal`                  | string         | `""`          | Prose description. Injected into the task brief at session start / resume.                             |
| `acceptance_criteria`   | list[string]   | `[]`          | Bullet list shown in the brief. Advisory — not checked programmatically.                               |
| `validation_commands`   | list[string]   | `[]`          | Shell commands run by `roadrunner validate`. All must exit 0 for `complete` to succeed.                |
| `validation_timeout`    | number         | `DEFAULT_VALIDATION_TIMEOUT` (300) | Per-task override in seconds. Must be a positive number.                       |
| `files_expected`        | list[string]   | `[]`          | Paths the task is allowed to touch. Used by `roadrunner commit` to scope staged changes.               |
| `documentation_targets` | list[string]   | `[]`          | Documentation files that should also be updated. Advisory — informational only.                        |
| `notes`                 | string         | `""`          | Free-form notes. Not interpreted by the control loop.                                                   |

Schema validation (`validate_task_schema`) runs on every `load_tasks`. It
rejects: missing required fields, invalid `id` format, unknown `status`,
non-list `depends_on` or `validation_commands`, and non-positive
`validation_timeout`.

### Minimal example

```yaml
project_base: main
tasks:
  - id: TASK-001
    title: "First task — replace me"
    status: todo
    depends_on: []
    goal: |
      Describe what this task accomplishes.
    acceptance_criteria:
      - "Describe a concrete, observable outcome"
    validation_commands:
      - "echo 'replace with a real check (test, lint, build)'"
    files_expected: []
```

---

## `.roadmap_state.json`

The control-loop state file. Mutated on every `start`, `complete`, `block`,
`reset`, and `check-stop`. Protected by an advisory POSIX lock
(`.roadmap_state.lock`) and written atomically via `os.replace`.

Schema v2 (current):

```json
{
  "schema_version": 2,
  "current_task_id": "ROAD-006",
  "iteration": 116,
  "session_iteration": 1,
  "attempts_per_task": {
    "ROAD-001": 3,
    "ROAD-005": 5
  },
  "updated_at": "2026-04-25T02:24:17.324121+00:00",
  "base_branch": "roadrunner/ROAD-005"
}
```

| Field               | Type            | Purpose                                                                                |
| ------------------- | --------------- | -------------------------------------------------------------------------------------- |
| `schema_version`    | int             | Matches `STATE_SCHEMA_VERSION` (currently `2`). Controls forward-compat gate.           |
| `current_task_id`   | string \| null  | ID of the task currently `in_progress`, or null between boundaries.                    |
| `iteration`         | int             | Lifetime audit counter. Never gates behavior. Only reset via `reset-iteration --hard`. |
| `session_iteration` | int             | Per-session runaway-protection counter. Reset every `SessionStart` fire and via `reset-iteration`. Gates the cap. |
| `attempts_per_task` | dict[str, int]  | Count of resume cycles per task. Reaching `MAX_TASK_ATTEMPTS` (5) auto-blocks the task. |
| `updated_at`        | ISO-8601 string | UTC timestamp of the last write.                                                       |
| `base_branch`       | string          | The branch in play when the last `start` ran — used to recover the base branch after task merges. |

## `.context_snapshot.json`

Written by the PreCompact hook (`roadrunner snapshot`) so Claude can cold-resume
after context compaction. Verified by the PostCompact hook
(`roadrunner post-compact`), which logs a `post_compact_verify` trace event.

Schema v1 (current):

```json
{
  "schema_version": 1,
  "snapshot_at": "2026-04-25T02:11:50.665330+00:00",
  "current_task": "ROAD-005",
  "iteration": 109,
  "next_eligible": "ROAD-006",
  "status_summary": {
    "ROAD-001": "done",
    "ROAD-002": "done",
    "ROAD-005": "in_progress",
    "ROAD-006": "todo"
  }
}
```

| Field            | Type            | Purpose                                                                 |
| ---------------- | --------------- | ----------------------------------------------------------------------- |
| `schema_version` | int             | Matches `SNAPSHOT_SCHEMA_VERSION` (currently `1`).                      |
| `snapshot_at`    | ISO-8601 string | UTC timestamp of the snapshot write.                                    |
| `current_task`   | string \| null  | ID of the `in_progress` task at snapshot time, if any.                   |
| `iteration`      | int             | Lifetime iteration counter at snapshot time.                            |
| `next_eligible`  | string \| null  | ID of the next eligible `todo` task, if any.                            |
| `status_summary` | dict[str, str]  | Flat `id → status` map covering every task in `tasks.yaml`.             |

PostCompact verification checks that every required field is present and that
`schema_version == SNAPSHOT_SCHEMA_VERSION`. Mismatches surface as
`schema_mismatch` / `missing_fields` keys in the `post_compact_verify` trace
event.

---

## Downstream Consumers

`entra-triage` vendors `roadrunner.py` in-tree and syncs periodically. Because the
v1 → v2 migration is setdefault-based (not a hard schema check), vendored copies
pick up the new schema without coordination: the state file on disk migrates the
first time a post-sync `roadrunner.py` invocation runs.

If you fork or vendor this file elsewhere, follow the same contract:

1. Bump `STATE_SCHEMA_VERSION` when adding new state fields.
2. In `read_state`, put `data.setdefault(new_field, default)` after the JSON load
   so older state files migrate cleanly.
3. Keep the forward-compat gate (`version > STATE_SCHEMA_VERSION → exit`) intact
   so older binaries can't silently corrupt newer state.
