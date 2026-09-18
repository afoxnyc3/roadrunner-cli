"""Read-only backlog synchronization with stable source identity and frozen plans."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

import yaml

from .supervisor import atomic, digest, location, locked, relative_path


def gh(arguments):
    result = subprocess.run(["gh", *arguments], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError(f"GitHub read failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def local_items(path):
    text = path.read_text()
    if path.suffix.lower() in (".md", ".markdown"):
        blocks = re.findall(r"```(?:yaml|yml)\s*\n(.*?)\n```", text, re.S)
        if len(blocks) != 1:
            raise ValueError("Markdown roadmap requires one fenced YAML tasks block with stable IDs")
        text = blocks[0]
    data = yaml.safe_load(text)
    if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
        raise ValueError("Roadmap requires a tasks list")
    result = []
    for task in data["tasks"]:
        if not isinstance(task, dict) or not re.fullmatch(r"[A-Z]+-\d+", str(task.get("id", ""))):
            raise ValueError("Every roadmap item needs a stable ID such as TASK-001")
        source_id = path.as_uri() + "#" + task["id"]
        result.append(dict(source_id=source_id, revision=digest(task), task=dict(task), external_state="open"))
    return result


def github_items(repo, issues, label=None, milestone=None):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("GitHub repository must be owner/repository")
    if issues:
        rows = [gh(["api", f"repos/{repo}/issues/{number}"]) for number in issues]
    else:
        arguments = ["api", "--paginate", "--slurp", "-X", "GET", f"repos/{repo}/issues", "-f", "state=all", "-f", "per_page=100"]
        if label:
            arguments += ["-f", "labels=" + label]
        if milestone:
            arguments += ["-f", "milestone=" + milestone]
        rows = [row for page in gh(arguments) for row in page]
    result = []
    for row in rows:
        if "pull_request" in row:
            continue
        result.append(
            dict(
                source_id=f"github:{repo}#{row['number']}",
                revision=digest({k: row.get(k) for k in ("id", "updated_at", "title", "body", "state")}),
                external_state=row["state"],
                url=row["html_url"],
                task=dict(
                    id=f"GH-{row['number']}",
                    title=row["title"],
                    goal=row.get("body") or "",
                    acceptance_criteria=[],
                    files_expected=[],
                    depends_on=[],
                ),
            )
        )
    return result


def synchronize(project, rows, rules):
    if len({row["source_id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate source IDs in selection")
    ids = [row["task"]["id"] for row in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate normalized task IDs; select one repository or disambiguate local IDs")
    control = location(project)
    with locked(control):
        registry_path = control / "sources.json"
        registry = json.loads(registry_path.read_text()) if registry_path.exists() else {}
        tasks = []
        for row in sorted(rows, key=lambda row: row["source_id"]):
            source_id = row["source_id"]
            previous = registry.get(source_id)
            task = row["task"]
            # Issue descriptions and source shell commands never set execution policy.
            task.pop("validation_commands", None)
            task.pop("status", None)
            rule = rules.get(source_id, {})
            for key in ("goal", "acceptance_criteria", "files_expected", "depends_on", "priority"):
                if key in rule:
                    task[key] = rule[key]
            task["files_expected"] = [relative_path(p) for p in task.get("files_expected", [])]
            changed = previous is not None and previous["revision"] != row["revision"]
            disposition = "ready"
            action = None
            if row["external_state"] == "closed":
                disposition, action = "externally_closed", "Review external closure; it is not Roadrunner resolution evidence."
            elif changed or (previous and previous.get("disposition") == "needs_review"):
                disposition, action = "needs_review", "Source changed or reopened. Review updated scope and acceptance criteria."
            elif not task.get("goal") or not task.get("acceptance_criteria") or not task.get("files_expected"):
                disposition, action = "needs_input", "Provide goal, acceptance criteria, and file scope in the reviewed intake rules."
            # A reviewed matching source revision acknowledges an edit/reopen.
            if disposition == "needs_review" and rule.get("approved_revision") == row["revision"]:
                disposition, action = "ready", None
            task.update(
                status="todo",
                source_id=source_id,
                source_revision=row["revision"],
                source_disposition=disposition,
                source_next_action=action,
            )
            tasks.append(task)
            history = list(previous.get("history", [])) if previous else []
            if changed:
                history.append(previous["revision"])
            registry[source_id] = dict(
                revision=row["revision"],
                external_state=row["external_state"],
                disposition=disposition,
                history=history,
                task_id=task["id"],
                next_action=action,
            )
        plan = {"tasks": tasks}
        plan_id = digest(plan)
        plans = control / "plans"
        plans.mkdir(exist_ok=True)
        destination = plans / (plan_id + ".yaml")
        if not destination.exists():
            destination.write_text(yaml.safe_dump(plan, sort_keys=False))
        atomic(registry_path, registry)
        return dict(
            plan=str(destination),
            plan_id=plan_id,
            selected=len(tasks),
            items=[
                {
                    "source_id": t["source_id"],
                    "revision": t["source_revision"],
                    "disposition": t["source_disposition"],
                    "next_action": t["source_next_action"],
                }
                for t in tasks
            ],
        )


def main(argv):
    parser = argparse.ArgumentParser(prog="roadrunner sync")
    parser.add_argument("--project", default=".")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--roadmap")
    source.add_argument("--github")
    parser.add_argument("--issue", type=int, action="append")
    parser.add_argument("--label")
    parser.add_argument("--milestone")
    parser.add_argument("--rules", help="Reviewed JSON map keyed by stable source ID")
    args = parser.parse_args(argv)
    try:
        rules = json.loads(Path(args.rules).read_text()) if args.rules else {}
        rows = (
            local_items(Path(args.roadmap).resolve()) if args.roadmap else github_items(args.github, args.issue, args.label, args.milestone)
        )
        result = synchronize(Path(args.project).resolve(), rows, rules)
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
