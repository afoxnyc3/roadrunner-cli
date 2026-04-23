# Work Log: ROAD-002 — roadrunner init — project scaffold command
**Completed:** 2026-04-23T13:08:57.264219+00:00
**Status:** done

## Goal
Add a new 'init' subcommand to roadrunner.py that scaffolds a new project directory
for use with roadrunner. Behaviour:
  python3 roadrunner.py init <target_dir> [--dry-run]
Creates in <target_dir>: tasks/tasks.yaml (minimal template), logs/.gitkeep,
CLAUDE.md (minimal template), .claude/settings.json (copied from roadrunner source),
hooks/ (copied from roadrunner source). Prints a step-by-step setup checklist.
--dry-run prints what would be created without touching the filesystem.
If <target_dir> is the current directory ('.'), skip creating the directory.
Refuse to overwrite existing files; print a warning and skip each conflict.


## Acceptance Criteria
- roadrunner init --help exits 0 and lists the --dry-run flag
- roadrunner init /tmp/rr_init_smoke --dry-run exits 0 without writing files
- roadrunner init /tmp/rr_init_smoke creates the expected structure
- Calling init again on same dir does NOT overwrite existing files
- All existing tests continue to pass

## Validation (4/4 passed)

### ✅ `python3 roadrunner.py init --help`
```
usage: roadrunner.py init [-h] [--dry-run] target_dir

positional arguments:
  target_dir  Target directory (use '.' for current working directory)

options:
  -h, --help  show this help message and exit
  --dry-run   Print what would be created without touching the filesystem
```

### ✅ `python3 roadrunner.py init /tmp/rr_init_smoke --dry-run`
```
[dry-run] Scaffolding roadrunner project at: /private/tmp/rr_init_smoke
[dry-run] mkdir  tasks/
[dry-run] write  tasks/tasks.yaml
[dry-run] mkdir  logs/
[dry-run] write  logs/.gitkeep
[dry-run] write  CLAUDE.md
[dry-run] mkdir  .claude/
[dry-run] copy   .claude/settings.json  <-  /Users/alex/dev/projects/roadrunner-cli/.claude/settings.json
[dry-run] mkdir  hooks/
[dry-run] copy   hooks/post_write_hook.sh  <-  /Users/alex/dev/projects/roadrunner-cli/hooks/post_write_hook.sh
[dry-run] copy   hook
```

### ✅ `python3 -m pytest tests/ -q`
```
........................................................................ [ 70%]
..............................                                           [100%]
102 passed in 1.30s
```

### ✅ `ruff check roadrunner.py`
```
All checks passed!
```

## Notes
Added 'init' subcommand. cmd_init() builds a declarative plan (mkdir/write/copy), walks it with per-file refuse-to-overwrite, and supports --dry-run. Scaffolds tasks/tasks.yaml (minimal template), logs/.gitkeep, CLAUDE.md (minimal agent brief), .claude/settings.json (copied from source), hooks/*.sh (copied + chmod +x). Target '.' reuses cwd; any other path is created if missing. Prints a 5-step setup checklist after the plan executes. Sources resolve relative to Path(__file__).parent so dev/editable installs work today; PyPI packaging of data files is deferred to ROAD-008.