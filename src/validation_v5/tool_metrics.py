"""Established code-quality tools as per-PR baselines (Mandatory 3), output contract in the v5 brief §2.2.

Every number uses only what existed before the merge: the touched production files at
``before_commit_sha`` and the same files with the PR applied (``merge_commit_sha``), read with
``git show <sha>:<path>``, and, for the hotspot, commits reachable from ``before_commit_sha`` in
the 182 days before ``merged_at``. Deltas are after - before. A value is ``None`` (JSON null)
when the tool failed or the number is undefined (e.g. a mean over no functions).
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Iterable

from radon.complexity import cc_visit
from radon.metrics import mi_visit
from radon.raw import analyze

HOTSPOT_WINDOW_DAYS = 182
PYLINT_TIMEOUT = 120
PYLINT_CATEGORIES = ("convention", "refactor", "warning", "error")
Files = dict[str, str]  # relative path -> source text


class ToolError(RuntimeError):
    """A tool could not produce numbers for this sample."""


# ---------------------------------------------------------------- reading files at a commit

def git_show(repository: Path, sha: str, path: str) -> str | None:
    """File contents at ``sha``, or None when the file does not exist there (added or deleted by the PR)."""
    result = subprocess.run(["git", "-C", str(repository), "show", f"{sha}:{path}"], capture_output=True)
    return result.stdout.decode("utf-8", errors="replace") if result.returncode == 0 else None


def read_side(repository: Path, sha: str, paths: Iterable[str]) -> Files:
    files = {}
    for path in paths:
        text = git_show(repository, sha, path)
        if text is not None:
            files[path] = text
    return files


# ---------------------------------------------------------------- radon

def radon_side(files: Files) -> dict[str, Any]:
    """Cyclomatic complexity over functions and methods, mean maintainability index per file, SLOC."""
    complexities, mis, sloc, unparsed = [], [], 0, 0
    for text in files.values():
        try:
            blocks = cc_visit(text)
            mi = mi_visit(text, True)
            raw = analyze(text)
        except (SyntaxError, ValueError, TypeError):
            unparsed += 1
            continue
        # cc_visit lists each method twice (inside its class and on its own); keep function blocks only.
        complexities += [block.complexity for block in blocks if type(block).__name__ == "Function"]
        mis.append(mi)
        sloc += raw.sloc
    return {"mean_cc": sum(complexities) / len(complexities) if complexities else None,
            "max_cc": max(complexities, default=0) if mis else None,
            "total_cc": sum(complexities) if mis else None,
            "mean_mi": sum(mis) / len(mis) if mis else None,
            "sloc": sloc if mis or not files else None,
            "unparsed_files": unparsed}


def radon_metrics(before: Files, after: Files) -> dict[str, Any]:
    old, new = radon_side(before), radon_side(after)
    row = {f"radon.{key}": new[key] for key in ("mean_cc", "max_cc", "mean_mi", "sloc")}
    for key in ("mean_cc", "max_cc", "mean_mi", "sloc"):
        # A side with no files (all touched files added, or all deleted) counts as zero size and
        # complexity; means over nothing stay undefined.
        empty = {"max_cc": 0, "sloc": 0}
        left = old[key] if old[key] is not None or before else empty.get(key)
        right = new[key] if new[key] is not None or after else empty.get(key)
        row[f"radon.delta_{key}"] = right - left if left is not None and right is not None else None
    row["radon.unparsed_files"] = old["unparsed_files"] + new["unparsed_files"]
    return row


# ---------------------------------------------------------------- pylint

def pylint_metrics(after: Files, sloc: int | None, python: str = sys.executable,
                   timeout: int = PYLINT_TIMEOUT) -> dict[str, Any]:
    """Score, message counts per category, R09xx design checks and refactor messages per KLOC."""
    keys = ("score", *PYLINT_CATEGORIES, "design", "refactor_per_kloc")
    if not after:
        return {f"pylint.{key}": None for key in keys}
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        for path, text in after.items():
            target = root / "src" / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        (root / "empty.rc").write_text("", encoding="utf-8")
        try:
            result = subprocess.run(
                [python, "-I", "-m", "pylint", "--rcfile", str(root / "empty.rc"), "--output-format=json2",
                 "--disable=import-error,no-name-in-module", "--score=y", *sorted(after)],
                cwd=root / "src", capture_output=True, timeout=timeout,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        except subprocess.TimeoutExpired:
            return {f"pylint.{key}": None for key in keys}
    try:
        report = json.loads(result.stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {f"pylint.{key}": None for key in keys}
    return parse_pylint(report, sloc)


def parse_pylint(report: dict[str, Any], sloc: int | None) -> dict[str, Any]:
    messages = report.get("messages", [])
    row: dict[str, Any] = {"pylint.score": report.get("statistics", {}).get("score")}
    for category in PYLINT_CATEGORIES:
        row[f"pylint.{category}"] = sum(m["type"] == category for m in messages)
    row["pylint.design"] = sum(m.get("messageId", "").startswith("R09") for m in messages)
    row["pylint.refactor_per_kloc"] = row["pylint.refactor"] / (sloc / 1000) if sloc else None
    return row


# ---------------------------------------------------------------- hotspot

def change_frequency(repository: Path, before_sha: str, merged_at: str, path: str,
                     days: int = HOTSPOT_WINDOW_DAYS) -> int:
    """Commits that touched ``path``, reachable from ``before_sha``, in the ``days`` before ``merged_at``.

    Walking from ``before_sha`` means nothing after the merge (or the PR itself) can be counted.
    """
    since = datetime.fromisoformat(merged_at.replace("Z", "+00:00")) - timedelta(days=days)
    out = subprocess.run(["git", "-C", str(repository), "rev-list", "--count", f"--since={since.isoformat()}",
                          before_sha, "--", path], capture_output=True, text=True)
    if out.returncode:
        raise ToolError(out.stderr.strip())
    return int(out.stdout.strip() or 0)


def hotspot_metrics(repository: Path, sample: dict[str, Any], before: Files) -> dict[str, Any]:
    """CodeScene-style hotspot (Tornhill, *Your Code as a Crime Scene*): change frequency x complexity.

    Per touched file: commits in the window x its total cyclomatic complexity before the PR.
    ``hotspot.score`` is the hottest touched file; a new file has frequency and complexity 0.
    """
    frequencies, products = [], []
    for path in sample["changed_python_files"]:
        frequency = change_frequency(repository, sample["before_commit_sha"], sample["merged_at"], path)
        complexity = radon_side({path: before[path]})["total_cc"] if path in before else 0
        frequencies.append(frequency)
        products.append(frequency * (complexity or 0))
    return {"hotspot.change_frequency": sum(frequencies),
            "hotspot.max_change_frequency": max(frequencies, default=0),
            "hotspot.score": max(products, default=0)}


# ---------------------------------------------------------------- one sample

def measure_sample(repository: Path, sample: dict[str, Any], tools: set[str],
                   python: str = sys.executable) -> dict[str, Any]:
    """All requested local tools (radon, pylint, hotspot) for one manifest row."""
    paths = sample["changed_python_files"]
    before = read_side(repository, sample["before_commit_sha"], paths)
    after = read_side(repository, sample["merge_commit_sha"], paths)
    row: dict[str, Any] = {"sample_id": sample["sample_id"]}
    radon_row = radon_metrics(before, after)
    if "radon" in tools:
        row.update(radon_row)
    if "pylint" in tools:
        row.update(pylint_metrics(after, radon_row["radon.sloc"], python))
    if "hotspot" in tools:
        try:
            row.update(hotspot_metrics(repository, sample, before))
        except ToolError:
            row.update({"hotspot.change_frequency": None, "hotspot.max_change_frequency": None,
                        "hotspot.score": None})
    return row


# ---------------------------------------------------------------- resumable output

def load_rows(path: Path) -> dict[str, dict[str, Any]]:
    """Merge every line of the output by sample_id (later lines add or override keys)."""
    rows: dict[str, dict[str, Any]] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                rows.setdefault(row["sample_id"], {}).update(row)
    return rows


def done(row: dict[str, Any] | None, tool: str) -> bool:
    """A tool is done for a sample once any of its keys was written, even as null (a failure is final)."""
    return bool(row) and any(key.startswith(f"{tool}.") for key in row)


def compact(path: Path) -> int:
    """Rewrite the output as exactly one line per sample (the brief's contract)."""
    rows = load_rows(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("".join(json.dumps(row) + "\n" for row in rows.values()), encoding="utf-8")
    temporary.replace(path)
    return len(rows)
