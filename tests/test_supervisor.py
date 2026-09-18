"""External Git projects and fake-agent subprocess contracts."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest
import yaml

from roadrunner import supervisor as runner


SOURCE = Path(__file__).resolve().parents[1]


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    runner.git(root, "init", "-b", "main")
    runner.git(root, "config", "user.name", "Fixture")
    runner.git(root, "config", "user.email", "fixture@example.invalid")
    (root / "base.txt").write_text("operator content")
    (root / "verify.py").write_text("from pathlib import Path\nassert Path('one').read_text() == 'fixed'\n")
    runner.git(root, "add", ".")
    runner.git(root, "commit", "-m", "initial")
    # Operator changes must survive every supervisor run.
    (root / "base.txt").write_text("operator dirty content")
    agent = tmp_path / "agent.py"
    agent.write_text("""import json, os
from pathlib import Path
task = json.loads(os.environ['ROADRUNNER_TASK'])
for name in task['files_expected']:
    Path(name).write_text('fixed')
""")
    policy = dict(
        adapter="fixture",
        sandbox="fixture",
        fixture_command=[sys.executable, str(agent)],
        validation_commands=[f"{sys.executable} verify.py"],
        protected_paths=["verify.py"],
        max_attempts=2,
        max_budget_usd=10,
        run_seconds=20,
        attempt_seconds=3,
    )
    (tmp_path / "policy.json").write_text(json.dumps(policy))
    task = dict(
        id="TASK-001",
        title="One",
        goal="Create one",
        status="todo",
        acceptance_criteria=["one is fixed"],
        files_expected=["one"],
        depends_on=[],
    )
    (tmp_path / "plan.yaml").write_text(yaml.safe_dump({"tasks": [task]}))
    return root


def command(project, *extra):
    return [
        sys.executable,
        "-m",
        "roadrunner",
        "run",
        "--project",
        str(project),
        "--plan",
        str(project.parent / "plan.yaml"),
        "--policy",
        str(project.parent / "policy.json"),
        *extra,
    ]


def invoke(project, *extra):
    return subprocess.run(
        command(project, *extra), text=True, capture_output=True, env=dict(os.environ, PYTHONPATH=str(SOURCE / "src")), timeout=30
    )


def state(project):
    paths = list(runner.location(project).glob("*/run.json"))
    assert len(paths) == 1
    return json.loads(paths[0].read_text()), paths[0]


def test_serial_dependency_integration_preserves_operator(project):
    path = project.parent / "plan.yaml"
    data = yaml.safe_load(path.read_text())
    data["tasks"].append({**data["tasks"][0], "id": "TASK-002", "depends_on": ["TASK-001"], "files_expected": ["two"]})
    path.write_text(yaml.safe_dump(data))
    result = invoke(project)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["outcome"] == "all_resolved"
    assert [i["phase"] for i in report["items"]] == ["resolved", "resolved"]
    assert runner.git(project, "show", report["branch"] + ":two") == "fixed"
    assert runner.git(project, "branch", "--show-current") == "main"
    assert (project / "base.txt").read_text() == "operator dirty content"
    assert not (project / "one").exists()
    saved, _ = state(project)
    assert saved["items"][1]["attempts"][0]["base"] == saved["items"][0]["evidence"]["candidate"]
    resumed = invoke(project, "--resume", saved["id"])
    assert resumed.returncode == 0
    assert state(project)[0]["reserved_usd"] == 2


def test_validation_retry_repairs(project):
    agent = project.parent / "agent.py"
    agent.write_text(
        "import os\nfrom pathlib import Path\nPath('one').write_text('bad' if os.environ['ROADRUNNER_ATTEMPT'] == '1' else 'fixed')\n"
    )
    result = invoke(project)
    assert result.returncode == 0, result.stdout + result.stderr
    saved, _ = state(project)
    assert len(saved["items"][0]["attempts"]) == 2
    assert saved["items"][0]["attempts"][0]["outcome"] == "failed"
    assert saved["reserved_usd"] == 2


def test_no_progress_blocks_and_independent_continues(project):
    path = project.parent / "plan.yaml"
    data = yaml.safe_load(path.read_text())
    data["tasks"][0]["acceptance_criteria"] = []
    data["tasks"].append({**data["tasks"][0], "id": "TASK-002", "acceptance_criteria": ["one fixed"]})
    path.write_text(yaml.safe_dump(data))
    result = invoke(project)
    assert result.returncode == 2
    assert [i["phase"] for i in json.loads(result.stdout)["items"]] == ["needs_input", "resolved"]


def test_tampered_gate_blocks(project):
    agent = project.parent / "agent.py"
    agent.write_text("from pathlib import Path\nPath('one').write_text('bad')\nPath('verify.py').write_text('pass')\n")
    result = invoke(project)
    assert result.returncode == 2
    saved, _ = state(project)
    assert saved["items"][0]["phase"] == "blocked"
    assert "Frozen gate" in saved["items"][0]["attempts"][0]["reason"]
    assert runner.git(project, "rev-parse", saved["branch"]) == saved["base"]


def test_invalid_transition_rejected():
    for phase in ("ready", "running", "validating", "blocked", "resolved"):
        with pytest.raises(ValueError):
            runner.transition({"phase": phase}, "resolved")


def test_reconcile_integrated_intent_without_duplicate(project):
    assert invoke(project).returncode == 0
    saved, path = state(project)
    candidate = saved["items"][0]["evidence"]["candidate"]
    saved["items"][0]["phase"] = "integrating"
    runner.atomic(path, saved)
    assert invoke(project, "--resume", saved["id"]).returncode == 0
    assert runner.git(project, "rev-parse", saved["branch"]) == candidate
    assert len(state(project)[0]["items"][0]["attempts"]) == 1


def test_deadline_and_cancellation_cleanup(project):
    (project.parent / "agent.py").write_text("import time\ntime.sleep(30)\n")
    process = subprocess.Popen(
        command(project), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=dict(os.environ, PYTHONPATH=str(SOURCE / "src"))
    )
    for _ in range(100):
        paths = list(runner.location(project).glob("*/*worker.log"))
        if paths:
            break
        time.sleep(0.05)
    process.send_signal(signal.SIGTERM)
    stdout, stderr = process.communicate(timeout=5)
    assert process.returncode == 2, stderr
    assert json.loads(stdout)["items"][0]["phase"] == "cancelled"
    assert state(project)[0]["reserved_usd"] == 1


def test_crash_resume_retains_allowance(project):
    (project.parent / "agent.py").write_text(
        "import os,time\nfrom pathlib import Path\n"
        "if os.environ['ROADRUNNER_ATTEMPT'] == '1': time.sleep(30)\nPath('one').write_text('fixed')\n"
    )
    process = subprocess.Popen(
        command(project), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=dict(os.environ, PYTHONPATH=str(SOURCE / "src"))
    )
    for _ in range(100):
        if list(runner.location(project).glob("*/*worker.log")):
            break
        time.sleep(0.05)
    process.kill()
    process.wait(timeout=5)
    time.sleep(0.2)  # Guardian observes controller pipe EOF and kills worker group.
    saved, _ = state(project)
    result = invoke(project, "--resume", saved["id"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert state(project)[0]["reserved_usd"] == 2


def test_attempt_timeout_blocks(project):
    (project.parent / "agent.py").write_text("import time\ntime.sleep(30)\n")
    path = project.parent / "policy.json"
    policy = json.loads(path.read_text())
    policy.update(max_attempts=1, attempt_seconds=0.2)
    path.write_text(json.dumps(policy))
    result = invoke(project)
    assert result.returncode == 2
    saved, _ = state(project)
    assert "Deadline exceeded" in saved["items"][0]["attempts"][0]["reason"]
    assert saved["items"][0]["phase"] == "blocked"


def test_changed_integration_ref_cannot_resolve(project):
    # Simulate an external writer, using the explicit trusted fixture adapter.
    (project.parent / "agent.py").write_text("""import json, subprocess
