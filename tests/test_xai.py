"""XAI layers A (structure vs diff) and B (hunk occlusion).

Most tests use the tiny fake CodeReviewer from test_diff_encoder.py (no download). The last test
uses the REAL microsoft/codereviewer, but only on a machine where it is already downloaded and
the v3 data exists; everywhere else it is skipped.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import math
from pathlib import Path

import pytest
import torch

from src.fusion.model import FusionModel, Projection
from src.semantic.diff_encoder import DiffEncoder, EncoderSettings
from src.xai.explain import ExplanationError, branch_contributions, explain_pr, parse_diff
from tests.test_diff_encoder import PROJECT_ANALYSIS, FakeModel, FakeTokenizer, file_diff, make_samples

ROOT = Path(__file__).resolve().parents[1]


def fake_encoder(**settings) -> DiffEncoder:
    return DiffEncoder(FakeTokenizer(), FakeModel(), "fake/model", EncoderSettings(**settings))


def two_hunk_file(path: str, first: list[str], second: list[str]) -> str:
    return "\n".join([f"diff --git a/{path} b/{path}", "index 1..2 100644", f"--- a/{path}", f"+++ b/{path}",
                      "@@ -1,2 +1,3 @@ def a():", *[f"+{line}" for line in first], " context",
                      "@@ -40,2 +41,4 @@ def b():", *[f"+{line}" for line in second], " more"]) + "\n"


DIFF = (two_hunk_file("src/pkg/core.py", ["x = 1"], ["y = 2", "z = 3"])
        + file_diff("src/pkg/util.py", ["helper = True"])
        + file_diff("tests/test_core.py", ["assert x"]))


def model_reading(direction: torch.Tensor, gnn_dim: int = 4, weight: float = 6.0, gnn_weight: float = 0.5) -> FusionModel:
    """A hand-built fusion model: risk rises with the diff vector's projection on ``direction``."""
    model = FusionModel(("gnn", "diff"))
    model.projections = {
        "gnn": Projection(torch.zeros(gnn_dim, dtype=torch.float64), torch.eye(gnn_dim, 1, dtype=torch.float64),
                          torch.ones(1, dtype=torch.float64)),
        "diff": Projection(torch.zeros(direction.numel(), dtype=torch.float64),
                           (direction / direction.norm()).double().reshape(-1, 1), torch.ones(1, dtype=torch.float64))}
    model.params = {"weight": torch.tensor([gnn_weight, weight], dtype=torch.float64),
                    "bias": torch.tensor([-0.5], dtype=torch.float64)}
    return model


# --- splitting the diff into hunks -------------------------------------------------------------

def test_diff_is_split_into_hunks_and_rebuilt_exactly():
    parsed = parse_diff(DIFF)
    assert [(h.file, h.new_start) for h in parsed.hunks] == [("src/pkg/core.py", 1), ("src/pkg/core.py", 41),
                                                            ("src/pkg/util.py", 1), ("tests/test_core.py", 1)]
    assert parsed.hunks[1].added == 2 and parsed.hunks[1].snippet() == ["+y = 2", "+z = 3"]
    encoder = fake_encoder()
    original = encoder.encode_diff(DIFF, PROJECT_ANALYSIS).vector
    assert torch.equal(encoder.encode_diff(parsed.render(), PROJECT_ANALYSIS).vector, original)


def test_removing_a_hunk_removes_only_that_hunk():
    parsed = parse_diff(DIFF)
    without_second = parsed.render(skip=1)
    assert "+y = 2" not in without_second and "+x = 1" in without_second and "helper" in without_second
    without_util = parsed.render(skip=2)
    assert "src/pkg/util.py" not in without_util                    # a file that loses its only hunk is dropped


# --- layer A -------------------------------------------------------------------------------------

def test_structure_and_diff_parts_add_up_to_the_score():
    model = model_reading(torch.randn(16, generator=torch.Generator().manual_seed(1)))
    gnn, diff = torch.tensor([1.5, 0.0, 0.0, 0.0]), torch.randn(16, generator=torch.Generator().manual_seed(2))
    parts = branch_contributions(model, gnn, diff)
    assert parts["exact"]
    assert math.isclose(parts["base_logit"] + parts["structure_gnn"] + parts["diff_codereviewer"], parts["logit"],
                        abs_tol=1e-12)
    assert math.isclose(parts["structure_gnn"], 0.5 * 1.5, abs_tol=1e-12)
    expected = float(model.predict_proba({"gnn": gnn.reshape(1, -1), "diff": diff.reshape(1, -1)})[0])
    assert math.isclose(parts["probability"], expected, abs_tol=1e-12)


# --- layer B -------------------------------------------------------------------------------------

