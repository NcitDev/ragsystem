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

# Hierarchical LOD collections (Level-of-Detail drill-down).
# L0 = git-dir summary (one paragraph per module). ~50 tokens.
# L1 = file summary (signatures + 2-sentence purpose). ~150 tokens.
# L2 = raw code chunks (existing code_chunks collection).
LOD_L0_COLLECTION = "lod_l0"
LOD_L1_COLLECTION = "lod_l1"


async def list_summaries(
    vectorstore: QdrantVectorStore,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return recent summary payloads for the TUI overview screen."""
    client = await vectorstore._get_client()
    summaries: list[dict[str, Any]] = []
    for collection in (SUMMARY_COLLECTION, LOD_L0_COLLECTION, LOD_L1_COLLECTION):
        if len(summaries) >= limit:
            break
        try:
            points, _ = await client.scroll(
                collection_name=collection,
                limit=max(1, limit - len(summaries)),
                with_payload=True,
                with_vectors=False,
            )
        except Exception as e:
            logger.debug("summary_list_collection_skipped", collection=collection, error=str(e))
            continue
        for point in points:
            payload = point.payload or {}
            content = payload.get("content", "")
            summaries.append(
                {
                    "collection": collection,
                    "id": str(point.id),
                    "content": content,
                    "preview": content[:240],
                    "chunk_type": payload.get("chunk_type", ""),
                    "module_path": payload.get("module_path", ""),
                    "file_path": payload.get("file_path", ""),
                    "member_count": payload.get("member_count"),
                    "file_count": payload.get("file_count"),
                }
            )
            if len(summaries) >= limit:
                break
    return summaries


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

    # Store summaries. Louvain community ids are not stable run-to-run and the
    # community count can shrink, so replace the whole community set: stale
    # summaries would otherwise accumulate forever and keep being served by the
    # `global` strategy.
    if summaries:
        try:
            await vectorstore.delete_by_filter(
                SUMMARY_COLLECTION, "chunk_type", "community_summary"
            )
        except Exception as e:
            logger.warning("stale_community_summaries_delete_failed", error=str(e))
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


# --- Hierarchical LOD (L0/L1) -------------------------------------------------
#
# L0 (module/dir) and L1 (file) summaries enable agent drill-down at query time:
# search L0 → narrow to dirs → search L1 within those dirs → narrow to files →
# search raw chunks (L2) within those files. Token cost per query drops because
# the agent inspects ~100-token summaries before fetching full chunks.
#
# Both levels are content-hash keyed: unchanged dirs/files skip re-generation.


import hashlib as _hashlib  # noqa: E402


def _module_path_of(file_path: str) -> str:
    """Git-dir module path (parent dir of file). Repo root → ``"."``."""
    from os.path import dirname
    return dirname(file_path) or "."


def _hash_text(text: str) -> str:
    return _hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


async def _gen_l1_for_file(
    file_path: str,
    file_chunks: list[dict[str, Any]],
    ollama_url: str,
    model: str,
) -> str | None:
    """Build L1 context (signature list + chunk-type hints) and call Ollama."""
    sigs: list[str] = []
    languages: set[str] = set()
    for c in file_chunks[:50]:  # Cap context
        ct = c.get("chunk_type", "")
        name = c.get("name", "")
        parent = c.get("parent_name", "")
        sym = f"{parent}.{name}" if parent else name
        if not sym:
            continue
        lang = c.get("language", "")
        if lang:
            languages.add(lang)
        sigs.append(f"  {ct}: {sym}")

    if not sigs:
        return None

    lang_str = ", ".join(sorted(languages)) or "?"
    context = (
        f"File: {file_path}\n"
        f"Languages: {lang_str}\n"
        f"Symbols ({len(sigs)}):\n" + "\n".join(sigs)
    )
    prompt = (
        "You are a code analyst. Given a file's symbol list, write a "
        "2-sentence summary describing the file's purpose and the main "
        "responsibilities of its top symbols. Be concrete and technical.\n\n"
        f"{context}\n\nSummary:"
    )
    return await _ollama_generate(prompt, ollama_url, model)


async def _gen_l0_for_module(
    module_path: str,
    file_l1_summaries: dict[str, str],
    ollama_url: str,
    model: str,
) -> str | None:
    """Build L0 context (file → L1 summary map) and call Ollama."""
    if not file_l1_summaries:
        return None

    lines = [f"Module directory: {module_path}", f"Files: {len(file_l1_summaries)}", ""]
    for fp, summ in list(file_l1_summaries.items())[:30]:
        lines.append(f"- {fp}: {summ[:200]}")
    context = "\n".join(lines)
    prompt = (
        "You are a code analyst. Given a directory's per-file summaries, "
        "write a single-paragraph (~50 tokens) summary of what this "
        "module does and how its files relate. Be concrete.\n\n"
        f"{context}\n\nSummary:"
    )
    return await _ollama_generate(prompt, ollama_url, model)


async def _ollama_generate(prompt: str, ollama_url: str, model: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{ollama_url}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
            )
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
    except Exception as e:
        logger.warning("lod_generation_failed", error=repr(e), error_type=type(e).__name__)
        return None


async def generate_lod_summaries(
    code_chunks: list[dict[str, Any]],
    vectorstore: QdrantVectorStore,
    changed_files: set[str] | None = None,
) -> tuple[int, int]:
    """Generate L1 (per-file) and L0 (per-git-dir) summaries.

    Args:
        code_chunks: All chunk payloads from the code collection.
        vectorstore: For upserting L0/L1 ChunkDocuments.
        changed_files: If provided, only regenerate L1 for these files (and
            L0 only for modules whose file set changed). Pass None to do all.

    Returns:
        (l0_count, l1_count) — number of summaries generated.
    """
    import os
    if os.environ.get("RAG_SKIP_SUMMARIES") == "1":
        logger.info("lod_summaries_skipped", reason="RAG_SKIP_SUMMARIES=1")
        return 0, 0

    settings = get_settings()
    model = settings.llm.agent_model  # qwen3:8b per design
    url = settings.llm.ollama_url

    # Full rebuild: wipe both LOD collections first. L1 ids are keyed by file
    # path hash, so summaries of deleted files would otherwise live forever.
    if changed_files is None:
        for lod_collection in (LOD_L0_COLLECTION, LOD_L1_COLLECTION):
            try:
                await vectorstore.drop_collection(lod_collection)
            except Exception as e:
                logger.warning("lod_collection_reset_failed", collection=lod_collection, error=str(e))

    # Group chunks by file
    by_file: dict[str, list[dict]] = {}
    for c in code_chunks:
        fp = c.get("file_path", "")
        if not fp:
            continue
        by_file.setdefault(fp, []).append(c)

    target_files = (
        {f for f in by_file if f in changed_files}
        if changed_files is not None
        else set(by_file.keys())
    )

    l1_docs: list[ChunkDocument] = []
    l1_summaries: dict[str, str] = {}  # file_path -> summary
    for fp in sorted(target_files):
        chunks = by_file.get(fp, [])
        if not chunks:
            continue
        summary = await _gen_l1_for_file(fp, chunks, url, model)
        if not summary:
            continue
        module_path = _module_path_of(fp)
        l1_summaries[fp] = summary
        l1_docs.append(ChunkDocument(
            content=summary,
            metadata={
                "file_path": fp,
                "module_path": module_path,
                "lod_level": "L1",
                "chunk_type": "lod_file_summary",
                "symbol_count": len(chunks),
            },
            chunk_id=f"lod_l1_{_hash_text(fp)}",
        ))

    if l1_docs:
        await vectorstore.upsert(LOD_L1_COLLECTION, l1_docs)

    # Group target files by module for L0 gen. Also pull in non-target files'
    # cached L1 summaries when re-summarizing a module — handles incremental
    # case where only some files in a dir changed.
    modules: dict[str, dict[str, str]] = {}
    for fp, summ in l1_summaries.items():
        modules.setdefault(_module_path_of(fp), {})[fp] = summ
    # Fill in unchanged files' summaries from L1 collection for modules being regenerated
    if changed_files is not None and modules:
        client = await vectorstore._get_client()
        for mod in list(modules.keys()):
            try:
                points, _ = await client.scroll(
                    collection_name=LOD_L1_COLLECTION,
                    scroll_filter=models_filter("module_path", mod),
                    with_payload=True,
                    with_vectors=False,
                    limit=200,
                )
                for p in points:
                    pl = p.payload or {}
                    fp = pl.get("file_path", "")
                    if fp and fp not in modules[mod]:
                        modules[mod][fp] = pl.get("content", "")
            except Exception as e:
                logger.debug("lod_l1_scroll_failed", module=mod, error=str(e))

    l0_docs: list[ChunkDocument] = []
    for module_path, file_summaries in modules.items():
        summary = await _gen_l0_for_module(module_path, file_summaries, url, model)
        if not summary:
            continue
        l0_docs.append(ChunkDocument(
            content=summary,
            metadata={
                "module_path": module_path,
                "lod_level": "L0",
                "chunk_type": "lod_module_summary",
                "file_count": len(file_summaries),
                "file_paths": list(file_summaries.keys())[:30],
            },
            chunk_id=f"lod_l0_{_hash_text(module_path)}",
        ))

    if l0_docs:
        await vectorstore.upsert(LOD_L0_COLLECTION, l0_docs)

    logger.info("lod_summaries_generated", l0=len(l0_docs), l1=len(l1_docs))
    return len(l0_docs), len(l1_docs)


def models_filter(field: str, value: str):
    """Helper: build a single-field Qdrant filter without circular imports."""
    from qdrant_client import models as _m
    return _m.Filter(must=[_m.FieldCondition(key=field, match=_m.MatchValue(value=value))])
