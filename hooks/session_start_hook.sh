#!/usr/bin/env bash
# hooks/session_start_hook.sh
# ─────────────────────────────────────────────────────────────────────────────
# SessionStart Hook — fires when a Claude Code session begins or resumes.
# Injects .context_snapshot.json as additionalContext if it exists.
# This ensures roadmap state survives compaction and session restarts.
#
# Exit behavior:
#   exit 0 always — this hook is informational, never blocks.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SNAPSHOT="$PROJECT_ROOT/.context_snapshot.json"

if [ ! -f "$SNAPSHOT" ]; then
    exit 0
fi

CONTEXT=$(python3 "$SCRIPT_DIR/_session_start.py" "$SNAPSHOT" 2>/dev/null) || true

if [ -n "$CONTEXT" ]; then
    echo "$CONTEXT"
fi

exit 0