from pathlib import Path
Path('one').write_text('fixed')
state = json.loads((Path.cwd().parent / 'run.json').read_text())
subprocess.run(['git', 'update-ref', '-d', state['branch']], check=True)
""")
    result = invoke(project)
    assert result.returncode == 2
    saved, _ = state(project)
    assert saved["items"][0]["phase"] == "blocked"
    assert "update-ref" in saved["items"][0]["reason"]


def test_frozen_policy_tampering_rejected(project):
    assert invoke(project).returncode == 0
    saved, path = state(project)
    saved["policy"]["validation_commands"] = ["true"]
    runner.atomic(path, saved)
    result = invoke(project, "--resume", saved["id"])
    assert result.returncode == 2
    assert "policy hash mismatch" in result.stderr


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS worker sandbox")
def test_sandbox_denies_controller_and_gate_writes(tmp_path):
    work = tmp_path / "work"
    scratch = tmp_path / "scratch"
    work.mkdir()
    scratch.mkdir()
    outside = tmp_path / "controller.json"
    outside.write_text("trusted")
    (work / "gate.py").write_text("trusted gate")
    policy = dict(sandbox="macos", protected_paths=["gate.py"])
    script = """from pathlib import Path
import sys
for target in sys.argv[1:]:
    try: Path(target).write_text('tampered')
    except PermissionError: pass
    else: raise RuntimeError('sandbox allowed protected write')
Path('allowed').write_text('ok')
"""
    log = tmp_path / "sandbox.log"
    code = runner.execute(
        [sys.executable, "-c", script, str(outside), str(work / "gate.py")], work, scratch, policy, time.time() + 5, log, dict(os.environ)
    )
    assert code == 0, log.read_text()
    assert outside.read_text() == "trusted"
    assert (work / "gate.py").read_text() == "trusted gate"
    assert (work / "allowed").read_text() == "ok"


@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS worker sandbox')
def test_external_project_under_enforced_sandbox(project):
    path = project.parent / 'policy.json'
    policy = json.loads(path.read_text())
    policy['sandbox'] = 'macos'
    path.write_text(json.dumps(policy))
    result = invoke(project)
    assert result.returncode == 0, result.stdout + result.stderr
    assert state(project)[0]['items'][0]['phase'] == 'resolved'
