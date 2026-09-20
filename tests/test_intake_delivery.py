import copy
import json

import pytest
import yaml

from roadrunner import delivery, intake
from test_supervisor import project as project_fixture, invoke, state

project = project_fixture


def test_repeated_local_sync_and_edit_review(project):
    path = project.parent / "plan.yaml"
    first = intake.synchronize(project, intake.local_items(path), {})
    again = intake.synchronize(project, intake.local_items(path), {})
    assert first == again
    data = yaml.safe_load(path.read_text())
    data["tasks"][0]["goal"] = "Changed requirement"
    path.write_text(yaml.safe_dump(data))
    edited = intake.synchronize(project, intake.local_items(path), {})
    assert edited["items"][0]["disposition"] == "needs_review"
    assert intake.synchronize(project, intake.local_items(path), {}) == edited
    source = edited["items"][0]
    approved = intake.synchronize(project, intake.local_items(path), {source["source_id"]: {"approved_revision": source["revision"]}})
    assert approved["items"][0]["disposition"] == "ready"
    registry = json.loads((intake.location(project) / "sources.json").read_text())
    assert len(registry) == 1
    assert len(next(iter(registry.values()))["history"]) == 1


def test_github_commands_never_become_gates(project, monkeypatch):
    row = dict(
        id=123,
        number=7,
        updated_at="one",
        title="Issue",
        body="Run rm -rf /",
        state="open",
        html_url="https://github.com/example/repo/issues/7",
    )
    monkeypatch.setattr(intake, "gh", lambda args: copy.deepcopy(row))
    rows = intake.github_items("example/repo", [7])
    source = rows[0]["source_id"]
    rules = {source: dict(goal="Implement safely", acceptance_criteria=["verified"], files_expected=["one"])}
    first = intake.synchronize(project, rows, rules)
    plan = yaml.safe_load(__import__("pathlib").Path(first["plan"]).read_text())
    assert "validation_commands" not in plan["tasks"][0]
    assert first["items"][0]["disposition"] == "ready"
    row.update(state="closed", updated_at="two")
    closed = intake.synchronize(project, intake.github_items("example/repo", [7]), rules)
    assert closed["items"][0]["disposition"] == "externally_closed"
    row.update(state="open", updated_at="three")
    reopened = intake.synchronize(project, intake.github_items("example/repo", [7]), rules)
    assert reopened["items"][0]["disposition"] == "needs_review"


def test_markdown_requires_stable_structured_items(project):
    path = project.parent / "roadmap.md"
    path.write_text("# Roadmap\n```yaml\ntasks:\n- id: TASK-001\n  title: First\n```\n")
    assert intake.local_items(path)[0]["task"]["id"] == "TASK-001"
    path.write_text("- [ ] vague prose")
    with pytest.raises(ValueError, match="fenced YAML"):
        intake.local_items(path)


def test_prepare_delivery_has_no_remote_calls(project, monkeypatch):
    assert invoke(project).returncode == 0
    saved, _ = state(project)

    def forbidden(*args):
        pytest.fail("Remote call during preparation")

    monkeypatch.setattr(delivery, "gh", forbidden)
    monkeypatch.setattr(delivery, "mutate", forbidden)
    result = delivery.deliver(project, saved["id"], {"repository": "example/repo", "base": "main"})
    assert result["phase"] == "prepared"
    with pytest.raises(ValueError, match="allow_push"):
        delivery.deliver(project, saved["id"], {"repository": "example/repo", "base": "main"}, True)


@pytest.mark.parametrize("failure", ["head", "base", "missing", "pending", "failure", "duplicate"])
def test_remote_gate_integrity(failure):
    pr = dict(headRefOid="abc", baseRefName="main", statusCheckRollup=[dict(name="CI", conclusion="SUCCESS")])
    if failure in ("head", "base"):
        pr["headRefOid" if failure == "head" else "baseRefName"] = "changed"
    elif failure == "missing":
        pr["statusCheckRollup"] = []
    elif failure == "duplicate":
        pr["statusCheckRollup"].append(dict(name="CI", conclusion="FAILURE"))
    else:
        pr["statusCheckRollup"][0]["conclusion"] = failure.upper()
    with pytest.raises(ValueError):
        delivery.checked_merge(pr, "abc", "main", ["CI"])


