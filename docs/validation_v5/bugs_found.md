# Graph-builder bugs found during validation (v5)

Found while checking the graph against PyCG, grimp and the hand-labelled gold set. **None of
these is fixed here.** They are reported for Harsha to fix in the graph builder (`src/analysis/`),
so the dataset and the code stay consistent.

Each example is a single file `pkg/m.py` (next to an empty `pkg/__init__.py`), run through
`extract_repository_ast` and `build_dependency_graph` on branch `update/dashboard` at
`b95ca14`. "Got" is the actual output and "expected" is the correct relation. All examples
were re-run on 2026-10-28, after the B2 fix: B2 is fixed, and the other eight behave as
described.

Severity is the effect on what the model sees. **High** means wrong edges in common code.
**Medium** means edges missing in common code. **Low** means rare code or an attribution
convention.

## B1. Builtin base classes are dropped (INHERITS, medium)

```python
class E(ValueError):
    pass
```
Got: no INHERITS edge. Expected: `pkg.m.E -INHERITS-> builtins.ValueError`.
Non-builtin external bases are kept (`collections.abc.MutableMapping`,
`urllib3.exceptions.HTTPError`), so only builtins are lost. Seen in the gold set: 8 of 9
missed INHERITS edges (`requests/exceptions.py`, `starlette/config.py`). Exception
hierarchies lose their link to `Exception`/`ValueError`/`OSError`/`Warning`.

## B2. Type annotations count as global accesses (ACCESSES_GLOBAL, high). FIXED

**Status:** fixed on `update/dashboard`. Re-checked on 2026-10-28: the example below now gives
no edge. In the gold set, all 5 annotation false positives are gone (ACCESSES_GLOBAL precision
went from 40% to 80%), and no other edge changed.

```python
from __future__ import annotations
T = int

def f(x: T) -> T:
    return x
```
Got: `pkg.m.f -ACCESSES_GLOBAL-> pkg.m.T`. Expected: none. The annotation is never evaluated
here. Even without the future import, a signature's annotations are evaluated once when the
`def` runs, not by `f`. This was 5 of the 6 false ACCESSES_GLOBAL edges in the gold set:
`SchemaType` (marshmallow, which is only defined under `TYPE_CHECKING`), `T` (starlette),
and `AlignMethod` and `RenderResult` (rich). Type aliases and `TypeVar`s become fake
coupling between every annotated function and the module that defines the alias.

## B3. Default argument values are read in the wrong scope (ACCESSES_GLOBAL, low/medium)

```python
environ = {}

class C:
    def __init__(self, environ=environ):
        self.environ = environ
```
Got: no edge. Expected: `pkg.m.C -ACCESSES_GLOBAL-> pkg.m.environ`. The default value runs
in the class body, where `environ` is the global, but the parameter of the same name hides it
(starlette `Config`). Related convention (not a wrong edge): `def m(self, a=X)` gives
`C.m -> X`, while Python reads `X` in the class body (`C -> X`). This happened once in the
gold set (flask `_sentinel`).

## B4. `super().method()` becomes a fake external node (CALLS, medium)

```python
class A:
    def __init__(self):
        pass

class B(A):
    def __init__(self):
        super().__init__()
```
Got: `pkg.m.B.__init__ -CALLS-> super.__init__` (an `external_callable`). Expected:
`pkg.m.B.__init__ -CALLS-> pkg.m.A.__init__`. All `super()` calls share one invented external
node, `super.__init__`, which links unrelated classes in the GNN. Seen in flask `Blueprint`.

## B5. A method name unique in the repository captures calls on other types (CALLS, high)

```python
class Emoji:
    def replace(self):
        pass

def f(s: str):
    return s.replace("a", "b")
```
Got: `pkg.m.f -CALLS-> pkg.m.Emoji.replace`. Expected: none (`str.replace`). When an
attribute call cannot be typed, a method name defined only once in the repository seems to
be used as the target. In rich, `title_text.plain.replace(...)` became
`Rule.__rich_console__ -> rich.emoji.Emoji.replace`. This is the only false CALLS edge in the
gold set. It also explains why `Text.expand_tabs` (a unique name) resolved while
`Text.truncate` and `Text.append` (names shared with other classes) did not.

## B6. A call on an instance imported from another module becomes a fake external node (CALLS, medium)

```python
# pkg/a.py
class S:
    def run(self):
        pass

s = S()

# pkg/m.py
from pkg.a import s

def f():
    s.run()
```
Got: `pkg.m.f -CALLS-> pkg.a.s.run` (an `external_callable` whose name looks internal, and
which does not exist). Expected: `pkg.m.f -CALLS-> pkg.a.S.run`. The same happens in PyCG's
`imports/init_import` snippet. The same-module case (`s = S(); s.run()`) is resolved
correctly. Related, trigger not isolated: in `rich/rule.py`, `console.print(...)` in the
`__main__` block became an external node `console.print`, even though `console = Console()`
is in the same file. A minimal copy of that pattern resolves correctly.

## B7. Module-level reads of module-level variables have no edge (ACCESSES_GLOBAL, low)

```python
x = 1
print(x)
```
Got: no edge. Expected: `pkg.m -ACCESSES_GLOBAL-> pkg.m.x`. A function reading `x` does get
the edge. *Calling* a module-level variable at module level also does (PyCG
`direct_calls/assigned_call`), so the rule is inconsistent. This happened twice in the gold
set (rich's `__main__` block).

## B8. A decorator factory call is charged to the decorated function (CALLS, low)

```python
def deco():
    def d(f):
        return f
    return d

@deco()
def g():
    pass
```
Got: `pkg.m.g -CALLS-> pkg.m.deco`. Expected: `pkg.m -CALLS-> pkg.m.deco`. The decorator runs
once, in the enclosing scope, when `g` is defined. `g` itself never calls `deco`. This came up
in PyCG `decorators/return` and `decorators/return_different_func`.

## B9. An explicit `Base.method(self)` to an inherited method becomes a fake external node (CALLS, low)

```python
class A:
    def __init__(self):
        pass

class B(A):
    pass

class C(B):
    def __init__(self):
        B.__init__(self)
```
Got: `pkg.m.C.__init__ -CALLS-> B.__init__` (an `external_callable`). Expected:
`pkg.m.C.__init__ -CALLS-> pkg.m.A.__init__`. Lookup does not walk the class hierarchy. Seen
in requests `JSONDecodeError.__init__`.

## Not bugs, recorded so nobody "fixes" them

* `flask/sansio/` has no `__init__.py` (an implicit namespace package). We include it and
  grimp does not. All 27 flask disagreements with grimp come from this, and ours is right.
* A class without `__init__`, when instantiated, has no `__init__` edge. That matches PyCG,
  since the callee is `object.__init__`.
