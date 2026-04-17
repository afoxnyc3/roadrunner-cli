#!/usr/bin/env bash
# hooks/session_start_hook.sh
# ─────────────────────────────────────────────────────────────────────────────
# SessionStart Hook — fires when a Claude Code session begins or resumes.
# Delegates to `roadrunner.py session-start`, which reads .context_snapshot.json
# and emits additionalContext JSON (or exits silently if no snapshot exists).
#
# Exit behavior:
#   exit 0 always — this hook is informational, never blocks.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

python3 "$PROJECT_ROOT/roadrunner.py" session-start
