from __future__ import annotations

import json

from scripts.build_future_pr_dataset import main


def test_existing_sample_cannot_silently_keep_a_stale_label(tmp_path, capsys):
    record = {
        "repo": "org/repo", "pr_number": 1, "sample_id": "org/repo#1",
        "merged_at": "2021-01-01T00:00:00Z", "label": 1,
        "merge_commit_sha": "a" * 40, "label_protocol_version": 3,
        "changed_python_files": ["pkg/service.py"],
    }
    labels = tmp_path / "labels.jsonl"
    labels.write_text(json.dumps(record) + "\n", encoding="utf-8")
    root = tmp_path / "samples"
    folder = root / "org__repo" / "1"
    folder.mkdir(parents=True)
    saved = {**record, "label": 0, "before_graph_path": "graph.pt"}
    metadata = folder / "metadata.json"
    metadata.write_text(json.dumps(saved), encoding="utf-8")
    (folder / "graph.pt").touch()
    result = main(["--labels", str(labels), "--output-dir", str(root)])
    assert result == 1
    assert "Stale sample" in capsys.readouterr().out
    assert json.loads(metadata.read_text(encoding="utf-8"))["label"] == 0
