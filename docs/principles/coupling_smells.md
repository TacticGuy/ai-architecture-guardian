## Cyclic Dependency
id: CYCLIC_DEPENDENCY
kind: smell
graph_signals: [new_cycle, import_cycle_member, mutual_import]
relations: [IMPORTS]
sources: Robert C. Martin, Design Principles and Design Patterns (2000)
A cycle lets a change in one module ripple back to itself through others. The graph can show the exact edges, but a reviewer still needs to check whether they are runtime or type-only imports. Break the smallest meaningful link, not every import in the component. **Minimal fix:** extract_shared_module.

## Hub-Like Dependency
id: HUB_DEPENDENCY
kind: smell
graph_signals: [afferent_hub, god_node]
relations: [IMPORTS, CALLS]
sources: Martin Fowler, Refactoring, 2nd ed. (2018)
A hub has many other modules depending on it. That can be appropriate for a stable shared utility, so high degree is a warning rather than a verdict. If unrelated responsibilities are mixed there, separate the smallest one. **Minimal fix:** split_module.

## Unstable Dependency
id: UNSTABLE_DEPENDENCY
kind: smell
graph_signals: [instability_rise, added_dependency]
relations: [IMPORTS, CALLS]
sources: Robert C. Martin, Design Principles and Design Patterns (2000)
A stable module may become harder to maintain when it reaches into a volatile neighbor. The increase in outgoing coupling shows where to investigate, not whether the neighbor is truly volatile. Put a narrow contract between them when the implementation varies. **Minimal fix:** dependency_inversion.

## God Class or Module
id: GOD_NODE
kind: smell
graph_signals: [god_node, afferent_hub]
relations: [CONTAINS, CALLS]
sources: Martin Fowler, Refactoring, 2nd ed. (2018)
An oversized class or module can collect unrelated decisions and collaborators. Many outgoing edges are a useful clue, but size alone does not prove a design problem. Identify one cohesive group of behavior before extracting it. **Minimal fix:** extract_class or split_module.

## Feature Envy
id: FEATURE_ENVY
kind: smell
graph_signals: [feature_envy, cross_module_call]
relations: [CALLS]
sources: Martin Fowler, Refactoring, 2nd ed. (2018)
A method may be misplaced when it uses another module's behavior more than its own. Cross-module calls show the candidate but do not reveal all data access. Move only the part that naturally belongs with the other data and keep tests around the public behavior. **Minimal fix:** move_function.

## Shotgun Surgery
id: SHOTGUN_SURGERY
kind: smell
graph_signals: [afferent_hub, added_dependency]
relations: [IMPORTS, CALLS]
sources: Martin Fowler, Refactoring, 2nd ed. (2018)
Shotgun surgery means one conceptual change requires edits in many places. A widely depended-on module can contribute to that pattern, but a single graph snapshot cannot establish it. Compare past diffs before consolidating the behavior. **Minimal fix:** move_function or extract_class.

## Divergent Change
id: DIVERGENT_CHANGE
kind: smell
graph_signals: [god_node, efferent_growth]
relations: [CALLS, IMPORTS]
sources: Martin Fowler, Refactoring, 2nd ed. (2018)
Divergent change means one module changes for several unrelated reasons. New dependencies can hint that it is taking on another role, but the history must confirm this. Split along responsibilities only after identifying those separate reasons. **Minimal fix:** extract_class or split_module.

## Global Mutable State
id: GLOBAL_MUTABLE_STATE
kind: smell
graph_signals: [global_state]
relations: [ACCESSES_GLOBAL]
sources: Python documentation, Data model; Martin Fowler, Refactoring, 2nd ed. (2018)
Shared mutable state can make behavior depend on call order. A global-access edge pinpoints a place to inspect, but an immutable constant is not the same risk. Encapsulate writes or pass state explicitly where practical. **Minimal fix:** encapsulate_variable or replace_global_with_parameter.

## Inappropriate Intimacy
id: INAPPROPRIATE_INTIMACY
kind: smell
graph_signals: [cross_module_call, added_dependency]
relations: [CALLS, IMPORTS]
sources: Martin Fowler, Refactoring, 2nd ed. (2018)
Modules become too intimate when they rely on each other's internal decisions. A new dependency is a lead, not proof that a private boundary was crossed. Move or hide the specific internal operation rather than adding a broad abstraction. **Minimal fix:** hide_delegate or move_function.

## Deep Inheritance
id: DEEP_INHERITANCE
kind: smell
graph_signals: [inheritance_coupling]
relations: [INHERITS]
sources: Martin Fowler, Refactoring, 2nd ed. (2018)
Each inheritance layer can make a child's behavior harder to trace. One new edge does not reveal the full depth, so inspect the chain before calling it a smell. If the child only needs one capability, delegation may be simpler. **Minimal fix:** replace_inheritance_with_composition.
