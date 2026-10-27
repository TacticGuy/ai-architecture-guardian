import json

import pytest

from scripts.rag_v5_evaluate import bootstrap, prepare_sheets, select_test_files
from scripts.rag_v5_survey import analyze, build_form


def test_bootstrap_is_repeatable():
    assert bootstrap([0.1, 0.2, 0.3]) == bootstrap([0.1, 0.2, 0.3])
    assert bootstrap([1, 1, 1])["low"] == 1


def test_sheets_exclude_synthetic_fixtures(tmp_path):
    fixture = {"schema": "attribution_v5/1", "split": "test", "predicted_degrading": True,
               "sample_id": "example/repo#1", "repo": "example/repo", "_note": "synthetic example for tests only"}
    (tmp_path / "one.json").write_text(json.dumps(fixture), encoding="utf-8")
    assert select_test_files(tmp_path) == []
    with pytest.raises(ValueError, match="No real"):
        prepare_sheets(tmp_path, tmp_path / "sheets")


def test_survey_blinding_is_deterministic(tmp_path):
    results = {"per_pr": [{"sample_id": "example/repo#1", "mode": mode,
                           "answer": {"explanation": mode, "suggestion": {}}}
                          for mode in ("signature", "text", "none")]}
    mapping = build_form(results, tmp_path / "form.md", tmp_path / "key.json")
    assert set(mapping["example/repo#1"].values()) == {"signature", "text", "none"}
    assert mapping == build_form(results, tmp_path / "form.md", tmp_path / "key.json")
    assert "Explanation A" in (tmp_path / "form.md").read_text(encoding="utf-8")


def test_survey_analysis_uses_real_rows_and_unblinds(tmp_path):
    key = {"mapping": {"example/repo#1": {"A": "signature", "B": "text", "C": "none"}}}
    (tmp_path / "key.json").write_text(json.dumps(key), encoding="utf-8")
    header = "respondent_id,years_coding,role,sample_id,variant,correct,useful,actionable,clear\n"
    rows = []
    for respondent, offset in (("r1", 0), ("r2", 1)):
        for variant, value in (("A", 5), ("B", 3), ("C", 2)):
            score = max(1, value - offset)
            rows.append(f"{respondent},2,student,example/repo#1,{variant},{score},{score},{score},{score}")
    (tmp_path / "responses.csv").write_text(header + "\n".join(rows) + "\n", encoding="utf-8")
    result = analyze(tmp_path / "responses.csv", tmp_path / "key.json")
    assert result["respondent_count"] == 2
    assert result["complete_paired_blocks"] == 2
    assert result["descriptive"]["signature"]["correct"]["mean"] == 4.5
