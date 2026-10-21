"""Repeat-failure signatures (issue #19).

A task that fails validation with the *same* failure and the *same* candidate
diff is making no progress; paying for more attempts is waste. The signature
is a hash of validator output after normalizing volatile fields, paired with a
hash of the candidate diff. A repeat counts only when BOTH are unchanged.

Normalized (extend here, with a test): ISO-8601 timestamps, durations
(``0.42s`` / ``120ms``), temp paths (the first component after the temp dir),
hex addresses, and ``pid N``. Everything else (check name, file names, line
numbers, test names) is kept, so fixing one error and exposing another is not
a repeat. Ported from pi-harness ``orchestrator/failure_sig.sh``.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?"), "<ts>"),
    (re.compile(r"(/private)?/(tmp|var/folders/[^/ ]+/[^/ ]+/T)/[^/ \n]+"), "<tmp>"),
    (re.compile(r"0x[0-9a-fA-F]+"), "<hex>"),
    (re.compile(r"(?<![0-9A-Za-z_.])\d+(\.\d+)?(ms|s)(?![0-9A-Za-z_])"), "<dur>"),
    (re.compile(r"(pid[ =:]?)\d+"), r"\1<n>"),
]


def _h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


def normalize(text: str) -> str:
    for pat, repl in _RULES:
        text = pat.sub(repl, text)
    return text


def failure_sig(results: list[dict]) -> str:
    """Signature of the failed commands in a validation run (command, exit
    code, kind, normalized output). Passing results are ignored."""
    parts = []
    for r in results:
        if r.get("passed"):
            continue
        parts.append(
            f"{r.get('command', '')}\nexit={r.get('returncode')}\nkind={r.get('kind', '')}\n"
            f"{r.get('stdout', '')}\n{r.get('stderr', '')}"
        )
    return _h(normalize("\n--\n".join(parts)))


def diff_sig(cwd: Path) -> str:
    """Hash of the working-tree diff vs HEAD (new files included, bytecode
    excluded so py-compile rewrites do not look like progress)."""
    subprocess.run(["git", "add", "-A", "-N"], cwd=cwd, capture_output=True)
    out = subprocess.run(
        ["git", "diff", "--", ".", ":(exclude)*.pyc", ":(exclude)*/__pycache__/*"],
        cwd=cwd,
        capture_output=True,
    ).stdout
    return hashlib.sha256(out).hexdigest()[:16]


def update_record(prev: dict | None, task_id: str, fsig: str, dsig: str) -> dict:
    """Next ``last_failure`` state record. ``repeats`` counts consecutive
    observations identical to the previous one in both signatures."""
    same = bool(prev) and prev.get("task_id") == task_id and prev.get("failure") == fsig and prev.get("diff") == dsig
    return {
        "task_id": task_id,
        "failure": fsig,
        "diff": dsig,
        "repeats": (prev.get("repeats", 0) + 1) if same else 0,
    }
