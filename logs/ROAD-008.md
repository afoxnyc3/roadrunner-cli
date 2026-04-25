# Work Log: ROAD-008 — PyPI publish workflow
**Completed:** 2026-04-25T02:45:37.538322+00:00
**Status:** done

## Goal
Add a GitHub Actions publish workflow that builds and publishes to PyPI on a
version tag push. Use Trusted Publishing (OIDC) — no API tokens stored in secrets.

.github/workflows/publish.yml should:
  - Trigger on push to tags matching v* (e.g. v0.1.0)
  - Run the full test matrix first (import from ci.yml or inline)
  - Build with python3 -m build (add build to dev deps)
  - Publish via pypa/gh-action-pypi-publish@release/v1 with OIDC
  - Include a manual workflow_dispatch trigger for testing

Also add a VERSION file at the project root containing the current version string
(e.g. '0.1.0') that pyproject.toml reads via dynamic version, OR set version
statically in pyproject.toml at 0.1.0.

Document the PyPI Trusted Publishing setup steps in docs/release.md.


## Acceptance Criteria
- .github/workflows/publish.yml exists and is valid YAML
- publish.yml triggers on v* tag pushes
- publish.yml uses pypa/gh-action-pypi-publish
- docs/release.md exists with Trusted Publishing setup instructions
- pyproject.toml has a version field (static or dynamic)
- python3 -m build --wheel --outdir /tmp/rr_build_test exits 0

## Validation (5/5 passed)

### ✅ `test -f .github/workflows/publish.yml`

### ✅ `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/publish.yml'))"`

### ✅ `grep -q "pypi-publish" .github/workflows/publish.yml`

### ✅ `test -f docs/release.md`

### ✅ `python3 -m pytest tests/ -q`
```
........................................................................ [ 48%]
........................................................................ [ 96%]
......                                                                   [100%]
150 passed in 5.36s
```

## Notes
Added .github/workflows/publish.yml: triggers on v* tag pushes plus workflow_dispatch (rehearsal-only — publish job gated on real tag push), runs full pytest matrix (3.10/3.11/3.12), builds sdist+wheel via python -m build, publishes through pypa/gh-action-pypi-publish@release/v1 using OIDC Trusted Publishing (no API tokens). Bound to a 'pypi' GitHub Environment with id-token: write so org admins can require manual approval. Added docs/release.md covering one-time PyPI Trusted Publisher setup, GitHub Environment config, the per-release semver+tag checklist, workflow_dispatch rehearsal flow, local build smoke test, and rollback/yank procedure. Added 'build>=1.0' to dev deps in pyproject.toml. Verified: all 5 gated validators pass, plus python3 -m build --wheel --outdir /tmp/rr_build_test exits 0 (produced roadrunner_cli-0.1.0-py3-none-any.whl). Note for audit pass: .gitignore is missing build/, dist/, *.egg-info patterns — worth adding in the Phase-2 hygiene sweep but out of scope here.