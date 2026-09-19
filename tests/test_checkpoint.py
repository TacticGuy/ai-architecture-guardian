from __future__ import annotations
from src.scraper.checkpoint import CheckpointStore


def test_checkpoint_persists_and_resets(tmp_path):
    path = tmp_path / "checkpoint.json"
    checkpoint = CheckpointStore(path)
    checkpoint.update("org/repo", "abc", False)
    assert CheckpointStore(path).get("org/repo") == {"cursor": "abc", "completed": False}
    checkpoint.reset()
    assert CheckpointStore(path).get("org/repo")["completed"] is False

