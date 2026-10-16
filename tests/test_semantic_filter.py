from src.filtering.semantic_filter import semantic_filter

KEYWORDS = ["refactor", "architecture", "decouple", "circular import"]


def test_title_body_and_commit_messages_are_searched_case_insensitively():
    passed, matched = semantic_filter({"title": "REFACTOR service", "body": "Architecture notes", "commit_messages": ["Decouple the cache"]}, KEYWORDS)
    assert passed and matched == ["refactor", "architecture", "decouple"]


def test_no_keyword_fails():
    assert semantic_filter({"title": "Fix typo in documentation", "body": None, "commit_messages": []}, KEYWORDS) == (False, [])


def test_generated_details_and_commit_bodies_do_not_create_keyword_matches():
    pr = {
        "title": "Bump actions/setup-python from 5 to 6",
        "body": "Dependency update\n<details><summary>Release notes</summary>Architecture rewrite</details>",
        "commit_messages": ["Bump dependency\nArchitecture notes copied from upstream"],
    }
    assert semantic_filter(pr, KEYWORDS) == (False, [])


def test_keywords_match_complete_terms_not_larger_words():
    assert semantic_filter(
        {"title": "Update refactored helper", "body": "", "commit_messages": []}, KEYWORDS
    ) == (False, [])

