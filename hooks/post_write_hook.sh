#!/usr/bin/env bash
# hooks/post_write_hook.sh
# ─────────────────────────────────────────────────────────────────────────────
# PostToolUse (Write|Edit|MultiEdit) — runs async after every file write.
# Runs ruff on Python files. Runs yamllint on YAML files.
# Async: Claude continues immediately; output injected on next turn.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

INPUT=$(cat)

FILE_PATH=$(echo "$INPUT" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('tool_input', {}).get('file_path', '') or
          d.get('tool_input', {}).get('path', ''))
except:
    print('')
" 2>/dev/null || echo "")

if [ -z "$FILE_PATH" ]; then
    exit 0
fi

# Python: ruff check
if [[ "$FILE_PATH" == *.py ]]; then
    if command -v ruff &>/dev/null; then
        ruff check "$FILE_PATH" --quiet || true
    fi
fi

# YAML: basic syntax check
if [[ "$FILE_PATH" == *.yaml ]] || [[ "$FILE_PATH" == *.yml ]]; then
    python3 -c "import yaml; yaml.safe_load(open('$FILE_PATH'))" 2>&1 || true
fi

exit 0
