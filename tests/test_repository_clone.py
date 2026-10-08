from __future__ import annotations

from src.repository.clone import clone_destination, repository_id


def test_clone_destination_is_nested_and_stable(tmp_path):
    repository = {"owner": "example-org", "name": "example_repo"}
    assert repository_id(repository) == "example-org/example_repo"
    assert clone_destination(tmp_path, repository) == tmp_path / "example-org" / "example_repo"
