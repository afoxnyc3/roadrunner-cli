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

# Prefer the local roadrunner.py (source/dev checkouts and any project that
# vendored the script at its root) so $PROJECT_ROOT-bound state stays bound;
# fall back to the installed `roadrunner` console script for `pip install
# roadrunner-cli` users whose freshly-init'd projects have no script at root.
if [ -f "$PROJECT_ROOT/roadrunner.py" ]; then
    RR=(python3 "$PROJECT_ROOT/roadrunner.py")
elif command -v roadrunner >/dev/null 2>&1; then
    RR=(roadrunner)
else
    echo "[roadrunner] cannot find 'roadrunner' on PATH and no roadrunner.py in $PROJECT_ROOT" >&2
    exit 0  # SessionStart is informational; do not block startup
fi

"${RR[@]}" session-start
