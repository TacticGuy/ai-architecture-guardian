from __future__ import annotations

import json

from scripts.export_v5_files import main


def _sample(root, repo, number, label):
    folder = root / repo.replace("/", "__") / str(number)
    folder.mkdir(parents=True)
    (folder / "diff.patch").write_text(f"+change {number}\n", encoding="utf-8")
    (folder / "metadata.json").write_text(json.dumps({
        "sample_id": f"{repo}#{number}", "repo": repo, "pr_number": number, "title": "t",
        "merged_at": "2022-01-01T00:00:00+00:00", "before_commit_sha": "a" * 40, "merge_commit_sha": "b" * 40,
        "changed_python_files": ["pkg/x.py"], "touched_modules": ["pkg.x"], "label": label,
        "label_protocol": "future_coupling_v1", "diff_path": "diff.patch"}), encoding="utf-8")


def test_manifest_and_diffs_follow_the_saved_split(tmp_path):
    data = tmp_path / "samples"
    _sample(data, "o/a", 1, 0)
    _sample(data, "o/b", 2, 1)
    split = tmp_path / "split.json"
    split.write_text(json.dumps({"train": ["o/a"], "validation": [], "test": ["o/b"]}), encoding="utf-8")
    assert main(["--data-dir", str(data), "--out-dir", str(tmp_path / "out"), "--split", str(split)]) == 0
    rows = [json.loads(line) for line in (tmp_path / "out/v5_manifest.jsonl").read_text().splitlines()]
    assert {(row["sample_id"], row["split"], row["label"], row["number"]) for row in rows} == {
        ("o/a#1", "train", 0, 1), ("o/b#2", "test", 1, 2)}
    diffs = {json.loads(line)["sample_id"]: json.loads(line)["diff"]
             for line in (tmp_path / "out/diffs_v5.jsonl").read_text().splitlines()}
    assert diffs == {"o/a#1": "+change 1\n", "o/b#2": "+change 2\n"}


def test_refuses_a_split_that_misses_a_repository(tmp_path):
    data = tmp_path / "samples"
    _sample(data, "o/a", 1, 0)
    split = tmp_path / "split.json"
    split.write_text(json.dumps({"train": [], "validation": [], "test": []}), encoding="utf-8")
    try:
        main(["--data-dir", str(data), "--out-dir", str(tmp_path / "out"), "--split", str(split)])
    except SystemExit as exc:
        assert "o/a" in str(exc)
    else:
        raise AssertionError("expected SystemExit")
