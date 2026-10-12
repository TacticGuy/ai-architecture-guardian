"""Points 9-11: diff embeddings. A tiny fake tokenizer/model stands in for CodeReviewer,
so these tests need no download and no network."""
from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import zlib

import pytest
import torch

from src.analysis.ast_parser import extract_repository_ast
from src.semantic.diff_encoder import (DiffEncoder, EncoderSettings, graph_includes_path, prepare_diff,
                                       split_diff_by_file)

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ANALYSIS = json.loads((ROOT / "config/settings.json").read_text(encoding="utf-8"))["static_analysis"]


class FakeTokenizer:
    """Word-level tokenizer: <s>=0, pad=1, </s>=2, every other word hashes to an id >= 10."""
    pad_token_id = 1

    def __init__(self, markers: bool = True) -> None:
        self.markers = markers

    def __call__(self, text: str, add_special_tokens: bool = True) -> dict:
        ids = [10 + zlib.crc32(word.encode()) % 1000 for word in text.split()]
        return {"input_ids": [0, *ids, 2] if add_special_tokens else ids}

    def get_vocab(self) -> dict[str, int]:
        return {"<add>": 3, "<del>": 4, "<keep>": 5} if self.markers else {"a": 3}


class FakeModel(torch.nn.Module):
    def __init__(self, dim: int = 16) -> None:
        super().__init__()
        torch.manual_seed(0)
        self.config = SimpleNamespace(hidden_size=dim)
        self.embedding = torch.nn.Embedding(1100, dim)

    def forward(self, input_ids, attention_mask):
        return SimpleNamespace(last_hidden_state=self.embedding(input_ids))


def make_encoder(**overrides) -> DiffEncoder:
    markers = overrides.pop("markers", True)
    return DiffEncoder(FakeTokenizer(markers), FakeModel(), "fake/model", EncoderSettings(**overrides))


def file_diff(path: str, added: list[str], removed: list[str] = (), context: list[str] = ()) -> str:
    body = [f"diff --git a/{path} b/{path}", "index 111..222 100644", f"--- a/{path}", f"+++ b/{path}",
            "@@ -1,3 +1,3 @@ def thing():"]
    body += [f" {line}" for line in context] + [f"-{line}" for line in removed] + [f"+{line}" for line in added]
    return "\n".join(body) + "\n"


SAMPLE_DIFF = (file_diff("src/pkg/core.py", ["import os", "x = 1"], ["y = 2"], ["def run():"])
               + file_diff("testing/test_core.py", ["assert run()"])
               + file_diff("docs/conf.py", ["project = 'x'"]))


# --- preparing the diff text ------------------------------------------------------------

def test_split_diff_by_file_finds_each_file_section():
    sections = split_diff_by_file(SAMPLE_DIFF)
    assert [path for path, _ in sections] == ["src/pkg/core.py", "testing/test_core.py", "docs/conf.py"]
    assert "+import os" in sections[0][1]


def test_diff_keeps_exactly_the_files_the_graph_analyses(tmp_path):
    paths = ["src/pkg/core.py", "src/pkg/test_helpers.py", "tests/test_a.py", "testing/test_b.py",
             "testing/acceptance_test.py", "docs/conf.py", "examples/demo.py", "setup.py",
             "src/pkg/conftest.py", "src/pkg/setup_helpers.py"]
    for relative in paths:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x = 1\n", encoding="utf-8")
    analysed = set(extract_repository_ast(tmp_path, PROJECT_ANALYSIS)["files"])
    assert {path for path in paths if graph_includes_path(path, PROJECT_ANALYSIS)} == analysed


def test_prepare_drops_non_graph_files_and_diff_headers():
    prepared = prepare_diff(SAMPLE_DIFF, PROJECT_ANALYSIS, use_markers=True)
    assert prepared.files_used == ["src/pkg/core.py"]
    assert prepared.files_dropped == ["testing/test_core.py", "docs/conf.py"]
    assert prepared.text.splitlines() == ["<keep>def run():", "<del>y = 2", "<add>import os", "<add>x = 1"]
    assert not prepared.fallback_full_diff


def test_raw_line_format_when_tokenizer_has_no_markers():
    prepared = prepare_diff(SAMPLE_DIFF, PROJECT_ANALYSIS, use_markers=False)
    assert prepared.text.splitlines() == [" def run():", "-y = 2", "+import os", "+x = 1"]
    assert make_encoder(markers=False).describe()["line_format"] == "raw"
    assert make_encoder(markers=True).describe()["line_format"] == "markers"


