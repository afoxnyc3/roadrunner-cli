# Work Log: ROAD-001 — pyproject.toml — pip-installable packaging
**Completed:** 2026-04-23T13:03:37.450376+00:00
**Status:** done

## Goal
Replace requirements.txt-only setup with a pyproject.toml that makes roadrunner
pip-installable and prepares the project for PyPI. Keep roadrunner.py at the root
(flat layout — no src/ restructure). Define a 'roadrunner' CLI entry point pointing
to roadrunner:main. Set python_requires>=3.10. Move runtime dep (pyyaml) to
[project.dependencies]. Move dev deps (pytest, ruff) to
[project.optional-dependencies.dev]. Keep requirements.txt pointing at the extras
for backward compat. Add a [tool.ruff] section pinning the lint rules already passing.


## Acceptance Criteria
- pyproject.toml exists with [project], [project.scripts], and [project.dependencies]
- Entry point roadrunner maps to roadrunner:main
- python_requires is set to >=3.10
- requirements.txt retained pointing at dev extras or core deps
- All existing tests continue to pass
- ruff check passes with no new violations

## Validation (5/5 passed)

### ✅ `test -f pyproject.toml`

### ✅ `grep -q "roadrunner" pyproject.toml`

### ✅ `grep -q "roadrunner:main" pyproject.toml`

### ✅ `python3 -m pytest tests/ -q`
```
........................................................................ [ 70%]
..............................                                           [100%]
102 passed in 1.25s
```

### ✅ `ruff check roadrunner.py tests/ hooks/`
```
All checks passed!
```

## Notes
Added pyproject.toml (setuptools backend, flat layout via py-modules=['roadrunner']). Runtime dep pyyaml under [project.dependencies]; pytest+ruff under [project.optional-dependencies.dev]. CLI entry 'roadrunner'→roadrunner:main. requires-python>=3.10. requirements.txt now a back-compat shim pointing at '-e .[dev]'. [tool.ruff] pinned to E/F/W with line-length=140 to match currently-passing baseline (stricter rules would fail on pre-existing code outside task scope).