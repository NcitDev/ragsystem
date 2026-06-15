# I Benchmarked 4 Local Code Search Tools on a 10,000-File Android Monorepo: Here's What I Learned

Context windows are getting massive. We hear constantly that you can "just drop your entire repo into a 1M token window" and let the LLM sort it out. But if you work on a production codebase—like a 10,000-file Android monorepo—you know this is a lie. It's slow, it's expensive, and it inevitably leads to the "Lost in the Middle" hallucination problem.

To build a truly autonomous coding agent, we need smart retrieval. The agent must be able to pinpoint exact symbols, trace architectural dependencies, and understand semantic intent—all without human hand-holding.

I set out to test the current state of local codebase retrieval. I took the **Dodo Pizza Android project** (5,099 code files, 3.3 million tokens) and benchmarked four different search strategies against 7 real-world developer tasks.

Here is what I found.

## The Contenders

1.  **Vanilla (`ripgrep`)**: The developer's baseline. Fast regex matching.
2.  **`ast-index`**: A specialized, SQLite-backed symbol index built from Abstract Syntax Trees.
3.  **Graphify**: A local `tree-sitter` extraction tool that builds a queryable knowledge graph (nodes and edges for calls, imports, inheritance).
4.  **Agentic RAG (+ AST)**: A custom system using a local LLM (`qwen3:8b` via Ollama) as a "pre-retrieval planner," connected to both an AST SQLite index and a Qdrant vector database.

## The Benchmark Tasks

I designed 7 tasks ranging from simple definition lookups to complex architectural tracing.

| Task | Prompt | Expected Files |
| :--- | :--- | :--- |
| **1. Exact Symbol** | Find the definition of `CheckoutOrderProcessingService`. | `CheckoutOrderProcessingService.kt` |
| **2. Semantic Intent** | Find where the app waits for a paid order to complete and resets the state. | `CheckoutOrderProcessingService.kt` |
| **3. Deep Architecture** | Trace the path from `DeferredTimeFragment` to `CheckoutService`. | `CheckoutStateService.kt`, `CheckoutServiceImpl.kt` |
| **4. Dependency Injection** | How is `CheckoutOrderProcessingService` provided to the DI graph? | `CheckoutStateModule.kt` |
| **5. Blast Radius** | If I change the `StateAnalyzer` interface, what feature modules are impacted? | `*FeatureDependencies.kt` |
| **6. Test Coverage** | Find the state-changing checkout payment functions and their nearby unit tests. | `WhenChargePayment.kt`, etc. |
| **7. Deprecation Hunt** | Find all deprecated code pointing to `setupAppStateForNewOrder`. | `CheckoutService.kt` |

---

## Initial Results: The "Dumb" Search Problem

Before implementing the Agentic Planner, the results were highly polarized. 

`ast-index` was incredibly fast (~15ms) and 100% precise for Task 1 (Exact Symbol). But it completely failed Task 2 (Semantic Intent) because it doesn't understand English.
Vanilla `ripgrep` found the files, but routinely dumped thousands of tokens of useless noise into the context pack.
Graphify struggled to pinpoint exact leaf-node implementation files, but excelled at mapping out the broad architecture.

### The Problem with Standard RAG
Initially, our RAG system performed poorly on architectural tasks (Task 4: Dependency Injection). It suffered from "Scattergun Retrieval." When asked to connect `StateAnalyzer` to `CheckoutService`, it asked the AST index for both symbols, which returned dozens of test files and mock objects. It blew up the token count (over 4,000 tokens) without providing a clean path.

Graphify, acting like a GPS, executed a shortest-path graph traversal and found the bridge in 1,500 tokens.

## The Breakthrough: The "Unified Knowledge Bridge"

To fix the RAG system, I made two critical architectural changes.

### 1. DI-Aware Chunking (Making RAG Graph-Aware)
I modified our `tree-sitter` extraction engine to natively understand Dagger/Hilt. When the indexer parses a Kotlin file, it now explicitly extracts `@Provides` and `@Inject` relationships into the SQLite metadata.

