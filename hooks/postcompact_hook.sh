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

# Pipe stdin through; never let observability failures break the loop.
python3 "$PROJECT_ROOT/roadrunner.py" post-compact || true
exit 0
