"""Search-plan execution: strategy dispatch, lexical promotion, sanity filter.

Extracted from the ``/search`` route in ``rag.server`` — pure move-and-rewire,
no behavior changes. This module must not import from ``rag.server``.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

logger = structlog.get_logger()


def _result_key(payload: dict[str, Any]) -> tuple[str, int, int, str, str]:
    return (
        str(payload.get("file_path", "")),
        int(payload.get("start_line", 0) or 0),
        int(payload.get("end_line", 0) or 0),
        str(payload.get("chunk_type", "")),
        str(payload.get("name", "")),
    )


def _lexical_hit_to_search_result(hit: dict[str, Any]):
    from rag.core.vectorstore import SearchResult

    payload = {
        "file_path": hit.get("file_path", ""),
        "name": hit.get("name", ""),
        "parent_name": hit.get("parent_name", ""),
        "chunk_type": hit.get("chunk_type", ""),
        "language": hit.get("language", ""),
        "start_line": hit.get("start_line", 0),
        "end_line": hit.get("end_line", 0),
        "retrieval_source": "lexical",
    }
    # Lexical scores from ``_score_code_row`` are unbounded term counts
    # (~1..8+); cosine scores are 0..1. Squash into the same band, then damp:
    # these are lexical-ONLY entries (hits also found semantically were deduped
    # and keep their semantic score), so a generic-word FTS match must sit
    # below a strong semantic hit (~0.45+), while an exact symbol-name match
    # (raw >= 5 → ~0.5+) still outranks embedding noise (~0.2-0.4).
    raw = float(hit.get("score", 0.0))
    return SearchResult(
        content=hit.get("code", ""),
        score=0.75 * raw / (raw + 3.0),
        payload=payload,
        point_id=f"lex:{hit.get('chunk_id', '')}",
    )


async def execute_search_plan(
    vectorstore,
    plan,
    query: str,
    top_k: int | None,
    req_filters: dict[str, Any] | None,
    code_collection: str,
) -> tuple[list, dict]:
    """Route a SearchPlan by strategy and return (results, matched_queries_map)."""
    if plan.strategy == "lod_drill":
        # Hierarchical drill-down: L0 (modules) → L1 (files) → L2 (chunks).
        # Falls back to flat hybrid if L0/L1 collections empty (e.g.
        # index pre-dates LOD or RAG_SKIP_SUMMARIES=1 was set).
        from rag.core.summaries import LOD_L0_COLLECTION, LOD_L1_COLLECTION

        l0_count = await vectorstore.count(LOD_L0_COLLECTION)
        if l0_count == 0:
            # No LOD data — degrade to flat hybrid search.
            logger.info("lod_drill_degraded", reason="no_lod_data")
            result_map: dict[str, tuple[Any, list[int]]] = {}
            for qi, q in enumerate(plan.queries):
                merged_filters = {**(plan.filters or {}), **(req_filters or {})}
                query_results = await vectorstore.search(
                    collection=code_collection,
                    query=q,
                    top_k=top_k or plan.top_k,
                    filters=merged_filters if merged_filters else None,
                )
                for r in query_results:
                    if r.point_id in result_map:
                        result_map[r.point_id][1].append(qi)
                    else:
                        result_map[r.point_id] = (r, [qi])
            results = [r for r, _ in result_map.values()]
            matched_queries_map = {pid: qis for pid, (_, qis) in result_map.items()}
        else:
            # Hop 1: top-3 modules
            l0_hits = await vectorstore.search(
                collection=LOD_L0_COLLECTION,
                query=query,
                top_k=3,
            )
            top_modules = [
                h.payload.get("module_path") for h in l0_hits
                if h.payload.get("module_path")
            ]

            # Hop 2: top-5 files within those modules
            l1_hits = []
            if top_modules:
                l1_hits = await vectorstore.search(
                    collection=LOD_L1_COLLECTION,
                    query=query,
                    top_k=5,
                    filters={"module_path": top_modules},
                )
            top_files = [
                h.payload.get("file_path") for h in l1_hits
                if h.payload.get("file_path")
            ]

            # Hop 3: chunks within those files
            results = []
            if top_files:
                merged_filters = {
                    "file_path": top_files,
                    **(plan.filters or {}),
                    **(req_filters or {}),
                }
                results = await vectorstore.search(
                    collection=code_collection,
                    query=query,
                    top_k=top_k or plan.top_k,
                    filters=merged_filters,
                )
            matched_queries_map = {}
            logger.info(
                "lod_drill_executed",
                modules=len(top_modules),
                files=len(top_files),
                chunks=len(results),
            )

    elif plan.strategy == "global":
        # Search module summaries collection
        from rag.core.summaries import SUMMARY_COLLECTION
        results = await vectorstore.search(
            collection=SUMMARY_COLLECTION,
            query=query,
            top_k=top_k or 5,
        )
        matched_queries_map = {}

    elif plan.strategy == "graph_walk":
        # Use code graph for multi-hop traversal + vector search
        from rag.core.graph import get_graph
        graph = get_graph()
        # Find entry point via vector search
        seed_results = await vectorstore.search(
            collection=code_collection,
            query=query,
            top_k=3,
        )
        # Traverse graph from each seed in score order (seed_results
        # is already score-sorted). Collect related file paths in
        # insertion order so the downstream slice [:10] is stable
        # across runs — sets are hash-randomized in Python, so the
        # previous ``set | list(...)[:10]`` truncation produced
        # different results between processes.
        ordered_files: dict[str, None] = {}
        for sr in seed_results:
            node_id = f"{sr.payload.get('file_path', '')}:{sr.payload.get('parent_name', '')}.{sr.payload.get('name', '')}".replace(".:", ":")
            # ``traverse`` returns BFS-ordered neighbours; preserve it.
            for n in graph.traverse(node_id, max_hops=2):
                if ":" not in n:
                    continue
                fp = n.split(":")[0]
                if fp:
                    ordered_files.setdefault(fp, None)

        related_files_ordered = list(ordered_files.keys())
        results = []
        for fp in related_files_ordered[:10]:
            file_results = await vectorstore.search(
                collection=code_collection,
                query=query,
                top_k=5,
                filters={"file_path": fp},
            )
            results.extend(file_results)

        # Deduplicate
        seen = set()
        deduped = []
        for r in results:
            if r.point_id not in seen:
                seen.add(r.point_id)
                deduped.append(r)
        results = deduped[:top_k or plan.top_k]
        matched_queries_map = {}

    else:
        # Standard: hybrid, filtered, naive, aggregate
        result_map: dict[str, tuple[Any, list[int]]] = {}
        for qi, q in enumerate(plan.queries):
            merged_filters = {**(plan.filters or {}), **(req_filters or {})}
            query_results = await vectorstore.search(
                collection=code_collection,
                query=q,
                top_k=top_k or plan.top_k,
                filters=merged_filters if merged_filters else None,
            )
            for r in query_results:
                if r.point_id in result_map:
                    result_map[r.point_id][1].append(qi)
                else:
                    result_map[r.point_id] = (r, [qi])

        results = [r for r, _ in result_map.values()]
        matched_queries_map = {pid: qis for pid, (_, qis) in result_map.items()}

    return results, matched_queries_map


def promote_lexical_hits(
    results: list,
    query: str,
    code_collection: str,
    top_k: int,
    filters: dict[str, Any] | None,
) -> list:
    """Promote exact/code-index matches before semantic scoring. Dense
    retrieval remains the fallback, but symbol/file/API queries should
    not lose to embedding noise when SQLite has direct evidence."""
    try:
        from rag.storage import db as _db

        lexical_hits = _db.search_code_chunks(
            query,
            collection=code_collection,
            limit=top_k,
            filters=filters if filters else None,
        )
        seen_keys = {_result_key(r.payload) for r in results}
        for hit in lexical_hits:
            lex_result = _lexical_hit_to_search_result(hit)
            key = _result_key(lex_result.payload)
            if key in seen_keys:
                continue
            results.append(lex_result)
            seen_keys.add(key)
    except Exception as e:
        logger.debug("lexical_search_failed", query=query, error=str(e))
    return results


def apply_symbol_sanity_filter(results: list, query: str) -> list:
    """Apply AST / symbol sanity verification filter for semantic results."""
    # Find CamelCase symbols of length >= 4 in the query. Drop common
    # capitalized English words ("Show me...", "Find all...", "Rename
    # X") — otherwise a natural-language question's leading verb is
    # treated as a required symbol and wipes every result to zero.
    _STOPWORD_SYMBOLS = {
        "show", "find", "rename", "trace", "list", "give", "tell",
        "what", "which", "where", "when", "who", "whom", "whose",
        "how", "why", "this", "that", "these", "those", "there",
        "here", "with", "from", "into", "your", "their", "have",
        "does", "code", "class", "base", "main", "should", "would",
        "could", "about", "into",
    }
    query_symbols = {
        s for s in re.findall(r"\b([A-Z][a-zA-Z0-9_]{3,})\b", query)
        if s.lower() not in _STOPWORD_SYMBOLS
    }
    if query_symbols:
        filtered_results = []
        for r in results:
            payload = r.payload or {}
            code = r.content or ""
            # Extract all names/references to check
            names_to_check = {
                str(payload.get("name", "")),
                str(payload.get("parent_name", "")),
                str(payload.get("file_path", ""))
            }
            # Check references/inherits lists
            for ref_list in ("references_fqn", "inherits_from"):
                for ref in payload.get(ref_list) or []:
                    names_to_check.add(ref)

            # Check if any query symbol is present in the names or code
            matched = False
            for sym in query_symbols:
                sym_lower = sym.lower()
                # Check exact word match in code
                if re.search(r"\b" + re.escape(sym) + r"\b", code):
                    matched = True
                    break
                # Check exact word/substring match in payload names
                if any(sym_lower in n.lower() for n in names_to_check):
                    matched = True
                    break

            if matched:
                filtered_results.append(r)
        # Safety net: a sanity filter must never delete *all*
        # evidence. If nothing matched (e.g. the symbol only appears
        # in code semantic search didn't rank, or it was a false
        # symbol), keep the unfiltered results rather than return 0.
        results = filtered_results or results
    return results
