"""Radon / pylint / hotspot runner for Mandatory 3."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("radon")
pytest.importorskip("pylint")

from scripts.run_tool_metrics_v5 import main, pylint_metrics, radon_metrics, write_as_packages  # noqa: E402
from src.dataset.pr_history import merged_prs_from_history  # noqa: E402
from tests.test_future_coupling import commit, history_repo  # noqa: E402,F401  (fixture)


def test_radon_counts_complexity_and_lines():
    metrics = radon_metrics({"a.py": "def f(x):\n    if x:\n        return 1\n    return 2\n", "gone.py": None})
    assert metrics["max_cc"] == 2.0 and metrics["blocks"] == 1.0 and metrics["sloc"] == 4.0


def test_stdlib_named_project_file_does_not_hang_pylint(tmp_path):
    """aiohttp's ``abc.py`` imports the standard ``abc``; written as a package module it finishes."""
    sources = {"pkg/abc.py": "from abc import ABC\n\n\nclass Base(ABC):\n    pass\n"}
    assert sorted(Path(p).relative_to(tmp_path).as_posix() for p in write_as_packages(tmp_path, sources)) == ["pkg/abc.py"]
    assert (tmp_path / "pkg/__init__.py").is_file()
    metrics = pylint_metrics(sources)
    assert metrics["score"] is not None and metrics["error"] == 0.0


def test_runner_writes_one_line_per_pr_and_resumes(history_repo, tmp_path):  # noqa: F811
    commit(history_repo, {"pkg/e.py": "import pkg.b\n\n\ndef g(x):\n    if x:\n        return 1\n    return 0\n"},
           "Add e (#4)", "2021-11-15T10:00:00+00:00")
    pr = {p.number: p for p in merged_prs_from_history(history_repo)}[4]
    clones = tmp_path / "clones"
    clones.mkdir()
    import subprocess
    subprocess.run(["git", "clone", "-q", str(history_repo), str(clones / "o__r")], check=True)
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(json.dumps({"sample_id": "o/r#4", "repo": "o/r", "split": "test", "merged_at": pr.merged_at,
                                    "before_commit_sha": pr.before_sha, "merge_commit_sha": pr.merge_sha,
                                    "changed_python_files": ["pkg/e.py"]}) + "\n", encoding="utf-8")
    output = tmp_path / "tools.jsonl"
    args = ["--manifest", str(manifest), "--clones", str(clones), "--output", str(output), "--workers", "1"]
    assert main(args) == 0
    [row] = [json.loads(line) for line in output.read_text().splitlines()]
    assert row["sample_id"] == "o/r#4" and row["radon.max_cc"] == 2.0 and row["radon.delta_sloc"] > 0
    assert row["pylint.score"] is not None and "hotspot.change_frequency" in row
    assert main(args) == 0 and len(output.read_text().splitlines()) == 1        # resumed: nothing new
    assert json.loads(output.with_suffix(".meta.json").read_text())["tools"]["radon"] != "missing"
