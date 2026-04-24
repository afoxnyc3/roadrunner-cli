"""Tests for roadrunner.py controller logic."""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
import roadrunner


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_project(tmp_path):
    """Set up a minimal roadrunner project tree in tmp_path."""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()

    tasks_data = {
        "tasks": [
            {
                "id": "TASK-001",
                "title": "First task",
                "status": "done",
                "depends_on": [],
                "goal": "Do the first thing",
                "acceptance_criteria": ["thing exists"],
                "validation_commands": ["true"],
                "files_expected": ["a.py"],
            },
            {
                "id": "TASK-002",
                "title": "Second task",
                "status": "todo",
                "depends_on": ["TASK-001"],
                "goal": "Do the second thing",
                "acceptance_criteria": ["thing two exists"],
                "validation_commands": ["true"],
                "files_expected": ["b.py"],
            },
            {
                "id": "TASK-003",
                "title": "Third task",
                "status": "todo",
                "depends_on": ["TASK-002"],
                "goal": "Do the third thing",
                "acceptance_criteria": [],
                "validation_commands": ["false"],
                "files_expected": [],
            },
        ]
    }

    tasks_file = tasks_dir / "tasks.yaml"
    with open(tasks_file, "w") as f:
        yaml.dump(tasks_data, f, default_flow_style=False, sort_keys=False)

    (logs_dir / "CHANGELOG.md").write_text("")

    # Patch module-level paths. TASKS_BACKUP is derived from TASKS_FILE at
    # module import time, so it must be re-derived here — otherwise save_tasks
    # writes backups to the real project dir and contaminates subsequent tests.
    orig = {
        "ROOT": roadrunner.ROOT,
        "TASKS_FILE": roadrunner.TASKS_FILE,
        "TASKS_BACKUP": roadrunner.TASKS_BACKUP,
        "LOGS_DIR": roadrunner.LOGS_DIR,
        "CHANGELOG": roadrunner.CHANGELOG,
        "STATE_FILE": roadrunner.STATE_FILE,
        "TRACE_LOG": roadrunner.TRACE_LOG,
    }
    roadrunner.ROOT = tmp_path
    roadrunner.TASKS_FILE = tasks_file
    roadrunner.TASKS_BACKUP = tasks_file.with_suffix(".yaml.bak")
    roadrunner.LOGS_DIR = logs_dir
    roadrunner.CHANGELOG = logs_dir / "CHANGELOG.md"
    roadrunner.STATE_FILE = tmp_path / ".roadmap_state.json"
    roadrunner.TRACE_LOG = logs_dir / "trace.jsonl"

    yield tmp_path

    # Restore
    for k, v in orig.items():
        setattr(roadrunner, k, v)


# ── Schema validation ────────────────────────────────────────────────────────


class TestValidateTaskSchema:
    def test_valid_task(self):
        task = {"id": "TST-001", "status": "todo", "title": "Test"}
        roadrunner.validate_task_schema(task, 0)

    def test_missing_id(self):
        with pytest.raises(ValueError, match="missing required fields.*id"):
            roadrunner.validate_task_schema({"status": "todo", "title": "T"}, 0)

    def test_missing_title_and_status(self):
        with pytest.raises(ValueError, match="missing required fields"):
            roadrunner.validate_task_schema({"id": "TST-001"}, 0)

    def test_validation_commands_not_list(self):
        task = {"id": "TST-001", "status": "todo", "title": "T", "validation_commands": "bad"}
        with pytest.raises(ValueError, match="validation_commands must be a list"):
            roadrunner.validate_task_schema(task, 0)

    def test_depends_on_not_list(self):
        task = {"id": "TST-001", "status": "todo", "title": "T", "depends_on": "TASK-001"}
        with pytest.raises(ValueError, match="depends_on must be a list"):
            roadrunner.validate_task_schema(task, 0)

    def test_invalid_status_pending(self):
        task = {"id": "TST-001", "status": "pending", "title": "T"}
        with pytest.raises(ValueError, match="invalid status 'pending'"):
            roadrunner.validate_task_schema(task, 0)

    def test_invalid_status_hyphenated(self):
        task = {"id": "TST-001", "status": "in-progress", "title": "T"}
        with pytest.raises(ValueError, match="invalid status 'in-progress'"):
            roadrunner.validate_task_schema(task, 0)

    def test_all_valid_statuses_accepted(self):
        for status in ("todo", "in_progress", "done", "blocked"):
            task = {"id": "TST-001", "status": status, "title": "T"}
            roadrunner.validate_task_schema(task, 0)

    def test_bad_id_path_traversal(self):
        task = {"id": "../etc", "status": "todo", "title": "T"}
        with pytest.raises(ValueError, match="invalid ID format"):
            roadrunner.validate_task_schema(task, 0)

    def test_bad_id_empty(self):
        task = {"id": "", "status": "todo", "title": "T"}
        with pytest.raises(ValueError, match="invalid ID format"):
            roadrunner.validate_task_schema(task, 0)

    def test_bad_id_spaces(self):
        task = {"id": "has spaces", "status": "todo", "title": "T"}
        with pytest.raises(ValueError, match="invalid ID format"):
            roadrunner.validate_task_schema(task, 0)

    def test_bad_id_lowercase(self):
        task = {"id": "task-001", "status": "todo", "title": "T"}
        with pytest.raises(ValueError, match="invalid ID format"):
            roadrunner.validate_task_schema(task, 0)

    def test_good_id_format(self):
        task = {"id": "TASK-001", "status": "todo", "title": "T"}
        roadrunner.validate_task_schema(task, 0)

    def test_bad_validation_timeout(self):
        task = {"id": "TST-001", "status": "todo", "title": "T", "validation_timeout": "fast"}
        with pytest.raises(ValueError, match="validation_timeout must be a positive number"):
            roadrunner.validate_task_schema(task, 0)

    def test_negative_validation_timeout(self):
        task = {"id": "TST-001", "status": "todo", "title": "T", "validation_timeout": -5}
        with pytest.raises(ValueError, match="validation_timeout must be a positive number"):
            roadrunner.validate_task_schema(task, 0)


# ── Eligibility ──────────────────────────────────────────────────────────────