def danger_setup():
    encoder = fake_encoder()
    danger = encoder.model.embedding.weight[FakeTokenizer()("<add>DANGER", add_special_tokens=False)["input_ids"][0]]
    diff_text = (two_hunk_file("src/pkg/core.py", ["safe = 1", "other = 2"], ["DANGER"] * 12)
                 + file_diff("src/pkg/util.py", ["fine = True", "also = 1"])
                 + file_diff("docs/conf.py", ["DANGER"] * 30))                 # docs are not analysed: ignored
    model = model_reading(danger.detach())
    stored = encoder.encode_diff(diff_text, PROJECT_ANALYSIS).vector
    return encoder, model, diff_text, stored


def explain(encoder, model, diff_text, stored, **extra):
    return explain_pr(model=model, encoder=encoder, analysis_settings=PROJECT_ANALYSIS, diff_text=diff_text,
                      gnn=torch.zeros(4), stored_diff=stored, **extra)


def test_planted_risky_hunk_comes_out_on_top():
    result = explain(*danger_setup())
    top = result["hunks"][0]
    assert (top["file"], top["new_lines"][0]) == ("src/pkg/core.py", 41)
    assert top["effect_on_risk"] > 0.1 and top["snippet"][0] == "+DANGER"
    assert all(hunk["file"] != "docs/conf.py" for hunk in result["hunks"])
    assert result["hunk_counts"] == {"total": 4, "in_analysed_files": 3, "explained": 3, "skipped_by_cap": 0}


def test_hunk_cap_keeps_the_largest_hunks():
    result = explain(*danger_setup(), max_hunks=1)
    assert [hunk["new_lines"][0] for hunk in result["hunks"]] == [41]          # the 12-line hunk
    assert result["hunk_counts"]["skipped_by_cap"] == 2


def test_explanations_are_deterministic():
    setup = danger_setup()
    assert explain(*setup) == explain(*setup)


def test_only_production_hunk_is_compared_with_no_diff_information():
    encoder, model, _, _ = danger_setup()
    diff_text = file_diff("src/pkg/core.py", ["DANGER"] * 5) + file_diff("tests/test_x.py", ["assert 1"])
    result = explain(encoder, model, diff_text, encoder.encode_diff(diff_text, PROJECT_ANALYSIS).vector)
    assert [hunk["reference"] for hunk in result["hunks"]] == ["no_diff_information"]
    parts = result["contributions"]
    no_diff = 1 / (1 + math.exp(-(parts["logit"] - parts["diff_codereviewer"])))
    assert math.isclose(result["hunks"][0]["effect_on_risk"], result["probability"] - no_diff, abs_tol=1e-12)


def test_vector_mismatch_stops_the_explanation():
    encoder, model, diff_text, stored = danger_setup()
    with pytest.raises(ExplanationError, match="does not reproduce the saved vector"):
        explain(encoder, model, diff_text, stored + 0.01)


# --- the script, end to end with the other two scripts ---------------------------------------------

def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_factory(model_name, settings, device):
    return DiffEncoder(FakeTokenizer(), FakeModel(), model_name, settings, device)


def build_pipeline(tmp_path: Path) -> dict[str, Path]:
    """Samples -> CodeReviewer vectors -> fusion model, exactly as on the real data."""
    samples, artifacts = tmp_path / "samples", tmp_path / "artifacts"
    artifacts.mkdir()
    rows, specs = [], []
    plan = ["train"] * 8 + ["validation"] * 4 + ["test"] * 4
    for number, split in enumerate(plan, 1):
        label = number % 2
        sample_id = f"org/r#{number}"
        body = ["DANGER"] * 6 if label else ["calm = 1", "steady = 2"]
        specs.append((sample_id, label, two_hunk_file("src/pkg/m.py", [f"v{number} = 0"], body)))
        rows.append({"row_index": number - 1, "sample_id": sample_id, "label": label, "split": split})
    make_samples(samples, specs)
    manifest = artifacts / "gnn_embeddings_v5.json"
    manifest.write_text(json.dumps({"embedding_file": "gnn_embeddings_v5.pt", "count": len(rows), "rows": rows}),
                        encoding="utf-8")
    generator = torch.Generator().manual_seed(0)
    torch.save({"sample_ids": [row["sample_id"] for row in rows], "embeddings": torch.randn(len(rows), 8, generator=generator),
                "labels": torch.tensor([row["label"] for row in rows]), "splits": [row["split"] for row in rows]},
               artifacts / "gnn_embeddings_v5.pt")
    paths = {"manifest": manifest, "samples": samples, "diff": tmp_path / "emb/embeddings.pt",
             "fusion": tmp_path / "fusion/fusion_model.pt", "xai": tmp_path / "xai"}
    assert load("build_diff_embeddings").main(["--manifest", str(manifest), "--samples-dir", str(samples),
                                               "--output-dir", str(tmp_path / "emb"), "--model", "fake/model"],
                                              encoder_factory=fake_factory) == 0
    assert load("train_fusion").main(["--manifest", str(manifest), "--diff", str(paths["diff"]),
                                      "--output-dir", str(tmp_path / "fusion"), "--bootstrap", "0",
                                      "--pca-dims", "3"]) == 0
    return paths