def test_test_only_diff_falls_back_to_the_full_diff():
    prepared = prepare_diff(file_diff("tests/test_x.py", ["assert True"]), PROJECT_ANALYSIS, use_markers=True)
    assert prepared.fallback_full_diff and prepared.files_used == ["tests/test_x.py"]
    assert prepared.text == "<add>assert True"


def test_keep_test_files_option_encodes_everything():
    prepared = prepare_diff(SAMPLE_DIFF, PROJECT_ANALYSIS, use_markers=True, graph_files_only=False)
    assert prepared.files_used == ["src/pkg/core.py", "testing/test_core.py", "docs/conf.py"]


# --- embedding -----------------------------------------------------------------------------

def test_embedding_is_fixed_size_float_and_deterministic():
    encoder = make_encoder()
    first = encoder.encode_diff(SAMPLE_DIFF, PROJECT_ANALYSIS)
    second = encoder.encode_diff(SAMPLE_DIFF, PROJECT_ANALYSIS)
    assert first.vector.shape == (16,) and first.vector.dtype == torch.float32
    assert torch.equal(first.vector, second.vector)
    other = encoder.encode_diff(file_diff("src/pkg/core.py", ["completely different change here"]), PROJECT_ANALYSIS)
    assert not torch.allclose(first.vector, other.vector)


def test_long_diffs_are_split_into_windows_that_fit_the_model():
    seen: list[int] = []
    encoder = make_encoder(max_tokens=12, stride=10)
    original = encoder.model.forward
    encoder.model.forward = lambda input_ids, attention_mask: (seen.extend(attention_mask.sum(1).tolist())
                                                               or original(input_ids, attention_mask))
    words = " ".join(f"word{i}" for i in range(55))
    vector, num_tokens, num_chunks, truncated = encoder.encode_text(words)
    assert num_tokens == 55 and num_chunks == 6 and not truncated   # windows of 10 cover all 55 tokens
    assert max(seen) <= 12 and vector.shape == (16,)                # never more than the model limit


def test_huge_diffs_are_capped_and_flagged():
    encoder = make_encoder(max_tokens=12, stride=10, max_chunks=3)
    _, num_tokens, num_chunks, truncated = encoder.encode_text(" ".join(f"w{i}" for i in range(500)))
    assert num_tokens == 500 and num_chunks == 3 and truncated


def test_batch_size_does_not_change_the_result():
    text = " ".join(f"w{i}" for i in range(100))
    small = make_encoder(max_tokens=12, stride=10, batch_size=1).encode_text(text)[0]
    large = make_encoder(max_tokens=12, stride=10, batch_size=64).encode_text(text)[0]
    assert torch.allclose(small, large, atol=1e-6)


def test_empty_diff_still_gives_a_vector():
    vector, num_tokens, num_chunks, _ = make_encoder().encode_text("")
    assert vector.shape == (16,) and num_tokens == 0 and num_chunks == 1


# --- the build script --------------------------------------------------------------------

def load_script():
    spec = importlib.util.spec_from_file_location("build_diff_embeddings", ROOT / "scripts/build_diff_embeddings.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_samples(root: Path, specs: list[tuple[str, int, str]]) -> None:
    for sample_id, label, diff in specs:
        repo, number = sample_id.split("#")
        folder = root / repo.replace("/", "__") / number
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "diff.patch").write_text(diff, encoding="utf-8")
        (folder / "metadata.json").write_text(json.dumps(
            {"sample_id": sample_id, "label": label, "diff_path": "diff.patch"}), encoding="utf-8")


def fake_factory(model_name, settings, device):
    return DiffEncoder(FakeTokenizer(), FakeModel(), model_name, settings, device)


SPECS = [("org/b#2", 0, file_diff("src/pkg/b.py", ["b = 2"])),
         ("org/a#1", 1, file_diff("src/pkg/a.py", ["a = 1"])),
         ("org/c#3", 0, file_diff("tests/test_c.py", ["assert c"]))]


def run(script, samples: Path, output: Path, *extra: str) -> int:
    return script.main(["--samples-dir", str(samples), "--output-dir", str(output), "--model", "fake/model", *extra],
                       encoder_factory=fake_factory)


