## Extract Function
id: extract_function
kind: refactoring
graph_signals: [god_node, feature_envy]
relations: [CALLS]
sources: Martin Fowler, Refactoring, 2nd ed. (2018)
Move a coherent block into a named function while preserving its behavior. This can expose a responsibility that is currently buried in a large method. Keep the first extraction local and cover the old behavior with tests. **Minimal fix:** extract_function.

## Move Function
id: move_function
kind: refactoring
graph_signals: [feature_envy, cross_module_call]
relations: [CALLS]
sources: Martin Fowler, Refactoring, 2nd ed. (2018)
Move behavior to the module that owns the data or decisions it mostly uses. A cluster of cross-module calls can identify a candidate. Update callers in a small step and preserve a compatibility wrapper if needed. **Minimal fix:** move_function.

## Move Field
id: move_field
kind: refactoring
graph_signals: [feature_envy, global_state]
relations: [ACCESSES_GLOBAL, CALLS]
sources: Martin Fowler, Refactoring, 2nd ed. (2018)
Place data with the code that mainly manages it. This can reduce cross-boundary reads and writes. Move one field at a time and keep initialization and persistence behavior unchanged. **Minimal fix:** move_field.

## Extract Class
id: extract_class
kind: refactoring
graph_signals: [god_node, afferent_hub]
relations: [CONTAINS, CALLS]
sources: Martin Fowler, Refactoring, 2nd ed. (2018)
Separate a cohesive responsibility from an overloaded class. The new class should have a clear job, not just reduce line count. Move a small group of data and methods together and test the existing interface. **Minimal fix:** extract_class.

## Inline Class
id: inline_class
kind: refactoring
graph_signals: [added_dependency, low_risk]
relations: [CALLS]
sources: Martin Fowler, Refactoring, 2nd ed. (2018)
A class with almost no independent responsibility can add an unnecessary hop. Inline it only if its remaining behavior belongs naturally in a neighbor. Preserve externally visible behavior and imports during the change. **Minimal fix:** inline_class.

## Hide Delegate
id: hide_delegate
kind: refactoring
graph_signals: [cross_module_call, added_dependency]
relations: [CALLS]
sources: Martin Fowler, Refactoring, 2nd ed. (2018)
Let a module expose a small operation instead of making callers navigate its internals. This can reduce knowledge of a deep object chain. Avoid adding wrappers for every method; hide only the unstable detail. **Minimal fix:** hide_delegate.

## Introduce Parameter Object
id: introduce_parameter_object
kind: refactoring
graph_signals: [global_state, cross_module_call]
relations: [CALLS, ACCESSES_GLOBAL]
sources: Martin Fowler, Refactoring, 2nd ed. (2018)
Group related values that travel together into one named object. This can make a dependency clearer than several separate arguments or globals. Do it only when the values truly form one concept. **Minimal fix:** introduce_parameter_object.

## Replace Global with Parameter
id: replace_global_with_parameter
kind: refactoring
graph_signals: [global_state]
relations: [ACCESSES_GLOBAL]
sources: Martin Fowler, Refactoring, 2nd ed. (2018); Python documentation, Data model
Pass the needed state into a function instead of reading it implicitly. Callers and tests can then choose the value directly. Start at one access site and avoid threading a large object through unrelated layers. **Minimal fix:** replace_global_with_parameter.

## Dependency Inversion via Protocol
id: dependency_inversion
kind: refactoring
graph_signals: [instability_rise, cross_module_call, new_cycle]
relations: [IMPORTS, CALLS]
sources: Robert C. Martin, Design Principles and Design Patterns (2000); PEP 544
Define the small behavior needed by the caller, then let the implementation satisfy it. This can reverse a troublesome concrete dependency without changing the feature's outcome. Keep the protocol narrow enough to match real use. **Minimal fix:** dependency_inversion.

## Extract Shared Module to Break a Cycle
id: extract_shared_module
kind: refactoring
graph_signals: [new_cycle, mutual_import, import_cycle_member]
relations: [IMPORTS]
sources: Robert C. Martin, Design Principles and Design Patterns (2000)
Move the shared concept needed by both modules into a neutral third module. Both original modules can then depend in one direction. Move only truly shared code; a catch-all utility module can become another hub. **Minimal fix:** extract_shared_module.
