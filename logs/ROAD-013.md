# Work Log: ROAD-013 — Append-only operator learnings log
**Completed:** 2026-05-28T02:08:52.261765+00:00
**Status:** done

## Goal
Roadrunner has trace.jsonl (structured machine log) and per-task work logs but no
'things you wish the agent had known from the start' artifact. Ralph's
AGENTS.md is a load-bearing artifact: the agent appends operational learnings
(e.g. 'build command is npm run build, not npm build') that the next iteration
consults.

Add logs/learnings.md as a designated append-only file with a header
paragraph explaining its purpose. Update CLAUDE.md under Context Hygiene to
instruct the agent to append a one-line entry whenever it discovers a non-obvious
project fact during a task. Have the SessionStart hook read the last 20 lines and
include them in additionalContext so they persist across session boundaries.
Surface the learnings count in 'roadrunner status'. Scaffold the file in new
projects via 'roadrunner init'. Document the pattern in docs/WORKFLOW.md.

Zero code complexity: an instruction + a small SessionStart edit + an init
scaffold change. The value is cumulative.


## Acceptance Criteria
- logs/learnings.md exists with a one-paragraph header explaining its purpose
- CLAUDE.md updated with the appending instruction under Context Hygiene
- SessionStart hook reads the last 20 lines of logs/learnings.md and includes them in additionalContext
- roadrunner status shows the count of learnings entries
- roadrunner init scaffolds logs/learnings.md in new projects
- docs/WORKFLOW.md has a brief section on the learnings log
- All existing tests continue to pass
- ruff check passes

## Validation (6/6 passed)

### ✅ `test -f logs/learnings.md`

### ✅ `grep -qi "learnings" CLAUDE.md`

### ✅ `grep -qi "learnings" docs/WORKFLOW.md`

### ✅ `python3 -m roadrunner init /tmp/rr_learnings_smoke --dry-run`
```
[dry-run] Scaffolding roadrunner project at: /private/tmp/rr_learnings_smoke
[dry-run] mkdir  tasks/
[dry-run] write  tasks/tasks.yaml
[dry-run] mkdir  logs/
[dry-run] write  logs/.gitkeep
[dry-run] write  logs/learnings.md
[dry-run] write  CLAUDE.md
[dry-run] mkdir  .claude/
[dry-run] copy   .claude/settings.json  <-  /Users/alex/dev/roadrunner-cli/.claude/settings.json
[dry-run] mkdir  hooks/
[dry-run] copy   hooks/README.md  <-  /Users/alex/dev/roadrunner-cli/hooks/README.md
[dry-run] copy   
```

### ✅ `python3 -m pytest tests/ -q`
```
........................................................................ [ 34%]
........................................................................ [ 68%]
...................................................................      [100%]
211 passed in 7.03s
```

### ✅ `ruff check src/roadrunner tests/ hooks/`
```
All checks passed!
```

## Notes
logs/learnings.md scaffolded (init + project itself); _learnings_entries/_tail skip header markdown and HTML-comment placeholders; SessionStart prepends 'Operator learnings (most recent first):' block when non-empty; cmd_status reports 'Learnings: N entries'; docs/WORKFLOW.md gains § 5 (sections renumbered); CLAUDE.md and scaffold CLAUDE.md instruct the agent to append. 9 new tests, 211 total passing, ruff clean.