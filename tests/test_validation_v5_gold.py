import json
from pathlib import Path

import pytest

from src.validation_v5.gold_set import RELATIONS, agreement, load_gold, predicted_triples, run_gold_set, score_file

FIXTURES = Path(__file__).parent / "fixtures" / "validation_v5"


def node(qualified_name, node_type, path="pkg/m.py"):
    return {"id": f"{path}:{qualified_name}", "type": node_type, "qualified_name": qualified_name, "path": path}


def edge(source, target, kind, path="pkg/m.py", target_path="pkg/m.py"):
    return {"source": f"{path}:{source}", "target": f"{target_path}:{target}", "type": kind}


GRAPH = {
    "nodes": [node("pkg.m", "module"), node("pkg.m.C", "class"), node("pkg.m.C.run", "method"),
              node("pkg.m.X", "global_variable"), node("pkg.other", "module", "pkg/other.py"),
              node("pkg.other.f", "function", "pkg/other.py"),
              node("ValueError", "external_callable", "ext"), node("os.path.join", "external_callable", "ext"),
              node("pkg.m.s.run", "external_callable", "ext")],
    "edges": [edge("pkg.m.C", "ValueError", "INHERITS", target_path="ext"),
              edge("pkg.m.C.run", "os.path.join", "CALLS", target_path="ext"),
              edge("pkg.m.C.run", "pkg.m.s.run", "CALLS", target_path="ext"),
              edge("pkg.m.C.run", "pkg.m.X", "ACCESSES_GLOBAL"),
              edge("pkg.m.C", "pkg.m.C.run", "CONTAINS"),
              edge("pkg.other.f", "pkg.m.C", "CALLS", path="pkg/other.py")],
}


def test_predicted_triples_follow_the_gold_naming_rules():
    assert predicted_triples(GRAPH, "pkg/m.py") == {
        ("INHERITS", "pkg.m.C", "builtins.ValueError"),     # bare builtin gets its module
        ("CALLS", "pkg.m.C.run", "pkg.m.s.run"),            # internal-looking external: kept, counts as wrong
        ("ACCESSES_GLOBAL", "pkg.m.C.run", "pkg.m.X"),
    }  # os.path.join (external) and edges starting in pkg/other.py are left out


def test_also_accept_maps_an_alternative_spelling_to_the_gold_relation():
    relations = [{"type": "INHERITS", "source": "pkg.m.C", "target": "builtins.OSError",
                  "also_accept": ["builtins.IOError"]}]
    result = score_file({("INHERITS", "pkg.m.C", "builtins.IOError")}, relations)
    assert result["per_relation"]["INHERITS"] == {"tp": 1, "fp": 0, "fn": 0}


def test_score_file_counts_per_relation():
    relations = [{"type": "CALLS", "source": "a", "target": "b"}, {"type": "CALLS", "source": "a", "target": "c"},
                 {"type": "ACCESSES_GLOBAL", "source": "a", "target": "g"}]
    result = score_file({("CALLS", "a", "b"), ("CALLS", "a", "z")}, relations)
    assert result["per_relation"]["CALLS"] == {"tp": 1, "fp": 1, "fn": 1}
    assert result["per_relation"]["ACCESSES_GLOBAL"] == {"tp": 0, "fp": 0, "fn": 1}
    assert result["missed"] == [["ACCESSES_GLOBAL", "a", "g"], ["CALLS", "a", "c"]]


def test_positive_specific_agreement():
    first = [{"type": "CALLS", "source": "a", "target": t} for t in "bcd"]
    second = [{"type": "CALLS", "source": "a", "target": t} for t in "bce"]
    result = agreement(first, second)
    assert result["overall"] == pytest.approx(2 * 2 / 6)
    assert result["only_first"] == [["CALLS", "a", "d"]] and result["only_second"] == [["CALLS", "a", "e"]]
    assert result["per_relation"]["INHERITS"] is None


def test_run_gold_set_with_an_injected_graph(tmp_path):
    gold = tmp_path / "gold.json"
    gold.write_text(json.dumps({"files": [{"repo": "o/r", "tag": "1", "path": "pkg/m.py", "relations": [
        {"type": "ACCESSES_GLOBAL", "source": "pkg.m.C.run", "target": "pkg.m.X"}]}]}))
    second = tmp_path / "second.json"
    second.write_text(json.dumps({"path": "pkg/m.py", "labeller": None, "relations": []}))
    result = run_gold_set(gold, tmp_path, {}, second, build=lambda folder: GRAPH)
    assert result["per_relation"]["ACCESSES_GLOBAL"]["tp"] == 1
    assert result["overall"]["fp"] == 2  # builtins.ValueError and pkg.m.s.run are not in this gold
    assert result["agreement"]["status"] == "second labeller has not labelled yet"


def test_shipped_gold_file_is_well_formed():
    files = load_gold(FIXTURES / "gold.json")
    assert len({entry["repo"] for entry in files}) == len(files) >= 5
    for entry in files:
        assert entry["relations"], entry["path"]
        for relation in entry["relations"]:
            assert relation["type"] in RELATIONS
            assert relation["source"] and relation["target"]
        triples = [(r["type"], r["source"], r["target"]) for r in entry["relations"]]
        assert len(triples) == len(set(triples)), f"duplicate relation in {entry['path']}"
