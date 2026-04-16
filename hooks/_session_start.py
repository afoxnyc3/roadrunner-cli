#!/usr/bin/env python3
"""Emit additionalContext JSON from .context_snapshot.json for SessionStart hook."""
import json
import sys

try:
    with open(sys.argv[1]) as f:
        snap = json.load(f)
except Exception:
    sys.exit(0)

parts = []
if snap.get("current_task"):
    parts.append(f"Current task: {snap['current_task']}")
if snap.get("next_eligible"):
    parts.append(f"Next eligible: {snap['next_eligible']}")
if snap.get("iteration"):
    parts.append(f"Iteration: {snap['iteration']}")
if snap.get("status_summary"):
    summary = ", ".join(f"{k}={v}" for k, v in snap["status_summary"].items())
    parts.append(f"Status: {summary}")

if parts:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": "Roadmap snapshot: " + " | ".join(parts),
                }
            }
        )
    )
