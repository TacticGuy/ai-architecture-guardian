from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script():
    spec = importlib.util.spec_from_file_location(
        "build_pr_dataset", ROOT / "scripts" / "build_pr_dataset.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_records(path: Path) -> None:
    path.write_text(
        "\n".join(
            json.dumps({
                "pr_id": f"org/repo#{number}",
                "repo": "org/repo",
                "pr_number": number,
                "merge_commit_sha": str(number) * 40,
            })
            for number in (1, 2, 3)
        ) + "\n",
        encoding="utf-8",
    )


def test_batch_limits_work_skips_existing_and_records_failures(tmp_path, monkeypatch, capsys):
    script = load_script()
    raw = tmp_path / "raw.jsonl"
    clone = tmp_path / "clone"
    output = tmp_path / "samples"
    (clone / ".git").mkdir(parents=True)
    write_records(raw)
    existing = output / "org__repo" / "1"
    existing.mkdir(parents=True)
    (existing / "metadata.json").write_text("{}", encoding="utf-8")

    def fake_build(pr, repository_path, output_root, analysis_settings):
        if pr["pr_number"] == 3:
            raise RuntimeError("unavailable commit")
        destination = output_root / "org__repo" / str(pr["pr_number"])
        destination.mkdir(parents=True)
        (destination / "metadata.json").write_text("{}", encoding="utf-8")
        return {"sample_id": pr["pr_id"], "label": 0}

    monkeypatch.setattr(script, "build_pr_sample", fake_build)
    status = script.main([
        "--repo", "org/repo", "--max-samples", "2", "--raw", str(raw),
        "--repository-path", str(clone), "--output-dir", str(output),
    ])

    assert status == 1
    summary = json.loads((output / "org__repo" / "last_run.json").read_text(encoding="utf-8"))
    assert summary["attempted"] == 2
    assert summary["built"] == 1
    assert summary["skipped"] == 1
    assert summary["failed"] == 1
    assert summary["failures"][0]["pr_id"] == "org/repo#3"
    printed = capsys.readouterr().out
    assert "Skipped existing: org/repo#1" in printed
    assert "Built: org/repo#2 label=0" in printed
    assert "Failed: org/repo#3" in printed


def test_missing_clone_explains_how_to_create_it(tmp_path, capsys):
    script = load_script()
    status = script.main([
        "--repo", "org/repo", "--raw", str(tmp_path / "missing.jsonl"),
        "--repository-path", str(tmp_path / "missing-clone"),
    ])
    assert status == 2
    assert "clone_repositories.py --repo org/repo" in capsys.readouterr().out
