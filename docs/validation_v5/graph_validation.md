# Graph validation against established tools (v5, Mandatory 1)

**Question.** Does our AST-based dependency graph get its edges right? We measured each edge
type against an independent reference and report precision (P), recall (R) and F1. Full
tables: `data/validation_v5/results.md`. Every disagreement is listed in `results.json`.

**Reproduce.** `python scripts/validate_graph_v5.py --pycg-dir <PyCG clone> --repos-dir <checkouts> --pycg-python <Python 3.10 with PyCG> --out data/validation_v5/`

## Method

| Edge type | Reference | Data |
|---|---|---|
| CALLS | PyCG micro-benchmark: hand-written `callgraph.json` per program [1] | 119 snippets in 18 categories (PyCG commit `8d5dc40`) |
| IMPORTS | grimp, the import graph behind import-linter [2] | 10 repositories at pinned tags (table below) |
| CALLS, INHERITS, ACCESSES_GLOBAL | Hand-labelled gold set (`tests/fixtures/validation_v5/`) | 6 real files from 6 repositories, 99 relations |

Both sides are reduced to the same unit before comparing:
* **PyCG:** internal (caller, callee) name pairs. Instantiating a class counts as a call to its
  `__init__`, as PyCG writes it. External callees (`<builtin>.*`, the standard library) are
  dropped from the ground truth, because our graph has no nodes for them.
* **grimp:** internal module → module pairs, with module names normalised (a `src.` prefix is
  stripped).
* **Gold set:** (relation, source, target) triples, under rules written down before scoring
  (`README.md` in the fixtures folder).

All scores are micro-averaged. **The PyCG programs and the 10 repositories are not our
dataset.** This measures the extraction *method* on independent code, not the 6,141 PRs.

## Results

| Check | Precision | Recall | F1 |
|---|---|---|---|
| CALLS vs PyCG micro-benchmark (ours) | 97.2 | 43.6 | 60.2 |
| CALLS, PyCG itself on the same benchmark (run here [1]) | 95.9 | 87.7 | 91.6 |
| IMPORTS vs grimp, 10 repositories | 97.7 | 100.0 | 98.8 |
| IMPORTS vs grimp, modules both tools scan | 100.0 | 100.0 | 100.0 |
| Gold set: CALLS | 97.9 | 88.7 | 93.1 |
| Gold set: INHERITS | 100.0 | 76.3 | 86.6 |
| Gold set: ACCESSES_GLOBAL | 80.0 | 50.0 | 61.5 |

The ACCESSES_GLOBAL row is after the fix for bug B2 (annotations). Before that fix it was
40.0 / 50.0 / 44.4. No other number in this table changed with the fix.

Repositories and tags for grimp: flask 3.1.3, click 8.5.0, requests v2.34.2, httpx 0.28.1,
rich v15.0.0, attrs 26.1.0, starlette 1.10.0, black 26.10.1, marshmallow 4.3.1 and typer 0.27.3.
The commit of each is in `results.json`.

## Error analysis

* **IMPORTS are reliable.** All 27 disagreements come from flask, where `flask/sansio/` is an
  implicit namespace package (it has no `__init__.py`). grimp does not scan it and we do. On
  modules both tools see, the two graphs are identical in all 10 repositories (1,159 edges). We
  checked every disagreement in flask, requests and click; requests and click have none.
* **CALLS edges are precise, but recall is limited** to what plain AST name resolution can see.
  On PyCG, 106 of 109 predicted edges are right. Misses concentrate where values flow through
  data or returns: `assignments` 0%, `dicts` 26%, `kwargs` 20%, `builtins` 20% and `lambdas` 36%
  recall, against 93% for `imports` and 67% for `classes`. On real code (the gold set) recall is
  much higher, at 88.7%, because most calls there are direct. All 3 PyCG false positives, and the
  only gold-set one, are real bugs (B5, B6, B8 in `bugs_found.md`).
* **PyCG itself, run on the same benchmark with the same conversion**, reaches 95.9% precision
  and 87.7% recall (213 of 243 gold edges, 9 false positives). The precision of the two is about
  the same, and the recall gap is the price of not tracking values: PyCG follows assignments,
  returns, containers and lambdas, and we do not. PyCG is weakest on `imports` (43% recall),
  where we reach 93%. This is a fair comparison of name resolution only: PyCG was built for this
  benchmark, and it produces call graphs, not the typed multi-relation graph the model needs.
* **INHERITS misses only builtin bases.** 8 of the 9 misses are `ValueError`, `OSError`,
  `Warning` and similar: builtin bases are dropped (B1). Every internal base and every
  non-builtin external base was found.
* **ACCESSES_GLOBAL is the weakest relation**, and the sample is small (8 gold relations). In
  the first run, 5 of the 6 false positives were names used only in type annotations (B2).
  After the fix, all 5 are gone and precision went from 40% to 80%, with nothing else changed.
  The one remaining false positive is a default argument read charged to the method instead
  of the class body (B3). The misses come from default argument values (B3) and module-level
  code (B7).

Nine extraction bugs, each with a minimal example, are in `bugs_found.md`. They were reported
to the graph-builder owner, not fixed here, so that the dataset and the code stay consistent.
B2 has since been fixed in the graph builder, and the tables above were re-run after that fix.

## Limitations

* **PyCG row.** PyCG (commit `8d5dc40`, version 0.0.8) was run in a separate Python 3.10
  environment, because it does not support newer Python versions, with each snippet's `main.py`
  as entry point, as its own tests do. Its output went through the same conversion as ours. Its
  measured numbers differ from the paper's abstract (precision ~99.2%, recall ~69.9%) because
  the paper also counts external callees, which we drop on both sides.
* **Gold set.** The gold set is small (6 files, 99 relations) and was labelled by one person.
  The second-labeller agreement on `starlette/config.py` is reported once
  `second_labeller.json` is filled in. The labels are a careful reading, not executed ground truth.
* **Recall ceiling.** Static name resolution cannot see dynamic dispatch, monkey-patching or
  values passed around in containers. For coupling this mostly means *missing* edges, which
  makes our coupling measures conservative.

## References

[1] V. Salis, T. Sotiropoulos, P. Louridas, D. Spinellis, D. Mitropoulos. "PyCG: Practical Call
Graph Generation in Python." ICSE 2021. arXiv:2103.00587. The abstract reports precision ~99.2%
and recall ~69.9%. Benchmark: https://github.com/vitsalis/PyCG (`micro-benchmark/`).
[2] grimp, https://github.com/python-grimp/grimp (version 3.18), the graph library used by
import-linter: https://import-linter.readthedocs.io.
