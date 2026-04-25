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

# Prefer the installed `roadrunner` console script (pip install roadrunner-cli);
# fall back to `python3 roadrunner.py` for source/dev checkouts that have the
# script at the project root.
if command -v roadrunner >/dev/null 2>&1; then
    RR=(roadrunner)
elif [ -f "$PROJECT_ROOT/roadrunner.py" ]; then
    RR=(python3 "$PROJECT_ROOT/roadrunner.py")
else
    echo "[roadrunner] cannot find 'roadrunner' on PATH and no roadrunner.py in $PROJECT_ROOT" >&2
    exit 0  # SessionStart is informational; do not block startup
fi

"${RR[@]}" session-start
