"""Orchestrate points 2–4: AST data, dependency graph, and node features."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.analysis.ast_parser import extract_repository_ast
from src.analysis.dependency_graph import build_dependency_graph
from src.analysis.features import create_node_features


def analyse_repository(repository_path: str | Path, output_directory: str | Path,
                       analysis_settings: dict[str, Any]) -> dict[str, Any]:
    """Perform static analysis and atomically persist all three reproducible artifacts."""
    ast_data = extract_repository_ast(repository_path, analysis_settings)
    graph = build_dependency_graph(ast_data)
    features = create_node_features(graph)
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(output / "ast.json", ast_data)
    _write_json_atomic(output / "dependency_graph.json", graph)
    _write_json_atomic(output / "node_features.json", features)
    return {"ast": ast_data, "graph": graph, "features": features}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
