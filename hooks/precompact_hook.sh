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
elif [ -f "$PROJECT_ROOT/roadrunner.py" ]; then
    RR=(python3 "$PROJECT_ROOT/roadrunner.py")
else
    echo "[roadrunner] cannot find 'roadrunner' on PATH and no roadrunner.py in $PROJECT_ROOT" >&2
    exit 0
fi

# Write snapshot and emit additionalContext JSON for Claude
"${RR[@]}" snapshot
