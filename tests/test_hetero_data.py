"""Point 5: dependency graphs become PyTorch Geometric HeteroData with a fixed schema."""
from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("torch_geometric")

from torch_geometric.data import Batch  # noqa: E402

from src.analysis.pipeline import analyse_repository  # noqa: E402
from src.ml.hetero_data import (  # noqa: E402
    EDGE_TYPES, NODE_TYPES, TENSOR_FEATURE_NAMES, build_hetero_data, load_hetero_data, save_hetero_data,
)


def analysis_settings() -> dict:
    return {"include_tests": False, "max_python_files_per_repository": 50,
            "excluded_directory_names": [".git", "__pycache__", ".venv"]}


def write(root, relative: str, text: str = "") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def analyse(tmp_path, name: str = "repo") -> dict:
    return analyse_repository(tmp_path / name, tmp_path / f"{name}_out", analysis_settings())


def make_package(tmp_path, name: str = "repo") -> dict:
    write(tmp_path, f"{name}/src/pkg/__init__.py", "")
    write(tmp_path, f"{name}/src/pkg/base.py", "class Base:\n    def ping(self, value, *args):\n        return value\n")
    write(tmp_path, f"{name}/src/pkg/core.py",
          "import os\nfrom .base import Base\n\n"
          "class Engine(Base):\n    def run(self):\n        self.ping(1)\n        return os.getcwd()\n\n"
          "def helper():\n    return Engine()\n")
    return analyse(tmp_path, name)


def to_hetero(result: dict):
    return build_hetero_data(result["graph"], result["features"])


def row_of(data, node_type: str, node_id: str) -> list[float]:
    return data[node_type].x[data[node_type].node_ids.index(node_id)].tolist()


def test_all_node_types_exist_with_15_float_columns(tmp_path):
    data = to_hetero(make_package(tmp_path))
    assert set(data.node_types) == set(NODE_TYPES)
    for node_type in NODE_TYPES:
        x = data[node_type].x
        assert x.dtype == torch.float32 and x.shape[1] == 15
        assert x.shape[0] == len(data[node_type].node_ids)
    assert data["module"].x.shape[0] == 3
    assert data["external_module"].x.shape[0] == 1     # os


def test_empty_node_types_still_have_the_right_shape(tmp_path):
    write(tmp_path, "repo/only.py", "def lonely():\n    return 1\n")
    data = to_hetero(analyse(tmp_path))
    assert tuple(data["class"].x.shape) == (0, 15)
    assert data["class"].node_ids == []


def test_feature_columns_follow_the_named_order(tmp_path):
    result = make_package(tmp_path)
    data = to_hetero(result)
    assert data.feature_names == list(TENSOR_FEATURE_NAMES) and "node_type" not in data.feature_names
    record = next(n for n in result["features"]["nodes"] if n["node_id"].endswith("pkg.base.Base.ping"))
    expected = [float(record["features"][name]) for name in TENSOR_FEATURE_NAMES]
    assert row_of(data, "method", record["node_id"]) == expected
    assert expected[TENSOR_FEATURE_NAMES.index("parameter_count")] == 3.0   # self, value, *args


def test_edges_land_in_the_right_store_with_the_right_endpoints(tmp_path):
    data = to_hetero(make_package(tmp_path))

    def pairs(edge_type):
        source_type, _, target_type = edge_type
        index = data[edge_type].edge_index
        return {(data[source_type].node_ids[s], data[target_type].node_ids[t]) for s, t in index.t().tolist()}

    assert ("src/pkg/core.py:pkg.core", "src/pkg/base.py:pkg.base") in pairs(("module", "IMPORTS", "module"))
    assert ("src/pkg/core.py:pkg.core", "external_module:os") in pairs(("module", "IMPORTS", "external_module"))
    assert ("src/pkg/core.py:pkg.core.Engine", "src/pkg/base.py:pkg.base.Base") in pairs(("class", "INHERITS", "class"))
    assert ("src/pkg/core.py:pkg.core.Engine.run", "external_callable:os.getcwd") in pairs(("method", "CALLS", "external_callable"))
    assert ("src/pkg/core.py:pkg.core.helper", "src/pkg/core.py:pkg.core.Engine") in pairs(("function", "CALLS", "class"))
    assert ("src/pkg/core.py:pkg.core.Engine", "src/pkg/core.py:pkg.core.Engine.run") in pairs(("class", "CONTAINS", "method"))


def test_every_edge_type_exists_and_every_graph_edge_is_kept(tmp_path):
    result = make_package(tmp_path)
    data = to_hetero(result)
    assert set(data.edge_types) == set(EDGE_TYPES)
    for edge_type in EDGE_TYPES:
        index = data[edge_type].edge_index
        assert index.dtype == torch.long and index.shape[0] == 2
    assert sum(data[edge_type].edge_index.shape[1] for edge_type in EDGE_TYPES) == len(result["graph"]["edges"])
    assert ("function", "INHERITS", "class") not in data.edge_types  # only classes inherit


def test_two_different_graphs_can_be_batched(tmp_path):
    first = to_hetero(make_package(tmp_path, "repo_a"))
    write(tmp_path, "repo_b/tiny.py", "def lonely():\n    return 1\n")
    second = to_hetero(analyse(tmp_path, "repo_b"))
    batch = Batch.from_data_list([first, second])
    assert batch.num_graphs == 2
    assert batch["function"].x.shape[0] == first["function"].x.shape[0] + second["function"].x.shape[0]
    assert batch["function"].batch.tolist().count(1) == second["function"].x.shape[0]


def test_save_then_load_gives_the_same_graph(tmp_path):
    data = to_hetero(make_package(tmp_path))
    path = tmp_path / "pyg" / "graph.pt"
    save_hetero_data(data, path)
    loaded = load_hetero_data(path)
    assert not path.with_suffix(".pt.tmp").exists()
    for node_type in NODE_TYPES:
        assert torch.equal(loaded[node_type].x, data[node_type].x)
        assert loaded[node_type].node_ids == data[node_type].node_ids
    for edge_type in EDGE_TYPES:
        assert torch.equal(loaded[edge_type].edge_index, data[edge_type].edge_index)
    assert loaded.feature_names == data.feature_names


def test_graphs_outside_the_schema_are_rejected_clearly(tmp_path):
    result = make_package(tmp_path)
    graph, features = result["graph"], result["features"]
    missing = dict(graph, edges=graph["edges"] + [{"source": "nowhere", "target": graph["nodes"][0]["id"], "type": "CALLS"}])
    with pytest.raises(ValueError, match="unknown node"):
        build_hetero_data(missing, features)
    module_id = next(n["id"] for n in graph["nodes"] if n["type"] == "module")
    odd = dict(graph, edges=graph["edges"] + [{"source": module_id, "target": module_id, "type": "INHERITS"}])
    with pytest.raises(ValueError, match="not in the HeteroData schema"):
        build_hetero_data(odd, features)
    bad_type = dict(graph, nodes=graph["nodes"] + [{"id": "x", "type": "lambda"}])
    with pytest.raises(ValueError, match="Unknown node type"):
        build_hetero_data(bad_type, features)