def explain_script(paths: dict[str, Path], *extra: str) -> int:
    return load("explain_prs").main(["--manifest", str(paths["manifest"]), "--diff", str(paths["diff"]),
                                     "--fusion-model", str(paths["fusion"]), "--samples-dir", str(paths["samples"]),
                                     "--output-dir", str(paths["xai"]), "--no-graph", *extra],
                                    encoder_factory=fake_factory)


def test_script_explains_the_test_prs_and_writes_a_summary(tmp_path, capsys):
    paths = build_pipeline(tmp_path)
    assert explain_script(paths) == 0
    assert "Explaining 4 PR(s)" in capsys.readouterr().out
    files = sorted(path.name for path in paths["xai"].glob("*.json"))
    assert files == ["org__r__13.json", "org__r__14.json", "org__r__15.json", "org__r__16.json"]
    report = json.loads((paths["xai"] / "org__r__14.json").read_text(encoding="utf-8"))
    assert report["split"] == "test" and report["label"] == 0 and report["hunks"]
    predictions = {row["sample_id"]: float(row["p_fusion"])
                   for row in csv.DictReader((paths["fusion"].parent / "predictions.csv").open(encoding="utf-8"))}
    assert math.isclose(report["probability"], predictions["org/r#14"], abs_tol=1e-6)   # same score as fusion
    with (paths["xai"] / "summary.csv").open(encoding="utf-8") as handle:
        assert len(list(csv.DictReader(handle))) == 4


def test_script_refuses_a_fusion_model_trained_on_other_inputs(tmp_path, capsys):
    paths = build_pipeline(tmp_path)
    store = torch.load(paths["diff"], weights_only=True)
    store["num_tokens"] = [value + 1 for value in store["num_tokens"]]                   # file changed after training
    torch.save(store, paths["diff"])
    assert explain_script(paths) == 2
    assert "Re-run scripts/train_fusion.py" in capsys.readouterr().out


def test_script_explains_chosen_prs_only(tmp_path):
    paths = build_pipeline(tmp_path)
    assert explain_script(paths, "--sample-id", "org/r#2") == 0
    assert [path.name for path in paths["xai"].glob("*.json")] == ["org__r__2.json"]
    assert explain_script(paths, "--sample-id", "org/zzz#1") == 2


# --- optional: the real CodeReviewer on this machine ------------------------------------------------

REAL_DIFF_STORE = ROOT / "data/embeddings/microsoft__codereviewer__gnn_embeddings_v3/embeddings.pt"
REAL_SAMPLES = ROOT / "data/future_pr_samples_v3"


def _real_encoder_or_skip() -> DiffEncoder:
    if not REAL_DIFF_STORE.is_file() or not REAL_SAMPLES.is_dir():
        pytest.skip("v3 CodeReviewer vectors / samples not on this machine")
    try:
        from transformers import AutoModel, AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained("microsoft/codereviewer", local_files_only=True)
        model = AutoModel.from_pretrained("microsoft/codereviewer", local_files_only=True)
    except Exception as exc:  # not installed or not downloaded: never download inside a test
        pytest.skip(f"microsoft/codereviewer not available offline: {type(exc).__name__}")
    stored = torch.load(REAL_DIFF_STORE, weights_only=True)["encoder"]
    settings = EncoderSettings(max_tokens=stored["max_tokens"], stride=stored["stride"],
                               max_chunks=stored["max_chunks"], graph_files_only=stored["graph_files_only"])
    return DiffEncoder(tokenizer, model.get_encoder(), "microsoft/codereviewer", settings)


def test_real_codereviewer_reproduces_the_saved_vectors_and_explains_a_pr():
    encoder = _real_encoder_or_skip()
    store = torch.load(REAL_DIFF_STORE, weights_only=True)
    assert encoder.describe() == store["encoder"]
    smallest = min(range(len(store["sample_ids"])), key=lambda row: store["num_tokens"][row])
    sample_id = store["sample_ids"][smallest]
    repo, number = sample_id.split("#")
    diff_text = (REAL_SAMPLES / repo.replace("/", "__") / number / "diff.patch").read_text(encoding="utf-8",
                                                                                            errors="replace")
    vector = encoder.encode_diff(diff_text, PROJECT_ANALYSIS, allow_fallback=False).vector
    assert vector.shape == (768,)
    assert torch.allclose(vector, store["embeddings"][smallest], atol=1e-4)            # same numbers as the build

    direction = torch.randn(768, generator=torch.Generator().manual_seed(0))
    result = explain(encoder, model_reading(direction), diff_text, store["embeddings"][smallest], max_hunks=3)
    assert result["hunks"] and all(math.isfinite(hunk["effect_on_risk"]) for hunk in result["hunks"])
