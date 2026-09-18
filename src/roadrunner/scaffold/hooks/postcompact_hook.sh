#!/usr/bin/env bash
# hooks/postcompact_hook.sh
# ─────────────────────────────────────────────────────────────────────────────
# PostCompact Hook — fires after Claude Code completes context compaction.
# Verifies that .context_snapshot.json survived compaction and logs a
# `post_compact_verify` trace event. Side-effect only: PostCompact does not
# support decision control (no block/allow), so this hook is informational
# and always exits 0.
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
    exit 0  # observability hook; never block on missing CLI
fi

# Pipe stdin through; never let observability failures break the loop.
"${RR[@]}" post-compact || true
exit 0
