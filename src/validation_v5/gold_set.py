"""CALLS / INHERITS / ACCESSES_GLOBAL vs a hand-labelled gold set (tests/fixtures/validation_v5/).

Our side is every edge of the three relations whose source node is defined in the labelled
file. Names follow the gold rules (README.md next to gold.json):

* CALLS keeps internal targets only, like the gold. An external-typed target whose name lies
  inside the repository's own packages is kept, because it is an internal call resolved to the
  wrong node, and the gold can then count it as wrong;
* INHERITS keeps every base; a bare builtin name becomes ``builtins.<name>``;
* a predicted target listed in a gold relation's ``also_accept`` counts as that relation.
"""
from __future__ import annotations

import builtins
import json
from pathlib import Path
from typing import Any, Callable

from src.analysis.ast_parser import extract_repository_ast
from src.analysis.dependency_graph import build_dependency_graph
from src.validation_v5.metrics import counts, micro, scores

RELATIONS = ("CALLS", "INHERITS", "ACCESSES_GLOBAL")
INTERNAL_TYPES = {"module", "class", "function", "method", "global_variable"}
Triple = tuple[str, str, str]


def load_gold(path: Path) -> list[dict[str, Any]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["files"]


def gold_triples(relations: list[dict[str, Any]]) -> tuple[set[Triple], dict[Triple, Triple]]:
    """The gold (type, source, target) set and a map from accepted alternatives to the gold triple."""
    triples, aliases = set(), {}
    for relation in relations:
        triple = (relation["type"], relation["source"], relation["target"])
        triples.add(triple)
        for alternative in relation.get("also_accept", []):
            aliases[(relation["type"], relation["source"], alternative)] = triple
    return triples, aliases


def predicted_triples(graph: dict[str, Any], path: str) -> set[Triple]:
    """Our relations that start in ``path``, named as the gold names them."""
    nodes = {node["id"]: node for node in graph["nodes"]}
    packages = {node["qualified_name"].split(".", 1)[0] for node in graph["nodes"] if node["type"] == "module"}
    path = path.replace("\\", "/")
    triples = set()
    for edge in graph["edges"]:
        if edge["type"] not in RELATIONS:
            continue
        source, target = nodes.get(edge["source"]), nodes.get(edge["target"])
        if source is None or target is None or source.get("path", "").replace("\\", "/") != path:
            continue
        name = target["qualified_name"]
        internal = target["type"] in INTERNAL_TYPES
        if edge["type"] == "CALLS" and not internal and name.split(".", 1)[0] not in packages:
            continue
        if edge["type"] == "INHERITS" and not internal and "." not in name and hasattr(builtins, name):
            name = f"builtins.{name}"
        triples.add((edge["type"], source["qualified_name"], name))
    return triples


def score_file(predicted: set[Triple], relations: list[dict[str, Any]]) -> dict[str, Any]:
    gold, aliases = gold_triples(relations)
    predicted = {aliases.get(triple, triple) for triple in predicted}
    per_relation = {kind: counts({t for t in predicted if t[0] == kind}, {t for t in gold if t[0] == kind})
                    for kind in RELATIONS}
    return {"per_relation": per_relation,
            "missed": sorted(map(list, gold - predicted)), "extra": sorted(map(list, predicted - gold))}


def agreement(first: list[dict[str, Any]], second: list[dict[str, Any]]) -> dict[str, Any]:
    """Positive specific agreement 2|A∩B| / (|A|+|B|) between two labellers, overall and per relation.

    For "list every relation" labelling there is no fixed set of negatives, so Cohen's kappa
    is undefined; this is the usual replacement (it equals F1 with either labeller as truth).
    """
    a, a_aliases = gold_triples(first)
    b = {a_aliases.get(triple, triple) for triple in gold_triples(second)[0]}

    def psa(left: set[Triple], right: set[Triple]) -> float | None:
        return 2 * len(left & right) / (len(left) + len(right)) if left or right else None

    return {"overall": psa(a, b), "first_count": len(a), "second_count": len(b),
            "per_relation": {kind: psa({t for t in a if t[0] == kind}, {t for t in b if t[0] == kind})
                             for kind in RELATIONS},
            "only_first": sorted(map(list, a - b)), "only_second": sorted(map(list, b - a))}


def run_gold_set(gold_path: Path, repos_dir: Path, settings: dict[str, Any],
                 second_path: Path | None = None,
                 build: Callable[[Path], dict[str, Any]] | None = None) -> dict[str, Any]:
    build = build or (lambda folder: build_dependency_graph(extract_repository_ast(str(folder), settings)))
    graphs: dict[str, dict[str, Any]] = {}
    files = []
    for entry in load_gold(gold_path):
        if entry["repo"] not in graphs:
            graphs[entry["repo"]] = build(Path(repos_dir) / entry["repo"].replace("/", "__"))
        result = score_file(predicted_triples(graphs[entry["repo"]], entry["path"]), entry["relations"])
        files.append({"repo": entry["repo"], "tag": entry["tag"], "path": entry["path"], **result})
    totals = {kind: micro(f["per_relation"][kind] for f in files) for kind in RELATIONS}
    output: dict[str, Any] = {"files": files, "per_relation": totals,
                              "overall": micro(f["per_relation"][k] for f in files for k in RELATIONS)}
    if second_path and Path(second_path).is_file():
        second = json.loads(Path(second_path).read_text(encoding="utf-8"))
        first = next((e for e in load_gold(gold_path) if e["path"] == second["path"]), None)
        if second.get("relations") and first:
            output["agreement"] = {"path": second["path"], "second_labeller": second.get("labeller"),
                                   **agreement(first["relations"], second["relations"])}
        else:
            output["agreement"] = {"path": second.get("path"), "status": "second labeller has not labelled yet"}
    return output


__all__ = ["agreement", "load_gold", "predicted_triples", "run_gold_set", "score_file", "scores"]