class TestEligibility:
    TASKS = [
        {"id": "A", "status": "done", "title": "A", "depends_on": []},
        {"id": "B", "status": "todo", "title": "B", "depends_on": ["A"]},
        {"id": "C", "status": "todo", "title": "C", "depends_on": ["B"]},
        {"id": "D", "status": "in_progress", "title": "D", "depends_on": []},
    ]

    def test_done_not_eligible(self):
        assert not roadrunner.is_eligible(self.TASKS[0], self.TASKS)

    def test_todo_with_met_deps(self):
        assert roadrunner.is_eligible(self.TASKS[1], self.TASKS)

    def test_todo_with_unmet_deps(self):
        assert not roadrunner.is_eligible(self.TASKS[2], self.TASKS)

    def test_in_progress_not_eligible(self):
        assert not roadrunner.is_eligible(self.TASKS[3], self.TASKS)

    def test_next_eligible(self):
        result = roadrunner.next_eligible_task(self.TASKS)
        assert result["id"] == "B"

    def test_no_eligible(self):
        tasks = [
            {"id": "X", "status": "done", "title": "X", "depends_on": []},
            {"id": "Y", "status": "in_progress", "title": "Y", "depends_on": []},
        ]
        assert roadrunner.next_eligible_task(tasks) is None

    def test_active_task(self):
        result = roadrunner.active_task(self.TASKS)
        assert result["id"] == "D"

    def test_no_active_task(self):
        tasks = [{"id": "X", "status": "done", "title": "X", "depends_on": []}]
        assert roadrunner.active_task(tasks) is None

    def test_circular_deps_never_eligible(self):
        """A→B→A cycle: neither task becomes eligible since deps are never 'done'."""
        tasks = [
            {"id": "CYC-001", "status": "todo", "title": "A", "depends_on": ["CYC-002"]},
            {"id": "CYC-002", "status": "todo", "title": "B", "depends_on": ["CYC-001"]},
        ]
        assert not roadrunner.is_eligible(tasks[0], tasks)
        assert not roadrunner.is_eligible(tasks[1], tasks)
        assert roadrunner.next_eligible_task(tasks) is None


# ── Completion signal ────────────────────────────────────────────────────────


class TestCompletionSignal:
    def test_bare_signal(self):
        assert roadrunner.is_completion_signal("ROADMAP_COMPLETE")

    def test_trailing_newline(self):
        assert roadrunner.is_completion_signal("ROADMAP_COMPLETE\n")

    def test_with_leading_text(self):
        assert roadrunner.is_completion_signal("All done.\n\nROADMAP_COMPLETE\n")

    def test_with_leading_whitespace(self):
        assert roadrunner.is_completion_signal("  ROADMAP_COMPLETE  ")

    def test_substring_no_match(self):
        assert not roadrunner.is_completion_signal(
            "Quote: ROADMAP_COMPLETE in the middle"
        )

    def test_mid_message_no_match(self):
        assert not roadrunner.is_completion_signal(
            "ROADMAP_COMPLETE\nbut then more text"
        )

    def test_empty_string(self):
        assert not roadrunner.is_completion_signal("")

    def test_none_coerced(self):
        assert not roadrunner.is_completion_signal("")

    def test_only_whitespace(self):
        assert not roadrunner.is_completion_signal("   \n  \n  ")


# ── State management ─────────────────────────────────────────────────────────


class TestState:
    def test_read_missing_state(self, tmp_project):
        state_file = tmp_project / ".roadmap_state.json"
        if state_file.exists():
            state_file.unlink()
        state = roadrunner.read_state()
        assert state["current_task_id"] is None
        assert state["iteration"] == 0
        assert state["attempts_per_task"] == {}

    def test_write_and_read_state(self, tmp_project):
        roadrunner.write_state("TASK-002", 3, {"TASK-002": 2})
        state = roadrunner.read_state()
        assert state["current_task_id"] == "TASK-002"
        assert state["iteration"] == 3
        assert state["attempts_per_task"]["TASK-002"] == 2

    def test_increment_attempts(self):
        state = {"attempts_per_task": {"TST-001": 2}}
        result = roadrunner.increment_attempts(state, "TST-001")
        assert result == 3
        assert state["attempts_per_task"]["TST-001"] == 3

    def test_increment_new_task(self):
        state = {"attempts_per_task": {}}
        result = roadrunner.increment_attempts(state, "TST-001")
        assert result == 1


# ── Atomic save ──────────────────────────────────────────────────────────────


class TestAtomicSave:
    def test_save_roundtrip(self, tmp_project):
        tasks = roadrunner.load_tasks()
        assert len(tasks) == 3
        tasks[1]["status"] = "in_progress"
        roadrunner.save_tasks(tasks)
        reloaded = roadrunner.load_tasks()
        assert reloaded[1]["status"] == "in_progress"

    def test_no_tmp_left(self, tmp_project):
        tasks = roadrunner.load_tasks()
        roadrunner.save_tasks(tasks)
        tmp_file = roadrunner.TASKS_FILE.with_suffix(
            roadrunner.TASKS_FILE.suffix + ".tmp"
        )
        assert not tmp_file.exists()

    def test_schema_validation_on_load(self, tmp_project):
        bad_data = {"tasks": [{"id": "BAD"}]}
        with open(roadrunner.TASKS_FILE, "w") as f:
            yaml.dump(bad_data, f)
        with pytest.raises(ValueError, match="missing required fields"):
            roadrunner.load_tasks()

    def test_rolling_backups_keeps_configured_count(self, tmp_project, monkeypatch):
        monkeypatch.setattr(roadrunner, "TASKS_BACKUP_KEEP", 3)
        tasks = roadrunner.load_tasks()
        # Perform more saves than backups retained; each save rolls .bak → .bak.1 → .bak.2 → .bak.3.
        for _ in range(6):
            roadrunner.save_tasks(tasks)
        assert roadrunner.TASKS_BACKUP.exists()
        assert roadrunner.TASKS_FILE.with_suffix(".yaml.bak.1").exists()
        assert roadrunner.TASKS_FILE.with_suffix(".yaml.bak.2").exists()
        assert roadrunner.TASKS_FILE.with_suffix(".yaml.bak.3").exists()
        # Must not exceed the configured retention
        assert not roadrunner.TASKS_FILE.with_suffix(".yaml.bak.4").exists()

    def test_save_failure_does_not_shift_backup_chain(self, tmp_project, monkeypatch):
        # Regression guard for H1 in the Opus-4.7 audit: a serialization failure
        # during save_tasks must not rotate the backup chain, so a transient
        # bug can't slowly evict good backups by triggering repeated failures.
        tasks = roadrunner.load_tasks()
        roadrunner.save_tasks(tasks)                        # produces .bak
        original_bak_bytes = roadrunner.TASKS_BACKUP.read_bytes()

        def boom(*args, **kwargs):
            raise RuntimeError("disk full — simulated")

        monkeypatch.setattr(roadrunner.yaml, "dump", boom)
        with pytest.raises(RuntimeError, match="disk full"):
            roadrunner.save_tasks(tasks)

        # .bak must still be the pre-failure content
        assert roadrunner.TASKS_BACKUP.read_bytes() == original_bak_bytes
        # The chain must NOT have shifted — .bak.1 should not exist because
        # rotation happens only after a successful tmp write.
        assert not roadrunner.TASKS_FILE.with_suffix(".yaml.bak.1").exists()
        # Leftover tmp from the failed write gets cleaned up on next successful save
        tmp_path = roadrunner.TASKS_FILE.with_suffix(roadrunner.TASKS_FILE.suffix + ".tmp")
        if tmp_path.exists():
            tmp_path.unlink()


