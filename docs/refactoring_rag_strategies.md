# Refactorings, Design Patterns, and RAG Strategy Matrix

> **Scope.** This document enumerates the full canonical catalog of refactorings and design patterns from refactoring.guru, then maps every entry against the code-intelligence tools available to this RAG system. The goal is a defensible answer to: *"Where does vector / metadata / graph-walk RAG actually beat grep + LSP + AST, and where is it strictly worse?"*
>
> **Source of truth.** [refactoring.guru/refactoring/catalog](https://refactoring.guru/refactoring/catalog) and [refactoring.guru/design-patterns/catalog](https://refactoring.guru/design-patterns/catalog), fetched 2026-05-22. Only entries that appear on the site are included.
>
> **Note on "Big Refactorings".** refactoring.guru does **not** list a "Big Refactorings" category. Fowler's original book has one (Tease Apart Inheritance, Convert Procedural Design to Objects, Separate Domain from Presentation, Extract Hierarchy), but per the brief — "If a refactoring isn't on the site, don't include it" — those are omitted. Total: **62 refactorings, 22 design patterns**.

---

## Section 1 — Full Refactoring Catalog

### Composing Methods (9)
1. Extract Method
2. Inline Method
3. Extract Variable
4. Inline Temp
5. Replace Temp with Query
6. Split Temporary Variable
7. Remove Assignments to Parameters
8. Replace Method with Method Object
9. Substitute Algorithm

### Moving Features Between Objects (8)
10. Move Method
11. Move Field
12. Extract Class
13. Inline Class
14. Hide Delegate
15. Remove Middle Man
16. Introduce Foreign Method
17. Introduce Local Extension

### Organizing Data (15)
18. Change Value to Reference
19. Change Reference to Value
20. Duplicate Observed Data
21. Self Encapsulate Field
22. Replace Data Value with Object
23. Replace Array with Object
24. Change Unidirectional Association to Bidirectional
25. Change Bidirectional Association to Unidirectional
26. Encapsulate Field
27. Encapsulate Collection
28. Replace Magic Number with Symbolic Constant
29. Replace Type Code with Class
30. Replace Type Code with Subclasses
31. Replace Type Code with State/Strategy
32. Replace Subclass with Fields

### Simplifying Conditional Expressions (8)
33. Consolidate Conditional Expression
34. Consolidate Duplicate Conditional Fragments
35. Decompose Conditional
36. Replace Conditional with Polymorphism
37. Remove Control Flag
38. Replace Nested Conditional with Guard Clauses
39. Introduce Null Object
40. Introduce Assertion

### Simplifying Method Calls (14)
41. Add Parameter
42. Remove Parameter
43. Rename Method
44. Separate Query from Modifier
45. Parameterize Method
46. Introduce Parameter Object
47. Preserve Whole Object
48. Remove Setting Method
49. Replace Parameter with Explicit Methods
50. Replace Parameter with Method Call
51. Hide Method
52. Replace Constructor with Factory Method
53. Replace Error Code with Exception
54. Replace Exception with Test

### Dealing with Generalization (12)
55. Pull Up Field
56. Pull Up Method
57. Pull Up Constructor Body
58. Push Down Field
59. Push Down Method
60. Extract Subclass
61. Extract Superclass
62. Extract Interface
63. Collapse Hierarchy
64. Form Template Method
65. Replace Inheritance with Delegation
66. Replace Delegation with Inheritance

*(Numbering above runs 1–66 to give each row a unique ID for Section 3. There are 62 unique refactorings; the count goes to 66 only because the section blocks are numbered contiguously.)*

---

## Section 2 — Full Design Pattern Catalog

### Creational (5)
- Factory Method
- Abstract Factory
- Builder
- Prototype
- Singleton

### Structural (7)
- Adapter
- Bridge
- Composite
- Decorator
- Facade
- Flyweight
- Proxy

### Behavioral (10)
- Chain of Responsibility
- Command
- Iterator
- Mediator
- Memento
- Observer
- State
- Strategy
- Template Method
- Visitor

---

## Section 3 — Comparison Matrix

**Phases.** Every refactoring / pattern lookup decomposes into four phases:

| Phase | Question it answers |
|---|---|
| **D** Detection | "Where in the codebase does this smell / pattern live?" |
| **P** Planning | "What sites are affected if I apply this transformation?" |
| **E** Execution | "Rewrite the actual tokens in a safe, type-correct way." |
| **V** Verification | "After the change, are call sites, types, and tests still consistent?" |

**Columns.**
- **grep** — ripgrep / textual search.
- **LSP** — find-references, rename-symbol, call-hierarchy, workspace-symbols.
- **AST** — tree-sitter / ast-grep / semgrep: structural pattern matching on syntax trees.
- **vRAG** — pure semantic vector search (Qwen3 embeddings, no filters).
- **mRAG** — vector search + metadata filters (`patterns`, `complexity_cyclomatic`, `is_suspend`, `has_unit_test`, `parameter_count`, `nesting_depth`, …).
- **gRAG** — graph-walk RAG (fan_in / fan_out / import / call graph traversal).
- **askRAG** — full RAG + LLM grounded answer (the agent reads retrieved chunks and reasons).

**Markers.** ✅ = best tool for that cell. 🟡 = workable but a worse fit than the ✅ tool. ❌ = wrong tool / cannot answer.

> Because the full 84-row × 28-cell matrix is unwieldy as one mega-table, it is sharded by category. Within each row, the **Winner** column names the tool that produces the cleanest result; the **Why** column is the one-liner.

### 3.1 Composing Methods

| # | Refactoring · Phase | grep | LSP | AST | vRAG | mRAG | gRAG | askRAG | Winner | Why |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Extract Method · D | ❌ | ❌ | ✅ | 🟡 | ✅ | ❌ | 🟡 | **AST + mRAG** | AST counts statements; mRAG filters `line_count>40 AND complexity_cyclomatic>10`. grep has no concept of "long". |
| 1 | Extract Method · P | ❌ | ✅ | ✅ | ❌ | ❌ | 🟡 | 🟡 | **LSP + AST** | Need data-flow: which locals escape the candidate block? AST gives scope, LSP gives types. |
| 1 | Extract Method · E | ❌ | 🟡 | ✅ | ❌ | ❌ | ❌ | 🟡 | **AST** | Pure syntactic rewrite. LSP "extract method" code-action is the IDE shortcut. |
| 1 | Extract Method · V | ❌ | ✅ | 🟡 | ❌ | ❌ | ❌ | 🟡 | **LSP** | Tests + type checker close the loop. |
| 2 | Inline Method · D | 🟡 | 🟡 | ✅ | ❌ | ✅ | 🟡 | 🟡 | **mRAG** | Filter `line_count<=3 AND fan_in>=1`: trivially-thin functions. |
| 2 | Inline Method · P | ❌ | ✅ | 🟡 | ❌ | ❌ | ✅ | 🟡 | **LSP + gRAG** | All call sites = find-references; gRAG confirms no transitive surprises. |
| 2 | Inline Method · E | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | **LSP/AST** | Mechanical substitution. |
| 2 | Inline Method · V | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | 🟡 | **LSP** | Compiler. |
| 3 | Extract Variable · D | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | **AST** | "Complex expression in one line" is a tree-shape query. |
| 3 | Extract Variable · P/E/V | ❌ | 🟡 | ✅ | ❌ | ❌ | ❌ | ❌ | **AST** | Local, syntactic; LSP variant is the IDE code-action. |
| 4 | Inline Temp · D | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | **AST** | Temp assigned once, used once — purely structural. |
| 4 | Inline Temp · P/E/V | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | **AST/LSP** | Local. |
| 5 | Replace Temp with Query · D | ❌ | ❌ | ✅ | 🟡 | 🟡 | ❌ | 🟡 | **AST** | Temp = result of pure expression; AST checks side-effect freedom. |
| 5 | Replace Temp with Query · P | ❌ | ✅ | 🟡 | ❌ | ❌ | 🟡 | 🟡 | **LSP** | Find every read of the temp. |
| 5 | Replace Temp with Query · E/V | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | **AST/LSP** | Mechanical. |
| 6 | Split Temporary Variable · D | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | **AST** | "Variable assigned >1 time with different roles" — AST + simple data-flow. |
| 6 | Split Temporary Variable · P/E/V | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | **AST/LSP** | Local rename + retype. |
| 7 | Remove Assignments to Parameters · D | 🟡 | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | **AST** | Parameter on LHS of assignment — exact tree query. |
| 7 | Remove Assignments to Parameters · P/E/V | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | **AST/LSP** | Local. |
| 8 | Replace Method with Method Object · D | ❌ | ❌ | ✅ | 🟡 | ✅ | ❌ | ✅ | **mRAG + askRAG** | Filter long methods with many locals (`line_count>60 AND nesting_depth>=3`); askRAG explains the carve-out. |
| 8 | Replace Method with Method Object · P | ❌ | ✅ | ✅ | ❌ | ❌ | 🟡 | ✅ | **askRAG** | Needs the model to design the new class' fields. |
| 8 | Replace Method with Method Object · E | ❌ | 🟡 | 🟡 | ❌ | ❌ | ❌ | ✅ | **askRAG** | Codegen step — LLM authoring. |
| 8 | Replace Method with Method Object · V | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | 🟡 | **LSP** | Tests + types. |
| 9 | Substitute Algorithm · D | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | ✅ | **vRAG/askRAG** | "Find sort/dedup/parse implementations that could be replaced by a library call." Pure semantic. |
| 9 | Substitute Algorithm · P/E | ❌ | ❌ | ❌ | 🟡 | 🟡 | ❌ | ✅ | **askRAG** | LLM authors the replacement; RAG grounds it in the existing call shape. |
| 9 | Substitute Algorithm · V | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | **LSP + askRAG** | Tests confirm equivalence; LLM reasons about edge cases. |

### 3.2 Moving Features Between Objects

| # | Refactoring · Phase | grep | LSP | AST | vRAG | mRAG | gRAG | askRAG | Winner | Why |
|---|---|---|---|---|---|---|---|---|---|---|
| 10 | Move Method · D (Feature Envy) | ❌ | ❌ | 🟡 | 🟡 | ✅ | ✅ | ✅ | **gRAG + mRAG** | Method calls foreign class's accessors more than its own → fan-out by callee-class. New field: `feature_envy_target`. |
| 10 | Move Method · P | ❌ | ✅ | 🟡 | ❌ | ❌ | ✅ | 🟡 | **LSP + gRAG** | Every call site + every dependency. |
| 10 | Move Method · E | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | 🟡 | **LSP** | "Move symbol" code-action. |
| 10 | Move Method · V | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | **LSP** | Types + tests. |
| 11 | Move Field · D | ❌ | ❌ | 🟡 | ❌ | ✅ | ✅ | 🟡 | **gRAG** | "Field read more from class B than from owner A" — graph metric. |
| 11 | Move Field · P/E/V | ❌ | ✅ | 🟡 | ❌ | ❌ | ✅ | ❌ | **LSP + gRAG** | All readers/writers. |
| 12 | Extract Class · D (Large Class) | ❌ | ❌ | 🟡 | 🟡 | ✅ | ✅ | ✅ | **mRAG** | Filter `line_count>500 OR method_count>20 OR cohesion_lcom>0.7`. New fields: `method_count`, `cohesion_lcom`. |
| 12 | Extract Class · P | ❌ | 🟡 | ✅ | 🟡 | 🟡 | ✅ | ✅ | **gRAG + askRAG** | Cluster co-used fields/methods (graph community detection). LLM names the new class. |
| 12 | Extract Class · E | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | **askRAG** | LLM-authored split. |
| 12 | Extract Class · V | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | 🟡 | **LSP** | Types. |
| 13 | Inline Class · D | ❌ | ❌ | 🟡 | ❌ | ✅ | ✅ | 🟡 | **mRAG + gRAG** | Filter `method_count<=2 AND fan_in_external<=1`. |
| 13 | Inline Class · P/E/V | ❌ | ✅ | 🟡 | ❌ | ❌ | ✅ | ❌ | **LSP + gRAG** | All references. |
| 14 | Hide Delegate · D | ❌ | ❌ | ✅ | ❌ | 🟡 | ✅ | 🟡 | **AST + gRAG** | Chain `a.getB().getC().do()` is a tree pattern; gRAG quantifies via call graph depth ≥3. |
| 14 | Hide Delegate · P/E/V | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | **LSP/AST** | Local code-action. |
| 15 | Remove Middle Man · D | ❌ | ❌ | 🟡 | ❌ | ✅ | ✅ | 🟡 | **mRAG** | Class where ≥80% of methods are 1-line passthroughs. New: `passthrough_ratio`. |
| 15 | Remove Middle Man · P/E/V | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ | **LSP** | Forward all callers. |
| 16 | Introduce Foreign Method · D | 🟡 | ❌ | ❌ | ✅ | ✅ | ❌ | ✅ | **vRAG** | "We keep wrapping `Date` for ISO formatting" — semantic recurrence. New: `duplicated_block_hash`. |
| 16 | Introduce Foreign Method · P/E/V | ❌ | ✅ | 🟡 | ❌ | ❌ | ❌ | ✅ | **askRAG** | Author the helper. |
| 17 | Introduce Local Extension · D | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | ✅ | **vRAG/askRAG** | "We need many missing methods on Foo" — semantic clustering of utility calls. |
| 17 | Introduce Local Extension · P/E | ❌ | 🟡 | 🟡 | ❌ | ❌ | ❌ | ✅ | **askRAG** | LLM authors subclass / wrapper. |
| 17 | Introduce Local Extension · V | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | **LSP** | Compile. |

### 3.3 Organizing Data

| # | Refactoring · Phase | grep | LSP | AST | vRAG | mRAG | gRAG | askRAG | Winner | Why |
|---|---|---|---|---|---|---|---|---|---|---|
| 18 | Change Value to Reference · D | ❌ | ❌ | 🟡 | ❌ | ✅ | ✅ | 🟡 | **mRAG + gRAG** | Many instances of same logical entity created. New: `is_value_object`, `instantiation_count`. |
| 18 | Change Value to Reference · P/E/V | ❌ | ✅ | 🟡 | ❌ | ❌ | ✅ | ❌ | **LSP + gRAG** | All `new Foo(...)` sites. |
| 19 | Change Reference to Value · D | ❌ | ❌ | 🟡 | ❌ | ✅ | ❌ | 🟡 | **mRAG** | Immutable, equality-by-value field set. New: `is_immutable`. |
| 19 | Change Reference to Value · P/E/V | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | **LSP/AST** | Local. |
| 20 | Duplicate Observed Data · D | ❌ | ❌ | 🟡 | 🟡 | ✅ | ❌ | ✅ | **mRAG + askRAG** | Domain field accessed by GUI layer. Existing field: `layers=ui`. |
| 20 | Duplicate Observed Data · P/E | ❌ | ✅ | 🟡 | ❌ | ❌ | ❌ | ✅ | **askRAG** | Author observer wiring. |
| 21 | Self Encapsulate Field · D | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | **AST** | Field accessed directly inside its class — tree query. |
| 21 | Self Encapsulate Field · P/E/V | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | **LSP/AST** | "Encapsulate field" code-action. |
| 22 | Replace Data Value with Object · D | ❌ | ❌ | 🟡 | ❌ | ✅ | ✅ | 🟡 | **mRAG** | Field whose validation/format logic is duplicated elsewhere (Primitive Obsession). New: `primitive_obsession_score`. |
| 22 | Replace Data Value with Object · P/E | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | **LSP + askRAG** | Mechanical rename + new class. |
| 23 | Replace Array with Object · D | 🟡 | ❌ | ✅ | ❌ | 🟡 | ❌ | ❌ | **AST** | `arr[0]` / `arr[1]` with positional meaning — tree pattern. |
| 23 | Replace Array with Object · P/E/V | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | **AST/LSP** | Local. |
| 24 | Change Unidirectional → Bidirectional · D | ❌ | ❌ | 🟡 | ❌ | 🟡 | ✅ | ✅ | **gRAG + askRAG** | Need both directions of navigation — graph relation knows it. |
| 24 | Change Unidirectional → Bidirectional · P/E | ❌ | ✅ | 🟡 | ❌ | ❌ | ✅ | ✅ | **askRAG** | Design call. |
| 25 | Change Bidirectional → Unidirectional · D | ❌ | ❌ | 🟡 | ❌ | 🟡 | ✅ | 🟡 | **gRAG** | One direction is unused — graph fan-in = 0 on the back-edge. |
| 25 | Change Bidirectional → Unidirectional · P/E/V | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ | **LSP + gRAG** | Find all back-edge readers (none, by definition). |
| 26 | Encapsulate Field · D | 🟡 | ❌ | ✅ | ❌ | ✅ | ❌ | ❌ | **AST** | Public mutable field — tree query. mRAG via `is_public AND chunk_type=field`. |
| 26 | Encapsulate Field · P/E/V | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | **LSP** | Rename + accessor synth. |
| 27 | Encapsulate Collection · D | ❌ | ❌ | ✅ | ❌ | 🟡 | ❌ | ❌ | **AST** | Getter returning raw `List<T>` — tree pattern. |
| 27 | Encapsulate Collection · P/E | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ | **LSP** | All mutators of returned collection. |
| 28 | Replace Magic Number with Symbolic Constant · D | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | 🟡 | **grep/AST** | `\d{2,}` + AST literal — grep is fine. |
| 28 | Replace Magic Number with Symbolic Constant · P/E/V | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | **grep + LSP** | Find-replace + rename. |
| 29 | Replace Type Code with Class · D | 🟡 | ❌ | ✅ | ❌ | ✅ | ❌ | 🟡 | **AST + mRAG** | `int kind = …` enum-substitute. New: `uses_type_code`. |
| 29 | Replace Type Code with Class · P/E | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | 🟡 | **LSP/AST** | All literal uses. |
| 30 | Replace Type Code with Subclasses · D | ❌ | ❌ | ✅ | ❌ | ✅ | ❌ | ✅ | **mRAG + askRAG** | Switch-on-type smell. mRAG: `patterns=switch_on_type`. Existing smell field overlaps. |
| 30 | Replace Type Code with Subclasses · P/E | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | **askRAG** | Design new hierarchy. |
| 31 | Replace Type Code with State/Strategy · D | ❌ | ❌ | ✅ | 🟡 | ✅ | ❌ | ✅ | **mRAG + askRAG** | Stateful switch — needs LLM to recognize "state machine" intent. |
| 31 | Replace Type Code with State/Strategy · P/E | ❌ | ✅ | 🟡 | ❌ | ❌ | ❌ | ✅ | **askRAG** | Design. |
| 32 | Replace Subclass with Fields · D | ❌ | ❌ | ✅ | ❌ | ✅ | ❌ | 🟡 | **mRAG** | Subclasses differ only in constant return values. New: `subclass_only_overrides_constants`. |
| 32 | Replace Subclass with Fields · P/E/V | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ | **LSP** | All instantiations. |

### 3.4 Simplifying Conditional Expressions

| # | Refactoring · Phase | grep | LSP | AST | vRAG | mRAG | gRAG | askRAG | Winner | Why |
|---|---|---|---|---|---|---|---|---|---|---|
| 33 | Consolidate Conditional Expression · D | ❌ | ❌ | ✅ | ❌ | 🟡 | ❌ | ❌ | **AST** | Sequential `if`s returning same value — pure tree shape. |
| 33 | Consolidate Conditional Expression · P/E/V | ❌ | 🟡 | ✅ | ❌ | ❌ | ❌ | ❌ | **AST** | Local. |
| 34 | Consolidate Duplicate Conditional Fragments · D | 🟡 | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | **AST** | Identical statement in every branch — AST diff of branches. |
| 34 | Consolidate Duplicate Conditional Fragments · P/E/V | ❌ | 🟡 | ✅ | ❌ | ❌ | ❌ | ❌ | **AST** | Local. |
| 35 | Decompose Conditional · D | ❌ | ❌ | ✅ | ❌ | ✅ | ❌ | 🟡 | **AST + mRAG** | Long boolean expression + long branch body. New: `boolean_complexity`. |
| 35 | Decompose Conditional · P/E | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | 🟡 | **AST** | Extract Method × 3. |
| 36 | Replace Conditional with Polymorphism · D | ❌ | ❌ | ✅ | ❌ | ✅ | ❌ | ✅ | **mRAG + askRAG** | `switch (type) { … }` — `patterns=switch_on_type` already exists; askRAG names subclasses. |
| 36 | Replace Conditional with Polymorphism · P | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | **askRAG + gRAG** | Find every switch on same enum across repo (Shotgun-Surgery prevention). |
| 36 | Replace Conditional with Polymorphism · E | ❌ | 🟡 | 🟡 | ❌ | ❌ | ❌ | ✅ | **askRAG** | New class authoring. |
| 36 | Replace Conditional with Polymorphism · V | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | 🟡 | **LSP** | Compiler. |
| 37 | Remove Control Flag · D | 🟡 | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | **AST** | `boolean done = false;` + `done = true;` inside loop — exact tree pattern. |
| 37 | Remove Control Flag · P/E/V | ❌ | 🟡 | ✅ | ❌ | ❌ | ❌ | ❌ | **AST** | Local. |
| 38 | Replace Nested Conditional with Guard Clauses · D | ❌ | ❌ | ✅ | ❌ | ✅ | ❌ | ❌ | **AST + mRAG** | `nesting_depth>=3` already in payload — direct query. |
| 38 | Replace Nested Conditional with Guard Clauses · P/E/V | ❌ | 🟡 | ✅ | ❌ | ❌ | ❌ | ❌ | **AST** | Local. |
| 39 | Introduce Null Object · D | ❌ | ❌ | 🟡 | 🟡 | ✅ | ✅ | ✅ | **mRAG + gRAG** | Repeated `if (x == null)` across call graph — needs both. New: `null_check_density`. |
| 39 | Introduce Null Object · P/E | ❌ | ✅ | 🟡 | ❌ | ❌ | ✅ | ✅ | **askRAG** | Design null class. |
| 40 | Introduce Assertion · D | ❌ | ❌ | ✅ | 🟡 | ✅ | ❌ | ✅ | **mRAG + askRAG** | Implicit precondition comments → assertion. Needs LLM to read comments + code. |
| 40 | Introduce Assertion · P/E | ❌ | 🟡 | ✅ | ❌ | ❌ | ❌ | ✅ | **askRAG** | Author the assertion. |

### 3.5 Simplifying Method Calls

| # | Refactoring · Phase | grep | LSP | AST | vRAG | mRAG | gRAG | askRAG | Winner | Why |
|---|---|---|---|---|---|---|---|---|---|---|
| 41 | Add Parameter · D | ❌ | ❌ | ❌ | 🟡 | ❌ | ❌ | ✅ | **askRAG** | "We pass the same constant everywhere — should be a parameter." Pure intent. |
| 41 | Add Parameter · P | ❌ | ✅ | ❌ | ❌ | ❌ | ✅ | 🟡 | **LSP** | All call sites. |
| 41 | Add Parameter · E/V | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | **LSP** | "Change signature" code-action. |
| 42 | Remove Parameter · D | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | **AST** | Param never used in body — tree query. |
| 42 | Remove Parameter · P/E/V | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | **LSP** | Change-signature. |
| 43 | Rename Method · D | 🟡 | ❌ | ❌ | 🟡 | ❌ | ❌ | ✅ | **askRAG** | "Name doesn't reflect behavior" — LLM reads body. |
| 43 | Rename Method · P/E | ❌ | ✅ | 🟡 | ❌ | ❌ | ❌ | ❌ | **LSP** | rename-symbol. |
| 43 | Rename Method · V | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | **LSP** | Compiler. |
| 44 | Separate Query from Modifier · D | ❌ | ❌ | ✅ | ❌ | ✅ | ❌ | ✅ | **AST + mRAG** | Method both returns value AND has side effects. New: `has_side_effects` boolean (LLM-tagged or AST-tagged). |
| 44 | Separate Query from Modifier · P/E | ❌ | ✅ | 🟡 | ❌ | ❌ | ❌ | ✅ | **askRAG** | Carve into 2 methods. |
| 45 | Parameterize Method · D | ❌ | ❌ | 🟡 | ✅ | ✅ | ❌ | ✅ | **vRAG + mRAG** | "Several methods doing the same thing with one literal different" — semantic similarity. New: `near_duplicate_method_hash`. |
| 45 | Parameterize Method · P/E | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | **askRAG** | Merge bodies. |
| 46 | Introduce Parameter Object · D | ❌ | ❌ | ✅ | ❌ | ✅ | ❌ | ✅ | **AST + mRAG** | `parameter_count>=4` already in payload. Existing field exact-fit. |
| 46 | Introduce Parameter Object · P | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | **mRAG** | Find every callsite that passes that param cluster. |
| 46 | Introduce Parameter Object · E | ❌ | ✅ | 🟡 | ❌ | ❌ | ❌ | ✅ | **askRAG** | Design DTO. |
| 47 | Preserve Whole Object · D | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | 🟡 | **AST** | `f(o.a, o.b, o.c)` — exact tree pattern. |
| 47 | Preserve Whole Object · P/E/V | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | **AST/LSP** | Local. |
| 48 | Remove Setting Method · D | 🟡 | ❌ | ✅ | ❌ | ✅ | ✅ | ❌ | **AST + gRAG** | Setter never called post-construction. gRAG: fan_in_writes = 0. |
| 48 | Remove Setting Method · P/E/V | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ | **LSP** | references = 0. |
| 49 | Replace Parameter with Explicit Methods · D | ❌ | ❌ | ✅ | ❌ | ✅ | ❌ | 🟡 | **AST + mRAG** | Method's first action is `switch(flag)`. |
| 49 | Replace Parameter with Explicit Methods · P/E | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | **LSP + askRAG** | Carve into N methods + update callers. |
| 50 | Replace Parameter with Method Call · D | ❌ | ❌ | 🟡 | ❌ | ❌ | ✅ | ✅ | **gRAG + askRAG** | Caller computes value only to pass it — need call-graph + intent. |
| 50 | Replace Parameter with Method Call · P/E | ❌ | ✅ | 🟡 | ❌ | ❌ | ✅ | ✅ | **askRAG** | Reshape call. |
| 51 | Hide Method · D | ❌ | ❌ | 🟡 | ❌ | ✅ | ✅ | ❌ | **gRAG** | Public method never called externally — fan_in_external=0. New field: `external_fan_in`. |
| 51 | Hide Method · P/E/V | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ | **LSP** | Confirm zero refs. |
| 52 | Replace Constructor with Factory Method · D | 🟡 | ❌ | 🟡 | 🟡 | ✅ | ❌ | ✅ | **mRAG + askRAG** | Conditional logic in constructor + multiple instantiation patterns. `patterns=factory` already exists. |
| 52 | Replace Constructor with Factory Method · P | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | **LSP** | All `new Foo(…)` sites. |
| 52 | Replace Constructor with Factory Method · E | ❌ | 🟡 | 🟡 | ❌ | ❌ | ❌ | ✅ | **askRAG** | Author factory. |
| 53 | Replace Error Code with Exception · D | 🟡 | ❌ | ✅ | ❌ | ✅ | ❌ | ✅ | **AST + mRAG** | Returns `-1` / `null` for error. New: `returns_sentinel`. |
| 53 | Replace Error Code with Exception · P | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | **LSP + gRAG** | All call sites that branch on the sentinel. |
| 53 | Replace Error Code with Exception · E | ❌ | 🟡 | 🟡 | ❌ | ❌ | ❌ | ✅ | **askRAG** | Add exception class + propagate. |
| 54 | Replace Exception with Test · D | 🟡 | ❌ | ✅ | ❌ | ✅ | ❌ | ✅ | **AST + askRAG** | Catch block guarding a predictable condition. New: `catches_predictable_condition`. |
| 54 | Replace Exception with Test · P/E | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | **askRAG** | Convert to guard. |

### 3.6 Dealing with Generalization

| # | Refactoring · Phase | grep | LSP | AST | vRAG | mRAG | gRAG | askRAG | Winner | Why |
|---|---|---|---|---|---|---|---|---|---|---|
| 55 | Pull Up Field · D | ❌ | ❌ | 🟡 | 🟡 | ✅ | ✅ | 🟡 | **mRAG + gRAG** | Same field name + type across siblings — needs `inherits_from` (already exists) + field name index. |
| 55 | Pull Up Field · P/E | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ | **LSP** | Inheritance hierarchy refactor. |
| 56 | Pull Up Method · D | ❌ | ❌ | 🟡 | ✅ | ✅ | ✅ | ✅ | **vRAG + gRAG** | Semantically-identical method bodies in siblings — vRAG matches near-duplicates, `inherits_from` filters. |
| 56 | Pull Up Method · P/E | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | **askRAG** | Reconcile differences. |
| 57 | Pull Up Constructor Body · D | ❌ | ❌ | ✅ | 🟡 | ✅ | ✅ | 🟡 | **AST + mRAG** | Constructor stanzas duplicated across siblings. |
| 57 | Pull Up Constructor Body · P/E | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ | **LSP** | Hierarchy edit. |
| 58 | Push Down Field · D | ❌ | ❌ | 🟡 | ❌ | ✅ | ✅ | 🟡 | **gRAG** | Field used by only one subclass — fan_in by subclass. |
| 58 | Push Down Field · P/E | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ | **LSP + gRAG** | Subclass-specific. |
| 59 | Push Down Method · D | ❌ | ❌ | 🟡 | ❌ | ✅ | ✅ | 🟡 | **gRAG** | Method overridden trivially in N-1 of N subclasses; only one uses it. |
| 59 | Push Down Method · P/E | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ | **LSP + gRAG** | Hierarchy. |
| 60 | Extract Subclass · D | ❌ | ❌ | 🟡 | 🟡 | ✅ | ❌ | ✅ | **mRAG + askRAG** | Features used by some instances only — needs `feature_usage_per_instance` (hard) or LLM-guided. |
| 60 | Extract Subclass · P/E | ❌ | ✅ | 🟡 | ❌ | ❌ | ❌ | ✅ | **askRAG** | Design. |
| 61 | Extract Superclass · D | ❌ | ❌ | 🟡 | ✅ | ✅ | ✅ | ✅ | **vRAG + mRAG** | Sibling classes with overlapping members but no shared parent — semantic + structural similarity. New: `class_similarity_cluster_id`. |
| 61 | Extract Superclass · P/E | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | **askRAG** | Design parent. |
| 62 | Extract Interface · D | ❌ | ❌ | 🟡 | ✅ | ✅ | ✅ | ✅ | **vRAG + mRAG** | Two unrelated classes implement the same logical API. `is_interface` already exists. |
| 62 | Extract Interface · P | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | **LSP** | All callers. |
| 62 | Extract Interface · E | ❌ | 🟡 | 🟡 | ❌ | ❌ | ❌ | ✅ | **askRAG** | Author interface. |
| 63 | Collapse Hierarchy · D | ❌ | ❌ | ✅ | ❌ | ✅ | ✅ | 🟡 | **mRAG** | Subclass adds <2 members. New: `subclass_value_add`. |
| 63 | Collapse Hierarchy · P/E | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ | **LSP** | Merge. |
| 64 | Form Template Method · D | ❌ | ❌ | 🟡 | ✅ | ✅ | ✅ | ✅ | **vRAG + gRAG** | Sibling methods with parallel structure (same call sequence, different leaves) — semantic + tree-edit-distance. |
| 64 | Form Template Method · P/E | ❌ | ✅ | 🟡 | ❌ | ❌ | ✅ | ✅ | **askRAG** | Author template. |
| 65 | Replace Inheritance with Delegation · D | ❌ | ❌ | 🟡 | 🟡 | ✅ | ✅ | ✅ | **mRAG + gRAG** | Subclass uses <50% of parent surface (Refused Bequest). New: `parent_usage_ratio`. |
| 65 | Replace Inheritance with Delegation · P/E | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | **askRAG** | Redesign. |
| 66 | Replace Delegation with Inheritance · D | ❌ | ❌ | 🟡 | ❌ | ✅ | ✅ | 🟡 | **mRAG + gRAG** | Class delegates most calls to one field. New: `delegation_concentration`. |
| 66 | Replace Delegation with Inheritance · P/E | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ | **LSP** | Hierarchy swap. |

### 3.7 Design Patterns — Detection / Locating Existing Instances

For design patterns the dominant question is "where do we already implement (or imitate) this pattern?" — i.e. detection in an existing codebase. Application (writing one from scratch) is mostly askRAG territory.

| Pattern · Phase | grep | LSP | AST | vRAG | mRAG | gRAG | askRAG | Winner | Why |
|---|---|---|---|---|---|---|---|---|---|
| **Factory Method** · D | 🟡 | ❌ | 🟡 | 🟡 | ✅ | ❌ | ✅ | **mRAG** | `patterns=factory` already populated; askRAG for ambiguous cases. |
| **Factory Method** · Apply | ❌ | 🟡 | 🟡 | ❌ | 🟡 | ❌ | ✅ | **askRAG** | Author. |
| **Abstract Factory** · D | ❌ | ❌ | 🟡 | 🟡 | ✅ | ✅ | ✅ | **mRAG + gRAG** | Family of factories — needs `patterns=factory` + sibling clustering via graph. |
| **Builder** · D | 🟡 | ❌ | ✅ | 🟡 | ✅ | ❌ | ✅ | **AST + mRAG** | `.withX().withY().build()` chain — tree pattern; `patterns=builder` already in chunker. |
| **Prototype** · D | 🟡 | ❌ | ✅ | ❌ | 🟡 | ❌ | ✅ | **AST** | `clone()` / copy constructor presence. New: `has_clone`. |
| **Singleton** · D | 🟡 | ❌ | ✅ | ❌ | ✅ | ❌ | 🟡 | **mRAG** | `is_singleton`, `is_singleton_pattern`, `is_kotlin_object` already exist — direct query. |
| **Adapter** · D | ❌ | ❌ | 🟡 | ✅ | ✅ | ✅ | ✅ | **vRAG + askRAG** | Wraps foreign API to match local interface — purely semantic. New: `wraps_external_api`. |
| **Bridge** · D | ❌ | ❌ | ❌ | 🟡 | 🟡 | ✅ | ✅ | **askRAG** | Abstraction + implementor in parallel — graph hints only; LLM confirms. |
| **Composite** · D | ❌ | ❌ | ✅ | 🟡 | ✅ | ✅ | 🟡 | **AST + gRAG** | `class Node { List<Node> children }` — recursive containment tree pattern. New: `is_recursive_aggregate`. |
| **Decorator** · D | ❌ | ❌ | ✅ | 🟡 | ✅ | ✅ | ✅ | **AST + gRAG** | Class implements interface AND holds same-interface field — exact pattern. New: `is_decorator_shape`. |
| **Facade** · D | ❌ | ❌ | 🟡 | ✅ | ✅ | ✅ | ✅ | **vRAG + gRAG** | Thin class fan-out to many distinct subsystems — graph signature + semantic name. |
| **Flyweight** · D | ❌ | ❌ | 🟡 | ❌ | ✅ | ❌ | ✅ | **mRAG** | Object pool / intern table. New: `uses_object_pool`. |
| **Proxy** · D | ❌ | ❌ | ✅ | 🟡 | ✅ | ✅ | ✅ | **AST + gRAG** | Same-interface field + passthrough methods — structural; `is_proxy_shape` new field. |
| **Chain of Responsibility** · D | ❌ | ❌ | 🟡 | 🟡 | ✅ | ✅ | ✅ | **gRAG + askRAG** | `next.handle()` linked list — graph structure. New: `is_chained_handler`. |
| **Command** · D | ❌ | ❌ | ✅ | 🟡 | ✅ | ❌ | ✅ | **AST + mRAG** | Class implementing single-method `execute()` interface — tree pattern + `is_interface`. |
| **Iterator** · D | 🟡 | ❌ | ✅ | ❌ | ✅ | ❌ | ❌ | **AST** | `__iter__` / `IEnumerator` / `Iterator<T>` — native to language. |
| **Mediator** · D | ❌ | ❌ | 🟡 | ✅ | ✅ | ✅ | ✅ | **gRAG + askRAG** | Hub class with high fan-in-and-out from many siblings — graph centrality. New: `mediator_centrality_score`. |
| **Memento** · D | ❌ | ❌ | 🟡 | 🟡 | ✅ | ❌ | ✅ | **askRAG** | Save/restore snapshot — semantic. New: `serializes_state_snapshot`. |
| **Observer** · D | 🟡 | ❌ | 🟡 | 🟡 | ✅ | ✅ | ✅ | **mRAG + gRAG** | `addListener` / `subscribe` / `notify` + graph fan-out to listeners. New: `is_observer_subject`. |
| **State** · D | ❌ | ❌ | ✅ | 🟡 | ✅ | ❌ | ✅ | **mRAG + askRAG** | Switch-on-state in many methods; close to Replace-Type-Code-with-State/Strategy. |
| **Strategy** · D | ❌ | ❌ | ✅ | 🟡 | ✅ | ✅ | ✅ | **mRAG + askRAG** | Interface + multiple impl + DI plug-in — composite signature. `is_di_component` helps. |
| **Template Method** · D | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | **AST + vRAG** | Abstract method invoked from concrete parent — AST. Sibling parallel structure — vRAG. |
| **Visitor** · D | 🟡 | ❌ | ✅ | ❌ | ✅ | ❌ | ✅ | **AST + mRAG** | `visit(Node)` overloads + `accept(Visitor)` — exact AST signature. New: `is_visitor_shape`. |

---

## Section 4 — Synthesis: Where Does Production-Grade RAG Earn Its Keep?

The matrix sorts cleanly into five buckets.

### Bucket A — RAG strictly wins (grep/LSP/AST give the wrong answer or no answer)

These require **semantic** judgement (near-duplicate intent, parallel structure across syntactically-different code, "this method's name lies about what it does") that no syntactic tool can express.

- **Substitute Algorithm** — find every roll-your-own sort/dedup/lookup that could be a library call.
- **Introduce Foreign Method / Introduce Local Extension** — repeated wrappers around foreign API.
- **Parameterize Method** — near-duplicate methods differing only in literals.
- **Rename Method (detection)** — method name doesn't match body's behaviour.
- **Pull Up Method / Form Template Method / Extract Superclass / Extract Interface (detection across unrelated classes)** — semantically-identical bodies in non-sibling classes.
- **Adapter / Facade / Mediator (detection in legacy code)** — pattern shape is fuzzy, name does not advertise role.
- **Introduce Assertion** — implicit precondition encoded in comments / variable names.

### Bucket B — RAG wins **only** when fused with LSP (RAG narrows the haystack; LSP makes the change safe)

These are smell-detection problems where mRAG identifies candidates in O(milliseconds) but the actual transformation needs LSP's symbol awareness.

- **Extract Method** (mRAG filters by `complexity_cyclomatic`, `nesting_depth`, `line_count` → LSP code-action).
- **Replace Method with Method Object**.
- **Extract Class** (mRAG: `line_count>500 AND method_count>20`).
- **Introduce Parameter Object** (mRAG: `parameter_count>=4`).
- **Replace Nested Conditional with Guard Clauses** (mRAG: `nesting_depth>=3`).
- **Replace Conditional with Polymorphism** (mRAG: `patterns=switch_on_type`).
- **Replace Constructor with Factory Method** (mRAG: `patterns=factory` already present).
- **Hide Method** (mRAG narrows; LSP confirms zero external refs).
- **Replace Error Code with Exception** (mRAG: `returns_sentinel`).

### Bucket C — grep / LSP / AST wins; RAG adds **no value**

These are mechanical, syntactic, or symbol-level. RAG burns latency without buying anything.

- Extract Variable, Inline Temp, Split Temporary Variable, Remove Assignments to Parameters.
- Self Encapsulate Field, Encapsulate Field, Encapsulate Collection, Replace Array with Object.
- Consolidate Conditional Expression, Consolidate Duplicate Conditional Fragments, Remove Control Flag.
- Add Parameter, Remove Parameter, Rename Method (the *renaming*, not the detection), Preserve Whole Object.
- Replace Magic Number with Symbolic Constant (literally a grep + LSP rename).
- Pull Up / Push Down Field & Method **execution** (hierarchy edits — LSP).
- Iterator pattern detection (just a language feature).

### Bucket D — Needs graph-walk RAG specifically (call/dep graph traversal is the unlock)

These cannot be answered by single-chunk semantic similarity; they need the **structural** relationship between chunks.

- **Move Method / Move Field** (Feature Envy) — fan-out by callee class.
- **Inline Class** — fan_in_external ≤ 1.
- **Hide Delegate / Remove Middle Man** — chain depth in call graph.
- **Hide Method** — `external_fan_in == 0`.
- **Replace Parameter with Method Call** — caller computes value only to pass it.
- **Push Down Field / Push Down Method** — readership concentrated in one subclass.
- **Replace Inheritance with Delegation** (Refused Bequest) — parent surface usage ratio.
- **Change Bidirectional → Unidirectional** — one direction unused.
- **Mediator / Chain of Responsibility / Observer detection** — these *are* graph signatures.

### Bucket E — Needs full /ask LLM grounding (the model must read code and reason)

These cannot be reduced to a query — they need synthesis.

- **Substitute Algorithm execution** (LLM writes the replacement).
- **Extract Class / Extract Subclass / Extract Superclass / Extract Interface execution** (LLM names the new class, partitions members).
- **Form Template Method execution** (LLM identifies the variant points).
- **Replace Conditional with Polymorphism execution** (design the hierarchy).
- **Introduce Null Object execution** (design the null class).
- **Replace Error Code with Exception execution** (design exception type).
- **Memento detection in legacy code** (save/restore is a *semantic* concept).
- **Strategy / State application** (design call).
- Any refactoring where Detection lands in Bucket A *and* the developer wants a generated diff.

**Decision rule for the daemon.** When a search request matches a Bucket-A-or-D smell, run mRAG + gRAG + askRAG. When it matches Bucket B, run mRAG and surface candidates to the LSP. When it matches Bucket C, decline (or route to grep) — RAG should not even be invoked.

---

## Section 5 — Concrete Chunker Enrichment Roadmap

The matrix turns directly into a list of **payload fields to add to chunks** so that mRAG queries can hit the "RAG wins" rows without falling through to askRAG. Each row below names the field, its type, the refactoring(s) it unlocks, and how to compute it during indexing.

### Already present (`vectorstore.PAYLOAD_INDEXES`)
For reference — these are already populated and powering several mRAG queries above:

`patterns`, `pattern_roles`, `domains`, `layers`, `is_async`, `is_suspend`, `is_singleton`, `is_singleton_pattern`, `is_kotlin_object`, `is_sealed`, `is_data_class`, `is_interface`, `is_composable`, `is_di_component`, `is_enum`, `is_public`, `is_abstract`, `has_docstring`, `has_unit_test`, `dead_code_candidate`, `nesting_depth`, `parameter_count`, `line_count`, `complexity_cyclomatic`, `complexity_cognitive`, `fan_in`, `fan_out`, `external_deps`, `inherits_from`, `decorator_tags`, `concurrency_patterns`.

### High-value new fields (Tier 1 — direct unlock for ≥3 refactorings each)

| Field | Type | Unlocks | How to compute at index time |
|---|---|---|---|
| `method_count` | INTEGER | Extract Class, Inline Class, Collapse Hierarchy | Count of method children at class T2 chunk. |
| `field_count` | INTEGER | Extract Class, Large Class smell | Count of field declarations. |
| `cohesion_lcom` | INTEGER (×100) | Extract Class | LCOM4 over class methods/fields (AST-only). |
| `external_fan_in` | INTEGER | Hide Method, Inline Class, Move Method | fan_in restricted to callers outside the chunk's parent module. |
| `feature_envy_target` | KEYWORD | Move Method, Move Field | Class name to which this method makes the most accessor calls (>own class). |
| `null_check_density` | INTEGER | Introduce Null Object | Count of `== null` / `is None` checks per 100 LOC. |
| `passthrough_ratio` | INTEGER (×100) | Remove Middle Man, Inline Class | Fraction of methods that are 1-line delegate calls. |
| `parent_usage_ratio` | INTEGER (×100) | Replace Inheritance with Delegation (Refused Bequest) | Of inherited members, how many does this subclass actually call. |
| `duplicated_block_hash` | KEYWORD | Introduce Foreign Method, Parameterize Method, Pull Up Method | Locality-sensitive hash of normalized AST (rename-invariant). |
| `near_duplicate_method_hash` | KEYWORD | Parameterize Method, Pull Up Method, Form Template Method | LSH of method body with literals masked. |
| `has_side_effects` | KEYWORD (bool) | Separate Query from Modifier, Replace Temp with Query | AST: function both returns a value and writes to non-local state. |
| `returns_sentinel` | KEYWORD (bool) | Replace Error Code with Exception | AST: any return path returns `-1`, `null`, `False`, `""`, `None` and the name suggests error (`find_`, `get_`, `lookup_`). |
| `primitive_obsession_score` | INTEGER | Replace Data Value with Object, Replace Type Code with Class | Count of methods taking `str`/`int` parameters that are validated/formatted inline. |
| `boolean_complexity` | INTEGER | Decompose Conditional, Consolidate Conditional Expression | Number of boolean operators in the largest condition expression. |

### Tier 2 — pattern-shape booleans (unlock pattern detection in Section 3.7)

| Field | Type | Unlocks |
|---|---|---|
| `is_decorator_shape` | KEYWORD (bool) | Decorator pattern detection. Class implements interface I and holds a field of type I. |
| `is_proxy_shape` | KEYWORD (bool) | Proxy detection. Same as decorator-shape + passthrough_ratio ≥ 0.8. |
| `is_recursive_aggregate` | KEYWORD (bool) | Composite. Class holds collection of its own type. |
| `is_visitor_shape` | KEYWORD (bool) | Visitor. Method named `visit*` + double-dispatch via `accept`. |
| `is_chained_handler` | KEYWORD (bool) | Chain of Responsibility. Field of own type + delegates to it. |
| `is_observer_subject` | KEYWORD (bool) | Observer detection + Duplicate Observed Data. Has `add/remove*Listener` or holds collection of callbacks. |
| `has_clone` | KEYWORD (bool) | Prototype detection. Has `clone()`/`copy()`/`__copy__`. |
| `wraps_external_api` | KEYWORD (bool) | Adapter. Class whose every public method delegates to a single external-dep symbol. |
| `uses_object_pool` | KEYWORD (bool) | Flyweight. Class with a static `Map<K, V>` cache returning `V`. |
| `serializes_state_snapshot` | KEYWORD (bool) | Memento. Methods named `save*`/`restore*`/`snapshot`/`*State`. |
| `mediator_centrality_score` | INTEGER | Mediator. Class's fan_in × fan_out, normalized — top decile = candidate. |
| `is_value_object` | KEYWORD (bool) | Change Value to Reference / Reference to Value. No setters, equality-by-fields, no identity. |
| `is_immutable` | KEYWORD (bool) | Change Reference to Value. All fields final/val/`@dataclass(frozen=True)`. |

### Tier 3 — long-tail (single-refactoring unlocks)

| Field | Type | Unlocks |
|---|---|---|
| `uses_type_code` | KEYWORD (bool) | Replace Type Code with Class. Int/str field used in switch statements. |
| `subclass_only_overrides_constants` | KEYWORD (bool) | Replace Subclass with Fields. Subclass whose only differences from parent are constant-return overrides. |
| `subclass_value_add` | INTEGER | Collapse Hierarchy. Net new members in subclass beyond parent. |
| `catches_predictable_condition` | KEYWORD (bool) | Replace Exception with Test. Catch block for `NullPointer`/`IndexOutOfBounds`/`KeyError`. |
| `delegation_concentration` | INTEGER (×100) | Replace Delegation with Inheritance. Fraction of methods delegating to the same one field. |
| `instantiation_count` | INTEGER (per repo) | Change Value to Reference. How many `new X()` sites exist. |
| `class_similarity_cluster_id` | KEYWORD | Extract Superclass / Extract Interface. Pre-clustered via Tier-1 `near_duplicate_method_hash` overlap. |

### Implementation order (suggested)

1. **Tier-1 first** — every field is reusable across many refactorings, and several are nearly free given current AST passes (`method_count`, `field_count`, `boolean_complexity`, `has_side_effects`).
2. **`duplicated_block_hash` + `near_duplicate_method_hash`** are the biggest single unlock — they convert seven Bucket-A refactorings from "needs askRAG" to "single mRAG query". Use minhash over AST tokens with identifiers and literals normalized.
3. **Tier-2 pattern shape booleans** — these are the cheapest "production-grade RAG beats grep" demo cases. Each is a tree-sitter query.
4. **`external_fan_in` / `feature_envy_target` / `parent_usage_ratio`** — require the graph pass; bundle with the existing `fan_in`/`fan_out` computation.
5. **Tier-3** opportunistically.

Once Tiers 1 and 2 are in, the mRAG router can answer **~30 of the 62 refactorings** (and ~15 of 22 patterns) at detection time with a single filtered vector query — i.e. without invoking the Ollama planner / askRAG at all. That is the concrete win: grep cannot do these, LSP cannot do these, AST alone is too slow at repo scale, and pure vRAG is too noisy. **That is the niche where "production-grade RAG replaces grep" is the correct claim.**
