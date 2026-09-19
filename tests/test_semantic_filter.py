from src.filtering.semantic_filter import semantic_filter

KEYWORDS = ["refactor", "architecture", "decouple", "circular import"]


def test_title_body_and_commit_messages_are_searched_case_insensitively():
    passed, matched = semantic_filter({"title": "REFACTOR service", "body": "Architecture notes", "commit_messages": ["Decouple the cache"]}, KEYWORDS)
    assert passed and matched == ["refactor", "architecture", "decouple"]


def test_no_keyword_fails():
    assert semantic_filter({"title": "Fix typo in documentation", "body": None, "commit_messages": []}, KEYWORDS) == (False, [])