# ── Run validation ───────────────────────────────────────────────────────────


class TestRunValidation:
    def test_passing_commands(self, tmp_project):
        task = {"id": "T", "validation_commands": ["true", "true"]}
        roadrunner.write_state(None, 0)
        passed, results = roadrunner.run_validation(task)
        assert passed
        assert len(results) == 2
        assert all(r["passed"] for r in results)

    def test_failing_command(self, tmp_project):
        task = {"id": "T", "validation_commands": ["true", "false"]}
        roadrunner.write_state(None, 0)
        passed, results = roadrunner.run_validation(task)
        assert not passed
        assert results[0]["passed"]
        assert not results[1]["passed"]

    def test_no_commands(self, tmp_project):
        task = {"id": "T", "validation_commands": []}
        passed, results = roadrunner.run_validation(task)
        assert passed
        assert results == []

    def test_trace_written(self, tmp_project):
        task = {"id": "T", "validation_commands": ["echo hi"]}
        roadrunner.write_state(None, 1)
        roadrunner.run_validation(task)
        trace_lines = roadrunner.TRACE_LOG.read_text().strip().splitlines()
        events = [json.loads(line) for line in trace_lines]
        assert any(e["event"] == "validation_command" for e in events)
        assert any(e["event"] == "validation_complete" for e in events)

    def test_timeout_treated_as_failure(self, tmp_project):
        task = {"id": "T", "validation_commands": ["slow_cmd"], "validation_timeout": 5}
        roadrunner.write_state(None, 1)
        exc = subprocess.TimeoutExpired("slow_cmd", 5)
        exc.stdout = b"partial out"
        exc.stderr = b"partial err"
        with patch("roadrunner.subprocess.run", side_effect=exc):
            passed, results = roadrunner.run_validation(task)
        assert not passed
        assert len(results) == 1
        assert results[0]["returncode"] == -1
        assert results[0]["timed_out"] is True
        assert results[0]["passed"] is False
        assert results[0]["stdout"] == "partial out"
        assert results[0]["stderr"] == "partial err"

    def test_timeout_with_none_output(self, tmp_project):
        """TimeoutExpired with stdout=None should not crash."""
        task = {"id": "T", "validation_commands": ["hang"], "validation_timeout": 1}
        roadrunner.write_state(None, 1)
        exc = subprocess.TimeoutExpired("hang", 1)
        exc.stdout = None
        exc.stderr = None
        with patch("roadrunner.subprocess.run", side_effect=exc):
            passed, results = roadrunner.run_validation(task)
        assert not passed
        assert results[0]["stdout"] == ""
        assert results[0]["stderr"] == ""

    def test_timeout_uses_task_value(self, tmp_project):
        """validation_timeout from task dict is passed to subprocess.run."""
        task = {"id": "T", "validation_commands": ["true"], "validation_timeout": 42}
        roadrunner.write_state(None, 1)
        with patch("roadrunner.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess("true", 0, stdout="", stderr="")
            roadrunner.run_validation(task)
        mock_run.assert_called_once_with(
            "true", shell=True, capture_output=True, text=True,
            cwd=roadrunner.ROOT, timeout=42,
        )


# ── Corrupt input ───────────────────────────────────────────────────────────


class TestCorruptInput:
    def test_load_tasks_invalid_yaml(self, tmp_project):
        # Parser errors are wrapped in a ValueError with operator guidance
        # so the loop halts with an actionable message instead of a raw traceback.
        roadrunner.TASKS_FILE.write_text(": [invalid yaml\n  broken:")
        with pytest.raises(ValueError, match="not valid YAML"):
            roadrunner.load_tasks()

    def test_read_state_invalid_json(self, tmp_project, capsys):
        # Corrupt state must not wedge the loop; reconverge from defaults.
        roadrunner.STATE_FILE.write_text("{not json!!")
        state = roadrunner.read_state()
        assert state == {"current_task_id": None, "iteration": 0, "attempts_per_task": {}}
        assert "state file unreadable" in capsys.readouterr().err

    def test_load_tasks_empty_yaml(self, tmp_project):
        roadrunner.TASKS_FILE.write_text("")
        tasks = roadrunner.load_tasks()
        assert tasks == []


# ── check-stop logic ────────────────────────────────────────────────────────


class TestCheckStop:
    """Test cmd_check_stop by calling it with mocked stdin."""

    def _run_check_stop(self, tmp_project, stdin_payload, max_iter="50", max_attempts="5"):
        args = type("Args", (), {
            "max_iterations": max_iter,
            "max_attempts": max_attempts,
        })()
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = json.dumps(stdin_payload)
            try:
                roadrunner.cmd_check_stop(args)
            except SystemExit:
                pass
        return self._last_stdout

    def _capture_check_stop(self, tmp_project, stdin_payload, max_iter="50", max_attempts="5"):
        args = type("Args", (), {
            "max_iterations": max_iter,
            "max_attempts": max_attempts,
        })()
        import io
        captured = io.StringIO()
        with patch("sys.stdin") as mock_stdin, patch("sys.stdout", captured):
            mock_stdin.read.return_value = json.dumps(stdin_payload)
            try:
                roadrunner.cmd_check_stop(args)
            except SystemExit:
                pass
        output = captured.getvalue().strip()
        return json.loads(output) if output else None

    def test_stop_hook_active_still_drives_loop_when_work_remains(self, tmp_project):
        """stop_hook_active is a hint, not a hard stop. If there's still eligible
        work, the hook keeps driving — the iteration cap and per-task auto-block
        are the real safety nets against runaway loops. Regression test for the
        'loop stops after every task or two' failure mode seen on the external
        entra-triage pilot."""
        roadrunner.write_state(None, 0)
        result = self._capture_check_stop(
            tmp_project, {"stop_hook_active": True, "last_assistant_message": "test"}
        )
        assert result is not None, "hook should keep driving when work remains"
        assert result.get("decision") == "block"
        assert "TASK-002" in result.get("reason", ""), "should inject next-task brief"

    def test_stop_hook_active_allows_stop_when_roadmap_finished(self, tmp_project):
        """The one case where stop_hook_active still short-circuits: genuinely
        nothing left to do (no active task, no eligible next)."""
        # Mark every task done so neither active_task nor next_eligible_task returns anything.
        tasks = roadrunner.load_tasks()
        for t in tasks:
            t["status"] = "done"
        roadrunner.save_tasks(tasks)
        roadrunner.write_state(None, 0)
        result = self._capture_check_stop(
            tmp_project, {"stop_hook_active": True, "last_assistant_message": "test"}
        )
        assert result is None, "with no work remaining + hook-loop signal, allow stop"

    def test_completion_signal_allows_stop(self, tmp_project):
        roadrunner.write_state(None, 0)
        result = self._capture_check_stop(
            tmp_project,
            {"stop_hook_active": False, "last_assistant_message": "done\n\nROADMAP_COMPLETE"},
        )
        assert result is None
        # Completion path must also write a terminal entry to CHANGELOG so the
        # audit trail is durable — a returns-early implementation would pass
        # the "result is None" check alone.
        changelog = roadrunner.CHANGELOG.read_text()
        assert "ALL" in changelog
        assert "Roadmap finished" in changelog

    def test_false_positive_blocked(self, tmp_project):
        roadrunner.write_state(None, 0)
        result = self._capture_check_stop(
            tmp_project,
            {"stop_hook_active": False, "last_assistant_message": "mention ROADMAP_COMPLETE here"},
        )
        assert result is not None
        assert result["decision"] == "block"

    def test_resumes_in_progress(self, tmp_project):
        tasks = roadrunner.load_tasks()
        tasks[1]["status"] = "in_progress"
        roadrunner.save_tasks(tasks)
        roadrunner.write_state("TASK-002", 1)
        result = self._capture_check_stop(
            tmp_project, {"stop_hook_active": False, "last_assistant_message": "working"}
        )
        assert "RESUME IN-PROGRESS" in result["reason"]
        assert "TASK-002" in result["reason"]

    def test_all_done_prompts_completion(self, tmp_project):
        roadrunner.write_state(None, 0)
        tasks = roadrunner.load_tasks()
        for t in tasks:
            t["status"] = "done"
        roadrunner.save_tasks(tasks)
        result = self._capture_check_stop(
            tmp_project, {"stop_hook_active": False, "last_assistant_message": "idle"}
        )
        assert "All tasks complete" in result["reason"]

    def test_iteration_cap(self, tmp_project):
        roadrunner.write_state(None, 49)
        result = self._capture_check_stop(
            tmp_project, {"stop_hook_active": False, "last_assistant_message": ""}
        )
        assert result["continue"] is False
        assert "Max iterations" in result["stopReason"]

    def test_auto_block_after_max_attempts(self, tmp_project):
        tasks = roadrunner.load_tasks()
        tasks[1]["status"] = "in_progress"
        roadrunner.save_tasks(tasks)
        roadrunner.write_state("TASK-002", 1, {"TASK-002": 4})
        result = self._capture_check_stop(
            tmp_project,
            {"stop_hook_active": False, "last_assistant_message": "still working"},
            max_attempts="5",
        )
        assert "auto-blocked" in result["reason"]
        reloaded = roadrunner.load_tasks()
        task_002 = roadrunner.get_task(reloaded, "TASK-002")
        assert task_002["status"] == "blocked"

    def test_auto_block_full_progression_from_zero(self, tmp_project):
        # Drive the full 0 → MAX progression through repeated check_stop calls
        # to prove the attempt counter increments across real hook cycles and
        # the task flips to blocked exactly at MAX, not before.
        tasks = roadrunner.load_tasks()
        tasks[1]["status"] = "in_progress"
        roadrunner.save_tasks(tasks)
        roadrunner.write_state("TASK-002", 0, {})
        for attempt in range(1, 5):
            result = self._capture_check_stop(
                tmp_project,
                {"stop_hook_active": False, "last_assistant_message": "still working"},
                max_attempts="5",
            )
            assert "RESUME IN-PROGRESS" in result["reason"], f"attempt {attempt} should resume, not block"
            state = roadrunner.read_state()
            assert state["attempts_per_task"]["TASK-002"] == attempt
            # Task stays in_progress until the 5th attempt trips auto-block.
            assert roadrunner.get_task(roadrunner.load_tasks(), "TASK-002")["status"] == "in_progress"
        # Fifth cycle trips auto-block.
        final = self._capture_check_stop(
            tmp_project,
            {"stop_hook_active": False, "last_assistant_message": "still working"},
            max_attempts="5",
        )
        assert "auto-blocked" in final["reason"]
        assert roadrunner.get_task(roadrunner.load_tasks(), "TASK-002")["status"] == "blocked"

    def test_iteration_increments_on_check_stop(self, tmp_project):
        roadrunner.write_state(None, 5)
        self._capture_check_stop(
            tmp_project, {"stop_hook_active": False, "last_assistant_message": ""}
        )
        state = roadrunner.read_state()
        assert state["iteration"] == 6

    def test_blocked_tasks_reported(self, tmp_project):
        tasks = roadrunner.load_tasks()
        for t in tasks:
            if t["id"] == "TASK-002":
                t["status"] = "blocked"
            elif t["id"] == "TASK-003":
                t["status"] = "todo"
        roadrunner.save_tasks(tasks)
        roadrunner.write_state(None, 0)
        result = self._capture_check_stop(
            tmp_project, {"stop_hook_active": False, "last_assistant_message": ""}
        )
        assert "Blocked" in result["reason"]


# ── Trace logging ────────────────────────────────────────────────────────────


class TestTraceLogging:
    def test_trace_event_writes_jsonl(self, tmp_project):
        roadrunner.trace_event("test_event", task_id="TST-001", iteration=1)
        lines = roadrunner.TRACE_LOG.read_text().strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["event"] == "test_event"
        assert record["task_id"] == "TST-001"
        assert record["iteration"] == 1

    def test_trace_with_extra(self, tmp_project):
        roadrunner.trace_event("test", extra={"foo": "bar"})
        record = json.loads(roadrunner.TRACE_LOG.read_text().strip())
        assert record["foo"] == "bar"

    def test_trace_duration(self, tmp_project):
        roadrunner.trace_event("test", duration_ms=123.456)
        record = json.loads(roadrunner.TRACE_LOG.read_text().strip())
        assert record["duration_ms"] == 123.5


# ── Build task brief ─────────────────────────────────────────────────────────


class TestBuildTaskBrief:
    TASK = {
        "id": "TASK-007",
        "title": "Test task",
        "goal": "Test the thing",
        "acceptance_criteria": ["it works"],
        "validation_commands": ["test -f out.txt"],
        "files_expected": ["out.txt"],
    }

    def test_normal_brief(self):
        brief = roadrunner._build_task_brief(self.TASK, 3, 50)
        assert "Continue working. Iteration 3/50." in brief
        assert "TASK-007" in brief
        assert "test -f out.txt" in brief

    def test_resume_brief(self):
        brief = roadrunner._build_task_brief(self.TASK, 3, 50, resume=True)
        assert "RESUME IN-PROGRESS TASK" in brief

    def test_no_bare_sentinel_line(self):
        brief = roadrunner._build_task_brief(self.TASK, 1, 50)
        assert not roadrunner.is_completion_signal(brief)


# ── Error handling / resilience ──────────────────────────────────────────────


class TestErrorHandling:
    def test_load_tasks_corrupt_yaml_raises_clear_error(self, tmp_project):
        roadrunner.TASKS_FILE.write_text("tasks:\n  - id: TASK-001\n    status: [broken")
        with pytest.raises(ValueError, match="not valid YAML"):
            roadrunner.load_tasks()

    def test_load_tasks_missing_file(self, tmp_project):
        roadrunner.TASKS_FILE.unlink()
        with pytest.raises(FileNotFoundError, match="tasks file not found"):
            roadrunner.load_tasks()

    def test_read_state_corrupt_json_falls_back(self, tmp_project, capsys):
        roadrunner.STATE_FILE.write_text("{not json")
        state = roadrunner.read_state()
        assert state["current_task_id"] is None
        assert state["iteration"] == 0
        assert "state file unreadable" in capsys.readouterr().err

    def test_read_state_not_a_dict_falls_back(self, tmp_project, capsys):
        roadrunner.STATE_FILE.write_text('["not", "a", "dict"]')
        state = roadrunner.read_state()
        assert state == {"current_task_id": None, "iteration": 0, "attempts_per_task": {}}
        assert "not a JSON object" in capsys.readouterr().err

    def test_trace_event_logs_stderr_on_write_failure(self, tmp_project, capsys, monkeypatch):
        missing = tmp_project / "does-not-exist" / "trace.jsonl"
        monkeypatch.setattr(roadrunner, "TRACE_LOG", missing)
        roadrunner.trace_event("probe")  # must not raise
        assert "trace_event failed" in capsys.readouterr().err

    def test_append_changelog_logs_stderr_on_write_failure(self, tmp_project, capsys, monkeypatch):
        missing = tmp_project / "does-not-exist" / "CHANGELOG.md"
        monkeypatch.setattr(roadrunner, "CHANGELOG", missing)
        roadrunner.append_changelog("TASK-001", "done")  # must not raise
        assert "changelog append failed" in capsys.readouterr().err


# ── Log rotation ─────────────────────────────────────────────────────────────


class TestLogRotation:
    def test_rotate_when_over_threshold(self, tmp_project, monkeypatch):
        monkeypatch.setattr(roadrunner, "LOG_ROTATE_BYTES", 100)
        roadrunner.TRACE_LOG.write_text("x" * 200)
        roadrunner.rotate_logs()
        assert not roadrunner.TRACE_LOG.exists()
        archives = list(roadrunner.LOGS_DIR.glob("trace.jsonl.*.gz"))
        assert len(archives) == 1

    def test_no_rotate_when_under_threshold(self, tmp_project, monkeypatch):
        monkeypatch.setattr(roadrunner, "LOG_ROTATE_BYTES", 10_000)
        roadrunner.TRACE_LOG.write_text("small")
        roadrunner.rotate_logs()
        assert roadrunner.TRACE_LOG.read_text() == "small"
        assert not list(roadrunner.LOGS_DIR.glob("trace.jsonl.*"))

    def test_prune_old_rotations(self, tmp_project, monkeypatch):
        import os as _os
        import time as _time

        monkeypatch.setattr(roadrunner, "LOG_RETAIN_DAYS", 1)
        old = roadrunner.LOGS_DIR / "trace.jsonl.20200101T000000Z.gz"
        old.write_text("archived")
        # Backdate its mtime to 10 days ago
        ten_days_ago = _time.time() - 10 * 86400
        _os.utime(old, (ten_days_ago, ten_days_ago))

        recent = roadrunner.LOGS_DIR / "trace.jsonl.20991231T235959Z.gz"
        recent.write_text("keep me")
        roadrunner.rotate_logs()
        assert not old.exists()
        assert recent.exists()

    def test_rotate_never_raises_on_error(self, tmp_project, monkeypatch):
        def boom(*a, **kw):
            raise RuntimeError("disk exploded")

        monkeypatch.setattr(roadrunner, "_rotate_one", boom)
        roadrunner.rotate_logs()  # must not raise

    def test_rotate_collision_safe_within_same_timestamp(self, tmp_project, monkeypatch):
        # Regression guard for H4 in the Opus-4.7 audit: back-to-back rotations
        # whose strftime stamps collide must not clobber the earlier archive.
        # Freeze the stamp so both calls land on the same filename base.
        class FrozenDatetime(roadrunner.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 4, 16, 12, 0, 0, 0, tzinfo=tz)

        monkeypatch.setattr(roadrunner, "datetime", FrozenDatetime)
        monkeypatch.setattr(roadrunner, "LOG_ROTATE_BYTES", 10)

        roadrunner.TRACE_LOG.write_text("x" * 50)
        roadrunner._rotate_one(roadrunner.TRACE_LOG)
        roadrunner.TRACE_LOG.write_text("y" * 50)
        roadrunner._rotate_one(roadrunner.TRACE_LOG)

        # Both rotations must be preserved as separate archives.
        archives = list(roadrunner.LOGS_DIR.glob("trace.jsonl.*.gz"))
        assert len(archives) == 2, f"expected 2 archives, found {[a.name for a in archives]}"


# ── Git branching ────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_git_project(tmp_project, monkeypatch):
    """Initialize a git repo inside tmp_project and patch roadrunner.ROOT to it."""
    root = tmp_project
    monkeypatch.setattr(roadrunner, "ROOT", root)
    # Isolate from the developer's global git config (GPG signing, default branch, etc.)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    for key, value in (
        ("user.email", "test@example.com"),
        ("user.name", "Test"),
        ("commit.gpgsign", "false"),
        ("tag.gpgsign", "false"),
        ("gpg.format", "openpgp"),
    ):
        subprocess.run(["git", "config", key, value], cwd=root, check=True)
    seed = root / "seed.txt"
    seed.write_text("initial\n")
    subprocess.run(["git", "add", "seed.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=root, check=True)
    return root


class TestGitBranching:
    def test_create_and_merge_clean(self, tmp_git_project):
        root = tmp_git_project
        assert roadrunner.create_task_branch("TASK-099") is True
        # Make a change on the task branch
        (root / "work.txt").write_text("work\n")
        subprocess.run(["git", "add", "work.txt"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "work"], cwd=root, check=True)
        assert roadrunner.merge_task_branch("TASK-099", "main") is True
        # Branch should be deleted after successful merge
        exists = subprocess.run(
            ["git", "rev-parse", "--verify", "roadrunner/TASK-099"],
            cwd=root, capture_output=True,
        ).returncode
        assert exists != 0

    def test_merge_conflict_reports_failure(self, tmp_git_project):
        root = tmp_git_project
        # Create task branch and diverge the target file
        assert roadrunner.create_task_branch("TASK-100") is True
        (root / "shared.txt").write_text("from task branch\n")
        subprocess.run(["git", "add", "shared.txt"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "task branch change"], cwd=root, check=True)

        # Switch back to main and make a conflicting change
        subprocess.run(["git", "checkout", "-q", "main"], cwd=root, check=True)
        (root / "shared.txt").write_text("from main\n")
        subprocess.run(["git", "add", "shared.txt"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "main change"], cwd=root, check=True)

        # Merge should fail cleanly and leave the branch intact for manual resolution
        assert roadrunner.merge_task_branch("TASK-100", "main") is False
        exists = subprocess.run(
            ["git", "rev-parse", "--verify", "roadrunner/TASK-100"],
            cwd=root, capture_output=True,
        ).returncode
        assert exists == 0
        # Both the merge error AND the abort step must be in the trace log so
        # a double-failure (abort itself erroring) is visible to operators.
        trace_text = roadrunner.TRACE_LOG.read_text() if roadrunner.TRACE_LOG.exists() else ""
        assert "git_merge_error" in trace_text
        assert "git_merge_abort" in trace_text

    def test_merge_missing_branch_noop(self, tmp_git_project):
        # No task branch exists — merge_task_branch should succeed trivially
        assert roadrunner.merge_task_branch("TASK-DOESNOTEXIST", "main") is True


class TestPushOnComplete:
    """ROAD-031: after a successful merge, push per push_on_complete config.
    Defaults to 'none' (back-compat). Push failures never fail the task."""

    def _with_origin(self, tmp_git_project, tmp_path_factory):
        """Wire a bare repo as origin so pushes actually land."""
        bare = tmp_path_factory.mktemp("origin.git")
        subprocess.run(["git", "init", "--bare", "-q"], cwd=bare, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", str(bare)],
            cwd=tmp_git_project, check=True,
        )
        subprocess.run(
            ["git", "push", "-q", "origin", "main"],
            cwd=tmp_git_project, check=True,
        )
        return bare

    def _set_push_mode(self, mode):
        import yaml as _yaml
        data = _yaml.safe_load(roadrunner.TASKS_FILE.read_text()) or {}
        data["push_on_complete"] = mode
        roadrunner.TASKS_FILE.write_text(_yaml.safe_dump(data, sort_keys=False))

    def _make_task_branch_with_work(self, root, task_id, filename):
        subprocess.run(["git", "checkout", "-q", "-b", f"roadrunner/{task_id}"], cwd=root, check=True)
        (root / filename).write_text("content\n")
        subprocess.run(["git", "add", filename], cwd=root, check=True)
        subprocess.run(["git", "commit", "-q", "-m", f"work on {task_id}"], cwd=root, check=True)
        subprocess.run(["git", "checkout", "-q", "main"], cwd=root, check=True)

    def test_default_none_does_not_push(self, tmp_git_project, tmp_path_factory):
        bare = self._with_origin(tmp_git_project, tmp_path_factory)
        # Default: no push_on_complete key in tasks.yaml
        self._make_task_branch_with_work(tmp_git_project, "TASK-050", "f.txt")
        assert roadrunner.merge_task_branch("TASK-050", "main") is True
        # Origin main should NOT have the new commit
        origin_log = subprocess.run(
            ["git", "--git-dir", str(bare), "log", "main", "--oneline"],
            capture_output=True, text=True,
        ).stdout
        assert "work on TASK-050" not in origin_log

    def test_base_pushes_base_branch(self, tmp_git_project, tmp_path_factory):
        bare = self._with_origin(tmp_git_project, tmp_path_factory)
        self._set_push_mode("base")
        self._make_task_branch_with_work(tmp_git_project, "TASK-051", "g.txt")
        assert roadrunner.merge_task_branch("TASK-051", "main") is True
        origin_log = subprocess.run(
            ["git", "--git-dir", str(bare), "log", "main", "--oneline"],
            capture_output=True, text=True,
        ).stdout
        assert "work on TASK-051" in origin_log
        # Task branch should NOT be on remote under 'base' mode
        origin_branches = subprocess.run(
            ["git", "--git-dir", str(bare), "branch", "--list"],
            capture_output=True, text=True,
        ).stdout
        assert "roadrunner/TASK-051" not in origin_branches

    def test_task_pushes_task_branch_only(self, tmp_git_project, tmp_path_factory):
        bare = self._with_origin(tmp_git_project, tmp_path_factory)
        self._set_push_mode("task")
        self._make_task_branch_with_work(tmp_git_project, "TASK-052", "h.txt")
        assert roadrunner.merge_task_branch("TASK-052", "main") is True
        origin_branches = subprocess.run(
            ["git", "--git-dir", str(bare), "branch", "--list"],
            capture_output=True, text=True,
        ).stdout
        assert "roadrunner/TASK-052" in origin_branches

    def test_push_failure_does_not_fail_merge(self, tmp_git_project, monkeypatch, capsys):
        # No origin configured → push will fail. Merge must still succeed.
        self._set_push_mode("base")
        self._make_task_branch_with_work(tmp_git_project, "TASK-053", "i.txt")
        assert roadrunner.merge_task_branch("TASK-053", "main") is True
        err = capsys.readouterr().err
        assert "Push to origin/main failed" in err

    def test_invalid_mode_treated_as_none(self, tmp_git_project, tmp_path_factory):
        bare = self._with_origin(tmp_git_project, tmp_path_factory)
        self._set_push_mode("garbage")
        self._make_task_branch_with_work(tmp_git_project, "TASK-054", "j.txt")
        assert roadrunner.merge_task_branch("TASK-054", "main") is True
        origin_log = subprocess.run(
            ["git", "--git-dir", str(bare), "log", "main", "--oneline"],
            capture_output=True, text=True,
        ).stdout
        assert "work on TASK-054" not in origin_log


class TestCommitScopeAware:
    """ROAD-021: cmd_commit stages only files in the task's files_expected +
    roadrunner overlay (logs/, tasks.yaml*, .reset_*). Refuses to commit when
    out-of-scope files are dirty. Regression test for the b21c768 failure mode
    where `git add -A` swept unrelated doc edits into a task's commit."""

    def _run_commit(self, task_id, notes="", type_=None):
        args = argparse.Namespace(task_id=task_id, notes=notes, type=type_)
        try:
            roadrunner.cmd_commit(args)
            return 0
        except SystemExit as exc:
            return exc.code if isinstance(exc.code, int) else 0

    def _last_commit_subject(self, root):
        out = subprocess.run(
            ["git", "log", "-1", "--pretty=%s"], cwd=root, capture_output=True, text=True
        )
        return out.stdout.strip()

    def test_commits_in_scope_files_only(self, tmg_with_task):
        root, task_id = tmg_with_task
        # File in files_expected + overlay file (logs/) — both legit.
        (root / "a.py").write_text("print('a')\n")
        (root / "logs").mkdir(exist_ok=True)
        (root / "logs" / "TASK-002.md").write_text("# work log\n")
        rc = self._run_commit(task_id)
        assert rc == 0
        subject = self._last_commit_subject(root)
        assert subject.startswith(f"feat({task_id}):")

    def test_refuses_out_of_scope_dirty_files(self, tmg_with_task, capsys):
        root, task_id = tmg_with_task
        (root / "a.py").write_text("print('a')\n")        # in scope
        (root / "secret.env").write_text("API_KEY=...\n")  # OUT of scope
        rc = self._run_commit(task_id)
        assert rc != 0
        err = capsys.readouterr().err
        assert "secret.env" in err
        assert "out-of-scope" in err.lower() or "out of scope" in err.lower()
        # The in-scope file must NOT be committed (nothing staged on refusal).
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True
        ).stdout
        assert "a.py" in status, "in-scope file should remain uncommitted when refused"

    def test_no_dirty_files_is_noop(self, tmg_with_task, capsys):
        root, task_id = tmg_with_task
        rc = self._run_commit(task_id)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Nothing to commit" in out

    def test_custom_type_flag(self, tmg_with_task):
        root, task_id = tmg_with_task
        (root / "a.py").write_text("x = 1\n")
        rc = self._run_commit(task_id, type_="refactor")
        assert rc == 0
        assert self._last_commit_subject(root).startswith(f"refactor({task_id}):")

    def test_invalid_type_rejected(self, tmg_with_task, capsys):
        root, task_id = tmg_with_task
        (root / "a.py").write_text("x = 1\n")
        rc = self._run_commit(task_id, type_="garbage")
        assert rc != 0
        assert "Invalid --type" in capsys.readouterr().err

    def test_notes_appear_in_commit_body(self, tmg_with_task):
        root, task_id = tmg_with_task
        (root / "a.py").write_text("x = 1\n")
        rc = self._run_commit(task_id, notes="fixes ABC-123 per review")
        assert rc == 0
        body = subprocess.run(
            ["git", "log", "-1", "--pretty=%B"], cwd=root, capture_output=True, text=True
        ).stdout
        assert "fixes ABC-123 per review" in body

    def test_unknown_task_id_errors(self, tmg_with_task, capsys):
        _root, _task_id = tmg_with_task
        rc = self._run_commit("TASK-NONEXISTENT")
        assert rc != 0
        assert "not found" in capsys.readouterr().err.lower()


@pytest.fixture
def tmg_with_task(tmp_git_project):
    """tmp_git_project plus a known TASK-002 whose files_expected is ['a.py'].

    Baselines tasks/ and logs/ into the initial commit so the test tree looks
    like a real post-`roadrunner init` project. Without this, git porcelain
    reports `?? tasks/` (directory-level) instead of per-file, which defeats
    the scope matcher.
    """
    tasks = roadrunner.load_tasks()
    for t in tasks:
        if t.get("id") == "TASK-002":
            t["files_expected"] = ["a.py"]
    roadrunner.save_tasks(tasks)
    subprocess.run(["git", "add", "tasks/", "logs/"], cwd=tmp_git_project, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "baseline roadrunner scaffold"],
        cwd=tmp_git_project, check=True,
    )
    return tmp_git_project, "TASK-002"


