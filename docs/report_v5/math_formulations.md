# Mathematical formulations for AI Architecture Guardian v5

These definitions follow `src/analysis/ast_parser.py`, `dependency_graph.py`,
`src/dataset/module_graph.py`, `structural_metrics.py`, and `future_coupling.py`.
The graph and labels are computed from repository snapshots; no future snapshot is
used as a prediction-time feature.

## AST to typed dependency graph

Let $G=(V,E,\tau_V,\tau_E)$ be a directed typed graph. The node-type map
$\tau_V$ takes values in {module, class, function, method, external_module,
external_callable, global_variable}. The edge-type map $\tau_E$ takes values
in {CONTAINS, IMPORTS, CALLS, INHERITS, ACCESSES_GLOBAL}.

* $(u,v,\mathrm{CONTAINS})\in E$ when the parser records $u$ as the lexical
  parent of $v$. This connects a module to its classes/functions and a class to
  its methods.
* $(u,v,\mathrm{IMPORTS})\in E$ when code owned by $u$ imports a name resolved
  to module $v$. Unresolved third-party names may use external-module nodes.
* $(u,v,\mathrm{CALLS})\in E$ when a call expression in $u$ resolves to callable
  $v$. Resolution is static and therefore cannot capture every dynamic call.
* $(u,v,\mathrm{INHERITS})\in E$ when class $u$ names class $v$ as a resolved
  base class.
* $(u,v,\mathrm{ACCESSES\_GLOBAL})\in E$ when function or method $u$ reads or
  writes a resolved module-level variable $v$.

Let $M$ be the project-module nodes and $o:V\to M\cup\{\bot\}$ map each
project symbol to its containing module. The module dependency graph has
$a\to b$ iff there is a dependency edge $(u,v)\in E$ with $o(u)=a$,
$o(v)=b$, and $a\ne b$. For future coupling the dependency relations are
IMPORTS, CALLS, INHERITS, and ACCESSES_GLOBAL; CONTAINS is not a dependency.
Duplicate module pairs count as one edge.

## Structural metrics

For the **module-import** graph used by `structural_metrics.py`, let $n$ be
its number of modules and $m$ its number of distinct non-self import edges.
The formulas below use this import projection, not the broader future-coupling
projection above.

$$D=\frac{m}{n(n-1)},\qquad C_{out}(v)=\frac{\deg^+(v)}{n-1}.$$

Both are defined as zero when $n\leq1$. Density is the fraction of possible
directed links present; out-degree centrality is the share of possible targets
that one module imports.

For the undirected projection, let $N(v)$ be the neighbors of $v$ and $e_v$
the number of undirected links between those neighbors. Then
$c(v)=2e_v/(|N(v)|(|N(v)|-1))$ when $|N(v)|\geq2$, otherwise zero, and
$\bar c=n^{-1}\sum_v c(v)$ for $n>0$. This measures how often a module's
neighbors are also connected to each other.

For incident degree $d(v)=\deg^+(v)+\deg^-(v)$, put
$p_v=d(v)/\sum_u d(u)$ when at least one edge exists. The normalized entropy is

$$H=-\frac{1}{\log_2 n}\sum_{v:d(v)>0}p_v\log_2 p_v.$$

The implementation returns zero when $n\leq1$ or $m=0$. Entropy describes how
evenly edge incidence is distributed, not whether the code is good. Tarjan's
algorithm counts strongly connected components containing at least two modules
or a self-loop. For every reported metric $X$, the PR delta is
$\Delta X=X_{after}-X_{before}$.

## Bounds and identities

For a simple directed graph without self-loops there are at most $n(n-1)$
edges, so $0\leq D\leq1$. Likewise $0\leq\deg^+(v)\leq n-1$, giving
$0\leq C_{out}(v)\leq1$. At most $\binom{|N(v)|}{2}$ neighbor pairs can be
connected, giving $0\leq c(v),\bar c\leq1$. Shannon entropy of a distribution
on $n$ values lies between zero and $\log_2 n$, so $0\leq H\leq1$ for
$n\geq2$.

Every directed edge contributes one incoming and one outgoing incidence:
$\sum_v C_a(v)=\sum_v C_e(v)=m$. Thus mean total coupling is
$\bar C=\frac1n\sum_v(C_a(v)+C_e(v))=2m/n$.
For $m>0$, $H=1$ iff all **incident degrees** are equal, because Shannon
entropy is maximal only for a uniform positive distribution. The unconditional
version of this claim is false for an edgeless graph: all degrees are zero but
the implementation defines $H=0$. This necessary qualification is explicit.

## Six-month future-coupling label

Let $T$ be touched modules still present at merge and at the future snapshot,
and $C_t(u)=C_a^t(u)+C_e^t(u)$. Define

$$g=\frac1{|T|}\sum_{u\in T}(C_{future}(u)-C_{merge}(u)),\quad
\Delta=\bar C_{future}-\bar C_{merge},\quad e=g-\Delta.$$

The label is $y=\mathbf1[e>\theta\ \lor\ \exists u\in T:\ u\text{ joins a new
cyclic import SCC}]$, with $\theta=0.5$. If no touched module survives, the
implementation returns no label rather than guessing. A PR-created cycle is
not the target: it can be found directly by graph search and appeared in only
3 of 260 pilot PRs in the project work package.

If every module's total coupling grows by the same amount $c$ **and the module
set is unchanged**, then $g=c$ and $\Delta=c$, so $e=0$. If new dependency
edges touch no module in $T$, their contributions to $g$ are zero while
$\bar C=2m/n$ increases for a **fixed module set**; therefore $e$ cannot
increase. With added or removed modules, the changing denominator $n$ can
invalidate both shortcuts, so they must not be claimed without that condition.

## Integrated Gradients and faithfulness

For a differentiable score $F$ and baseline $x'$, attribution to input feature
$i$ is

$$IG_i(x)=(x_i-x'_i)\int_0^1
\frac{\partial F(x'+\alpha(x-x'))}{\partial x_i}\,d\alpha.$$

Under the usual smoothness conditions, the chain rule and fundamental theorem
of calculus give $\sum_i IG_i=F(x)-F(x')$ (completeness). The intended baseline
is the training-set mean feature vector, fitted without test data. The
unfaithfulness score is $1-\exp[-KL(p\,\|\,p_{masked})]$; lower means the
masked explanation retains more of the model prediction. This is a model
faithfulness measure, not proof that the predicted future is correct.
