"""Serial, evidence-backed execution. Controller data lives outside worker write access.

Legacy YAML status is never imported as resolution evidence. Git ref updates use
compare-and-swap; a persisted integration intent makes that side effect recoverable.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext
import fcntl
import hashlib
import json
import math
import os
import re
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import uuid

import yaml

TERMINAL = {"resolved", "blocked", "needs_input", "failed", "cancelled"}
TRANSITIONS = {
    "ready": {"running", "blocked", "needs_input", "cancelled"},
    "running": {"validating", "ready", "blocked", "failed", "cancelled"},
    "validating": {"integrating", "ready", "blocked", "failed", "cancelled"},
    "integrating": {"resolved", "blocked", "failed", "cancelled"},
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def atomic(path: Path, value):
    temp = path.with_suffix(".tmp")
    with temp.open("w") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=root, text=True, capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip()


def location(project: Path) -> Path:
    common = Path(git(project, "rev-parse", "--git-common-dir"))
    return (project / common).resolve() / "roadrunner"


@contextmanager
def locked(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "controller.lock").open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Another controller is active for this project") from exc
        yield


def transition(item, phase, reason=None):
    if phase not in TRANSITIONS.get(item["phase"], set()):
        raise ValueError(f"Invalid transition {item['phase']} -> {phase}")
    item["phase"] = phase
    item["updated_at"] = time.time()
    if reason:
        item["reason"] = reason
    elif phase == "resolved":
        item.pop("reason", None)


def relative_path(value):
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] == ".git":
        raise ValueError(f"Unsafe scope path: {value}")
    return path.as_posix()


def load_plan(path: Path, policy: dict, expected_digest=None) -> list[dict]:
    from .cli import validate_plan, validate_task_schema

    document = yaml.safe_load(path.read_text())
    if expected_digest is not None and digest(document) != expected_digest:
        raise ValueError("Frozen plan contents differ from the selected source revision; restore or resynchronize the plan")
    tasks = document.get("tasks") if isinstance(document, dict) else None
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("Selected plan must contain a nonempty tasks list")
    for index, task in enumerate(tasks):
        validate_task_schema(task, index)
    validate_plan(tasks)
    result = []
    for original in tasks:
        task = dict(original)
        task.pop("status", None)
        task["files_expected"] = [relative_path(p) for p in task.get("files_expected", [])]
        # Commands come only from the separately reviewed project policy.
        task["validation_commands"] = policy["validation_commands"]
        result.append(task)
    return sorted(result, key=lambda t: (t.get("priority", 100), t["id"]))


def load_policy(path: Path) -> dict:
    policy = json.loads(path.read_text())
    defaults = dict(
        max_attempts=3,
        attempt_seconds=300,
        run_seconds=1800,
        validation_seconds=120,
        max_budget_usd=3.0,
        attempt_budget_usd=1.0,
        adapter="claude",
        sandbox="macos",
        protected_paths=[],
        delivery="local",
    )
    policy = {**defaults, **policy}
    for key in ("max_attempts", "attempt_seconds", "run_seconds", "validation_seconds", "max_budget_usd", "attempt_budget_usd"):
        value = policy[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{key} must be finite and positive")
    if not isinstance(policy["max_attempts"], int):
        raise ValueError("max_attempts must be an integer")
    gates = policy.get("validation_commands")
    if not isinstance(gates, list) or not gates or any(not isinstance(g, str) or not g.strip() for g in gates):
        raise ValueError("Reviewed policy must specify nonempty validation_commands")
    policy["protected_paths"] = [relative_path(p) for p in policy["protected_paths"]]
    if policy["adapter"] not in ("claude", "fixture"):
        raise ValueError("Supported adapter: claude (fixture is for disposable tests only)")
    if policy["sandbox"] not in ("macos", "fixture") or (policy["sandbox"] == "fixture" and policy["adapter"] != "fixture"):
        raise ValueError("Claude requires an enforced macOS sandbox")
    if policy["delivery"] != "local":
        raise ValueError("Remote delivery requires the explicit delivery command and policy")
    return policy


def sandbox_command(command: list[str], work: Path, scratch: Path, policy: dict, network=False) -> list[str]:
    if policy["sandbox"] == "fixture":
        return command
    if sys.platform != "darwin" or not shutil.which("sandbox-exec"):
        raise ValueError("macOS sandbox-exec unavailable; configure a supported constrained host")
    # State, Git metadata, gates, and the operator checkout are outside these roots.
    profile = "(version 1)(allow default)(deny file-write*)(deny signal)"
    if not network:
        profile += "(deny network*)"
    for path in (work, scratch):
        profile += f"(allow file-write* (subpath {json.dumps(str(path.resolve()))}))"
    profile += '(allow file-write* (literal "/dev/null"))'
    profile += f"(deny file-write* (literal {json.dumps(str(work / '.git'))}))"
    for name in policy["protected_paths"]:
        profile += f"(deny file-write* (subpath {json.dumps(str(work / name))}))"
    return ["sandbox-exec", "-p", profile, *command]


def terminate(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def execute(command, work, scratch, policy, deadline, log, env, network=False, stderr_log=None):
    """File-backed output, bounded wall time, cancellation, descendant cleanup."""
    command = sandbox_command(command, work, scratch, policy, network)
    command = [sys.executable, "-I", str(Path(__file__).with_name("process_guard.py")), *command]
    with log.open("wb") as output, stderr_log.open("wb") if stderr_log else nullcontext(subprocess.STDOUT) as error:
        process = subprocess.Popen(command, cwd=work, env=env, stdout=output, stderr=error, stdin=subprocess.PIPE, start_new_session=True)
        try:
            while process.poll() is None:
                if time.time() >= deadline:
                    raise TimeoutError(f"Deadline exceeded; inspect {log}")
                time.sleep(0.05)
            return process.returncode
        finally:
            terminate(process)
            if process.stdin:
                process.stdin.close()


def protected_hashes(project, paths):
    result = {}
    for value in paths:
        path = project / value
        if path.is_symlink():
            raise ValueError(f"Protected path is a symlink: {value}")
        files = sorted(path.rglob("*")) if path.is_dir() else [path]
        result[value] = [[str(p.relative_to(project)), hashlib.sha256(p.read_bytes()).hexdigest()] for p in files if p.is_file()]
    return result


def changed_paths(work):
    tracked = git(work, "diff", "--name-only", "-z", "HEAD").split("\0")
    untracked = git(work, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
    return sorted(set(p for p in tracked + untracked if p))


def inspect_scope(work, task, protected):
    paths = changed_paths(work)
    allowed = task["files_expected"]
    for path in paths:
        if not any(path == p or path.startswith(p.rstrip("/") + "/") for p in allowed):
            raise ValueError(f"Out-of-scope change: {path}; amend reviewed plan or repair worker changes")
        if any(path == p or path.startswith(p.rstrip("/") + "/") for p in protected):
            raise ValueError(f"Protected gate changed: {path}")
        candidate = work / path
        if candidate.is_symlink() or (candidate.exists() and not candidate.resolve().is_relative_to(work.resolve())):
            raise ValueError(f"Symlink scope escape: {path}")
    return paths


def worker_command(policy, task, attempt, scratch):
    if policy["adapter"] == "fixture":
        command = policy.get("fixture_command")
        if not isinstance(command, list) or not command:
            raise ValueError("fixture_command must be an argv array")
        return command
    prompt = (
        "Implement this one task within files_expected. Do not change Git, controller state, "
        "or validation policy. The controller commits, validates and integrates independently. "
        "If blocked, explain the missing input and next action.\n" + json.dumps(task)
    )
    return [
        "claude",
        "-p",
        prompt,
        "--output-format",
        "json",
        "--max-budget-usd",
        str(attempt["budget_usd"]),
        "--max-turns",
        "30",
        "--permission-mode",
        "dontAsk",
        "--tools",
        "Read,Edit,Write,Glob,Grep",
        "--allowedTools",
        "Read,Edit,Write,Glob,Grep",
        "--setting-sources",
        "",
        "--settings",
        '{"disableAllHooks":true}',
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--disable-slash-commands",
        "--no-session-persistence",
    ]


def checkpoint(directory, state):
    atomic(directory / "run.json", state)


def verify_evidence(project, state, item):
    """Validate the complete persisted gate before replaying any integration intent."""
    evidence = item.get("evidence", {})
    if evidence.get("gate_version") != state["gate_version"]:
        raise ValueError("Integration evidence belongs to a different gate version")
    gates = evidence.get("gates")
    commands = state["policy"]["validation_commands"]
    if not isinstance(gates, list) or len(gates) != len(commands) or not commands:
        raise ValueError("Integration evidence is missing required gate results")
    for gate, command in zip(gates, commands):
        if not isinstance(gate, dict) or gate.get("command") != command or type(gate.get("exit_code")) is not int or gate["exit_code"] != 0:
            raise ValueError("Integration evidence does not prove the frozen validation commands passed")
    attempts = item.get("attempts", [])
    if not attempts or evidence.get("attempt_id") != attempts[-1].get("id") or evidence.get("base") != attempts[-1].get("base"):
        raise ValueError("Integration evidence does not belong to the current attempt")
    for name in ("base", "task_commit", "candidate"):
        revision = evidence.get(name)
        if not isinstance(revision, str) or not re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})", revision):
            raise ValueError(f"Invalid integration {name} revision")
        if git(project, "cat-file", "-t", revision) != "commit":
            raise ValueError(f"Integration {name} is not a commit")
    git(project, "merge-base", "--is-ancestor", evidence["base"], evidence["task_commit"])
    git(project, "merge-base", "--is-ancestor", evidence["task_commit"], evidence["candidate"])
    return evidence


def reconcile(project, directory, state):
    for item in state["items"]:
        if item["phase"] in ("resolved", "integrating"):
            try:
                evidence = verify_evidence(project, state, item)
                if item["phase"] == "resolved":
                    git(project, "merge-base", "--is-ancestor", evidence["candidate"], state["branch"])
                    continue
                current = git(project, "rev-parse", state["branch"])
                if current == evidence["base"]:
                    git(project, "update-ref", state["branch"], evidence["candidate"], current)
                elif current != evidence["candidate"]:
                    raise ValueError("Integration intent no longer matches branch")
                transition(item, "resolved")
            except (ValueError, KeyError) as exc:
                # External ref rewrites or corrupt intents revoke delivery, retaining evidence.
                item["phase"] = "blocked"
                item["reason"] = f"Integration evidence is no longer valid: {exc}. Reconcile the integration branch and gate evidence."
        elif item["phase"] in ("running", "validating"):
            # Charged attempts and reserved budget survive crashes. Never infer success.
            work = directory / ("work-" + item["task"]["id"])
            if work.exists() and item["attempts"]:
                git(work, "reset", "--mixed", item["attempts"][-1]["base"])
            transition(item, "ready", "Interrupted attempt; retry within remaining allowance")
    checkpoint(directory, state)


def drive(project, directory, state):
    policy = state["policy"]
    if digest(policy) != state["gate_version"]:
        raise ValueError("Frozen policy hash mismatch; restore controller state from trusted evidence")
    reconcile(project, directory, state)
    while True:
        unfinished = [item for item in state["items"] if item["phase"] not in TERMINAL]
        if not unfinished:
            break
        if time.time() >= state["deadline"]:
            for item in unfinished:
                transition(item, "blocked", "Run deadline exhausted. Review evidence and explicitly plan a new run.")
            break
        resolved = {item["task"]["id"] for item in state["items"] if item["phase"] == "resolved"}
        ready = [item for item in unfinished if all(dep in resolved for dep in item["task"].get("depends_on", []))]
        if not ready:
            for item in unfinished:
                transition(item, "blocked", "Prerequisite unresolved. Resolve the dependency blocker and select a new run.")
            break
        item = ready[0]
        task = item["task"]
        if task.get("source_disposition", "ready") != "ready":
            transition(item, "needs_input", task.get("source_next_action") or "Review source disposition before execution")
            checkpoint(directory, state)
            continue
        if not task.get("goal") or not task.get("acceptance_criteria") or not task.get("files_expected"):
            transition(item, "needs_input", "Specify goal, acceptance criteria, and allowed files in the reviewed plan.")
            checkpoint(directory, state)
            continue
        remaining = policy["max_budget_usd"] - state["reserved_usd"]
        if len(item["attempts"]) >= policy["max_attempts"] or remaining <= 0.000001:
            transition(item, "blocked", "Attempt or usage allowance exhausted. Inspect attempt logs and revise the plan or policy.")
            checkpoint(directory, state)
            continue
        number = len(item["attempts"]) + 1
        base = git(project, "rev-parse", state["branch"])
        work = directory / ("work-" + task["id"])
        scratch = directory / ("scratch-" + task["id"])
        scratch.mkdir(exist_ok=True)
        attempt = dict(
            id=str(uuid.uuid4()), number=number, base=base, started_at=time.time(), budget_usd=min(remaining, policy["attempt_budget_usd"])
        )
        item["attempts"].append(attempt)
        state["reserved_usd"] += attempt["budget_usd"]
        transition(item, "running")
        checkpoint(directory, state)
        failure_category = "infrastructure"
        try:
            if not work.exists():
                git(project, "worktree", "add", "--detach", str(work), base)
            elif git(work, "rev-parse", "HEAD") != base:
                raise ValueError("Retry worktree base changed; inspect retained work and create a reviewed recovery plan")
            gate_hashes = protected_hashes(work, policy["protected_paths"])
            if "gate_files" not in state:
                state["gate_files"] = gate_hashes
                checkpoint(directory, state)
            elif gate_hashes != state["gate_files"]:
                raise ValueError("Gate files differ from frozen baseline. Restore reviewed validation files.")
            env = dict(
                os.environ,
                CLAUDE_PROJECT_DIR=str(work),
                TMPDIR=str(scratch),
                CLAUDE_CONFIG_DIR=str(scratch / "claude"),
                ROADRUNNER_TASK=json.dumps(task),
                ROADRUNNER_ATTEMPT=str(number),
                ROADRUNNER_ATTEMPT_ID=attempt["id"],
            )
            env.pop("PYTHONPATH", None)
            log = directory / f"{task['id']}-{number}-worker.log"
            error_log = directory / f"{task['id']}-{number}-worker-stderr.log"
            attempt["worker_log"] = str(log)
            attempt["worker_stderr"] = str(error_log)
            deadline = min(state["deadline"], time.time() + policy["attempt_seconds"])
            code = execute(
                worker_command(policy, task, attempt, scratch),
                work,
                scratch,
                policy,
                deadline,
                log,
                env,
                network=policy["adapter"] == "claude",
                stderr_log=error_log,
            )
            attempt["worker_log"] = str(log)
            if code:
                raise ValueError(f"Worker exited {code}. Inspect {log}; check adapter/authentication or implementation.")
            if policy["adapter"] == "claude":
                response = json.loads(log.read_text())
                attempt["session_id"] = response.get("session_id")
                attempt["cost_usd"] = response.get("total_cost_usd")
                cost = attempt["cost_usd"]
                if (
                    response.get("is_error")
                    or isinstance(cost, bool)
                    or not isinstance(cost, (int, float))
                    or not math.isfinite(cost)
                    or cost < 0
                ):
                    raise ValueError("Agent error or missing usage telemetry. Inspect worker log and adapter compatibility.")
                if cost > attempt["budget_usd"]:
                    state["reserved_usd"] += cost - attempt["budget_usd"]
                    raise ValueError("Agent exceeded native attempt budget; review adapter usage before continuing")
            failure_category = "implementation"
            if protected_hashes(work, policy["protected_paths"]) != gate_hashes:
                raise ValueError("Frozen gate files changed. Restore protected files before retry.")
            paths = inspect_scope(work, task, policy["protected_paths"])
            if not paths:
                raise ValueError("No implementation progress; agent claims alone cannot resolve a task")
            transition(item, "validating")
            checkpoint(directory, state)
            # Commit only inspected paths; controller never stages arbitrary worker metadata.
            git(work, "add", "--", *paths)
            git(
                work,
                "-c",
                "user.name=Roadrunner",
                "-c",
                "user.email=roadrunner@localhost",
                "commit",
                "-m",
                f"fix: {task['id']} {task['title']}",
            )
            task_commit = git(work, "rev-parse", "HEAD")
            integration = directory / f"candidate-{task['id']}-{number}"
            git(project, "worktree", "add", "--detach", str(integration), base)
            git(
                integration,
                "-c",
                "user.name=Roadrunner",
                "-c",
                "user.email=roadrunner@localhost",
                "merge",
                "--no-ff",
                "--no-edit",
                task_commit,
            )
            candidate = git(integration, "rev-parse", "HEAD")
            failure_category = "validation"
            gate_results = []
            for index, command in enumerate(policy["validation_commands"]):
                gate_log = directory / f"{task['id']}-{number}-gate-{index}.log"
                code = execute(
                    ["/bin/sh", "-c", command],
                    integration,
                    scratch,
                    policy,
                    min(state["deadline"], time.time() + policy["validation_seconds"]),
                    gate_log,
                    dict(env, CLAUDE_PROJECT_DIR=str(integration)),
                )
                gate_results.append(dict(command=command, exit_code=code, log=str(gate_log)))
                if code:
                    raise ValueError(f"Validation failed: {command}. Inspect {gate_log} and repair implementation.")
            if changed_paths(integration) or git(integration, "rev-parse", "HEAD") != candidate:
                raise ValueError("Validation changed candidate contents; clean build artifacts and rerun")
            item["evidence"] = dict(
                base=base,
                candidate=candidate,
                task_commit=task_commit,
                gate_version=state["gate_version"],
                gates=gate_results,
                attempt_id=attempt["id"],
            )
            failure_category = "integration"
            transition(item, "integrating")
            checkpoint(directory, state)
            git(project, "update-ref", state["branch"], candidate, base)
            if git(project, "rev-parse", state["branch"]) != candidate:
                raise ValueError("Integration ref verification failed")
            transition(item, "resolved")
            attempt["outcome"] = "resolved"
        except KeyboardInterrupt:
            transition(item, "cancelled", "Run cancelled. Retained work and evidence require explicit review before a new run.")
            for other in state["items"]:
                if other["phase"] == "ready":
                    transition(other, "cancelled", "Run cancelled by operator")
            checkpoint(directory, state)
            break
        except (ValueError, OSError, subprocess.SubprocessError, TimeoutError) as exc:
            attempt["outcome"] = "failed"
            attempt["failure_category"] = failure_category
            attempt["reason"] = str(exc)
            if item["phase"] == "integrating":
                transition(item, "blocked", str(exc))
            else:
                # Preserve the failed implementation but remove controller-created commit
                # from retry HEAD. Its diff remains available for the next worker.
                if work.exists():
                    try:
                        git(work, "reset", "--mixed", base)
                    except ValueError:
                        pass
                transition(item, "ready", str(exc))
        attempt["finished_at"] = time.time()
        checkpoint(directory, state)
    checkpoint(directory, state)
    return report(state)


def report(state):
    summary = dict(
        run_id=state["id"],
        branch=state["branch"],
        fixture=state["policy"]["adapter"] == "fixture",
        outcome="all_resolved" if all(i["phase"] == "resolved" for i in state["items"]) else "finished_with_blockers",
        reserved_usd=state["reserved_usd"],
        items=[
            {
                "id": i["task"]["id"],
                "source_id": i["task"].get("source_id"),
                "source_revision": i["task"].get("source_revision"),
                "phase": i["phase"],
                "reason": i.get("reason"),
                "attempts": len(i["attempts"]),
                "evidence": i.get("evidence"),
            }
            for i in state["items"]
        ],
    )
    print(json.dumps(summary, indent=2))
    return 0 if summary["outcome"] == "all_resolved" else 2


def run(args):
    project = Path(args.project).resolve()
    control = location(project)
    with locked(control):
        if args.resume:
            if not args.resume or str(uuid.UUID(args.resume)) != args.resume:
                raise ValueError("Invalid run ID")
            directory = control / args.resume
            state = json.loads((directory / "run.json").read_text())
        else:
            if not args.plan or not args.policy:
                raise ValueError("A reviewed --plan and --policy are required")
            policy = load_policy(Path(args.policy).resolve())
            plan_path = Path(args.plan).resolve()
            expected_digest = plan_path.stem if plan_path.parent == control / "plans" else None
            tasks = load_plan(plan_path, policy, expected_digest)
            run_id = str(uuid.uuid4())
            directory = control / run_id
            directory.mkdir()
            base = git(project, "rev-parse", "HEAD")
            branch = "refs/heads/roadrunner/run-" + run_id
            git(project, "update-ref", branch, base, "0" * 40)
            state = dict(
                id=run_id,
                project=str(project),
                branch=branch,
                base=base,
                policy=policy,
                gate_version=digest(policy),
                created_at=time.time(),
                deadline=time.time() + policy["run_seconds"],
                reserved_usd=0,
                items=[dict(task=t, phase="ready", attempts=[]) for t in tasks],
            )
            checkpoint(directory, state)
        if digest(state["policy"]) != state["gate_version"]:
            raise ValueError("Frozen policy hash mismatch; restore controller state from trusted evidence")
        try:
            return drive(project, directory, state)
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            for item in state["items"]:
                if item["phase"] not in TERMINAL:
                    transition(item, "blocked", f"Controller recovery required: {exc}")
            checkpoint(directory, state)
            return report(state)


def main(argv):
    parser = argparse.ArgumentParser(prog="roadrunner run")
    parser.add_argument("--project", default=".")
    parser.add_argument("--plan")
    parser.add_argument("--policy")
    parser.add_argument("--resume")
    args = parser.parse_args(argv)
    previous = signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        return run(args)
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"outcome": "blocked", "reason": str(exc)}), file=sys.stderr)
        return 2
    finally:
        signal.signal(signal.SIGTERM, previous)
