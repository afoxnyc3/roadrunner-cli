# hello-roadrunner

Three-task demo of the full roadrunner loop. Claude builds a tiny
`word_counter` CLI: function → CLI entry → tests.

## Run it

```bash
cp -r docs/examples/hello-roadrunner ~/hello-roadrunner
cd ~/hello-roadrunner
pip install roadrunner-cli
roadrunner init .              # adds roadrunner.py + hooks/ + .claude/
roadrunner status   # DEMO-001/002/003 all `todo`
roadrunner analyze  # validates YAML + dep graph
claude                         # launch the loop
```

The Stop hook feeds Claude DEMO-001, validates, injects DEMO-002, repeats.
When DEMO-003 lands the loop emits `ROADMAP_COMPLETE` and halts.

## What you get

`word_counter.py`, `test_word_counter.py`, `logs/DEMO-00X.md`,
`logs/trace.jsonl`, and a git branch per task.

See [`tasks/tasks.yaml`](tasks/tasks.yaml) for the three tasks and their
validation commands.