class TestProjectBase:
    """ROAD-025: cmd_start must branch from the configured project_base, not from
    whatever branch HEAD happens to be. This prevents the stacking pattern
    where task N's branch forks from task N-1's branch."""

    def test_get_project_base_reads_from_tasks_yaml(self, tmp_project):
        # tmp_project writes tasks.yaml without project_base; fallback kicks in.
        # Rewrite it with an explicit project_base key.
        import yaml as _yaml
        existing = _yaml.safe_load(roadrunner.TASKS_FILE.read_text())
        existing["project_base"] = "develop"
        roadrunner.TASKS_FILE.write_text(_yaml.safe_dump(existing, sort_keys=False))
        assert roadrunner.get_project_base() == "develop"

    def test_get_project_base_falls_back_without_key(self, tmp_project, monkeypatch):
        # No project_base in the file → falls back to _current_branch() or "main"
        monkeypatch.setattr(roadrunner, "_current_branch", lambda: None)
        assert roadrunner.get_project_base() == "main"

    def test_create_task_branch_forks_from_base_not_current_head(self, tmp_git_project):
        # Simulate a previous task branch sitting on top: HEAD moves to it.
        root = tmp_git_project
        assert roadrunner.create_task_branch("TASK-PREV", base_branch="main") is True
        (root / "prev.txt").write_text("prev\n")
        subprocess.run(["git", "add", "prev.txt"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "prev task work"], cwd=root, check=True)
        # We are now on roadrunner/TASK-PREV with a divergent commit.
        # Create the next task branch with explicit base=main — it must NOT
        # include prev.txt (i.e., must branch from main, not from HEAD).
        assert roadrunner.create_task_branch("TASK-NEXT", base_branch="main") is True
        assert not (root / "prev.txt").exists(), \
            "TASK-NEXT must fork from main; prev.txt from TASK-PREV must be absent"