```python
# Extracting Dependency Injection during chunking
if "@Provides" in cleaned:
    meta["is_di_provider"] = "true"
    provides_kt = re.findall(r"@Provides[\s\S]*?fun\s+\w+\s*\([^)]*\)\s*:\s*([A-Z]\w+)", cleaned)
    if provides_kt:
        meta["provides"] = list(set(provides_kt))
```

Now, when the RAG system indexes `CheckoutStateModule.kt`, the database *literally knows* it `provides: ["CheckoutOrderProcessingService"]`. This closed the gap between RAG's precision and Graphify's architectural awareness.

### 2. The Local LLM Planner
I put `qwen3:8b` strictly at the front of the pipeline. Instead of passing the user's raw prompt into the vector database, the LLM reads the prompt and outputs a JSON Search Plan:

```json
{
  "queries": ["waitForPayedOrder", "setupAppStateForNewOrder"],
  "strategy": "filtered",
  "filters": {"language": "kotlin"}
}
```
The LLM translates human intent into exact AST symbols.

## Final Benchmark Results (With LLM Planner & DI Metadata)

| Task | RAG (+LLM Planner) | Graphify | `ast-index` | Vanilla `rg` |
| :--- | :---: | :---: | :---: | :---: |
| 1. Exact Symbol | **Hit** | **Hit** | **Hit** | **Hit** |
| 2. Semantic Intent | **Hit** | Miss | Miss | **Hit** |
| 3. Deep Architecture | Miss | Miss | Miss | Miss |
| 4. DI Tracing | **Hit** | **Hit** | Miss | **Hit** |
| 5. Blast Radius | **Hit** | Miss | Miss | **Hit** |
| 6. Test Coverage | Miss* | Miss | Miss | **Hit** |
| 7. Deprecation | **Hit** | Miss | **Hit** | **Hit** |

*(Note: Task 6 failed in RAG because the LLM strictly filtered for `chunk_type: test`, which dropped the results).*

### Token Efficiency (Compression Ratio)
We calculated how efficiently each tool compressed the 3.3 million token corpus down to the necessary context.

*   **Naive Corpus**: 3,353,158 tokens (1.0x)
*   **Graphify**: ~1,500 tokens (**~2,500x fewer**)
*   **Agentic RAG**: ~1,400 tokens (**~2,500x fewer**)

## Key Insights

### 1. Where Graphify Shines: The "Relational Whisperer"
Graphify is mathematically strict. If you want to know "What is the shortest path between Component A and Component B?", Graphify's BFS traversal is unbeatable. It is the perfect tool for generating architectural maps of legacy codebases.

### 2. Where RAG Wins: The "Blast Radius"
Graphify's shortest-path logic actually *hides* important refactoring data. In Task 5 (Impact Analysis), Graphify missed the impact because it only cared about a single path. Our Agentic RAG system successfully pulled in the 3 different `FeatureDependencies.kt` files that consume `StateAnalyzer`. For an autonomous coding agent, this "noise" is actually a vital safety signal—it tells the agent exactly what will break if it modifies an interface.

### 3. The Ultimate Trade-off: Latency
This is the hidden cost of Agentic RAG. 
*   `ast-index`: ~10ms
*   `Graphify`: ~800ms
*   **Agentic RAG (Local LLM)**: ~75 seconds

Running an 8-billion parameter model on your local machine to plan a search takes time. 

## Conclusion

There is no "One Tool to Rule Them All."

*   **For fast, daily navigation**: Give your developers `ast-index`.
*   **For architectural audits**: Map the repo with `Graphify`.
*   **For an autonomous Coding Agent**: You need **Agentic RAG**. By injecting explicit dependency graph metadata (DI annotations) into an AST-aware vector store, and fronting it with a local LLM planner, you get a system that actually understands semantic intent and architectural blast radius. 

It might take 70 seconds to plan the retrieval on your laptop, but it delivers the exact 1,500 tokens of context your agent needs to solve a complex issue without hallucinating.
