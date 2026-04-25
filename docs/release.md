# Release Process

Roadrunner publishes to PyPI via [GitHub Actions](../.github/workflows/publish.yml)
using **PyPI Trusted Publishing** (OIDC). No long-lived API tokens are stored
in repo secrets — the publish job exchanges its workflow OIDC token for a
short-lived upload token at runtime.

This document covers the one-time PyPI/GitHub setup and the per-release
checklist.

---

## One-time setup

You only do this once per project (or once per Trusted Publisher environment).

### 1. Reserve the package name on PyPI

1. Sign in at <https://pypi.org/>.
2. The first publish needs to come from a Trusted Publisher, so you cannot
   "reserve" the name with a manual upload. Instead, create the publisher
   record below and then push your first `v*` tag — the OIDC publish will
   create the project automatically.

If you want the name immediately reserved (recommended to prevent squatting):
do an initial manual `twine upload` of a `0.0.1.dev0` build, then proceed
with the OIDC setup. Future releases continue via OIDC.

### 2. Configure the Trusted Publisher on PyPI

For the **production** PyPI:

1. Go to <https://pypi.org/manage/account/publishing/>.
2. Under **Add a new pending publisher**, fill in:
   - **PyPI Project Name**: `roadrunner-cli`
   - **Owner**: `afoxnyc` (the GitHub user/org that owns the repo)
   - **Repository name**: `roadrunner-cli`
   - **Workflow name**: `publish.yml`
   - **Environment name**: `pypi`
3. Click **Add**.

For **TestPyPI** (optional but recommended for rehearsals):

1. Repeat the steps at <https://test.pypi.org/manage/account/publishing/>
   with the same fields, but use environment name `testpypi`.
2. Add a second job to `publish.yml` if you want automatic test publishes
   (omitted from the default workflow to keep things simple).

### 3. Create the GitHub Environment

GitHub Environments let you gate the publish job behind manual approval if
you want a human checkpoint before every release.

1. In the repo: **Settings → Environments → New environment** → name it
   `pypi` (must match the `environment.name` field in `publish.yml`).
2. Optionally add a **Required reviewer** so each publish needs explicit
   approval. Useful for early releases; remove later if it becomes friction.
3. Optionally restrict the environment to specific tags or branches.

That's the whole one-time setup.

---

## Per-release checklist

Every release follows the same six steps. Treat the checklist as the source
of truth — any deviation means writing it down here first.

1. **Confirm `main` is green.** Check the [CI badge](../.github/workflows/ci.yml)
   and that there are no open critical issues blocking release.

2. **Bump the version.** Edit `pyproject.toml`:

   ```toml
   [project]
   version = "X.Y.Z"
   ```

   Follow [Semantic Versioning](https://semver.org/):
   - **Patch** (`0.1.0` → `0.1.1`): bug fixes, doc updates, no API change.
   - **Minor** (`0.1.0` → `0.2.0`): new commands or features, backward-compatible.
   - **Major** (`0.1.0` → `1.0.0`): breaking changes to `tasks.yaml` schema,
     state-file schema, hook contracts, or CLI surface.

3. **Update `CHANGELOG.md`.** Move the unreleased entries under a new
   `## [X.Y.Z] — YYYY-MM-DD` heading. Cross-reference the relevant ROAD-NNN
   tasks where helpful.

4. **Commit on `main`:**

   ```bash
   git add pyproject.toml CHANGELOG.md
   git commit -m "release: vX.Y.Z"
   git push origin main
   ```

5. **Tag and push:**

   ```bash
   git tag -a vX.Y.Z -m "Release X.Y.Z"
   git push origin vX.Y.Z
   ```

   The `v*` tag push triggers `.github/workflows/publish.yml`. The workflow
   runs the full test matrix, builds the sdist + wheel, then publishes via
   OIDC. If you configured a required reviewer on the `pypi` environment,
   it will pause for approval at the publish step.

6. **Verify the release.** After the workflow completes:

   ```bash
   pip install --upgrade roadrunner-cli==X.Y.Z
   roadrunner --help        # should print the CLI usage
   ```

   Then create a GitHub Release referencing the tag, paste the changelog
   section, and attach any release notes.

---

## Rehearsing without publishing

The `publish` workflow has a `workflow_dispatch` trigger so a maintainer can
exercise the build steps without cutting a real release.

1. Go to the **Actions** tab → select **publish** → **Run workflow**.
2. Pick the branch you want to rehearse against.
3. The `test` and `build` jobs run; the `publish` job is gated on
   `github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')`
   and is skipped, so nothing is uploaded.

Use this to verify the build artifacts before tagging:

- The `python-package-distributions` artifact attached to the run will
  contain `roadrunner_cli-X.Y.Z-py3-none-any.whl` and the matching `.tar.gz`.
- Download, install in a clean venv (`pip install <wheel>`), and smoke-test
  the `roadrunner` console script.

---

## Local rehearsal

Before pushing a tag, build locally:

```bash
pip install build
python -m build --sdist --wheel --outdir dist/
```

That should produce both files in `dist/`. Smoke-test:

```bash
python -m venv /tmp/rr-release-test
/tmp/rr-release-test/bin/pip install dist/roadrunner_cli-*.whl
/tmp/rr-release-test/bin/roadrunner --help
```

If `--help` works, the wheel is shippable.

---

## Rollback

PyPI does **not** allow re-uploading a deleted version with the same number.
If a release is broken:

1. **Yank** the broken release on PyPI:
   <https://pypi.org/manage/project/roadrunner-cli/release/X.Y.Z/> →
   **Options → Yank**. This hides the version from `pip install
   roadrunner-cli` (no version bound) but leaves it installable for users
   who explicitly pin it.
2. Bump to the next patch version (e.g. `X.Y.Z+1`) with the fix and ship a
   new release. Never reuse a version number.
3. Document the yank in `CHANGELOG.md` under the affected version.

---

## References

- [PyPI Trusted Publishing docs](https://docs.pypi.org/trusted-publishers/)
- [`pypa/gh-action-pypi-publish`](https://github.com/pypa/gh-action-pypi-publish)
- [GitHub Environments](https://docs.github.com/en/actions/deployment/targeting-different-environments)
- [Semantic Versioning](https://semver.org/)
