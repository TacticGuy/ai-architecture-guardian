## Acyclic Dependencies Principle
id: ADP
kind: principle
graph_signals: [new_cycle, import_cycle_member, mutual_import]
relations: [IMPORTS]
sources: Robert C. Martin, Design Principles and Design Patterns (2000)
Module dependencies should not form cycles. A cycle makes it harder to understand and change one module without considering the others. Inspect the exact import path before changing code, because an apparent cycle can sometimes be harmless type-only use. **Minimal fix:** extract_shared_module or dependency_inversion.

## Stable Dependencies Principle
id: SDP
kind: principle
graph_signals: [instability_rise, added_dependency]
relations: [IMPORTS, CALLS]
sources: Robert C. Martin, Design Principles and Design Patterns (2000)
Dependencies should generally point toward modules that are less likely to change. A new outgoing link from a heavily used module can make that module less stable. Compare incoming and outgoing dependencies, then check actual responsibilities before moving the link. **Minimal fix:** dependency_inversion.

## Stable Abstractions Principle
id: SAP
kind: principle
graph_signals: [afferent_hub, cross_module_call]
relations: [CALLS, IMPORTS]
sources: Robert C. Martin, Design Principles and Design Patterns (2000)
A module used by many others should offer stable abstractions rather than expose volatile details. An incoming hub is not a defect by itself, but it has a larger blast radius. Keep the stable contract small and isolate replaceable implementations. **Minimal fix:** split_protocol or dependency_inversion.

## Common Closure Principle
id: CCP
kind: principle
graph_signals: [feature_envy, cross_module_call]
relations: [CALLS]
sources: Robert C. Martin, Design Principles and Design Patterns (2000)
Code that tends to change together should be organized together. A method that mostly calls another module may sit on the wrong side of the boundary. Look at change history before moving it, because one cross-module call is not enough evidence. **Minimal fix:** move_function.

## Common Reuse Principle
id: CRP
kind: principle
graph_signals: [afferent_hub, god_node]
relations: [IMPORTS, CALLS]
sources: Robert C. Martin, Design Principles and Design Patterns (2000)
Users of a package should not be forced to depend on things they never use. A large hub can make unrelated clients share the same release and test burden. Split the public surface along genuine reuse groups, not just graph size. **Minimal fix:** split_module.

## Efferent Coupling
id: EFFERENT_COUPLING
kind: principle
graph_signals: [efferent_growth]
relations: [IMPORTS, CALLS, INHERITS, ACCESSES_GLOBAL]
sources: Robert C. Martin, Design Principles and Design Patterns (2000)
Efferent coupling counts the modules a module depends on. Growth means the changed area may need more coordination when its dependencies evolve. Review whether each new dependency belongs there before proposing a refactor. **Minimal fix:** move_function or dependency_inversion.

## Afferent Coupling
id: AFFERENT_COUPLING
kind: principle
graph_signals: [afferent_hub]
relations: [IMPORTS, CALLS]
sources: Robert C. Martin, Design Principles and Design Patterns (2000)
Afferent coupling counts the modules that depend on this module. High incoming coupling can be healthy for a stable utility, but it increases the cost of breaking changes. Favor a small, tested interface at this boundary. **Minimal fix:** split_protocol.

## Instability Measure
id: INSTABILITY
kind: principle
graph_signals: [instability_rise, efferent_growth]
relations: [IMPORTS, CALLS]
sources: Robert C. Martin, Design Principles and Design Patterns (2000)
Instability is Ce divided by Ca plus Ce, when the denominator is nonzero. A rise means the module relies on more others relative to how many rely on it. Treat this as a clue to inspect, not a stand-alone quality score. **Minimal fix:** dependency_inversion.

## Break a Module Cycle at Its Cause
id: CYCLE_BOUNDARY
kind: principle
graph_signals: [new_cycle, mutual_import]
relations: [IMPORTS]
sources: Robert C. Martin, Design Principles and Design Patterns (2000)
A two-way dependency often means both modules need something owned by the other. Moving shared types or behavior to a third, neutral module can restore one-way flow. Avoid a local import that merely hides the cycle without changing the design. **Minimal fix:** extract_shared_module.

## Keep Reuse Direction Clear
id: REUSE_DIRECTION
kind: principle
graph_signals: [added_dependency, cross_module_call]
relations: [IMPORTS, CALLS]
sources: Robert C. Martin, Design Principles and Design Patterns (2000)
Shared code should serve its users without depending back on them. A new reverse edge can turn a useful library into a tangled feature module. Check the actual call before moving it; some dependencies are deliberate. **Minimal fix:** dependency_inversion or move_function.
