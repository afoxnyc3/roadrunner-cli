#!/usr/bin/env bash
# hooks/precompact_hook.sh
# ─────────────────────────────────────────────────────────────────────────────
# PreCompact Hook — fires before conversation compaction.
# Writes current roadmap state to disk so Claude can resume after context reset.
# stdout is injected into the new context window as additionalContext.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

if command -v roadrunner >/dev/null 2>&1; then
    RR=(roadrunner)
elif python3 -c "import roadrunner" >/dev/null 2>&1; then
    RR=(python3 -m roadrunner)
elif [ -d "$PROJECT_ROOT/src/roadrunner" ]; then
    RR=(env "PYTHONPATH=$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m roadrunner)
else
    echo "[roadrunner] cannot import the 'roadrunner' package; PreCompact snapshot skipped" >&2
    exit 0
fi

# Write snapshot and emit additionalContext JSON for Claude
"${RR[@]}" snapshot
