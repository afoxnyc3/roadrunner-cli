"""Run with an installed console script and a fresh disposable directory.

This intentionally imports no Roadrunner modules: every product action uses the
installed entry point from outside the source checkout.
"""

import json
import os
from pathlib import Path
import subprocess
import sys


def qualify(executable, destination):
    executable = Path(executable).resolve()
    root = Path(destination).resolve()
    root.mkdir(parents=True, exist_ok=False)
    project = root / "external-project"
    project.mkdir()
    env = dict(os.environ, PATH=str(executable.parent) + os.pathsep + os.environ["PATH"])
    env.pop("PYTHONPATH", None)
    env.pop("CLAUDE_PROJECT_DIR", None)

    def call(*args, expected=0):
        result = subprocess.run([str(executable), *args], cwd=project, env=env, text=True, capture_output=True, timeout=120)
        if result.returncode != expected:
            raise AssertionError(result.stdout + result.stderr)
        return result.stdout

    def git(*args):
        return subprocess.run(["git", *args], cwd=project, check=True, capture_output=True, text=True).stdout.strip()

    (project / "CLAUDE.md").write_text("Existing operator instructions\n")
    (project / ".claude").mkdir()
    (project / ".claude/settings.json").write_text('{"existing":true}')
    call("init", ".")
    assert (project / "hooks/stop_hook.sh").exists()
    assert (project / "CLAUDE.md").read_text() == "Existing operator instructions\n"
    assert json.loads((project / ".claude/settings.json").read_text()) == {"existing": True}
    (project / "gate.py").write_text(
        "from pathlib import Path\nfor name in ['one','two','retry','after']:\n"
        " p=Path(name)\n if p.exists(): assert p.read_text() == 'fixed', name\n"
    )
    (project / "operator.txt").write_text("committed")
    git("init", "-b", "main")
    git("config", "user.name", "Installed qualification")
    git("config", "user.email", "fixture@example.invalid")
    git("add", ".")
    git("commit", "-m", "external baseline")
    baseline = git("rev-parse", "HEAD")
    (project / "operator.txt").write_text("preserve this uncommitted edit")
    python = str(executable.parent / "python")
    agent = root / "fake-agent.py"
    agent.write_text("""import json, os, sys
from pathlib import Path
task=json.loads(os.environ['ROADRUNNER_TASK'])
name=task['files_expected'][0]
if name=='external':
 print('External service unavailable. Supply a service fixture before retry.'); sys.exit(17)
if name=='two': assert Path('one').read_text()=='fixed'
value='bad' if name=='retry' and os.environ['ROADRUNNER_ATTEMPT']=='1' else 'fixed'
Path(name).write_text(value)
""")
    tasks = []
    for index, name in enumerate(["one", "two", "retry", "ambiguous", "external", "after"], 1):
        tasks.append(
            dict(
                id=f"TASK-{index:03}",
                title=name,
                status="todo",
                goal=f"Create {name}",
                acceptance_criteria=[] if name == "ambiguous" else [f"{name} equals fixed"],
                files_expected=[name],
                depends_on=["TASK-001"] if name == "two" else [],
            )
        )
    # JSON is valid YAML, so this fixture needs no third-party imports.
    plan = root / "roadmap.yaml"
    plan.write_text(json.dumps({"tasks": tasks}))
    policy = root / "policy.json"
    policy.write_text(
        json.dumps(
            dict(
                adapter="fixture",
                sandbox="macos" if sys.platform == "darwin" else "fixture",
                fixture_command=[python, str(agent)],
                validation_commands=[f"{python} gate.py"],
                protected_paths=["gate.py"],
                max_attempts=2,
                run_seconds=90,
                attempt_seconds=10,
                max_budget_usd=10,
            )
        )
    )
    doctor = json.loads(call("doctor", "--policy", str(policy)))
    first = json.loads(call("sync", "--roadmap", str(plan)))
    second = json.loads(call("sync", "--roadmap", str(plan)))
    assert first == second
    report = json.loads(call("run", "--plan", first["plan"], "--policy", str(policy), expected=2))
    assert [item["phase"] for item in report["items"]] == ["resolved", "resolved", "resolved", "needs_input", "blocked", "resolved"]
    assert report["items"][2]["attempts"] == 2
    for name in ("one", "two", "retry", "after"):
        assert git("show", report["branch"] + ":" + name) == "fixed"
        assert not (project / name).exists()
    assert git("rev-parse", "HEAD") == baseline
    assert (project / "operator.txt").read_text() == "preserve this uncommitted edit"
    resumed = json.loads(call("run", "--resume", report["run_id"], expected=2))
    assert resumed == report
    result = dict(
        installed_executable=str(executable),
        external_project=str(project),
        doctor=doctor,
        source_plan=first,
        report=report,
        operator_preserved=True,
        repeated_sync_identical=True,
        repeated_resume_identical=True,
        real_agent=False,
    )
    (root / "qualification.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    qualify(sys.argv[1], sys.argv[2])
