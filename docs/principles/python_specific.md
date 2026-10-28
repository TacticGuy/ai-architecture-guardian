## Local Import Hiding a Cycle
id: LOCAL_IMPORT_CYCLE
kind: smell
graph_signals: [new_cycle, mutual_import, import_cycle_member]
relations: [IMPORTS]
sources: Python documentation, The import system; Robert C. Martin (2000)
A local import may postpone a circular import error without removing the design cycle. The two modules still know about each other. Check whether a neutral shared module or a passed-in dependency would remove the relationship. **Minimal fix:** extract_shared_module.

## Package Init Re-Export Hub
id: INIT_REEXPORT_HUB
kind: smell
graph_signals: [afferent_hub, import_cycle_member]
relations: [IMPORTS]
sources: Python documentation, The import system
A package initializer that re-exports many symbols can become a central import path. This is convenient for users, but it can obscure the module that owns a symbol. Keep public re-exports deliberate and avoid importing back through the package root internally. **Minimal fix:** split_module.

## Module-Level Singleton
id: MODULE_SINGLETON
kind: smell
graph_signals: [global_state, afferent_hub]
relations: [ACCESSES_GLOBAL]
sources: Python documentation, Data model
One shared mutable instance can silently connect otherwise separate functions. Tests may then depend on execution order. Pass a narrow instance or encapsulate its lifecycle when multiple callers need it. **Minimal fix:** replace_global_with_parameter.

## Protocol for a Narrow Dependency
id: PYTHON_PROTOCOL
kind: principle
graph_signals: [cross_module_call, instability_rise]
relations: [CALLS, IMPORTS]
sources: PEP 544, Protocols: Structural subtyping
A typing.Protocol describes the operations a caller needs without requiring a shared base class. It can help policy code depend on a stable contract instead of one concrete implementation. Keep the protocol small and test runtime behavior separately. **Minimal fix:** dependency_inversion.

## Type-Only Import
id: TYPE_ONLY_IMPORT
kind: principle
graph_signals: [import_cycle_member, mutual_import]
relations: [IMPORTS]
sources: Python documentation, typing.TYPE_CHECKING; The import system
Some imports exist only to annotate types and need not run at import time. Guarding a true type-only import can avoid a runtime cycle, but it does not remove conceptual coupling. Check the code path before proposing this as the whole fix. **Minimal fix:** extract_shared_module.

## Explicit Configuration Value
id: EXPLICIT_CONFIGURATION
kind: principle
graph_signals: [global_state]
relations: [ACCESSES_GLOBAL]
sources: Python documentation, Data model
Configuration stored in a mutable module global can be hard to vary in tests. A function parameter or small configuration object makes the dependency visible. Avoid passing the entire application state for one value. **Minimal fix:** replace_global_with_parameter.

## Avoid Import-Time Side Effects
id: IMPORT_SIDE_EFFECT
kind: smell
graph_signals: [import_cycle_member, added_dependency]
relations: [IMPORTS]
sources: Python documentation, The import system
Imports are easiest to reason about when they primarily define names. Import-time registration or initialization can make a new edge change behavior unexpectedly. Move the side effect to an explicit startup function if the code requires ordering. **Minimal fix:** extract_function.

## Keep Public Package API Small
id: PACKAGE_API
kind: principle
graph_signals: [afferent_hub, added_dependency]
relations: [IMPORTS]
sources: Python documentation, Packages
A package root can be a useful public entry point without exposing every internal helper. A broad API makes later moves more disruptive. Re-export only stable names and let internal modules import their owners directly. **Minimal fix:** split_module.

## Avoid Hidden Registry Coupling
id: HIDDEN_REGISTRY
kind: smell
graph_signals: [global_state, cross_module_call]
relations: [ACCESSES_GLOBAL, CALLS]
sources: Python documentation, Data model
A global registry can make a function depend on modules it never names directly. The graph's global-access edge marks a place worth inspecting. Prefer explicit registration at startup or inject the needed registry into the caller. **Minimal fix:** replace_global_with_parameter.

## Prefer Cohesive Python Modules
id: COHESIVE_MODULE
kind: principle
graph_signals: [god_node, efferent_growth, feature_envy]
relations: [CONTAINS, IMPORTS, CALLS]
sources: Robert C. Martin (2000); Martin Fowler, Refactoring, 2nd ed. (2018)
A Python module can hold several related functions without needing a class. When unrelated features accumulate there, new imports and calls can make it harder to change. Extract one cohesive group instead of splitting solely by file length. **Minimal fix:** split_module.