def test_script_writes_embeddings_and_index_keyed_by_sample_id(tmp_path):
    script, samples, output = load_script(), tmp_path / "samples", tmp_path / "out"
    make_samples(samples, SPECS)
    assert run(script, samples, output) == 0
    store = torch.load(output / "embeddings.pt", weights_only=True)    # safe loader works
    assert store["sample_ids"] == ["org/a#1", "org/b#2", "org/c#3"]
    assert tuple(store["embeddings"].shape) == (3, 16) and store["dim"] == 16
    labels = dict(zip(store["sample_ids"], store["labels"].tolist()))
    assert labels == {"org/a#1": 1, "org/b#2": 0, "org/c#3": 0}
    assert store["fallback_full_diff"] == [False, False, True]
    with (output / "index.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [(row["sample_id"], row["label"]) for row in rows] == [("org/a#1", "1"), ("org/b#2", "0"), ("org/c#3", "0")]


def test_rerun_only_encodes_new_or_changed_samples(tmp_path, capsys):
    script, samples, output = load_script(), tmp_path / "samples", tmp_path / "out"
    make_samples(samples, SPECS[:2])
    assert run(script, samples, output) == 0
    before = torch.load(output / "embeddings.pt", weights_only=True)
    capsys.readouterr()

    assert run(script, samples, output) == 0
    assert "Nothing to do" in capsys.readouterr().out

    make_samples(samples, [SPECS[2], ("org/a#1", 1, file_diff("src/pkg/a.py", ["a = 'changed'"]))])
    assert run(script, samples, output) == 0
    printed = capsys.readouterr().out
    assert "new or changed: 2" in printed
    after = torch.load(output / "embeddings.pt", weights_only=True)
    assert after["sample_ids"] == ["org/a#1", "org/b#2", "org/c#3"]                 # rows kept, one appended
    assert torch.equal(after["embeddings"][1], before["embeddings"][1])           # unchanged sample untouched
    assert not torch.equal(after["embeddings"][0], before["embeddings"][0])       # changed diff re-encoded


def test_limit_and_sample_id_select_what_is_encoded(tmp_path):
    script, samples = load_script(), tmp_path / "samples"
    make_samples(samples, SPECS)
    assert run(script, samples, tmp_path / "first", "--limit", "2") == 0
    assert len(torch.load(tmp_path / "first/embeddings.pt", weights_only=True)["sample_ids"]) == 2
    assert run(script, samples, tmp_path / "one", "--sample-id", "org/b#2") == 0
    assert torch.load(tmp_path / "one/embeddings.pt", weights_only=True)["sample_ids"] == ["org/b#2"]
    assert run(script, samples, tmp_path / "bad", "--sample-id", "org/zzz#9") == 2


def test_different_settings_are_never_mixed_into_one_file(tmp_path, capsys):
    script, samples, output = load_script(), tmp_path / "samples", tmp_path / "out"
    make_samples(samples, SPECS[:1])
    assert run(script, samples, output) == 0
    make_samples(samples, SPECS[1:2])
    assert run(script, samples, output, "--max-chunks", "4") == 2
    assert "different settings" in capsys.readouterr().out
    assert len(torch.load(output / "embeddings.pt", weights_only=True)["sample_ids"]) == 1


def test_duplicate_sample_ids_are_rejected(tmp_path):
    script, samples = load_script(), tmp_path / "samples"
    make_samples(samples, SPECS[:1])                     # org/b#2
    copy = samples / "org__b_copy" / "2"
    copy.mkdir(parents=True)
    for name in ("diff.patch", "metadata.json"):
        (copy / name).write_bytes((samples / "org__b" / "2" / name).read_bytes())
    assert run(script, samples, tmp_path / "out") == 2


# --- manifest mode (fusion inputs must match the GNN's samples exactly) ------------------

def test_no_fallback_mode_refuses_test_only_diffs():
    encoder = make_encoder()
    with pytest.raises(ValueError, match="no eligible production diff"):
        encoder.encode_diff(file_diff("tests/test_x.py", ["assert True"]), PROJECT_ANALYSIS, allow_fallback=False)
    assert encoder.encode_diff(SAMPLE_DIFF, PROJECT_ANALYSIS, allow_fallback=False).files_used == ["src/pkg/core.py"]


MANIFEST_SPECS = [("org/r#10", 1, file_diff("src/pkg/a.py", ["a = 1"])),
                  ("org/r#11", 0, file_diff("src/pkg/b.py", ["b = 2"])),
                  ("org/r#12", 1, file_diff("src/pkg/c.py", ["c = 3"])),
                  ("org/r#13", 0, file_diff("src/pkg/d.py", ["d = 4"])),
                  ("org/r#9", 1, file_diff("src/pkg/purged.py", ["p = 0"])),     # in folder, not in manifest
                  ("org/r#100", 1, file_diff("src/pkg/purged2.py", ["q = 0"]))]  # in folder, not in manifest
MANIFEST_ROWS = [("org/r#12", 1, "train"), ("org/r#10", 1, "validation"),
                 ("org/r#11", 0, "test"), ("org/r#13", 0, "test")]


def write_manifest(path: Path, rows=MANIFEST_ROWS) -> Path:
    path.write_text(json.dumps({"count": len(rows), "rows": [
        {"row_index": i, "sample_id": sid, "label": label, "split": split}
        for i, (sid, label, split) in enumerate(rows)]}), encoding="utf-8")
    return path


def run_manifest(script, samples: Path, output: Path, manifest: Path, *extra: str) -> int:
    return run(script, samples, output, "--manifest", str(manifest), *extra)


def test_manifest_mode_encodes_exactly_the_manifest_samples_with_its_splits(tmp_path, capsys):
    script, samples, output = load_script(), tmp_path / "samples", tmp_path / "out"
    make_samples(samples, MANIFEST_SPECS)
    manifest = write_manifest(tmp_path / "gnn_embeddings_v9.json")
    assert run_manifest(script, samples, output, manifest) == 0
    printed = capsys.readouterr().out
    assert "ignored in folder (not in manifest): 2 -> org/r#9, org/r#100" in printed   # sorted by PR number
    assert "Manifest check passed" in printed
    store = torch.load(output / "embeddings.pt", weights_only=True)
    assert store["sample_ids"] == ["org/r#12", "org/r#10", "org/r#11", "org/r#13"]    # manifest order
    assert store["splits"] == ["train", "validation", "test", "test"]
    assert store["labels"].tolist() == [1, 1, 0, 0]
    assert tuple(store["embeddings"].shape) == (4, 16)
    assert store["manifest"]["count"] == 4 and store["fallback_full_diff"] == [False] * 4
    with (output / "index.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [(r["sample_id"], r["label"], r["split"]) for r in rows] == [(sid, str(lab), sp) for sid, lab, sp in MANIFEST_ROWS]

    assert run_manifest(script, samples, output, manifest) == 0                       # rerun: nothing new
    assert "Nothing to do" in capsys.readouterr().out


def test_manifest_sample_without_a_diff_is_an_error(tmp_path, capsys):
    script, samples = load_script(), tmp_path / "samples"
    make_samples(samples, MANIFEST_SPECS[1:])                                          # org/r#10 missing
    assert run_manifest(script, samples, tmp_path / "out", write_manifest(tmp_path / "m.json")) == 2
    assert "have no diff in the folder: org/r#10" in capsys.readouterr().out
    assert not (tmp_path / "out").exists()


def test_label_disagreement_with_manifest_is_an_error(tmp_path, capsys):
    script, samples = load_script(), tmp_path / "samples"
    make_samples(samples, MANIFEST_SPECS)
    rows = [("org/r#12", 0, "train"), *MANIFEST_ROWS[1:]]                              # metadata says 1
    assert run_manifest(script, samples, tmp_path / "out", write_manifest(tmp_path / "m.json", rows)) == 2
    assert "org/r#12: metadata label 1 != manifest label 0" in capsys.readouterr().out


def test_manifest_mode_never_uses_the_full_diff_fallback(tmp_path, capsys):
    script, samples, output = load_script(), tmp_path / "samples", tmp_path / "out"
    make_samples(samples, [*MANIFEST_SPECS[:3], ("org/r#13", 0, file_diff("tests/test_d.py", ["assert d"]))])
    assert run_manifest(script, samples, output, write_manifest(tmp_path / "m.json")) == 1
    printed = capsys.readouterr().out
    assert "FAILED org/r#13: no eligible production diff" in printed
    assert "Manifest check passed" not in printed


def test_bad_or_duplicate_manifests_are_rejected(tmp_path):
    script, samples = load_script(), tmp_path / "samples"
    make_samples(samples, MANIFEST_SPECS)
    duplicated = write_manifest(tmp_path / "dup.json", [*MANIFEST_ROWS, MANIFEST_ROWS[0]])
    bad_split = write_manifest(tmp_path / "split.json", [("org/r#12", 1, "dev")])
    assert run_manifest(script, samples, tmp_path / "o1", duplicated) == 2
    assert run_manifest(script, samples, tmp_path / "o2", bad_split) == 2
    with pytest.raises(SystemExit):                                                   # manifest decides the samples
        run_manifest(script, samples, tmp_path / "o3", write_manifest(tmp_path / "m.json"), "--sample-id", "org/r#10")


def test_output_built_for_another_manifest_is_not_reused(tmp_path, capsys):
    script, samples, output = load_script(), tmp_path / "samples", tmp_path / "out"
    make_samples(samples, MANIFEST_SPECS)
    assert run_manifest(script, samples, output, write_manifest(tmp_path / "a.json")) == 0
    other = write_manifest(tmp_path / "b.json", MANIFEST_ROWS[:3])
    assert run_manifest(script, samples, output, other) == 2
    assert "different manifest" in capsys.readouterr().out


def test_verify_catches_wrong_split_counts_and_labels():
    script = load_script()
    manifest = {"rows": [{"sample_id": sid, "label": lab, "split": sp} for sid, lab, sp in MANIFEST_ROWS]}
    store = {"sample_ids": [r[0] for r in MANIFEST_ROWS], "labels": torch.tensor([1, 1, 0, 0]),
             "splits": ["train", "validation", "test", "test"], "embeddings": torch.zeros(4, 16), "dim": 16}
    script.verify_against_manifest(store, manifest)                                    # correct one passes
    with pytest.raises(script.ManifestError, match="split mismatch"):
        script.verify_against_manifest({**store, "splits": ["train", "test", "test", "test"]}, manifest)
    with pytest.raises(script.ManifestError, match="label mismatch"):
        script.verify_against_manifest({**store, "labels": torch.tensor([0, 1, 0, 0])}, manifest)
    with pytest.raises(script.ManifestError, match="set differs"):
        script.verify_against_manifest({**store, "sample_ids": ["org/r#12", "org/r#10", "org/r#11", "org/r#99"]}, manifest)
    with pytest.raises(script.ManifestError, match="duplicate"):
        script.verify_against_manifest({**store, "sample_ids": ["org/r#12", "org/r#12", "org/r#11", "org/r#13"]}, manifest)
    with pytest.raises(script.ManifestError, match="NaN"):
        script.verify_against_manifest({**store, "embeddings": torch.full((4, 16), float("nan"))}, manifest)


# --- data version comes from the manifest name -------------------------------------------

def test_samples_folder_follows_the_manifest_version(tmp_path):
    script = load_script()
    assert script.manifest_version(Path("artifacts/gnn_embeddings_v3.json")) == "v3"
    assert script.manifest_version(Path("artifacts/gnn_embeddings_v12.json")) == "v12"
    assert script.manifest_version(Path("artifacts/gnn_embeddings.json")) is None
    assert script.manifest_version(Path("artifacts/gnn_v3_embeddings.json")) is None     # version must be at the end
    assert script.default_samples_dir(Path("a/gnn_embeddings_v4.json"), tmp_path) == tmp_path / "data/future_pr_samples_v4"
    assert script.default_samples_dir(None, tmp_path) == tmp_path / "data/future_pr_samples"


def test_new_manifest_version_reads_its_own_folder_by_default(tmp_path, capsys):
    script = load_script()
    manifest = write_manifest(tmp_path / "gnn_embeddings_v987.json")
    code = script.main(["--manifest", str(manifest), "--output-dir", str(tmp_path / "out"), "--model", "fake/model"],
                       encoder_factory=fake_factory)
    assert code == 2                                                                  # that folder does not exist
    printed = capsys.readouterr().out
    assert "No samples" in printed and str(Path("data") / "future_pr_samples_v987") in printed
    assert not (tmp_path / "out").exists()


def test_manifest_without_a_version_needs_samples_dir(tmp_path, capsys):
    script, samples = load_script(), tmp_path / "samples"
    make_samples(samples, MANIFEST_SPECS)
    manifest = write_manifest(tmp_path / "gnn_embeddings.json")
    with pytest.raises(SystemExit):
        script.main(["--manifest", str(manifest), "--model", "fake/model"], encoder_factory=fake_factory)
    assert "Pass --samples-dir" in capsys.readouterr().err
    assert run_manifest(script, samples, tmp_path / "out", manifest) == 0              # explicit folder still works