class TestCompleteClearsState:
    """ROAD-023: cmd_complete must clear current_task_id in .roadmap_state.json
    so SessionStart / check_stop don't read a stale pointer to a just-done task."""

    def test_complete_nulls_current_task_id(self, tmp_git_project):
        # Seed state as if a task had been started
        roadrunner.write_state(
            "TASK-002", 3, {"TASK-002": 1}, extra={"base_branch": "main"}
        )
        # Sanity check the seed
        assert roadrunner.read_state().get("current_task_id") == "TASK-002"

        args = argparse.Namespace(task_id="TASK-002", notes="finished")
        try:
            roadrunner.cmd_complete(args)
        except SystemExit as exc:
            # complete exits 0 on success; non-zero means validation failed.
            assert exc.code in (None, 0), f"cmd_complete errored with code {exc.code}"

        state = roadrunner.read_state()
        assert state.get("current_task_id") is None, "current_task_id must clear"
        # Iteration and attempts survive — they're loop-lifetime, not task-lifetime.
        assert state.get("iteration") == 3
        assert state.get("attempts_per_task", {}).get("TASK-002") == 1


# ── Schema version (M2) ──────────────────────────────────────────────────────


class TestStateSchemaVersion:
    def test_write_includes_schema_version(self, tmp_project):
        roadrunner.write_state("TASK-001", 3)
        data = json.loads(roadrunner.STATE_FILE.read_text())
        assert data["schema_version"] == roadrunner.STATE_SCHEMA_VERSION

    def test_legacy_state_without_version_reads_as_v1(self, tmp_project):
        # A state file from an older roadrunner (no schema_version field) must
        # still be readable — treated as v1 for backward compatibility.
        roadrunner.STATE_FILE.write_text(
            json.dumps({"current_task_id": "TASK-002", "iteration": 7, "attempts_per_task": {}})
        )
        state = roadrunner.read_state()
        assert state["current_task_id"] == "TASK-002"
        assert state["iteration"] == 7

    def test_future_schema_version_exits_and_preserves_file(self, tmp_project, capsys):
        # A state file from a NEWER roadrunner must not be silently overwritten;
        # read_state must sys.exit so the caller never falls through to a write.
        original = json.dumps({"schema_version": 99, "current_task_id": "TASK-X", "iteration": 42})
        roadrunner.STATE_FILE.write_text(original)
        with pytest.raises(SystemExit) as exc_info:
            roadrunner.read_state()
        assert exc_info.value.code == 2
        # On-disk state is unchanged so the forward-compatible version is recoverable
        assert roadrunner.STATE_FILE.read_text() == original
        err = capsys.readouterr().err
        assert "unknown schema_version" in err

    def test_snapshot_includes_schema_version(self, tmp_project):
        roadrunner.write_context_snapshot()
        snap_path = tmp_project / ".context_snapshot.json"
        data = json.loads(snap_path.read_text())
        assert data["schema_version"] == roadrunner.SNAPSHOT_SCHEMA_VERSION


