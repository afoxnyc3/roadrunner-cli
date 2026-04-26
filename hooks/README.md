# Roadrunner Claude Code Hooks

These shell scripts are wired up by `.claude/settings.json` and fire on
Claude Code lifecycle events. Each one is a thin shim that re-invokes
`roadrunner.py` with a specific subcommand. The full event contract lives
in [`DESIGN.md` §2](../DESIGN.md).

| Hook                      | Fires on                                | Purpose                                                                                                                  |
| ------------------------- | --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `stop_hook.sh`            | Claude Code is about to stop            | The core enforcement point. Decides whether the loop is allowed to halt; otherwise injects the next task brief.          |
| `session_start_hook.sh`   | A new Claude Code session begins        | Reads `.context_snapshot.json`, emits a roadmap overview as additional context, and resets the per-session iteration counter. |
| `precompact_hook.sh`      | Just before context compaction          | Dumps current roadmap state to `.context_snapshot.json` so the new session can recover it.                               |
| `postcompact_hook.sh`     | Just after context compaction           | Verifies the snapshot survived and writes a `post_compact_verify` event to `logs/trace.jsonl`.                           |
| `post_write_hook.sh`      | After a Write/Edit/MultiEdit tool use   | Schema-validates `tasks/tasks.yaml` and rolls a backup when that file is the one being written. Other writes are ignored. |

All scripts exit 0 on success; non-zero exit codes are surfaced to Claude
Code as hook failures and shown to the operator. Every script is
shellcheck-clean (`just lint-hooks`).
