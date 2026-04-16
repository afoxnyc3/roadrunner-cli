"""Tests for roadrunner.py controller logic."""

import json
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

    # Patch module-level paths
    orig = {
        "ROOT": roadrunner.ROOT,
        "TASKS_FILE": roadrunner.TASKS_FILE,
        "LOGS_DIR": roadrunner.LOGS_DIR,
        "CHANGELOG": roadrunner.CHANGELOG,
        "STATE_FILE": roadrunner.STATE_FILE,
        "TRACE_LOG": roadrunner.TRACE_LOG,
    }
    roadrunner.ROOT = tmp_path
    roadrunner.TASKS_FILE = tasks_file
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
        task = {"id": "T-1", "status": "todo", "title": "Test"}
        roadrunner.validate_task_schema(task, 0)

    def test_missing_id(self):
        with pytest.raises(ValueError, match="missing required fields.*id"):
            roadrunner.validate_task_schema({"status": "todo", "title": "T"}, 0)

    def test_missing_title_and_status(self):
        with pytest.raises(ValueError, match="missing required fields"):
            roadrunner.validate_task_schema({"id": "T-1"}, 0)

    def test_validation_commands_not_list(self):
        task = {"id": "T-1", "status": "todo", "title": "T", "validation_commands": "bad"}
        with pytest.raises(ValueError, match="validation_commands must be a list"):
            roadrunner.validate_task_schema(task, 0)

    def test_depends_on_not_list(self):
        task = {"id": "T-1", "status": "todo", "title": "T", "depends_on": "TASK-001"}
        with pytest.raises(ValueError, match="depends_on must be a list"):
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
        state = {"attempts_per_task": {"T-1": 2}}
        result = roadrunner.increment_attempts(state, "T-1")
        assert result == 3
        assert state["attempts_per_task"]["T-1"] == 3

    def test_increment_new_task(self):
        state = {"attempts_per_task": {}}
        result = roadrunner.increment_attempts(state, "T-1")
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

    def test_stop_hook_active_allows_stop(self, tmp_project):
        roadrunner.write_state(None, 0)
        result = self._capture_check_stop(
            tmp_project, {"stop_hook_active": True, "last_assistant_message": "test"}
        )
        assert result is None

    def test_completion_signal_allows_stop(self, tmp_project):
        roadrunner.write_state(None, 0)
        result = self._capture_check_stop(
            tmp_project,
            {"stop_hook_active": False, "last_assistant_message": "done\n\nROADMAP_COMPLETE"},
        )
        assert result is None

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
        roadrunner.trace_event("test_event", task_id="T-1", iteration=1)
        lines = roadrunner.TRACE_LOG.read_text().strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["event"] == "test_event"
        assert record["task_id"] == "T-1"
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
