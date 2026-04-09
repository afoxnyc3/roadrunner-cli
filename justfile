# justfile — thin operator interface. Logic lives in roadmap_loop.py.

# Show all task statuses
status:
    python roadmap_loop.py status

# Show next eligible task
next:
    python roadmap_loop.py next

# Start a task: just start TASK-001
start task_id:
    python roadmap_loop.py start {{task_id}}

# Validate a task: just validate TASK-001
validate task_id:
    python roadmap_loop.py validate {{task_id}}

# Complete a task: just complete TASK-001 "notes here"
complete task_id notes="":
    python roadmap_loop.py complete {{task_id}} --notes "{{notes}}"

# Block a task: just block TASK-001 "reason"
block task_id notes="":
    python roadmap_loop.py block {{task_id}} --notes "{{notes}}"

# Write reset marker: just reset TASK-001 "summary"
reset task_id summary="":
    python roadmap_loop.py reset {{task_id}} --summary "{{summary}}"

# System health check
health:
    python roadmap_loop.py health

# Write context snapshot manually
snapshot:
    python roadmap_loop.py snapshot

# Install dependencies
install:
    pip install -r requirements.txt

# Make all hooks executable
hooks:
    chmod +x hooks/*.sh