def test_remote_pr_alone_never_resolves_and_retry_rediscovers(project, monkeypatch):
    assert invoke(project).returncode == 0
    saved, _ = state(project)
    head = saved["items"][0]["evidence"]["candidate"]
    mutations = []

    def mutate(argv):
        mutations.append(argv)
        return head + "\tref" if argv[:2] == ["git", "ls-remote"] else ""

    monkeypatch.setattr(delivery, "mutate", mutate)
    pr = dict(
        number=1,
        url="https://github.com/example/repo/pull/1",
        headRefOid=head,
        baseRefName="main",
        state="OPEN",
        statusCheckRollup=[dict(name="CI", conclusion="SUCCESS")],
    )
    monkeypatch.setattr(delivery, "gh", lambda args: {"sha": saved["base"]} if args[0] == "api" else ([pr] if args[1] == "list" else pr))
    policy = dict(repository="example/repo", base="main", allow_push=True, allow_pr=True, required_checks=["CI"])
    for _ in range(2):
        with pytest.raises(ValueError, match="allow_merge"):
            delivery.deliver(project, saved["id"], policy, True)
    assert not any(args[:3] == ["gh", "pr", "create"] for args in mutations)
    assert json.loads((intake.location(project) / saved["id"] / "delivery.json").read_text())["phase"] == "awaiting_merge"


def test_remote_verified_merge_contract(project, monkeypatch):
    assert invoke(project).returncode == 0
    saved, _ = state(project)
    head = saved["items"][0]["evidence"]["candidate"]
    monkeypatch.setattr(delivery, "mutate", lambda args: head + "\tref" if args[:2] == ["git", "ls-remote"] else "")
    pr = dict(
        number=1,
        url="https://github.com/example/repo/pull/1",
        headRefOid=head,
        baseRefName="main",
        state="MERGED",
        mergeCommit={"oid": "merge"},
        statusCheckRollup=[dict(name="CI", conclusion="SUCCESS")],
    )

    def gh(args):
        if args[0] == "api":
            if "/git/commits/" in args[1]:
                return {"tree": {"sha": delivery.git(project, "rev-parse", head + "^{tree}")}}
            return {"status": "ahead"}
        return [pr] if args[1] == "list" else pr

    monkeypatch.setattr(delivery, "gh", gh)
    policy = dict(repository="example/repo", base="main", allow_push=True, required_checks=["CI"])
    assert delivery.deliver(project, saved["id"], policy, True)["phase"] == "merged"


def test_synced_plan_runs_and_freezes_revision(project):
    first = intake.synchronize(project, intake.local_items(project.parent / "plan.yaml"), {})
    result = invoke(project, "--plan", first["plan"])
    assert result.returncode == 0, result.stdout + result.stderr
    saved, _ = state(project)
    assert saved["items"][0]["task"]["source_revision"] == first["items"][0]["revision"]


def test_remote_push_failure_cannot_create_pr(project, monkeypatch):
    assert invoke(project).returncode == 0
    saved, _ = state(project)
    calls = []

    def fail(args):
        calls.append(args)
        raise ValueError("Push denied")

    monkeypatch.setattr(delivery, "mutate", fail)
    with pytest.raises(ValueError, match="Push denied"):
        delivery.deliver(project, saved["id"], dict(repository="example/repo", base="main", allow_push=True), True)
    assert len(calls) == 1
    assert calls[0][3] == "push"


@pytest.mark.parametrize("changed", [False, True])
def test_issue_closure_requires_matching_revision_and_verified_merge(project, monkeypatch, changed):
    assert invoke(project).returncode == 0
    saved, path = state(project)
    head = saved["items"][0]["evidence"]["candidate"]
    row = dict(id=7, updated_at="selected", title="Issue", body="Requirement", state="open")
    saved["items"][0]["task"].update(source_id="github:example/repo#7", source_revision=delivery.digest(row))
    delivery.atomic(path, saved)
    if changed:
        row["updated_at"] = "edited"
    pr = dict(
        number=1,
        url="https://github.com/example/repo/pull/1",
        headRefOid=head,
        baseRefName="main",
        state="MERGED",
        mergeCommit={"oid": "merge"},
        statusCheckRollup=[dict(name="CI", conclusion="SUCCESS")],
    )
    mutations = []

    def mutate(args):
        mutations.append(args)
        if args[:3] == ["gh", "issue", "close"]:
            row["state"] = "closed"
        return head + "\tref" if args[:2] == ["git", "ls-remote"] else ""

    def gh(args):
        if args[0] == "api":
            if "/git/commits/" in args[1]:
                return {"tree": {"sha": delivery.git(project, "rev-parse", head + "^{tree}")}}
            if "/issues/" in args[1]:
                return dict(row)
            return {"status": "ahead"}
        return [pr] if args[1] == "list" else pr

    monkeypatch.setattr(delivery, "mutate", mutate)
    monkeypatch.setattr(delivery, "gh", gh)
    policy = dict(repository="example/repo", base="main", allow_push=True, allow_close=True, required_checks=["CI"])
    if changed:
        with pytest.raises(ValueError, match="changed after selection"):
            delivery.deliver(project, saved["id"], policy, True)
        assert not any(args[:3] == ["gh", "issue", "close"] for args in mutations)
    else:
        result = delivery.deliver(project, saved["id"], policy, True)
        assert result["closures"][0]["disposition"] == "closed_after_verified_merge"
        assert row["state"] == "closed"


