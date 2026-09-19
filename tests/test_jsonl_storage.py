from __future__ import annotations
from src.storage.jsonl import JSONLAppender, iter_jsonl


def test_jsonl_append_and_duplicate_detection(tmp_path):
    path = tmp_path / "records.jsonl"
    writer = JSONLAppender(path)
    assert writer.append({"pr_id": "org/repo#1", "title": "one"})
    assert not writer.append({"pr_id": "org/repo#1", "title": "duplicate"})
    assert list(iter_jsonl(path)) == [{"pr_id": "org/repo#1", "title": "one"}]

