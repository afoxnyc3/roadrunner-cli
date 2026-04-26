"""Integration tests for bash hook scripts.

Tests pipe mock payloads through the actual hook scripts and verify
exit codes, stdout JSON, and stderr feedback.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
HOOKS_DIR = PROJECT_ROOT / "hooks"


def run_hook(hook_name: str, stdin_data: dict | str = "", env_extra: dict | None = None) -> subprocess.CompletedProcess:
    """Run a hook script with the given stdin payload."""
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(PROJECT_ROOT)
    if env_extra:
        env.update(env_extra)
    stdin_str = json.dumps(stdin_data) if isinstance(stdin_data, dict) else stdin_data
    return subprocess.run(
        ["bash", str(HOOKS_DIR / hook_name)],
        input=stdin_str,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(PROJECT_ROOT),
    )


# ── Stop Hook ────────────────────────────────────────────────────────────────


class TestStopHook:
    def test_stop_hook_active_allows_stop(self):
        result = run_hook("stop_hook.sh", {"stop_hook_active": True, "last_assistant_message": ""})
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_blocks_when_tasks_remain(self):
        result = run_hook("stop_hook.sh", {"stop_hook_active": False, "last_assistant_message": "working"})
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output.get("decision") == "block" or output.get("continue") is False

    def test_completion_signal_allows_stop(self):
        result = run_hook("stop_hook.sh", {
            "stop_hook_active": False,
            "last_assistant_message": "All done.\n\nROADMAP_COMPLETE",
        })
        assert result.returncode == 0


# ── SessionStart Hook ────────────────────────────────────────────────────────


class TestSessionStartHook:
    def test_with_snapshot(self):
        """When .context_snapshot.json exists, hook emits additionalContext."""
        snapshot_path = PROJECT_ROOT / ".context_snapshot.json"
        if not snapshot_path.exists():
            pytest.skip(".context_snapshot.json not present")
        result = run_hook("session_start_hook.sh", "")
        assert result.returncode == 0
        if result.stdout.strip():
            output = json.loads(result.stdout)
            assert "hookSpecificOutput" in output
            assert "additionalContext" in output["hookSpecificOutput"]

    def test_without_snapshot(self, tmp_path):
        """When snapshot is absent, hook exits 0 silently."""
        # Stage a minimal project tree. The bash hook delegates to
        # ``python -m roadrunner session-start`` which resolves against the
        # installed package, so the tmp root only needs hooks + tasks.
        import shutil
        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        shutil.copy2(HOOKS_DIR / "session_start_hook.sh", hooks_dir / "session_start_hook.sh")
        (tmp_path / "tasks").mkdir()
        (tmp_path / "tasks" / "tasks.yaml").write_text("tasks: []\n")
        result = subprocess.run(
            ["bash", str(hooks_dir / "session_start_hook.sh")],
            input="",
            capture_output=True,
            text=True,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert result.stdout.strip() == ""


# ── PreCompact Hook ──────────────────────────────────────────────────────────


class TestPreCompactHook:
    def test_writes_snapshot_no_stdout(self):
        """PreCompact should write file but produce no additionalContext stdout."""
        result = run_hook("precompact_hook.sh", "")
        assert result.returncode == 0
        # PreCompact no longer prints additionalContext (removed in ADR-007)
        assert "additionalContext" not in result.stdout
        # Snapshot file should exist
        assert (PROJECT_ROOT / ".context_snapshot.json").exists()


# ── PostToolUse Hook ─────────────────────────────────────────────────────────


class TestPostWriteHook:
    def test_python_file_runs_ruff(self):
        """Payload with a .py file should trigger ruff (if available)."""
        payload = {"tool_input": {"file_path": str(PROJECT_ROOT / "src" / "roadrunner" / "cli.py")}}
        result = run_hook("post_write_hook.sh", payload)
        assert result.returncode == 0

    def test_yaml_file_runs_parse(self):
        """Payload with a .yaml file should trigger yaml parse check."""
        payload = {"tool_input": {"file_path": str(PROJECT_ROOT / "tasks" / "tasks.yaml")}}
        result = run_hook("post_write_hook.sh", payload)
        assert result.returncode == 0

    def test_unknown_extension_passes(self):
        """Payload with a .txt file should pass through silently."""
        payload = {"tool_input": {"file_path": "/tmp/test.txt"}}
        result = run_hook("post_write_hook.sh", payload)
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_empty_path_passes(self):
        """Missing file_path should exit 0."""
        result = run_hook("post_write_hook.sh", {"tool_input": {}})
        assert result.returncode == 0

    def test_shell_injection_safe(self, tmp_path):
        """File path with quotes should not execute arbitrary code."""
        canary = tmp_path / "canary"
        canary.write_text("alive")
        malicious_path = f"{tmp_path}/x';rm '{canary}';#.yaml"
        payload = {"tool_input": {"file_path": malicious_path}}
        result = run_hook("post_write_hook.sh", payload)
        assert result.returncode == 0
        assert canary.exists(), "Shell injection canary was deleted!"


# ── Crash-recovery mid-task (end-to-end) ─────────────────────────────────────


class TestCrashRecoveryMidTask:
    """Simulate process death between `start` and `complete`.

    Drives roadrunner.py as a subprocess to prove the on-disk state machine
    alone is enough for the Stop hook to pick up the in-progress task on the
    next iteration — no in-memory state required.
    """

    def _write_min_project(self, root: Path) -> None:
        import yaml as _yaml
        (root / "tasks").mkdir()
        (root / "logs").mkdir()
        tasks = {
            "tasks": [
                {
                    "id": "TASK-001",
                    "title": "First",
                    "status": "todo",
                    "depends_on": [],
                    "validation_commands": ["true"],
                }
            ]
        }
        with open(root / "tasks" / "tasks.yaml", "w") as f:
            _yaml.dump(tasks, f)

    def test_start_then_crash_then_check_stop_resumes(self, tmp_path):
        import sys
        import yaml as _yaml

        # Stage an isolated project tree. The cli is invoked through the
        # installed package (``python -m roadrunner``); no source files need
        # to be copied. ``cwd=tmp_path`` makes ROOT resolve to the tmp tree.
        self._write_min_project(tmp_path)

        # Step 1: start the task in one subprocess (simulating one loop iteration)
        start = subprocess.run(
            [sys.executable, "-m", "roadrunner", "start", "TASK-001"],
            cwd=str(tmp_path), capture_output=True, text=True,
        )
        assert start.returncode == 0, start.stderr

        # Step 2: simulate crash — no `complete` call. State on disk must reflect in-progress.
        with open(tmp_path / "tasks" / "tasks.yaml") as f:
            after = _yaml.safe_load(f)
        assert after["tasks"][0]["status"] == "in_progress"
        state = json.loads((tmp_path / ".roadmap_state.json").read_text())
        assert state["current_task_id"] == "TASK-001"

        # Step 3: next loop iteration fires the Stop hook → check-stop must resume.
        payload = json.dumps({"stop_hook_active": False, "last_assistant_message": "mid-work"})
        resume = subprocess.run(
            [sys.executable, "-m", "roadrunner", "check-stop", "--max-iterations", "50"],
            cwd=str(tmp_path), input=payload, capture_output=True, text=True,
        )
        assert resume.returncode == 0, resume.stderr
        decision = json.loads(resume.stdout)
        assert decision["decision"] == "block"
        assert "RESUME IN-PROGRESS" in decision["reason"]
        assert "TASK-001" in decision["reason"]
