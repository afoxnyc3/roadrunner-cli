#!/usr/bin/env bash
# hooks/session_start_hook.sh
# ─────────────────────────────────────────────────────────────────────────────
# SessionStart Hook — fires when a Claude Code session begins or resumes.
# Delegates to `roadrunner session-start` (or `python -m roadrunner
# session-start`), which reads tasks.yaml live and emits an
# additionalContext directive for turn 1 (or exits silently if no
# roadmap is present). The .context_snapshot.json file is intentionally
# NOT consulted here — see cmd_session_start in src/roadrunner/cli.py
# for the rationale (stale snapshots can poison context).
#
# Exit behavior:
#   exit 0 always — this hook is informational, never blocks.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Resolve a working roadrunner invocation (same priority as stop_hook.sh):
#   1. installed console script  2. python3 -m roadrunner  3. PYTHONPATH src/
if command -v roadrunner >/dev/null 2>&1; then
    RR=(roadrunner)
elif python3 -c "import roadrunner" >/dev/null 2>&1; then
    RR=(python3 -m roadrunner)
elif [ -d "$PROJECT_ROOT/src/roadrunner" ]; then
    RR=(env "PYTHONPATH=$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m roadrunner)
else
    echo "[roadrunner] cannot import the 'roadrunner' package; SessionStart skipped" >&2
    exit 0  # SessionStart is informational; do not block startup
fi

"${RR[@]}" session-start
