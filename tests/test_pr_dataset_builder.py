from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from src.dataset.builder import DatasetSampleExcluded, build_pr_sample
from src.ml.hetero_data import load_hetero_data


def git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def repository_with_new_cycle(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "repo"
    repository.mkdir()
    git(repository, "init", "-b", "main")
    git(repository, "config", "user.name", "Dataset Test")
    git(repository, "config", "user.email", "dataset@example.test")

    package = repository / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "a.py").write_text("from pkg import b\n", encoding="utf-8")
    (package / "b.py").write_text("VALUE = 1\n", encoding="utf-8")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "base")

    git(repository, "switch", "-c", "feature")
    (package / "b.py").write_text("from pkg import a\nVALUE = 1\n", encoding="utf-8")
    git(repository, "add", "pkg/b.py")
    git(repository, "commit", "-m", "introduce cycle")

    git(repository, "switch", "main")
    (repository / "README.md").write_text("main\n", encoding="utf-8")
    git(repository, "add", "README.md")
    git(repository, "commit", "-m", "main work")
    git(repository, "merge", "--no-ff", "feature", "-m", "merge feature")
    return repository, git(repository, "rev-parse", "HEAD")


def analysis_settings() -> dict:
    return {
        "include_tests": False,
        "max_python_files_per_repository": 50,
        "excluded_directory_names": [".git", "__pycache__"],
        "excluded_file_names": [],
    }


def test_builds_complete_positive_graph_pair_sample(tmp_path):
    repository, merge_sha = repository_with_new_cycle(tmp_path)
    output = tmp_path / "samples"
    metadata = build_pr_sample(
        {"repo": "example/project", "pr_number": 7, "merge_commit_sha": merge_sha},
        repository,
        output,
        analysis_settings(),
    )
    sample = output / "example__project" / "7"

    assert metadata["sample_id"] == "example/project#7"
    assert metadata["label"] == 1
    assert metadata["changed_python_files"] == ["pkg/b.py"]
    assert metadata["metrics_path"] == "metrics.json"
    assert (sample / "diff.patch").is_file()
    assert load_hetero_data(sample / "before/graph.pt").schema_version == 1
    assert load_hetero_data(sample / "after/graph.pt").schema_version == 1

    label = json.loads((sample / "label.json").read_text(encoding="utf-8"))
    assert label["reason"] == "new_dependency_cycle"
    assert label["new_cycles"] == [["pkg.a", "pkg.b"]]
    assert label["touched_modules"] == ["pkg.b"]

    metrics = json.loads((sample / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["delta"]["internal_import_edge_count"] == 1
    assert metrics["delta"]["cyclic_component_count"] == 1
    assert metrics["before"]["module_count"] == metrics["after"]["module_count"] == 3


def test_excludes_pr_without_python_changes_before_creating_output(tmp_path):
    repository, _ = repository_with_new_cycle(tmp_path)
    git(repository, "switch", "-c", "docs-only")
    (repository / "README.md").write_text("documentation\n", encoding="utf-8")
    git(repository, "add", "README.md")
    git(repository, "commit", "-m", "docs")
    docs_sha = git(repository, "rev-parse", "HEAD")
    output = tmp_path / "samples-no-python"

    with pytest.raises(DatasetSampleExcluded, match="changes no Python files"):
        build_pr_sample(
            {"repo": "org/repo", "pr_number": 2, "merge_commit_sha": docs_sha},
            repository,
            output,
            analysis_settings(),
        )
    assert not (output / "org__repo" / "2").exists()
