"""Explicit remote delivery. Preparing is read-only; mutations require policy + --execute.

Local integration and remote merge/closure are separate recorded dispositions.
Every mutating retry starts by rediscovering remote state.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid

from .intake import gh
from .supervisor import atomic, digest, git, location, locked


def mutate(argv):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise ValueError(f"Remote operation failed: {' '.join(argv[:3])}: {result.stderr.strip()}")
    return result.stdout.strip()


def require(policy, capability):
    if policy.get("allow_" + capability) is not True:
        raise ValueError(f"Remote {capability} requires allow_{capability}: true in reviewed delivery policy")


def checked_merge(pr, head, base, required):
    if pr.get("headRefOid") != head or pr.get("baseRefName") != base:
        raise ValueError("PR head/base differs from validated delivery candidate")
    checks = {}
    for check in pr.get("statusCheckRollup") or []:
        name = check.get("name") or check.get("context")
        result = check.get("conclusion") or check.get("state")
        checks.setdefault(name, []).append(result)
    if not required or any(not checks.get(name) or any(value != "SUCCESS" for value in checks[name]) for name in required):
        raise ValueError("Required remote checks missing, pending, or failing; await successful checks on exact PR head")


def deliver(project, run_id, policy, execute=False):
    if str(uuid.UUID(run_id)) != run_id:
        raise ValueError("Invalid run ID")
    repo = policy.get("repository", "")
    base = policy.get("base", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or not base or base.startswith("-"):
        raise ValueError("Delivery policy requires repository owner/name and base branch")
    control = location(project)
    with locked(control):
        directory = control / run_id
        state = json.loads((directory / "run.json").read_text())
        if any(item["phase"] != "resolved" for item in state["items"]):
            raise ValueError("All selected items must have verified local integration before remote delivery")
        head = git(project, "rev-parse", state["branch"])
        candidates = [item["evidence"]["candidate"] for item in state["items"]]
        if head not in candidates:
            raise ValueError("Local integration branch changed since validation")
        for candidate in candidates:
            git(project, "merge-base", "--is-ancestor", candidate, head)
        branch = state["branch"].removeprefix("refs/heads/")
        result = dict(
            run_id=run_id,
            phase="prepared",
            repository=repo,
            base=base,
            head=head,
            branch=branch,
            policy_version=digest(policy),
            next_action="Review delivery policy and invoke deliver --execute when authorized.",
        )
        atomic(directory / "delivery-plan.json", result)
        if not execute:
            return result
        require(policy, "push")
        remote = f"https://github.com/{repo}.git"
        # Push exact frozen SHA, without force; retries are naturally idempotent.
        mutate(["git", "-C", str(project), "push", remote, f"{head}:refs/heads/{branch}"])
        observed = mutate(["git", "ls-remote", remote, f"refs/heads/{branch}"]).split()
        if not observed or observed[0] != head:
            raise ValueError("Remote push verification failed; inspect remote branch")
        prs = gh(["pr", "list", "--repo", repo, "--head", branch, "--base", base, "--state", "all", "--json", "number,headRefOid,state"])
        if len(prs) > 1:
            raise ValueError("Multiple matching PRs; reconcile remote ambiguity")
        if not prs:
            require(policy, "pr")
            # Persist intent before remote side effects; rediscovery handles lost responses.
            result["phase"] = "creating_pr"
            atomic(directory / "delivery.json", result)
            mutate(
                [
                    "gh",
                    "pr",
                    "create",
                    "--repo",
                    repo,
                    "--head",
                    branch,
                    "--base",
                    base,
                    "--title",
                    f"Roadrunner verified run {run_id}",
                    "--body",
                    f"Validated local integration at {head}. Run {run_id}; policy {state['gate_version']}.",
                ]
            )
            prs = gh(
                ["pr", "list", "--repo", repo, "--head", branch, "--base", base, "--state", "all", "--json", "number,headRefOid,state"]
            )
            if len(prs) != 1:
                raise ValueError("PR creation outcome ambiguous; inspect remote state before retry")
        number = str(prs[0]["number"])
        fields = "number,url,headRefOid,baseRefName,state,mergeCommit,mergedAt,statusCheckRollup"
        pr = gh(["pr", "view", number, "--repo", repo, "--json", fields])
        result.update(
            phase="awaiting_merge",
            pr=pr["url"],
            number=number,
            next_action="Wait for required checks and authorize merge; PR creation is not resolution.",
        )
        atomic(directory / "delivery.json", result)
        checked_merge(pr, head, base, policy.get("required_checks", []))
        if pr.get("state") != "MERGED":
            if pr.get("state") != "OPEN":
                raise ValueError("PR closed without merge; inspect and reopen explicitly")
            remote_base = gh(["api", f"repos/{repo}/commits/{base}"])["sha"]
            if remote_base != state["base"]:
                raise ValueError("Remote base changed since local validation; rebuild and revalidate before merging")
            require(policy, "merge")
            mutate(["gh", "pr", "merge", number, "--repo", repo, "--squash", "--match-head-commit", head])
            pr = gh(["pr", "view", number, "--repo", repo, "--json", fields])
        if pr.get("state") != "MERGED" or not pr.get("mergeCommit", {}).get("oid"):
            raise ValueError("PR is not verifiably merged; awaiting merge remains unfinished")
        checked_merge(pr, head, base, policy.get("required_checks", []))
        merged = pr["mergeCommit"]["oid"]
        remote_commit = gh(["api", f"repos/{repo}/git/commits/{merged}"])
        if remote_commit.get("tree", {}).get("sha") != git(project, "rev-parse", head + "^{tree}"):
            raise ValueError("Remote merge tree differs from validated candidate; revalidate before source resolution")
        comparison = gh(["api", f"repos/{repo}/compare/{merged}...{base}"])
        if comparison.get("status") not in ("ahead", "identical"):
            raise ValueError("Merge commit is not reachable from remote base; do not close sources")
        result.update(
            phase="merged", merge_commit=merged, next_action="Source closure requires explicit policy and matching source revisions."
        )
        atomic(directory / "delivery.json", result)
        if policy.get("allow_close"):
            closures = []
            for item in state["items"]:
                task = item["task"]
                source = task.get("source_id", "")
                if not source.startswith(f"github:{repo}#"):
                    continue
                issue = source.rsplit("#", 1)[1]
                row = gh(["api", f"repos/{repo}/issues/{issue}"])
                revision = digest({k: row.get(k) for k in ("id", "updated_at", "title", "body", "state")})
                if row["state"] == "closed":
                    # An externally closed issue is not proof that our merge resolved it.
                    closures.append(dict(source_id=source, disposition="externally_closed"))
                    continue
                if revision != task.get("source_revision"):
                    raise ValueError(f"Source {source} changed after selection; review before closure")
                mutate(["gh", "issue", "close", issue, "--repo", repo, "--reason", "completed"])
                if gh(["api", f"repos/{repo}/issues/{issue}"]).get("state") != "closed":
                    raise ValueError(f"Closure verification failed: {source}")
                closures.append(dict(source_id=source, disposition="closed_after_verified_merge"))
                result["closures"] = closures
                atomic(directory / "delivery.json", result)
            result.update(phase="merged_sources_reconciled", closures=closures, next_action=None)
            atomic(directory / "delivery.json", result)
        return result


def main(argv):
    parser = argparse.ArgumentParser(prog="roadrunner deliver")
    parser.add_argument("--project", default=".")
    parser.add_argument("--run", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = deliver(Path(args.project).resolve(), args.run, json.loads(Path(args.policy).read_text()), args.execute)
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({"phase": "blocked", "next_action": str(exc)}), file=sys.stderr)
        return 2
