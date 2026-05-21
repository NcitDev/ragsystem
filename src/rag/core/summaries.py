"""Generate per-module/community summaries via Ollama at index time.

Summaries are stored in a separate Qdrant collection for global retrieval mode.
Only regenerated when community membership changes.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from rag.config import get_settings
from rag.core.graph import CodeGraph, Community
from rag.core.vectorstore import ChunkDocument, QdrantVectorStore

logger = structlog.get_logger()

SUMMARY_COLLECTION = "module_summaries"


async def generate_community_summaries(
    graph: CodeGraph,
    vectorstore: QdrantVectorStore,
    code_chunks: list[dict[str, Any]] | None = None,
) -> int:
    """Generate LLM summaries for each community and store in Qdrant.

    Args:
        graph: CodeGraph with communities already detected
        vectorstore: For storing summary embeddings
        code_chunks: Optional — chunk payloads to build summary context from.
                    If None, builds context from graph node attributes.

    Returns:
        Number of summaries generated.
    """
    import os
    if os.environ.get("RAG_SKIP_SUMMARIES") == "1":
        logger.info("summaries_skipped", reason="RAG_SKIP_SUMMARIES=1")
        return 0

    settings = get_settings()

    if not graph.communities:
        logger.info("no_communities_to_summarize")
        return 0

    # Build chunk lookup for context
    chunk_by_node: dict[str, dict] = {}
    if code_chunks:
        for c in code_chunks:
            fp = c.get("file_path", "")
            name = c.get("name", "")
            parent = c.get("parent_name", "")
            if parent:
                key = f"{fp}:{parent}.{name}"
            elif name:
                key = f"{fp}:{name}"
            else:
                continue
            chunk_by_node[key] = c

    summaries: list[ChunkDocument] = []
    generated = 0

    for comm_id, community in graph.communities.items():
        # Build context for this community
        context = _build_community_context(community, graph, chunk_by_node)
        if not context:
            continue

        # Generate summary via Ollama
        summary_text = await _generate_summary(context, settings.llm.ollama_url, settings.llm.agent_model)
        if not summary_text:
            continue

        community.label = summary_text

        summaries.append(ChunkDocument(
            content=summary_text,
            metadata={
                "community_id": comm_id,
                "file_paths": community.files[:20],
                "member_count": len(community.members),
                "chunk_type": "community_summary",
                "language": _dominant_language(community, graph),
                "patterns": _collect_patterns(community, graph),
                "domains": _collect_domains(community, graph),
            },
            chunk_id=f"community_{comm_id}",
        ))
        generated += 1

    # Store summaries
    if summaries:
        await vectorstore.upsert(SUMMARY_COLLECTION, summaries)
        logger.info("summaries_stored", count=generated, collection=SUMMARY_COLLECTION)

    return generated


def _build_community_context(
    community: Community,
    graph: CodeGraph,
    chunk_by_node: dict[str, dict],
) -> str:
    """Build a text context describing a community for LLM summarization."""
    lines: list[str] = []
    lines.append(f"Code module with {len(community.members)} symbols across {len(community.files)} files:")
    lines.append(f"Files: {', '.join(community.files[:10])}")
    lines.append("")

    # Add top symbols with their signatures
    for node_id in community.members[:30]:  # Cap to avoid huge prompts
        chunk = chunk_by_node.get(node_id)
        if chunk:
            ct = chunk.get("chunk_type", "")
            name = chunk.get("name", "")
            parent = chunk.get("parent_name", "")
            sig = f"{parent}.{name}" if parent else name
            patterns = chunk.get("patterns", [])
            pat_str = f" [{', '.join(patterns)}]" if patterns else ""
            lines.append(f"  - {ct}: {sig}{pat_str}")
        else:
            # From graph node attributes
            attrs = graph.graph.nodes.get(node_id, {})
            name = attrs.get("name", node_id.split(":")[-1])
            lines.append(f"  - {name}")

    # Add key relationships
    edges_shown = 0
    for node_id in community.members[:20]:
        callees = graph.get_callees(node_id)
        for callee in callees[:3]:
            if callee in set(community.members):
                lines.append(f"  {node_id.split(':')[-1]} -> {callee.split(':')[-1]}")
                edges_shown += 1
                if edges_shown > 15:
                    break
        if edges_shown > 15:
            break

    return "\n".join(lines)


async def _generate_summary(context: str, ollama_url: str, model: str) -> str | None:
    """Call Ollama to generate a module summary."""
    prompt = (
        "You are a code analyst. Given the following code module description, "
        "write a concise 2-3 sentence summary of what this module does, "
        "its main responsibility, and key patterns used. Be specific and technical.\n\n"
        f"{context}\n\n"
        "Summary:"
    )

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{ollama_url}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
            )
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
    except Exception as e:
        logger.warning(
            "summary_generation_failed",
            error=repr(e),
            error_type=type(e).__name__,
        )
        return None


def _dominant_language(community: Community, graph: CodeGraph) -> str:
    """Find the most common language in a community."""
    langs: dict[str, int] = {}
    for node_id in community.members:
        lang = graph.graph.nodes.get(node_id, {}).get("language", "")
        if lang:
            langs[lang] = langs.get(lang, 0) + 1
    return max(langs, key=langs.get, default="unknown") if langs else "unknown"


def _collect_patterns(community: Community, graph: CodeGraph) -> list[str]:
    """Collect unique patterns across community members."""
    patterns: set[str] = set()
    for node_id in community.members:
        for p in graph.graph.nodes.get(node_id, {}).get("patterns", []):
            patterns.add(p)
    return sorted(patterns)[:10]


def _collect_domains(community: Community, graph: CodeGraph) -> list[str]:
    """Collect unique domains across community members."""
    domains: set[str] = set()
    for node_id in community.members:
        for d in graph.graph.nodes.get(node_id, {}).get("domains", []):
            domains.add(d)
    return sorted(domains)[:5]
