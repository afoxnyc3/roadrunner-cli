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
        # Run from a directory without a snapshot
        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        # Copy hook files to tmp
        import shutil
        shutil.copy2(HOOKS_DIR / "session_start_hook.sh", hooks_dir / "session_start_hook.sh")
        shutil.copy2(HOOKS_DIR / "_session_start.py", hooks_dir / "_session_start.py")
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
        payload = {"tool_input": {"file_path": str(PROJECT_ROOT / "roadrunner.py")}}
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
