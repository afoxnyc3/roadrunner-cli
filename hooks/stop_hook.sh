#!/usr/bin/env bash
# hooks/stop_hook.sh
# ─────────────────────────────────────────────────────────────────────────────
# Stop Hook — fires when Claude Code agent finishes responding.
# Determines whether Claude is allowed to stop or must continue working.
#
# Output contract (two shapes for two outcomes — not interchangeable):
#   {"decision": "block", "reason": "..."}
#     → Soft block. Claude continues; `reason` is injected as next-turn context.
#     Used for: resume brief, next-task brief, blocked-task report, done-prompt.
#
#   {"continue": false, "stopReason": "..."}
#     → Hard halt. Claude Code session terminates; `stopReason` shown to user.
#     Used ONLY for the iteration cap. Overrides any other decision.
#
# Exit codes:
#   exit 0  → JSON on stdout is authoritative (normal case)
#   exit 2  → legacy force-continue via stderr; prefer JSON output instead
#
# CRITICAL: Always check stop_hook_active to prevent infinite loops.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
MAX_ITERATIONS="${ROADMAP_MAX_ITERATIONS:-100}"  # ROAD-010: session cap (was 50 lifetime)

# Resolve a working roadrunner invocation:
#   1. installed `roadrunner` console script (pip install roadrunner-cli)
#   2. `python3 -m roadrunner` (covers editable installs and source checkouts
#      where `pip install -e .` has been run)
#   3. PYTHONPATH-injected source layout (fresh source checkout, no install)
if command -v roadrunner >/dev/null 2>&1; then
    RR=(roadrunner)
elif python3 -c "import roadrunner" >/dev/null 2>&1; then
    RR=(python3 -m roadrunner)
elif [ -d "$PROJECT_ROOT/src/roadrunner" ]; then
    RR=(env "PYTHONPATH=$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m roadrunner)
else
    echo "[roadrunner] cannot import the 'roadrunner' package; install with 'pip install roadrunner-cli' or 'pip install -e .'" >&2
    exit 1
fi

# Read stdin from Claude Code
INPUT=$(cat)

# ── Infinite loop guard ───────────────────────────────────────────────────────
# If stop_hook_active is true, a previous hook invocation already ran.
# Allow Claude to stop to break the loop.
HOOK_ACTIVE=$(echo "$INPUT" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print('true' if d.get('stop_hook_active') else 'false')
except:
    print('false')
" 2>/dev/null || echo "false")

if [ "$HOOK_ACTIVE" = "true" ]; then
    exit 0
fi

# ── Delegate to Python controller ─────────────────────────────────────────────
# Pass stdin through to check-stop command which owns all logic.
echo "$INPUT" | "${RR[@]}" check-stop --max-iterations "$MAX_ITERATIONS"