# ── Concurrent hook fires (M3) ───────────────────────────────────────────────


class TestCheckStopLock:
    def test_lock_serializes_concurrent_increments(self, tmp_project):
        # Two threads calling the read→increment→write section back-to-back
        # must BOTH see their iteration bump land; the lock prevents the classic
        # lost-update race where both read the same value, both write value+1,
        # and the second write clobbers the first.
        import threading

        roadrunner.write_state(None, 0)

        barrier = threading.Barrier(2)

        def bump():
            barrier.wait()
            with roadrunner._exclusive_state_lock():
                s = roadrunner.read_state()
                roadrunner.write_state(s.get("current_task_id"), s["iteration"] + 1)

        t1 = threading.Thread(target=bump)
        t2 = threading.Thread(target=bump)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        final = roadrunner.read_state()
        assert final["iteration"] == 2, (
            f"expected both bumps to land; got iteration={final['iteration']} "
            "(lost-update race likely)"
        )


# ── UTF-8 preservation (M4) ──────────────────────────────────────────────────


class TestUtf8Roundtrip:
    def test_trace_preserves_non_ascii(self, tmp_project):
        roadrunner.trace_event("probe", extra={"title": "café — π"})
        line = roadrunner.TRACE_LOG.read_text().strip().splitlines()[-1]
        assert "café" in line
        assert "π" in line
        # The escaped form must NOT be present
        assert "caf\\u00e9" not in line

    def test_state_preserves_non_ascii(self, tmp_project):
        roadrunner.write_state("TASK-001", 1, extra={"base_branch": "主-branch"})
        raw = roadrunner.STATE_FILE.read_text()
        assert "主-branch" in raw
        assert "\\u" not in raw.replace("\\u0000", "")  # no generic escapes

    def test_reset_marker_preserves_non_ascii(self, tmp_project):
        roadrunner.write_reset_marker("TASK-001", summary="résumé ✓")
        marker_text = (tmp_project / ".reset_TASK-001").read_text()
        assert "résumé" in marker_text
        assert "✓" in marker_text


