"""Read-only preflight for an existing project and reviewed run policy."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from .supervisor import execute, git, load_policy, location


def main(argv):
    parser = argparse.ArgumentParser(prog="roadrunner doctor")
    parser.add_argument("--project", default=".")
    parser.add_argument("--policy", required=True)
    args = parser.parse_args(argv)
    checks = []
    try:
        project = Path(args.project).resolve()
        policy = load_policy(Path(args.policy))
        checks.append(dict(check="git", value=git(project, "rev-parse", "HEAD")))
        checks.append(dict(check="state_storage", value=str(location(project)), writable=os.access(location(project).parent, os.W_OK)))
        checks.append(dict(check="validation", value=policy["validation_commands"], protected=policy["protected_paths"]))
        if policy["adapter"] == "claude":
            if not shutil.which("claude"):
                raise ValueError("Install Claude Code and authenticate before running")
            version = subprocess.run(["claude", "--version"], text=True, capture_output=True, timeout=10)
            if version.returncode:
                raise ValueError("Claude adapter version check failed")
            checks.append(dict(check="adapter_version", value=version.stdout.strip()))
            auth = subprocess.run(["claude", "auth", "status"], text=True, capture_output=True, timeout=10)
            if auth.returncode:
                raise ValueError("Claude authentication unavailable; run claude auth login")
            checks.append(dict(check="authentication", value="available; canary still required"))
        with tempfile.TemporaryDirectory(prefix="roadrunner-doctor-") as temporary:
            root = Path(temporary).resolve()
            work = root / "worker"
            scratch = root / "scratch"
            work.mkdir()
            scratch.mkdir()
            log = root / "probe.log"
            code = execute(["/usr/bin/true"], work, scratch, policy, time.time() + 5, log, dict(os.environ))
            if code:
                raise ValueError("Worker isolation probe failed: " + log.read_text())
        checks.append(dict(check="isolation", value=policy["sandbox"]))
        print(json.dumps(dict(outcome="ready_for_canary", checks=checks), indent=2))
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps(dict(outcome="blocked", checks=checks, next_action=str(exc)), indent=2))
        return 2
