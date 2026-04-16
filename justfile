# justfile — thin operator interface. Logic lives in roadrunner.py.

# Show all task statuses
status:
    python3 roadrunner.py status

# Show next eligible task
next:
    python3 roadrunner.py next

# Start a task: just start TASK-001
start task_id:
    python3 roadrunner.py start {{task_id}}

# Validate a task: just validate TASK-001
validate task_id:
    python3 roadrunner.py validate {{task_id}}

# Complete a task: just complete TASK-001 "notes here"
complete task_id notes="":
    python3 roadrunner.py complete {{task_id}} --notes "{{notes}}"

# Block a task: just block TASK-001 "reason"
block task_id notes="":
    python3 roadrunner.py block {{task_id}} --notes "{{notes}}"

# Write reset marker: just reset TASK-001 "summary"
reset task_id summary="":
    python3 roadrunner.py reset {{task_id}} --summary "{{summary}}"

# System health check
health:
    python3 roadrunner.py health

# Write context snapshot manually
snapshot:
    python3 roadrunner.py snapshot

# Install dependencies
install:
    pip install -r requirements.txt

# Make all hooks executable
hooks:
    chmod +x hooks/*.sh

# Run the full CI gate locally (pytest + ruff)
ci:
    pytest tests/ -v
    ruff check roadrunner.py hooks/ tests/

# Run tests only
test:
    pytest tests/ -v

# Run lint only
lint:
    ruff check roadrunner.py hooks/ tests/
