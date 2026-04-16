# CLAUDE.md — Roadmap Loop Agent Brief

## Operating Model

You are executing a deterministic roadmap. Python owns control. You own implementation.
**One task per cycle. No side quests. No skipping ahead.**

---

## Your Job Each Cycle

1. Run `python3 roadrunner.py next` to see the current task
2. Run `python3 roadrunner.py start TASK-XXX` before touching any files
3. Implement the task — stay within its scope
4. Run `python3 roadrunner.py validate TASK-XXX` to check your work
5. Fix any failures — validation commands are the source of truth, not your assessment
6. Run `python3 roadrunner.py complete TASK-XXX --notes "what you did"` to close the task
7. Run `python3 roadrunner.py reset TASK-XXX --summary "one line"` to write the boundary marker

**The Stop hook will determine what comes next. Do not attempt to decide task order yourself.**

---

## Completion Signal

When ALL tasks are `done` and there is no remaining eligible work:

Output this exact string on its own line (must be the last non-empty line of your message):

```
ROADMAP_COMPLETE
```

This halts the loop. Do not output it unless the roadmap is genuinely finished.
Do not quote it mid-sentence — the signal is line-anchored and only triggers when it appears alone on the final line.

---

## Blocked Tasks

If a task cannot be completed due to an unresolvable dependency or external blocker:

```bash
python3 roadrunner.py block TASK-XXX --notes "reason for block"
```

Document what is blocking. Do not keep retrying indefinitely.

**Auto-block:** If the Stop hook detects you have resumed the same in-progress task 5 times without completing it, the task is automatically blocked. You will be notified when this happens.

---

## Validation Is the Gate

A task is done when `python3 roadrunner.py validate TASK-XXX` exits 0.
Not when you think it looks right. Not when the code exists. When validation passes.

---

## Context Hygiene

- Work on exactly one task per cycle
- Do not reference prior task details unless directly relevant to current task
- After each `complete`, treat the prior task as closed
- On session start, the SessionStart hook injects a roadmap snapshot automatically
- The `.context_snapshot.json` and `.roadmap_state.json` are your memory — read them if the snapshot seems stale

---

## File Scope

Only touch files listed in the current task's `files_expected` and `documentation_targets`.
If you need to modify something outside scope, note it in the task's `--notes` and continue.

---

## Commands Reference

```bash
python3 roadrunner.py status                        # show all task statuses
python3 roadrunner.py next                          # show next eligible task
python3 roadrunner.py start TASK-XXX               # begin a task
python3 roadrunner.py validate TASK-XXX            # run validation only
python3 roadrunner.py complete TASK-XXX --notes "" # complete with validation
python3 roadrunner.py block TASK-XXX --notes ""    # mark blocked
python3 roadrunner.py reset TASK-XXX --summary ""  # write boundary marker
python3 roadrunner.py health                        # system health check
```

---

## What the Stop Hook Does

After every response, the Stop hook checks (in this order):

1. Is `stop_hook_active` true? → allow stop (prevents infinite loop)
2. Iteration limit reached? → hard stop with message
3. Did you output `ROADMAP_COMPLETE` as the last line? → allow stop
4. Is a task `in_progress`? → inject a resume brief and block stop
5. Are there eligible `todo` tasks? → inject the next task brief and block stop
6. Are tasks blocked? → report blocked tasks and block stop
7. Are all tasks done? → prompt you to output `ROADMAP_COMPLETE`

**Auto-block guard:** If you resume the same in-progress task 5+ times without completing it, the hook auto-blocks the task and tells you to move on.

You do not need to manage this. The hook manages it. Just do the work.
