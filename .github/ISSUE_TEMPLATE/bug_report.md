---
name: Bug report
about: Report a defect in roadrunner-cli
title: "[bug] "
labels: bug
---

**What happened**

A clear description of the bug.

**What you expected**

What should have happened instead.

**Reproduction**

Minimal steps to reproduce. Include the relevant slice of `tasks/tasks.yaml`
if the bug involves task scheduling or validation.

**Environment**

- Python version (`python3 --version`):
- Roadrunner version (`pip show roadrunner-cli`, or `git rev-parse HEAD` if from source):
- OS and version:

**Logs**

Paste the relevant lines from `logs/trace.jsonl` and `logs/CHANGELOG.md`.
Redact anything sensitive.
