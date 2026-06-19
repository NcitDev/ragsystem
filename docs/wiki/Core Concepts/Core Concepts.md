# Core Concepts

<cite>
**Referenced Files in This Document**
- [README.md](file://README.md)
- [src/rag/app.py](file://src/rag/app.py)
- [src/rag/server.py](file://src/rag/server.py)
- [src/rag/agents/retrieval.py](file://src/rag/agents/retrieval.py)
- [src/rag/agents/repo_agent.py](file://src/rag/agents/repo_agent.py)
- [src/rag/core/chunker.py](file://src/rag/core/chunker.py)
- [src/rag/core/indexer.py](file://src/rag/core/indexer.py)
- [src/rag/core/scoring.py](file://src/rag/core/scoring.py)
- [src/rag/core/embedder.py](file://src/rag/core/embedder.py)
- [src/rag/core/vectorstore.py](file://src/rag/core/vectorstore.py)
- [src/rag/core/ast_index.py](file://src/rag/core/ast_index.py)
- [src/rag/core/summaries.py](file://src/rag/core/summaries.py)
- [src/rag/storage/db.py](file://src/rag/storage/db.py)
- [docs/dodo_rag_replacement_plan.md](file://docs/dodo_rag_replacement_plan.md)
- [skills/rag-smart-retrieval/SKILL.md](file://skills/rag-smart-retrieval/SKILL.md)
- [benchmark_production_scenarios.py](file://benchmark_production_scenarios.py)
- [benchmark_production_results.json](file://benchmark_production_results.json)
- [docs/benchmark_production_scenarios/summary.md](file://docs/benchmark_production_scenarios/summary.md)
- [benchmark_refactor_effort.py](file://benchmark_refactor_effort.py)
- [skills/rag-refactor-agent/SKILL.md](file://skills/rag-refactor-agent/SKILL.md)
- [skills/rag-project-enrichment/SKILL.md](file://skills/rag-project-enrichment/SKILL.md)
</cite>

## Update Summary
**Changes Made**
- Added comprehensive Smart Agent skill documentation with two-phase blast radius analysis
- Integrated production-ready retrieval strategies with benchmarking framework
- Enhanced performance optimization guidelines with concrete metrics and targets
- Added project enrichment and refactor agent skills for complete developer workflow
- Updated search strategies to include Smart Agent decision tree and production scenarios

## Table of Contents
1. [Introduction](#introduction)
2. [RAG Fundamentals](#rag-fundamentals)
3. [Search Strategies](#search-strategies)
4. [Code Chunking and Indexing](#code-chunking-and-indexing)
5. [Vector Embeddings and Storage](#vector-embeddings-and-storage)
6. [Agent Orchestration](#agent-orchestration)
7. [Smart Agent Skills and Production Strategies](#smart-agent-skills-and-production-strategies)
8. [Benchmarking Framework and Performance Optimization](#benchmarking-framework-and-performance-optimization)
9. [Core Components and Terminology](#core-components-and-terminology)
10. [System Architecture Overview](#system-architecture-overview)
11. [Operational Planning](#operational-planning)
12. [Performance Considerations](#performance-considerations)
13. [Troubleshooting Guide](#troubleshooting-guide)
14. [Conclusion](#conclusion)

## Introduction
This comprehensive documentation presents the core concepts underlying the Retrieval-Augmented Generation (RAG) system, now organized into seven focused sections that build upon each other to provide both foundational understanding and advanced technical insights. The system implements sophisticated code-aware retrieval capabilities through a multi-layered architecture that combines lexical search, semantic vector similarity, and hierarchical LOD (Level of Detail) navigation.

The documentation addresses three primary pillars: fundamental RAG principles, practical search strategies, and technical implementation details spanning code chunking, vector embeddings, and agent orchestration. Recent enhancements include comprehensive Smart Agent skills, two-phase blast radius analysis, production-ready retrieval strategies, and a robust benchmarking framework that validates system performance across realistic developer scenarios.

## RAG Fundamentals
Retrieval-Augmented Generation represents a paradigm shift in how artificial intelligence systems access and utilize knowledge. Unlike traditional language models that rely solely on their pre-trained knowledge, RAG systems dynamically retrieve relevant information from external sources before generating responses, dramatically improving accuracy and factual grounding.

### Core Principles
The fundamental concept centers on two complementary processes: retrieval and generation. During retrieval, the system searches through vast repositories of documents, code, or other textual content to identify the most relevant pieces of information. This process typically involves multiple modalities including lexical pattern matching, semantic similarity, and contextual relevance assessment.

Generation then takes these retrieved chunks and synthesizes them into coherent responses that incorporate the retrieved context. The key innovation lies in the seamless integration of information retrieval with language generation, creating systems that can provide up-to-date, contextually relevant answers backed by concrete evidence from the knowledge base.

### System Architecture Components
A typical RAG architecture comprises several interconnected components working in harmony. The retrieval engine serves as the foundation, processing queries through various search strategies and returning ranked results. These results feed into the generation model, which synthesizes contextually appropriate responses while maintaining coherence and relevance.

The system maintains a feedback loop where generation quality influences subsequent retrieval performance. High-quality generated responses often reveal gaps in the initial retrieval, prompting iterative refinement processes that improve both recall and precision over time.

### Code-Aware RAG Implementation
In the context of code repositories, RAG implementation requires specialized considerations. Code contains unique characteristics including syntax structures, semantic relationships between functions and classes, and domain-specific terminology that differs significantly from natural language text. Effective code-aware RAG systems must account for these differences while maintaining the core RAG principles.

The implementation addresses challenges such as handling multiple programming languages, preserving code syntax integrity during chunking, maintaining semantic relationships across code boundaries, and optimizing search performance for large-scale codebases containing millions of lines of code.

**Section sources**
- [src/rag/core/chunker.py](file://src/rag/core/chunker.py)
- [src/rag/core/embedder.py](file://src/rag/core/embedder.py)
- [src/rag/core/vectorstore.py](file://src/rag/core/vectorstore.py)

## Search Strategies
The search strategy layer represents the decision-making component of the retrieval system, determining how queries are processed and which retrieval methods are employed. This layer orchestrates between different search modalities while optimizing for performance, accuracy, and user experience.

### Strategy Selection Logic
Effective search strategy selection requires careful consideration of query characteristics, available data structures, and performance constraints. The system employs adaptive strategy selection that considers factors such as query complexity, available computational resources, and desired response quality. Simple queries might benefit from fast lexical searches, while complex semantic queries require more computationally intensive vector similarity operations.

### Hybrid Search Approach
The hybrid search strategy combines multiple retrieval modalities to maximize both precision and recall. Lexical search provides fast, exact pattern matching capabilities, while vector similarity enables semantic understanding of query intent. The integration process involves merging results from different sources, eliminating duplicates, and applying weighted scoring to produce final rankings.

This approach addresses limitations inherent in single-modality systems. Lexical search excels at finding exact matches but struggles with semantic variations and synonyms. Vector similarity handles semantic understanding but may return irrelevant results due to ambiguity in word meanings. The hybrid approach leverages the strengths of both while mitigating their weaknesses.

### LOD Drill-Down Navigation
Level of Detail (LOD) drill-down represents a hierarchical navigation strategy that progressively narrows search scope based on semantic relationships and structural hierarchies. This approach begins with broad, high-level concepts and progressively focuses on more specific details as needed.

The LOD hierarchy typically follows a multi-tier structure: L0 represents the highest level of abstraction with broad categories and major components, L1 provides file-level granularity with specific implementations, and L2 offers fine-grained chunk-level detail with precise code segments. This structure enables efficient navigation through large codebases while maintaining contextual relevance.

### Global Summaries and Context Provision
Global summary strategies provide broad context for queries that require high-level understanding or overview information. These strategies operate at the repository level, aggregating information across all files and components to provide comprehensive context. This approach proves particularly valuable for queries seeking architectural understanding, design patterns, or system-wide perspectives.

The global summary mechanism maintains hierarchical relationships while aggregating information, ensuring that high-level concepts remain accessible while preserving detailed information for deeper exploration. This dual approach enables users to quickly understand system scope and then dive into specific implementation details as needed.

**Section sources**
- [src/rag/agents/retrieval.py](file://src/rag/agents/retrieval.py)
- [src/rag/core/summaries.py](file://src/rag/core/summaries.py)
- [src/rag/server.py](file://src/rag/server.py)

## Code Chunking and Indexing
Code-aware chunking represents a sophisticated approach to text segmentation that preserves semantic and syntactic boundaries while accommodating the unique characteristics of programming languages. This process transforms raw code repositories into searchable, retrievable units that maintain both structural integrity and semantic meaning.

### Tree-Sitter Integration
The chunking system leverages Tree-Sitter, a powerful parsing library that provides language-agnostic syntax tree construction. Tree-Sitter excels at handling multiple programming languages simultaneously while maintaining accurate syntax representation. This capability enables the system to process diverse codebases containing mixed language content without sacrificing parsing accuracy.

Tree-Sitter's incremental parsing capabilities further enhance performance by efficiently updating parse trees when code changes occur. This incremental approach minimizes computational overhead during continuous indexing operations, making real-time updates feasible even for large repositories.

### Chunk Boundary Determination
Effective chunk boundary determination requires balancing granularity with semantic coherence. Chunks must be small enough to maintain relevance and avoid overwhelming retrieval systems, yet large enough to preserve meaningful context and avoid fragmentation. The system employs sophisticated algorithms that consider multiple factors including function boundaries, class structures, comment blocks, and logical statement groupings.

Language-specific considerations play a crucial role in chunk boundary determination. Different programming languages exhibit distinct structural patterns that require tailored approaches. For example, Python relies heavily on indentation for block structure, while C-family languages use braces. The chunking algorithm adapts to these language-specific conventions while maintaining consistent retrieval performance across all supported languages.

### Semantic Chunk Preservation
Beyond syntactic boundaries, the chunking system preserves semantic relationships that are critical for effective code retrieval. Function definitions, class declarations, and module boundaries often represent meaningful semantic units that should remain intact during the chunking process. Breaking these semantic boundaries would fragment related code and reduce retrieval effectiveness.

The system maintains context around chunk boundaries by including appropriate header and footer content that provides necessary context without introducing excessive noise. This balanced approach ensures that chunks contain sufficient context for understanding while remaining focused enough to maintain retrieval precision.

### Indexing Pipeline Integration
The chunking process seamlessly integrates with the broader indexing pipeline, feeding processed chunks into both lexical and vector indexing systems. Each chunk receives metadata that describes its source, structure, and relationships to other code elements. This metadata enables sophisticated search capabilities beyond simple text matching.

The indexing pipeline transforms chunked code into multiple representations optimized for different retrieval modalities. Lexical indexing creates searchable structures for pattern matching and exact matches, while vector indexing generates embeddings for semantic similarity operations. This dual representation maximizes retrieval effectiveness across diverse query types and scenarios.

**Section sources**
- [src/rag/core/chunker.py](file://src/rag/core/chunker.py)
- [src/rag/core/indexer.py](file://src/rag/core/indexer.py)
- [src/rag/core/ast_index.py](file://src/rag/core/ast_index.py)

## Vector Embeddings and Storage
Vector embeddings transform textual and code content into high-dimensional mathematical representations that capture semantic meaning and relationships. This transformation enables sophisticated similarity operations that go beyond traditional keyword matching to understand conceptual similarities and contextual relationships.

### Embedding Generation Process
The embedding generation process converts processed chunks into dense vector representations that preserve semantic relationships in mathematical space. Each embedding captures the essence of its source content while enabling efficient similarity calculations through vector arithmetic operations.

Multiple embedding strategies coexist within the system, supporting different use cases and performance requirements. Traditional sentence transformers provide strong general-purpose semantic understanding, while specialized code embeddings focus on capturing programming language semantics and developer intent. The system maintains flexibility to select appropriate embedding strategies based on content type and application requirements.

### Vector Database Architecture
Vector storage leverages specialized databases designed for high-dimensional similarity search operations. These databases optimize for nearest neighbor searches, dynamic updates, and scalable performance across large datasets. The architecture supports both batch ingestion and real-time updates, enabling continuous learning and adaptation.

Collection management provides organizational structures that partition embeddings by project, language, or functional domain. This partitioning improves search performance by reducing search spaces and enables targeted retrieval operations that focus on relevant subsets of the knowledge base.

### Similarity Search Operations
Vector similarity search operates on the principle that semantically similar content occupies nearby positions in vector space. The system employs advanced algorithms that efficiently locate nearby vectors while maintaining accuracy across high-dimensional spaces. These operations support both exact matches and approximate nearest neighbor searches, balancing precision with computational efficiency.

Search operations incorporate multiple similarity metrics that account for different aspects of content relationships. Cosine similarity emphasizes directional relationships regardless of magnitude, while Euclidean distance considers both direction and magnitude differences. The system combines these metrics with domain-specific weighting to optimize for code search scenarios.

### Performance Optimization Strategies
Vector database performance optimization addresses several key challenges including dimensionality curse, scalability constraints, and real-time update requirements. The system employs techniques such as dimensionality reduction, quantization, and hierarchical clustering to maintain performance as dataset scales grow.

Indexing strategies adapt to different workload patterns, supporting both batch processing for large-scale updates and interactive queries for real-time applications. The architecture maintains consistency between different indexing strategies while providing flexible access patterns optimized for specific use cases.

**Section sources**
- [src/rag/core/embedder.py](file://src/rag/core/embedder.py)
- [src/rag/core/vectorstore.py](file://src/rag/core/vectorstore.py)

## Agent Orchestration
Agent orchestration represents the coordination layer that manages complex workflows involving multiple retrieval strategies, context construction, and result synthesis. This layer transforms individual components into cohesive systems capable of handling sophisticated user queries and multi-step reasoning processes.

### Multi-Agent Coordination Framework
The orchestration framework coordinates multiple specialized agents that handle different aspects of the retrieval and generation process. Each agent specializes in specific tasks such as query understanding, strategy selection, context assembly, or result ranking. This specialization enables each agent to excel in its domain while contributing to overall system effectiveness.

Communication protocols between agents ensure seamless information exchange while maintaining modularity and independence. These protocols define standardized interfaces for sharing intermediate results, coordinating timing, and managing dependencies between different processing stages.

### Context Pack Construction and Packaging
Context pack construction represents the process of assembling relevant information into cohesive packages suitable for generation. This process involves selecting appropriate chunks, ordering them for optimal flow, and adding necessary metadata for generation context. The system maintains flexibility in context composition while ensuring that packages remain within acceptable size limits.

Packaging mechanisms handle diverse content types including code snippets, documentation fragments, and structural information. Each package maintains internal coherence while providing sufficient context for accurate generation. The system optimizes packaging for different generation models and use cases.

### Query Planning and Strategy Selection
Query planning encompasses the decision-making processes that determine optimal retrieval strategies for specific queries. The system analyzes query characteristics, available resources, and expected outcomes to select appropriate combinations of search strategies and processing pipelines.

Strategy selection considers multiple factors including query complexity, required accuracy levels, available computational resources, and temporal constraints. The system maintains adaptive selection mechanisms that learn from past performance to improve future strategy choices.

### Result Synthesis and Quality Assurance
Result synthesis combines retrieved information with generation capabilities to produce coherent, contextually appropriate responses. This process involves integrating multiple sources, resolving conflicts between different pieces of information, and ensuring that final outputs maintain factual accuracy and relevance.

Quality assurance mechanisms validate synthesized results through multiple verification processes including fact-checking, coherence assessment, and relevance scoring. These mechanisms ensure that generated responses meet established quality standards while maintaining the benefits of automated processing.

**Section sources**
- [src/rag/agents/repo_agent.py](file://src/rag/agents/repo_agent.py)
- [src/rag/agents/retrieval.py](file://src/rag/agents/retrieval.py)

## Smart Agent Skills and Production Strategies
The Smart Agent represents a sophisticated production-ready retrieval system that combines multiple retrieval strategies into a unified, decision-driven approach. Built on comprehensive benchmarking data from 6 refactoring tasks across Signal-Android (300K+ LOC), the Smart Agent provides optimal retrieval performance through intelligent strategy selection and two-phase blast radius analysis.

### Smart Agent Decision Tree
The Smart Agent employs a decision tree that guides tool selection based on query characteristics and retrieval goals. The system evaluates whether the user seeks exact symbols, project knowledge, blast radius analysis, code patterns, or text/regex patterns, then selects the optimal retrieval strategy accordingly.

**Decision Tree Architecture:**
- **Exact symbols (classes/functions/interfaces):** Use `/resolve` with definitions-only mode
- **Project knowledge (events, DI maps, workflows):** Use `/docs-search` for semantic search on documentation collections
- **Blast radius analysis:** Use two-phase `/resolve` strategy with selective usage filtering
- **Code patterns/flows:** Use `/context-pack` with semantic disabled, then loop to `/resolve`
- **Text/regex patterns:** Use ripgrep to discover symbols, then loop to `/resolve`

### Two-Phase Blast Radius Analysis
The two-phase blast radius analysis represents a sophisticated approach to understanding the impact of code changes. This strategy prevents the common pitfall of reading all usage files by implementing a controlled filtering process that maintains high precision while limiting retrieval volume.

**Phase 1 - Count and Scope:**
- Execute `/resolve` with usages_limit=100 (count only, no file reads)
- Read definitions to establish target directory scope
- Note total usage count (e.g., "53 files reference Job")

**Phase 2 - Selective Reading:**
Apply relevance filtering to limit to 15 most relevant usages:
1. **Same directory** as definitions (highest relevance)
2. **Symbol name in filename** (functional relevance)  
3. **First 10 usages** by server ranking (structural importance)

Report total count to users: "53 files reference Job — here are the 15 most relevant."

### Production-Ready Retrieval Strategies
The Smart Agent implements production-grade retrieval strategies validated through extensive benchmarking. Key performance targets include:
- **Turns:** 1-5 per retrieval operation
- **Tokens:** < 10,000 per retrieval operation  
- **Precision:** > 90% for symbol-based queries
- **Signal%:** 100% for context-pack filtering
- **Latency:** < 1s for optimal operations

### Smart Agent Skill Documentation
The Smart Agent skill provides comprehensive guidance for choosing the right retrieval tool to minimize turns, tokens, and noise while maximizing precision. The skill includes detailed tool references, anti-patterns, and performance budgets specifically tuned for production environments.

**Key Features:**
- Decision tree for optimal tool selection
- Two-phase blast radius strategy for impact analysis
- Performance budget targets for production systems
- Anti-patterns to avoid for optimal results
- Golden rules for code and knowledge retrieval

**Section sources**
- [skills/rag-smart-retrieval/SKILL.md](file://skills/rag-smart-retrieval/SKILL.md)
- [benchmark_production_scenarios.py](file://benchmark_production_scenarios.py)
- [benchmark_production_results.json](file://benchmark_production_results.json)
- [docs/benchmark_production_scenarios/summary.md](file://docs/benchmark_production_scenarios/summary.md)

## Benchmarking Framework and Performance Optimization
The RAG system incorporates a comprehensive benchmarking framework that validates retrieval performance across realistic developer scenarios and provides concrete optimization guidelines for production deployments.

### Production Scenarios Benchmark
The benchmark framework compares five retrieval agents across 10 realistic developer scenarios from Signal-Android, measuring performance across multiple dimensions including turns, tokens, precision, signal%, coverage, and latency.

**Agents Compared:**
- **Smart Agent:** Production skill with two-phase blast radius analysis
- **AST-Index:** Command-line symbol/search/usages tool
- **Graphify:** Graph-based subgraph traversal
- **Naive Agent:** Context-pack only with semantic enabled
- **Vanilla (rg):** Ripgrep text search

**Performance Metrics:**
- **Average Precision:** Smart Agent 70.2% vs AST-Index 23.1% vs Graphify 15.0%
- **Average Tokens:** Smart Agent 4,904 vs AST-Index 16,417 vs Graphify 15,258
- **Average Latency:** Smart Agent 125ms vs AST-Index 110ms vs Graphify 5,142ms

### Refactoring Effort Benchmark
A secondary benchmark evaluates four code-retrieval agents across six refactoring tasks, highlighting retrieval strengths for different scenarios including semantic architecture understanding, exact symbol lookup, flow tracing, dependency injection wiring, blast radius analysis, and annotation scavenging.

**Task Categories:**
- **Semantic Architecture:** RAG+AST advantage for understanding complex systems
- **Exact Symbol Lookup:** AST-Index advantage for precise symbol resolution  
- **Flow Tracing:** RAG+AST for semantic flow understanding
- **Dependency Injection:** AST-Index for symbol resolution
- **Blast Radius Analysis:** Graphify for graph neighbor traversal
- **Annotation Scavenging:** Vanilla/rg for literal text patterns

### Performance Optimization Guidelines
Based on benchmarking results, the system provides concrete optimization guidelines for production deployments:

**Token Budget Targets:**
- Definitions-only queries: < 10,000 tokens
- Two-phase blast radius: < 15,000 tokens  
- Context-pack filtering: < 10,000 tokens
- Semantic fallback: < 20,000 tokens

**Turn Optimization:**
- Minimize tool calls to 1-3 per retrieval operation
- Use two-phase strategies to avoid reading all usage files
- Implement selective filtering for blast radius analysis
- Leverage context-pack filtering to reduce noise

**Latency Targets:**
- `/resolve` operations: < 500ms
- `/context-pack` operations: < 800ms  
- Two-phase blast radius: < 1s
- Semantic search: < 200ms

### Developer Workflow Integration
The benchmarking framework supports comprehensive developer workflows through specialized skills:

**RAG Refactor Agent:**
- Guides Codex to ask repo-agent for exact code context
- Provides reuse checks, tests, callers, module boundaries
- Integrates documentation and event specifications
- Supports evaluation metrics and risk assessment

**RAG Project Enrichment:**
- Creates source-cited documentation for project knowledge
- Generates analytics event catalogs, metrics catalogs, feature flags
- Builds dependency injection maps, workflow state maps
- Enhances RAG with durable project knowledge

**Section sources**
- [benchmark_production_scenarios.py](file://benchmark_production_scenarios.py)
- [benchmark_refactor_effort.py](file://benchmark_refactor_effort.py)
- [skills/rag-refactor-agent/SKILL.md](file://skills/rag-refactor-agent/SKILL.md)
- [skills/rag-project-enrichment/SKILL.md](file://skills/rag-project-enrichment/SKILL.md)

## Core Components and Terminology
The RAG system defines several key components and terminologies that serve as the foundation for understanding and implementing the retrieval architecture. These concepts provide shared vocabulary and conceptual frameworks that enable effective communication among developers, researchers, and users.

### Fundamental Data Structures
ChunkDocument represents the primary unit of indexed content produced by the chunking pipeline. Each document encapsulates processed code segments along with comprehensive metadata describing source location, structural relationships, and processing attributes. This structure serves as the atomic unit for both lexical and vector indexing operations.

SearchPlan encapsulates the strategic approach for processing specific queries, including selected retrieval strategies, filtering criteria, and result parameters. The plan serves as a blueprint for coordinated execution across multiple system components, ensuring consistent and predictable behavior across different query types and scenarios.

RepoAgentPlan extends the planning concept to higher-level agent coordination, orchestrating complex workflows that may involve multiple search iterations, context refinement cycles, and result synthesis operations. This planning layer enables sophisticated multi-step reasoning processes that can adapt to evolving query requirements.

### Indexing Infrastructure
The indexer component represents the comprehensive pipeline that transforms raw code repositories into searchable knowledge bases. This infrastructure coordinates multiple processing stages including parsing, chunking, metadata extraction, embedding generation, and storage operations. The indexer maintains state information and progress tracking to support resumable operations and incremental updates.

### Retrieval and Scoring Systems
Scoring mechanisms combine multiple signal sources to produce final result rankings that balance relevance, recency, and quality considerations. These systems integrate lexical match scores, semantic similarity measures, and structural relationship indicators to provide comprehensive relevance assessments.

### Smart Agent Components
The Smart Agent introduces specialized components for production-ready retrieval:
- **Two-phase blast radius filtering** for impact analysis
- **Decision tree integration** for optimal tool selection
- **Performance budget enforcement** for production constraints
- **Benchmark-driven optimization** based on empirical data

## System Architecture Overview
The RAG system architecture integrates multiple specialized components that work together to provide comprehensive code search and retrieval capabilities. The architecture balances performance, scalability, and functionality while maintaining clean separation of concerns across different functional domains.

```mermaid
graph TB
subgraph "User Interface Layer"
UI["Web Interface"]
CLI["Command Line Interface"]
API["HTTP API Endpoints"]
SKILLS["Smart Agent Skills"]
END
subgraph "Orchestration Layer"
RA["Repo Agent"]
RET["Retrieval Agent"]
PLAN["Search Planning"]
SMART["Smart Agent Decision Tree"]
END
subgraph "Processing Layer"
CHUNK["Code Chunking"]
PARSE["Tree-Sitter Parsing"]
META["Metadata Extraction"]
EMBED["Embedding Generation"]
END
subgraph "Storage Layer"
CODEIDX["Code Index (SQLite)"]
VECSTORE["Vector Store (Qdrant)"]
CACHE["Result Cache"]
DOCS["Docs Collection (Qdrant)"]
END
subgraph "Analysis Layer"
SCORE["Result Scoring"]
SUMM["Hierarchical Summaries"]
GRAPH["Graph Analysis"]
BENCHMARK["Benchmark Framework"]
END
UI --> RA
CLI --> RA
API --> RA
SKILLS --> SMART
SMART --> PLAN
PLAN --> RET
RET --> CHUNK
CHUNK --> PARSE
PARSE --> META
META --> EMBED
EMBED --> VECSTORE
CHUNK --> CODEIDX
RET --> CODEIDX
RET --> VECSTORE
RET --> DOCS
RET --> SCORE
SCORE --> SUMM
SCORE --> GRAPH
SUMM --> CACHE
GRAPH --> CACHE
CACHE --> RA
BENCHMARK --> RA
BENCHMARK --> SMART
```

**Diagram sources**
- [src/rag/app.py](file://src/rag/app.py)
- [src/rag/server.py](file://src/rag/server.py)
- [src/rag/agents/repo_agent.py](file://src/rag/agents/repo_agent.py)
- [src/rag/agents/retrieval.py](file://src/rag/agents/retrieval.py)
- [src/rag/core/chunker.py](file://src/rag/core/chunker.py)
- [src/rag/core/indexer.py](file://src/rag/core/indexer.py)
- [src/rag/core/embedder.py](file://src/rag/core/embedder.py)
- [src/rag/core/vectorstore.py](file://src/rag/core/vectorstore.py)
- [src/rag/core/scoring.py](file://src/rag/core/scoring.py)
- [src/rag/core/summaries.py](file://src/rag/core/summaries.py)
- [src/rag/storage/db.py](file://src/rag/storage/db.py)
- [skills/rag-smart-retrieval/SKILL.md](file://skills/rag-smart-retrieval/SKILL.md)
- [benchmark_production_scenarios.py](file://benchmark_production_scenarios.py)

The architecture follows a layered approach that separates concerns while enabling efficient data flow between components. Each layer maintains specific responsibilities while providing well-defined interfaces for interaction with adjacent layers. This design enables independent development, testing, and optimization of individual components while maintaining system cohesion.

## Operational Planning
The operational framework encompasses the policies, procedures, and monitoring systems that ensure reliable and efficient RAG system operation. This framework addresses both technical operational concerns and business requirements for system maintenance, scaling, and performance optimization.

### Indexing Operations and Scheduling
Indexing operations follow carefully orchestrated schedules that balance system performance with data freshness requirements. The system maintains multiple indexing queues to handle different content types and update frequencies, ensuring that critical updates receive priority treatment while background maintenance continues unobtrusively.

Incremental update mechanisms minimize disruption during continuous indexing operations by processing only changed content and maintaining consistency with existing indexes. These mechanisms employ sophisticated change detection algorithms that identify modifications while avoiding unnecessary reprocessing of unchanged content.

### Resource Management and Queue Operations
Resource management encompasses allocation of computational resources, memory management, and I/O optimization across all system components. The system maintains separate processing queues for different operation types, preventing resource contention and ensuring fair treatment of different workload patterns.

Queue management systems track operation progress, handle failures gracefully, and provide recovery mechanisms for interrupted operations. These systems maintain visibility into system health and enable proactive intervention when performance degrades or resource constraints become apparent.

### Monitoring and Performance Metrics
Comprehensive monitoring systems track system performance across multiple dimensions including query latency, indexing throughput, resource utilization, and service availability. These metrics enable informed decision-making regarding system scaling, optimization opportunities, and capacity planning.

Performance dashboards provide real-time visibility into system operations, highlighting trends and anomalies that may indicate performance issues or optimization opportunities. The monitoring framework supports both reactive troubleshooting and proactive performance management.

### Smart Agent Deployment
The Smart Agent introduces specialized operational considerations:
- **Decision tree validation** through continuous benchmarking
- **Two-phase blast radius** monitoring for precision-latency trade-offs
- **Performance budget enforcement** for production constraints
- **Skill-based workflow orchestration** for developer productivity

**Section sources**
- [docs/dodo_rag_replacement_plan.md](file://docs/dodo_rag_replacement_plan.md)

## Performance Considerations
Performance optimization in RAG systems requires addressing multiple concurrent challenges including query latency, indexing throughput, memory usage, and computational efficiency. The system employs various strategies to balance these competing demands while maintaining high-quality retrieval performance.

### Query Optimization Strategies
Query optimization focuses on minimizing response times while maintaining retrieval accuracy. Techniques include result caching for common queries, intelligent pruning of search spaces, and adaptive strategy selection that chooses optimal processing paths based on query characteristics.

Indexing optimization targets reducing the time required to process and store new content. This includes optimizing chunking algorithms, parallelizing embedding generation, and employing efficient storage formats that minimize I/O overhead during retrieval operations.

### Scalability and Resource Management
Scalability considerations encompass horizontal scaling across multiple nodes, vertical scaling through resource augmentation, and architectural optimizations that enable growth without proportional performance degradation. The system maintains flexibility to adapt scaling strategies based on workload patterns and resource availability.

Memory management strategies address the substantial memory requirements of vector embeddings and large-scale indexes. Techniques include compression of embedding vectors, efficient data structures for sparse representations, and intelligent caching mechanisms that balance memory usage with performance requirements.

### Latency and Throughput Trade-offs
The system continuously balances latency requirements with throughput objectives, recognizing that different use cases have varying tolerance for delays versus volume processing capabilities. Adaptive algorithms adjust processing priorities based on real-time workload analysis and performance metrics.

### Smart Agent Performance Targets
The Smart Agent establishes concrete performance targets validated through comprehensive benchmarking:
- **Turns:** 1-5 per retrieval operation
- **Tokens:** < 10,000 for definitions-only queries
- **Precision:** > 90% for symbol-based queries
- **Latency:** < 1s for optimal operations
- **Signal%:** 100% for filtered context-pack results

**Section sources**
- [benchmark_production_scenarios.py](file://benchmark_production_scenarios.py)
- [skills/rag-smart-retrieval/SKILL.md](file://skills/rag-smart-retrieval/SKILL.md)

## Troubleshooting Guide
Effective troubleshooting requires systematic approaches to diagnosing and resolving issues across the multi-layered RAG architecture. Common problems span indexing failures, retrieval performance issues, storage corruption, and integration challenges with external systems.

### Indexing and Processing Issues
Indexing failures often stem from parsing errors in source code, insufficient memory for large files, or corrupted input data. Diagnostic approaches include examining parser error logs, validating file encoding and structure, and identifying problematic files that trigger processing failures.

Processing bottlenecks typically result from inefficient chunking algorithms, inadequate embedding generation resources, or storage performance issues. Resolution strategies involve algorithm optimization, resource scaling, and storage configuration improvements.

### Retrieval and Search Problems
Retrieval issues commonly involve poor result quality, incorrect strategy selection, or performance degradation over time. Diagnostics focus on query analysis, strategy effectiveness measurement, and system performance monitoring to identify root causes and implement targeted solutions.

### Storage and Data Integrity
Storage-related problems encompass data corruption, index inconsistencies, and performance degradation in vector databases. Recovery procedures include data validation checks, index rebuilding operations, and backup restoration processes that ensure data integrity and system reliability.

### Smart Agent Specific Issues
Smart Agent troubleshooting focuses on decision tree validation, two-phase blast radius filtering, and performance budget adherence:
- **Decision tree failures:** Validate query classification and tool selection logic
- **Blast radius filtering:** Check relevance filtering thresholds and directory matching
- **Performance targets:** Monitor token budgets and latency constraints
- **Skill integration:** Verify proper skill execution and parameter passing

**Section sources**
- [src/rag/server.py](file://src/rag/server.py)
- [src/rag/core/vectorstore.py](file://src/rag/core/vectorstore.py)
- [src/rag/core/chunker.py](file://src/rag/core/chunker.py)
- [skills/rag-smart-retrieval/SKILL.md](file://skills/rag-smart-retrieval/SKILL.md)

## Conclusion
The comprehensive Core Concepts documentation establishes the foundational understanding necessary for effective implementation and operation of the RAG system. By organizing content into seven focused sections covering fundamentals, strategies, technical implementation, Smart Agent skills, benchmarking framework, and operational aspects, the documentation provides both accessibility for newcomers and depth for advanced practitioners.

The seven-section structure enables progressive learning from basic principles through technical implementation details to production-ready strategies and performance optimization. This approach accommodates different learning styles and expertise levels while maintaining conceptual coherence across all sections.

The documentation's emphasis on code-aware RAG implementation addresses the unique challenges of working with programming languages and code repositories. The integration of Tree-Sitter parsing, sophisticated chunking algorithms, and hierarchical LOD navigation demonstrates how specialized approaches can enhance retrieval effectiveness in technical domains.

Recent enhancements including Smart Agent skills, two-phase blast radius analysis, comprehensive benchmarking framework, and production-ready retrieval strategies represent significant advances in RAG system maturity. These additions provide concrete, validated approaches for achieving optimal performance in real-world development scenarios.

Future evolution of the RAG system will likely build upon these foundational concepts while incorporating emerging technologies and methodologies. The modular architecture, comprehensive documentation, and robust benchmarking framework provide solid foundations for continued development and enhancement of retrieval capabilities in code-centric environments.

The integration of Smart Agent skills, project enrichment capabilities, and comprehensive benchmarking ensures that the system remains aligned with real-world developer needs while maintaining scientific rigor in performance validation. This balanced approach positions the RAG system as both a practical development tool and a research platform for advancing code search and retrieval technologies.