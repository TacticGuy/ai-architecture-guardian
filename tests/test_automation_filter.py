import pytest

from src.filtering.automation_filter import is_automated_pr


@pytest.mark.parametrize("author", ["dependabot", "dependabot[bot]", "renovate[bot]", "release-bot[bot]"])
def test_known_and_github_bot_accounts_are_automated(author):
    assert is_automated_pr({"author": author}) is True


@pytest.mark.parametrize("author", ["alice", "architecture-team", None])
def test_human_or_missing_authors_are_not_assumed_to_be_bots(author):
    assert is_automated_pr({"author": author}) is False
