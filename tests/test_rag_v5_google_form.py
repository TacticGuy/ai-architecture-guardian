"""Blind survey: readable form content, private key, and the Google Forms export converter."""
from __future__ import annotations

import csv
import json

from scripts.rag_v5_google_form import ROLE_QUESTION, ROWS, YEARS_QUESTION, build, convert, evidence_text, fix_text


def _checkpoint(blank: str | None = None) -> list[dict]:
    records = []
    for number in range(1, 4):
        for mode in ("signature", "text", "none"):
            text = "" if (f"o/r#{number}", mode) == (blank, mode) and mode == "text" else f"{mode} says {number}"
            records.append({"sample_id": f"o/r#{number}", "mode": mode, "evidence_summary": "PR: Fix it. Risk score 0.6 "
                            "(threshold 0.5). Strongest graph edges: a.py:a.f -> CALLS -> b.py:b.g (0.0123)",
                            "answer": {"explanation": text, "suggestion": {"refactoring": "Move g", "steps": ["1. do"]}}})
    return records


def test_only_prs_answered_by_all_three_systems_are_used_and_order_is_hidden():
    prs, key = build(_checkpoint(blank="o/r#2"), count=2, seed=1)
    assert [pr["sample_id"] for pr in prs] == ["o/r#1", "o/r#3"] and key["eligible_prs"] == 2
    for pr in prs:
        assert sorted(key["mapping"][pr["sample_id"]].values()) == ["none", "signature", "text"]
        assert all("says" in explanation["text"] for explanation in pr["explanations"])


def test_evidence_and_fix_are_plain_text():
    text = evidence_text("o/r#7", "PR: Add cache. Risk score 0.62 (threshold 0.44). Strongest graph edges: "
                                  "x/a.py:a.Cache -> CALLS -> x/b.py:b.load (0.0123)")
    assert "https://github.com/o/r/pull/7" in text and "flags it" in text and "a.Cache CALLS b.load (+0.012)" in text
    fix = fix_text({"refactoring": "Extract Function", "files": ["a.py"], "steps": ["1. Move", "2) Test"]})
    assert fix == "Suggested fix: Extract Function\nFiles: a.py\nSteps:\n  1. Move\n  2. Test"
    assert fix_text({}) == "Suggested fix: none given."


def test_a_score_just_below_the_threshold_does_not_look_equal_to_it():
    text = evidence_text("o/r#8", "PR: Tweak. Risk score 0.441004 (threshold 0.441173). Strongest graph edges: "
                                  "x/a.py:a.f -> CALLS -> x/b.py:b.g (0.0050)")
    assert "risk score is 0.4410 (threshold 0.4412), so it does not flag it" in text

def test_google_forms_export_becomes_one_row_per_rating(tmp_path):
    prs, key = build(_checkpoint(), count=2, seed=1)
    export = tmp_path / "export.csv"
    header = ["Timestamp", ROLE_QUESTION, YEARS_QUESTION]
    values = ["2026-10-28", "Professional developer", "4"]
    for index in (1, 2):
        for letter in "ABC":
            for row_index, label in enumerate(ROWS):
                header.append(f"PR {index}, explanation {letter} [{label}]")
                values.append(str(1 + row_index))
    with export.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows([header, values])
    out = tmp_path / "long.csv"
    assert convert(export, key, out) == 6
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert rows[0]["respondent_id"] == "r001" and rows[0]["role"] == "Professional developer"
    assert (rows[0]["correct"], rows[0]["useful"], rows[0]["actionable"], rows[0]["clear"]) == ("1", "2", "3", "4")
    assert {row["sample_id"] for row in rows} == set(key["mapping"])
