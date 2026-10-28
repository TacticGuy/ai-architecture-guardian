# Hand-labelled gold set (Task 1c)

`gold.json` lists, for six real files from six pinned repositories, every CALLS, INHERITS and
ACCESSES_GLOBAL relation that starts in that file. The labels were written by reading the
source, before looking at our graph's output for that file.

`second_labeller.json` is for the agreement check. A second person labels
`starlette/config.py` on their own (about 15 minutes), following the rules below and without
looking at `gold.json`. Then run `scripts/validate_graph_v5.py`, which reports their agreement.

## Rules

Names are dotted import names (`package.module.Class.method`); a nested function is
`outer.inner`. The source is the scope where the code runs:

* code in a function or method: that function or method;
* code at module level, including `if __name__ == "__main__":`: the module;
* code in a class body, including **default argument values** and decorators of its
  methods: the class (Python evaluates these once, when the class body runs).

**CALLS**: a call whose callee a careful reader can name, defined in the repository's own
packages. Calling a class (instantiation) targets the class. `self.m()` / `super().m()` target
the class that actually defines `m`. A method on an object whose type is clear from the code
(a parameter annotated `Console`, a value built with `Text(...)`) counts. Calls to the
standard library, third-party code and builtins are left out, as are dynamic calls
(`cast(value)` where `cast` is a parameter).

**INHERITS**: every base class, internal or external. External bases use their defining
module (`builtins.ValueError`, `collections.abc.MutableMapping`). `also_accept` lists other
correct spellings of the same base (an alias, or a choice made at import time).

**ACCESSES_GLOBAL**: a read or write of a module-level variable (an assignment at module
level, not a `def` or `class`) of the repository, after its defining assignment. Names used
only in type annotations are left out. They are type information, not data flow. Under
`from __future__ import annotations` they are never evaluated. Without it, a signature's
annotations are evaluated once when the `def` runs, not when the function is called.