# ── SessionStart handler (N4) ────────────────────────────────────────────────


class TestSessionStart:
    """ROAD-028: SessionStart emits an INSTRUCTION, not ambient status, so the
    agent can start working on turn 1 without the user typing 'Begin'.

    Decision tree covered: no tasks file / no tasks / in-progress / eligible
    next / blocked / all-done."""

    def _run(self, capsys):
        roadrunner.cmd_session_start(argparse.Namespace())
        return capsys.readouterr().out.strip()

    def test_silent_when_tasks_file_absent(self, tmp_project, capsys):
        # tmp_project created tasks.yaml; remove it to exercise the "no file" path.
        roadrunner.TASKS_FILE.unlink()
        assert self._run(capsys) == ""

    def test_eligible_task_produces_start_instruction(self, tmp_project, capsys):
        # tmp_project has TASK-001=done, TASK-002=todo (eligible).
        out = self._run(capsys)
        data = json.loads(out)
        ctx = data["hookSpecificOutput"]["additionalContext"]
        assert data["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        assert "python3 roadrunner.py start TASK-002" in ctx
        # Should be directive, not passive status
        assert "Your first action" in ctx or "first action" in ctx.lower()

    def test_in_progress_task_produces_resume_brief(self, tmp_project, capsys):
        tasks = roadrunner.load_tasks()
        for t in tasks:
            if t.get("id") == "TASK-002":
                t["status"] = "in_progress"
        roadrunner.save_tasks(tasks)
        out = self._run(capsys)
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        assert "RESUME" in ctx.upper()
        assert "TASK-002" in ctx

    def test_all_done_prompts_for_completion_sentinel(self, tmp_project, capsys):
        tasks = roadrunner.load_tasks()
        for t in tasks:
            t["status"] = "done"
        roadrunner.save_tasks(tasks)
        out = self._run(capsys)
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        assert "ROADMAP_COMPLETE" in ctx
        assert "All tasks are done" in ctx

    def test_blocked_tasks_are_reported(self, tmp_project, capsys):
        tasks = roadrunner.load_tasks()
        for t in tasks:
            if t.get("status") != "done":
                t["status"] = "blocked"
        roadrunner.save_tasks(tasks)
        out = self._run(capsys)
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        assert "Blocked" in ctx or "blocked" in ctx
        assert "TASK-002" in ctx or "TASK-003" in ctx
