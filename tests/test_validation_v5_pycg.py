import json

from src.validation_v5.pycg_bench import (
    discover_snippets, evaluate_snippet, gold_edges, is_internal, module_names, our_call_edges,
)

SETTINGS = {"include_tests": False, "max_python_files_per_repository": 100,
            "excluded_directory_names": [], "excluded_file_names": []}


def node(qualified_name, node_type):
    return {"id": f"x.py:{qualified_name}", "type": node_type, "qualified_name": qualified_name}


def test_class_call_becomes_init_and_class_without_init_is_dropped():
    graph = {"nodes": [node("main", "module"), node("main.A", "class"), node("main.A.__init__", "method"),
                       node("main.B", "class")],
             "edges": [{"source": "x.py:main", "target": "x.py:main.A", "type": "CALLS"},
                       {"source": "x.py:main", "target": "x.py:main.B", "type": "CALLS"},
                       {"source": "x.py:main", "target": "x.py:main.A", "type": "CONTAINS"}]}
    assert our_call_edges(graph) == {("main", "main.A.__init__")}


def test_module_names_follow_pycg(tmp_path):
    for path in ("main.py", "__init__.py", "nested/__init__.py", "nested/to_import.py"):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("")
    assert module_names(tmp_path) == {"main", "__init__", "nested", "nested.to_import"}


def test_external_gold_callees_are_dropped_and_counted():
    callgraph = {"main": ["main.func", "<builtin>.print", "os.path.join"], "main.func": []}
    edges, dropped = gold_edges(callgraph, {"main"})
    assert edges == {("main", "main.func")}
    assert dropped == 2
    assert is_internal("main.A.f", {"main"}) and not is_internal("mainly.f", {"main"})


def test_evaluate_snippet_end_to_end(tmp_path):
    snippet = tmp_path / "classes" / "instance"
    snippet.mkdir(parents=True)
    (snippet / "main.py").write_text("class MyClass:\n    def __init__(self):\n        pass\n\n"
                                     "    def func(self):\n        pass\n\na = MyClass()\na.func()\nprint(a)\n")
    (snippet / "callgraph.json").write_text(json.dumps({
        "main": ["main.MyClass.__init__", "main.MyClass.func", "<builtin>.print"],
        "main.MyClass.__init__": [], "main.MyClass.func": []}))
    assert discover_snippets(tmp_path) == [("classes", "instance", snippet)]
    row = evaluate_snippet(snippet, SETTINGS)
    assert (row["tp"], row["fp"], row["fn"], row["gold_external_dropped"]) == (2, 0, 0, 1)


def test_evaluate_snippet_scores_a_given_prediction(tmp_path):
    (tmp_path / "main.py").write_text("def f():\n    pass\n")
    (tmp_path / "callgraph.json").write_text(json.dumps({"main": ["main.f"], "main.f": []}))
    row = evaluate_snippet(tmp_path, SETTINGS, predicted={("main", "main.g"), ("main", "ext.thing")})
    assert (row["tp"], row["fp"], row["fn"]) == (0, 1, 1)  # the external prediction is ignored
    assert row["extra"] == [["main", "main.g"]]
