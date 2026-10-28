## Single Responsibility Principle
id: SRP
kind: principle
graph_signals: [god_node, feature_envy]
relations: [CALLS, CONTAINS]
sources: Robert C. Martin, Design Principles and Design Patterns (2000)
A module is easier to change when it has one clear reason to change. A node that coordinates many unrelated collaborators may be carrying several responsibilities. Inspect the behavior before splitting it; a high degree alone is not proof. **Minimal fix:** extract_function or extract_class.

## Open-Closed Principle
id: OCP
kind: principle
graph_signals: [efferent_growth, cross_module_call]
relations: [CALLS, INHERITS]
sources: Robert C. Martin, Design Principles and Design Patterns (2000)
Stable behavior should be extendable without repeatedly changing its core. A new cross-module call may reveal that a central module needs editing for each new case. Introduce a small extension point only when the diff shows repeated variation. **Minimal fix:** dependency_inversion or extract_function.

## Liskov Substitution Principle
id: LSP
kind: principle
graph_signals: [inheritance_coupling]
relations: [INHERITS]
sources: Robert C. Martin, Design Principles and Design Patterns (2000)
A subtype should keep the promises of its parent type. New inheritance links can make behavior fragile if callers need special cases for one child. The graph flags where to inspect, but tests of the behavioral contract decide whether this principle is actually at risk. **Minimal fix:** replace_inheritance_with_composition.

## Interface Segregation Principle
id: ISP
kind: principle
graph_signals: [god_node, cross_module_call]
relations: [CALLS]
sources: Robert C. Martin, Design Principles and Design Patterns (2000)
Clients should depend on only the operations they use. A broad shared interface can pull unrelated modules together. Check which methods each caller needs before creating narrower protocols. **Minimal fix:** split_protocol.

## Dependency Inversion Principle
id: DIP
kind: principle
graph_signals: [cross_module_call, instability_rise, added_dependency]
relations: [CALLS, IMPORTS]
sources: Robert C. Martin, Design Principles and Design Patterns (2000)
Policy code should not be tightly tied to one low-level implementation. A new direct dependency from policy to infrastructure can make both harder to change. A small protocol owned by the caller can separate the contract from its implementation. **Minimal fix:** dependency_inversion.

## Prefer Explicit Dependencies
id: EXPLICIT_DEPENDENCIES
kind: principle
graph_signals: [global_state, added_dependency]
relations: [ACCESSES_GLOBAL, IMPORTS]
sources: Robert C. Martin, Design Principles and Design Patterns (2000); Python documentation, typing module
Inputs are easier to test when callers can see them. Reading shared mutable state hides a dependency from a function's signature. Pass the required value or a narrow service explicitly if the change is local enough. **Minimal fix:** replace_global_with_parameter.

## Keep Policy Separate from Mechanism
id: POLICY_BOUNDARY
kind: principle
graph_signals: [cross_module_call, efferent_growth]
relations: [CALLS, IMPORTS]
sources: Robert C. Martin, Design Principles and Design Patterns (2000)
Business decisions and low-level mechanisms tend to change for different reasons. A new direct call across that boundary can make a policy module sensitive to infrastructure changes. First identify the boundary in the actual code, then move a small operation behind it. **Minimal fix:** dependency_inversion.

## Composition Before Deep Inheritance
id: COMPOSITION
kind: principle
graph_signals: [inheritance_coupling]
relations: [INHERITS]
sources: Martin Fowler, Refactoring, 2nd ed. (2018)
Inheritance shares behavior but also binds a child to a parent's choices. A new cross-module inheritance edge deserves a review of the contract and future change points. A delegated object can be smaller and more flexible when only one behavior is reused. **Minimal fix:** replace_inheritance_with_composition.

## Narrow Module Boundaries
id: NARROW_BOUNDARY
kind: principle
graph_signals: [afferent_hub, efferent_growth]
relations: [IMPORTS, CALLS]
sources: Robert C. Martin, Design Principles and Design Patterns (2000)
Modules with many incoming and outgoing dependencies are expensive places to change. A single new edge is not automatically harmful, but repeated growth can create a bottleneck. Keep a public boundary small and move unrelated operations closer to their users. **Minimal fix:** move_function or split_module.

## Test the Contract, Not the Shape
id: CONTRACT_TESTS
kind: principle
graph_signals: [inheritance_coupling, low_risk]
relations: [INHERITS, CALLS]
sources: Robert C. Martin, Design Principles and Design Patterns (2000)
Graph evidence shows relationships, not whether behavior is correct. A low-risk score does not prove a new dependency is harmless. When inheritance or an interface changes, test what callers may rely on before recommending a larger refactor. **Minimal fix:** add_contract_test.
