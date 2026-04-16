#!/usr/bin/env bash
# hooks/task_completed_hook.sh
# ─────────────────────────────────────────────────────────────────────────────
# TaskCompleted Hook — fires when any agent tries to mark a task as completed.
# Runs the task's validation_commands before allowing completion.
#
# Exit behavior:
#   exit 0   → allow task completion
#   exit 2   → block completion, stderr is fed back to the model as feedback
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

INPUT=$(cat)

# Debug: log raw payload (project-local, not /tmp) so we can confirm field names.
# Remove this block once the TaskCompleted payload schema is confirmed from a live run.
DEBUG_LOG="$PROJECT_ROOT/logs/.taskcompleted_payloads.log"
mkdir -p "$PROJECT_ROOT/logs"
echo "--- $(date -u +%Y-%m-%dT%H:%M:%SZ) ---" >> "$DEBUG_LOG"
echo "$INPUT" >> "$DEBUG_LOG"

# Extract a TASK-### roadmap id from the payload. Probe common fields, then
# fall back to scanning the whole payload for a TASK-### token. The roadmap's
# ID space is TASK-\d{3}+; Claude Code's internal task_id is unrelated.
TASK_ID=$(echo "$INPUT" | python3 -c "
import json, re, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print('')
    sys.exit(0)

def first_match(s):
    m = re.search(r'TASK-\d{3,}', s or '')
    return m.group(0) if m else ''

# Priority order: explicit fields, then nested tool_input, then scan full payload.
candidates = [
    d.get('task_id'),
    d.get('taskId'),
    d.get('title'),
    d.get('content'),
    (d.get('tool_input') or {}).get('task_id'),
    (d.get('tool_input') or {}).get('subject'),
    (d.get('tool_input') or {}).get('description'),
]
for c in candidates:
    if isinstance(c, str):
        hit = first_match(c)
        if hit:
            print(hit)
            sys.exit(0)

# Last resort: scan the entire payload as JSON text.
print(first_match(json.dumps(d)))
" 2>/dev/null || echo "")

if [ -z "$TASK_ID" ]; then
    # Payload did not reference a roadmap task — allow through.
    exit 0
fi

# Run validation via Python controller
python3 "$PROJECT_ROOT/roadrunner.py" validate "$TASK_ID"
RESULT=$?

if [ $RESULT -ne 0 ]; then
    echo "Validation failed for $TASK_ID. Fix the issues above before marking complete." >&2
    exit 2
fi

exit 0
