# Roadrunner CLI

Roadrunner works through a reviewed backlog in an existing Git project. A serial Python controller selects tasks, invokes Claude Code, validates committed changes, and integrates successful work into a dedicated local run branch. Each selected item ends as verified local resolution or an actionable blocker. A model claim, passing tests on an unintegrated branch, or a newly created PR cannot resolve an item.

This branch is a release candidate qualified for local delivery on macOS. The installed workflow passed both the failure-injection fixture suite and a bounded native Claude Code canary with verified Git integration. Live GitHub mutations remain unqualified; see [the implementation checklist](docs/shipping-implementation-checklist.md) for evidence and limits. No release has been published from this work.

## Installed workflow

Install a built wheel into a virtual environment, then work in your existing project:

```sh
roadrunner init .
roadrunner sync --roadmap tasks/tasks.yaml
roadrunner doctor --policy /absolute/path/run-policy.json
roadrunner run --plan /absolute/path/from-sync.yaml --policy /absolute/path/run-policy.json
```

`init` preserves existing instructions and settings. `sync` returns the path to a frozen normalized plan. Review the selection and policy before the first run. GitHub intake is read-only:

```sh
roadrunner sync --github OWNER/REPO --issue 123 --issue 124 --rules intake-rules.json
# Or select a label/milestone:
roadrunner sync --github OWNER/REPO --label ready --milestone 2 --rules intake-rules.json
```

Issues require reviewed goal, acceptance criteria, and file scope. Commands copied from issue text are never executed as gates. Repeated synchronization is idempotent; edited/reopened sources require explicit revision approval. Markdown roadmaps use one fenced YAML `tasks` block with stable task IDs.

A minimal policy:

```json
{
  "adapter": "claude",
  "sandbox": "macos",
  "delivery": "local",
  "validation_commands": ["PYTHONDONTWRITEBYTECODE=1 python3 tests/acceptance.py"],
  "protected_paths": ["tests/acceptance.py"],
  "max_attempts": 2,
  "attempt_seconds": 120,
  "validation_seconds": 60,
  "run_seconds": 600,
  "max_budget_usd": 3,
  "attempt_budget_usd": 0.5
}
```

Choose meaningful acceptance gates and protect their scripts and supporting fixtures. Restrict `files_expected` to the intended implementation. Validation runs without network access; prepare dependencies first and ignore disposable build outputs in Git. The real-worker execution host currently requires macOS `sandbox-exec`; unsupported hosts fail closed. Claude gets Read/Edit/Write/Glob/Grep tools, while the controller owns shell validation and Git operations. General-purpose worker shell execution is not currently supported.

## Resolution and recovery

The operator checkout stays on its existing branch, including uncommitted changes. Work starts from the committed HEAD and lands on `roadrunner/run-<UUID>`. Review that local branch before adopting it. Controller state, frozen policy, attempt records, integration candidates and full logs live under the Git common directory's `roadrunner/<UUID>/` directory. Task worktrees live in a private temporary directory outside Git metadata (recorded as `task_work_root` in `run.json`), retained across retries and resume. Preserve that directory while recovering unfinished work; system temporary-file cleanup may remove it.

A task progresses through `ready`, `running`, `validating`, `integrating`, and `resolved`. Missing requirements become `needs_input`; exhausted attempts/deadlines and unresolved prerequisites become `blocked`. Cancellation produces `cancelled`. Exit code 0 means all selected tasks resolved locally; exit code 2 means blockers or cancellation, with a JSON report explaining the disposition.

```sh
roadrunner run --resume RUN_UUID
```

Resume preserves the original deadline and charged attempt/budget allowances, reconciles interrupted integration, and never infers completion from a worker's response. Cancel with Ctrl-C or SIGTERM. The worker group is terminated on cancellation, deadline, and controller pipe loss. Failed worktrees remain for inspection. Terminal blockers require reviewing their next action and explicitly selecting a new run; they are not silently reopened.

Cost accounting conservatively reserves each attempt's native Claude dollar cap before launch; reservations are not refunded after interruption or retries. Missing/error usage telemetry cannot resolve work. The installed native canary verified authentication, file creation, structured usage telemetry, and completion below the configured caps. This small run does not establish provider hard-cap behavior at exhaustion or compatibility with every Claude version. The `fixture` adapter is explicitly reported and is only for trusted disposable testing.

## Optional remote delivery

Local integration is the default delivery target. Remote delivery remains a separate phase:

```sh
roadrunner deliver --run RUN_UUID --policy delivery-policy.json
```

This prepares a local artifact and makes no remote calls. A delivery policy names `repository`, `base`, and nonempty `required_checks`. Mutations additionally require `--execute` and individually enabled `allow_push`, `allow_pr`, `allow_merge`, and `allow_close` capabilities. Only enable capabilities that the operator has authorized.

A PR waiting for checks or merge is unfinished remote delivery. The controller verifies exact PR head/base, required successful checks, remote merge ancestry and tree equivalence, and source revisions before optional issue closure. A changed remote base requires revalidation. Real GitHub writes have not been qualified by this branch's mocked contract tests.

## Development and qualification

```sh
pip install -e '.[dev]'
just ci
shellcheck hooks/*.sh
python -m build --wheel
# After installing that wheel in a separate environment:
python tests/qualify_installed.py /path/to/venv/bin/roadrunner /fresh/disposable/directory
```

The installed qualification covers six selected items: dependencies, repair on retry, missing requirements, an external blocker, and independent work afterward. It checks local integration evidence, repeated sync/resume, and preservation of the operator checkout. On macOS, sandbox tests must run in an environment permitted to invoke `sandbox-exec`.

The earlier hook commands remain available for compatibility, but their agent-writable YAML is not the autonomous supervisor's authority. Hook-era documentation in `docs/architecture.md`, `docs/WORKFLOW.md`, and historical roadmaps describes that older workflow. Use `run` and its evidence report for the guarantees described here.

See [shipping plan](docs/shipping-plan-2026-09-18.md), [implementation checklist](docs/shipping-implementation-checklist.md), and [configuration example](docs/shipping-run-policy.json).
