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
elif [ -f "$PROJECT_ROOT/roadrunner.py" ]; then
    RR=(python3 "$PROJECT_ROOT/roadrunner.py")
else
    exit 0  # observability hook; never block on missing CLI
fi

# Pipe stdin through; never let observability failures break the loop.
"${RR[@]}" post-compact || true
exit 0