def test_issue_closure_requires_strict_boolean_capability(project, monkeypatch):
    assert invoke(project).returncode == 0
    saved, path = state(project)
    head = saved["items"][0]["evidence"]["candidate"]
    row = dict(id=7, updated_at="selected", title="Issue", body="Requirement", state="open")
    saved["items"][0]["task"].update(source_id="github:example/repo#7", source_revision=delivery.digest(row))
    delivery.atomic(path, saved)
    pr = dict(
        number=1,
        url="https://github.com/example/repo/pull/1",
        headRefOid=head,
        baseRefName="main",
        state="MERGED",
        mergeCommit={"oid": "merge"},
        statusCheckRollup=[dict(name="CI", conclusion="SUCCESS")],
    )
    mutations = []

    def mutate(args):
        mutations.append(args)
        return head + "\tref" if args[:2] == ["git", "ls-remote"] else ""

    def gh(args):
        if args[0] == "api":
            if "/git/commits/" in args[1]:
                return {"tree": {"sha": delivery.git(project, "rev-parse", head + "^{tree}")}}
            if "/issues/" in args[1]:
                return dict(row)
            return {"status": "ahead"}
        return [pr] if args[1] == "list" else pr

    monkeypatch.setattr(delivery, "mutate", mutate)
    monkeypatch.setattr(delivery, "gh", gh)
    with pytest.raises(ValueError, match="allow_close: true"):
        delivery.deliver(
            project,
            saved["id"],
            dict(repository="example/repo", base="main", allow_push=True, allow_close="true", required_checks=["CI"]),
            True,
        )
    assert not any(args[:3] == ["gh", "issue", "close"] for args in mutations)


def test_delivery_rejects_corrupt_local_gate_before_remote_access(project, monkeypatch):
    assert invoke(project).returncode == 0
    saved, path = state(project)
    saved["items"][0]["evidence"]["gates"][0]["command"] = "true"
    delivery.atomic(path, saved)

    def forbidden(*args):
        pytest.fail("Corrupt local evidence reached remote access")

    monkeypatch.setattr(delivery, "gh", forbidden)
    monkeypatch.setattr(delivery, "mutate", forbidden)
    with pytest.raises(ValueError, match="frozen validation"):
        delivery.deliver(project, saved["id"], {"repository": "example/repo", "base": "main"}, True)


def test_sync_rejects_modified_frozen_plan(project):
    result = intake.synchronize(project, intake.local_items(project.parent / "plan.yaml"), {})
    path = __import__("pathlib").Path(result["plan"])
    data = yaml.safe_load(path.read_text())
    data["tasks"][0]["files_expected"] = ["unreviewed"]
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="Frozen plan"):
        intake.synchronize(project, intake.local_items(project.parent / "plan.yaml"), {})
    attempted = invoke(project, "--plan", str(path))
    assert attempted.returncode == 2
    assert "Frozen plan" in attempted.stderr


def test_sync_recovers_when_registry_write_is_interrupted(project, monkeypatch):
    path = project.parent / "plan.yaml"
    first = intake.synchronize(project, intake.local_items(path), {})
    data = yaml.safe_load(path.read_text())
    data["tasks"][0]["goal"] = "Updated requirement"
    path.write_text(yaml.safe_dump(data))
    original = intake.atomic

    def interrupted(destination, value):
        if destination.name == "sources.json":
            raise OSError("simulated interruption before registry commit")
        original(destination, value)

    monkeypatch.setattr(intake, "atomic", interrupted)
    with pytest.raises(OSError):
        intake.synchronize(project, intake.local_items(path), {})
    monkeypatch.setattr(intake, "atomic", original)
    recovered = intake.synchronize(project, intake.local_items(path), {})
    assert recovered == intake.synchronize(project, intake.local_items(path), {})
    registry = json.loads((intake.location(project) / "sources.json").read_text())
    assert len(registry) == 1
    assert next(iter(registry.values()))["history"] == [first["items"][0]["revision"]]
