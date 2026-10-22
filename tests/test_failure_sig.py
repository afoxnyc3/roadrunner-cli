"""Repeat-failure signature tests (issue #19)."""

import subprocess

from roadrunner import failure_sig as fs


def R(out="", cmd="pytest", rc=1, kind="fail"):
    return {"command": cmd, "passed": False, "returncode": rc, "kind": kind, "stdout": out, "stderr": ""}


def same(a, b):
    return fs.failure_sig([R(a)]) == fs.failure_sig([R(b)])


def test_timestamps_normalized():
    assert same("E at 2026-10-20T10:00:01Z boom", "E at 2026-10-21 11:22:33.123+00:00 boom")


def test_durations_normalized():
    assert same("1 failed in 0.42s", "1 failed in 120.5s")
    assert same("took 15ms", "took 900ms")


def test_duration_not_confused_with_identifiers():
    assert not same("error in test_5s_case", "error in test_9s_case")


def test_tmp_paths_normalized_but_not_deeper_components():
    assert same("open /tmp/abc123/file.py failed", "open /tmp/zzz999/file.py failed")
    assert same("/private/var/folders/aa/bb/T/x1 bad", "/private/var/folders/cc/dd/T/y2 bad")


def test_hex_and_pid_normalized():
    assert same("obj at 0x7f00aa11", "obj at 0x1234abcd")
    assert same("worker pid 123 died", "worker pid 98765 died")


def test_different_error_is_not_a_repeat():
    assert not same("AssertionError: expected 3", "AssertionError: expected 4")
    assert not same("foo.py:10: E501", "foo.py:11: E501")
    assert not same("test_a FAILED", "test_b FAILED")


def test_kind_and_exit_code_separate_timeout_from_failure():
    assert fs.failure_sig([R(rc=1, kind="fail")]) != fs.failure_sig([R(rc=-1, kind="timeout")])


def test_passing_results_ignored():
    ok = {"command": "ruff", "passed": True, "returncode": 0, "stdout": "all fine 1.2s", "stderr": ""}
    assert fs.failure_sig([ok, R("x")]) == fs.failure_sig([R("x")])


def _repo(tmp_path):
    for c in (["init", "-q"], ["config", "user.email", "a@b"], ["config", "user.name", "t"]):
        subprocess.run(["git", *c], cwd=tmp_path, check=True)
    (tmp_path / "a.py").write_text("x=1\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "i"], cwd=tmp_path, check=True)


def test_diff_sig_tracks_changes_and_ignores_pyc(tmp_path):
    _repo(tmp_path)
    base = fs.diff_sig(tmp_path)
    (tmp_path / "a.py").write_text("x=2\n")
    changed = fs.diff_sig(tmp_path)
    assert changed != base
    assert fs.diff_sig(tmp_path) == changed
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "a.cpython-312.pyc").write_bytes(b"1")
    assert fs.diff_sig(tmp_path) == changed
    (tmp_path / "new.py").write_text("y=1\n")
    assert fs.diff_sig(tmp_path) != changed


def test_update_record_counts_only_when_both_unchanged():
    r0 = fs.update_record(None, "T", "f1", "d1")
    assert r0["repeats"] == 0
    r1 = fs.update_record(r0, "T", "f1", "d1")
    assert r1["repeats"] == 1
    assert fs.update_record(r1, "T", "f1", "d2")["repeats"] == 0  # diff changed
    assert fs.update_record(r1, "T", "f2", "d1")["repeats"] == 0  # failure changed
    assert fs.update_record(r1, "U", "f1", "d1")["repeats"] == 0  # other task
