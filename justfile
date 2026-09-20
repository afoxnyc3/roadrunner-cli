# justfile — thin operator interface. Logic lives in the installed roadrunner package.

# Show all task statuses
status:
    python3 -m roadrunner status

# Show next eligible task
next:
    python3 -m roadrunner next

# Start a task: just start TASK-001
start task_id:
    python3 -m roadrunner start {{task_id}}

# Validate a task: just validate TASK-001
validate task_id:
    python3 -m roadrunner validate {{task_id}}

# Complete a task: just complete TASK-001 "notes here"
complete task_id notes="":
    python3 -m roadrunner complete {{task_id}} --notes "{{notes}}"

# Block a task: just block TASK-001 "reason"
block task_id notes="":
    python3 -m roadrunner block {{task_id}} --notes "{{notes}}"

# Write reset marker: just reset TASK-001 "summary"
reset task_id summary="":
    python3 -m roadrunner reset {{task_id}} --summary "{{summary}}"

# System health check
health:
    python3 -m roadrunner health

# Write context snapshot manually
snapshot:
    python3 -m roadrunner snapshot

# Install dependencies (editable, with dev extras)
install:
    pip install -e '.[dev]'

# Make all hooks executable
hooks:
    chmod +x hooks/*.sh

# Run the full CI gate locally (pytest + ruff + mypy)
# Scope matches .github/workflows/ci.yml exactly so green locally = green on push.
ci:
    pytest tests/ -v
    ruff check src/ hooks/ tests/
    python3 -m mypy src tests --ignore-missing-imports

# Run tests only
test:
    pytest tests/ -v

# Run lint only
lint:
    ruff check src/ hooks/ tests/
