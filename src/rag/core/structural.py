"""Structural (AST/graph payload) retrieval over Qdrant.

Extracted from closures inside ``create_app`` in ``rag.server`` — pure
move-and-rewire, no behavior changes. This module must not import from
``rag.server``; the vectorstore is passed in by the route layer.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel

logger = structlog.get_logger()


class RelatedLink(BaseModel):
    """A structurally-related file returned as a LINK (no code) to save tokens.

    The caller fetches the body on demand (e.g. via /resolve or read) only for
    the ones it actually needs.
    """

    file_path: str
    name: str
    lines: str
    relation: str  # sibling | collaborator | subclass_or_caller
    repo: str = ""  # set on cross-repo fan-out


async def query_structural_usages_from_qdrant(
    vectorstore, collection: str, symbols: list[str], repo: str
) -> list[dict[str, Any]]:
    from qdrant_client import models
    client = await vectorstore._get_client()
    hits = []

    # Resolve FQNs and called_by for the symbols in one scroll query per symbol
    fqns = []
    called_by_locations = []
    for symbol in symbols:
        try:
            qfilter = models.Filter(
                must=[
                    models.FieldCondition(key="name", match=models.MatchValue(value=symbol)),
                    models.FieldCondition(
                        key="chunk_type",
                        match=models.MatchAny(any=["class_declaration", "interface_declaration", "method", "function", "class", "interface"])
                    )
                ]
            )
            res = await client.scroll(
                collection_name=collection,
                scroll_filter=qfilter,
                limit=5,
                with_payload=True
            )
            has_fqn = False
            if res and res[0]:
                for pt in res[0]:
                    payload = pt.payload or {}
                    defines_fqn = payload.get("defines_fqn")
                    if defines_fqn:
                        fqns.append(defines_fqn)
                        has_fqn = True
                    cb = payload.get("called_by")
                    if cb:
                        if isinstance(cb, list):
                            called_by_locations.extend(cb)
                        elif isinstance(cb, str):
                            called_by_locations.append(cb)
            if not has_fqn:
                fqns.append(symbol)
        except Exception:
            fqns.append(symbol)

    # Convert absolute paths to relative paths and retrieve those chunks
    if called_by_locations:
        try:
            from rag.core.repos import RepoManager

            repo_info = RepoManager().get(repo)
            if repo_info is None:
                raise ValueError(f"Unknown repo: {repo}")
            repo_path = Path(repo_info.path).resolve()

            for loc in called_by_locations:
                if ":" not in loc:
                    continue
                path_part, line_part = loc.rsplit(":", 1)
                try:
                    line_num = int(line_part)
                except ValueError:
                    continue
                path_obj = Path(path_part).resolve()
                try:
                    rel_path = str(path_obj.relative_to(repo_path))
                except ValueError:
                    continue

                # Query Qdrant for a chunk covering this line in this file
                qfilter = models.Filter(
                    must=[
                        models.FieldCondition(key="file_path", match=models.MatchValue(value=rel_path)),
                        models.FieldCondition(key="start_line", range=models.Range(lte=line_num)),
                        models.FieldCondition(key="end_line", range=models.Range(gte=line_num))
                    ]
                )
                res = await client.scroll(
                    collection_name=collection,
                    scroll_filter=qfilter,
                    limit=5,
                    with_payload=True
                )
                if res and res[0]:
                    for pt in res[0]:
                        payload = pt.payload or {}
                        start_line = payload.get("start_line", 1)
                        end_line = payload.get("end_line", 1)
                        label = payload.get("name", "") or Path(rel_path).name
                        chunk_id = f"graph:{rel_path}:{start_line}:{label}"
                        if any(h["chunk_id"] == chunk_id for h in hits):
                            continue

                        code = payload.get("content", "")
                        hits.append({
                            "chunk_id": chunk_id,
                            "file_path": rel_path,
                            "name": label,
                            "parent_name": "",
                            "chunk_type": payload.get("chunk_type", "class"),
                            "language": payload.get("language", ""),
                            "start_line": start_line,
                            "end_line": end_line,
                            "lines": f"{start_line}-{end_line}",
                            "code": code,
                            "token_estimate": max(1, (len(code) + 3) // 4),
                            "score": 20.0,
                            "citation": f"{rel_path}:{start_line}-{end_line} ({label})",
                            "why_included": "references_relationship",
                        })
        except Exception as e:
            logger.warning("called_by_resolution_failed", error=str(e))

    for fqn in set(fqns):
        try:
            # Scroll matching inherits_from or references_fqn
            qfilter = models.Filter(
                should=[
                    models.FieldCondition(key="inherits_from", match=models.MatchValue(value=fqn)),
                    models.FieldCondition(key="references_fqn", match=models.MatchValue(value=fqn))
                ]
            )
            res = await client.scroll(
                collection_name=collection,
                scroll_filter=qfilter,
                limit=50,
                with_payload=True,
                with_vectors=False
            )
            points = res[0]
            for p in points:
                payload = p.payload or {}
                file_path = payload.get("file_path", "")
                if not file_path:
                    continue

                # Deduplicate points by chunk_id
                start_line = payload.get("start_line", 1)
                end_line = payload.get("end_line", 1)
                label = payload.get("name", "") or Path(file_path).name
                chunk_id = f"graph:{file_path}:{start_line}:{label}"
                if any(h["chunk_id"] == chunk_id for h in hits):
                    continue

                code = payload.get("content", "")

                # Determine structural explanation
                is_inherits = fqn in payload.get("inherits_from", [])
                why_included = "inherits_from_relationship" if is_inherits else "references_relationship"

                hits.append({
                    "chunk_id": chunk_id,
                    "file_path": file_path,
                    "name": label,
                    "parent_name": "",
                    "chunk_type": payload.get("chunk_type", "class"),
                    "language": payload.get("language", ""),
                    "start_line": start_line,
                    "end_line": end_line,
                    "lines": f"{start_line}-{end_line}",
                    "code": code,
                    "token_estimate": max(1, (len(code) + 3) // 4),
                    "score": 15.0,
                    "citation": f"{file_path}:{start_line}-{end_line} ({label})",
                    "why_included": why_included,
                })
        except Exception as e:
            logger.warning("structural_usages_qdrant_error", symbol=fqn, error=str(e))
    return hits


async def related_files(
    vectorstore, collection: str, symbols: list[str], prime_paths: set[str],
    anchor_files: set[str] | None = None, limit: int = 25,
) -> list[RelatedLink]:
    """Deterministically find files structurally related to the prime symbols
    — NO LLM loop. Three directions, all from the Qdrant payload:
      * sibling           — same package/directory as the prime definition
      * collaborator      — a type the prime references (forward references_fqn)
      * subclass_or_caller— a chunk that references the prime's FQN (reverse)
    Returned as links (path/name/lines/relation), not code, to save tokens.
    """
    from qdrant_client import models

    client = await vectorstore._get_client()
    internal_prefix = "org.thoughtcrime.securesms"
    syms_lower = {s.lower() for s in symbols}
    # Rank by relation: structural edges (subclass/caller, collaborator) beat
    # generic same-package siblings, which are only kept when the filename is
    # name-related to a queried symbol (drops package noise like
    # KeepAliveService when asking about Job).
    _PRIORITY = {"subclass": 0, "subclass_or_caller": 1, "collaborator": 2, "sibling": 3}
    ranked: dict[str, tuple[int, RelatedLink]] = {}

    def _add(payload: dict, relation: str) -> None:
        fp = payload.get("file_path", "")
        if not fp or fp in prime_paths:
            return
        pr = _PRIORITY[relation]
        if fp in ranked and ranked[fp][0] <= pr:
            return  # already held at equal-or-higher priority
        lines = f"{payload.get('start_line', '?')}-{payload.get('end_line', '?')}"
        ranked[fp] = (pr, RelatedLink(
            file_path=fp, name=payload.get("name", "") or Path(fp).stem,
            lines=lines, relation=relation,
        ))

    def _name_related(fp: str) -> bool:
        stem = Path(fp).stem.lower()
        return any(s in stem or stem in s for s in syms_lower)

    async def _scroll(field: str, value: str, match_text: bool = False, lim: int = 60):
        cond = (models.MatchText(text=value) if match_text else models.MatchValue(value=value))
        try:
            res = await client.scroll(
                collection_name=collection,
                scroll_filter=models.Filter(must=[models.FieldCondition(key=field, match=cond)]),
                limit=lim, with_payload=True,
            )
            return [pt.payload or {} for pt in (res[0] or [])]
        except Exception:
            return []

    # Anchor chunks come from the grounded symbol NAMES *and* the resolved
    # definition FILES — the latter are the reliable anchors (a found
    # definition's package siblings/collaborators are what we're after).
    anchors: list[dict] = []
    seen_anchor: set = set()

    async def _collect_anchor(payload: dict) -> None:
        key = (payload.get("file_path"), payload.get("defines_fqn"), payload.get("name"))
        if key not in seen_anchor:
            seen_anchor.add(key)
            anchors.append(payload)

    # Anchor collection — parallelized. (Was sequential; embedded Qdrant's
    # per-scroll cost dominated the agentic latency.)
    name_res, file_res = await asyncio.gather(
        asyncio.gather(*[_scroll("name", s, lim=3) for s in symbols]),
        asyncio.gather(*[_scroll("file_path", pf, lim=6)
                        for pf in (set(prime_paths) | set(anchor_files or []))]),
    )
    for batch in name_res:
        for prime in batch:
            await _collect_anchor(prime)
    for batch in file_res:
        for prime in batch:
            if prime.get("defines_fqn") or prime.get("chunk_type", "") in (
                "class_declaration", "interface_declaration", "class", "interface",
            ):
                await _collect_anchor(prime)

    async def _edges_for(prime: dict) -> list[tuple[dict, str]]:
        """All structural edges for one anchor, as (payload, relation) in
        priority order. The 4 scroll types run concurrently; the per-ref
        collaborator lookups are batched into ONE MatchAny scroll (was up to
        12 sequential scrolls — the main latency sink)."""
        symbol = prime.get("name", "")
        fqn = prime.get("defines_fqn")
        fp = prime.get("file_path", "")
        pkg = str(Path(fp).parent) if fp else ""
        inh_keys = ([symbol] if symbol else []) + ([fqn] if fqn else [])
        refs = [r for r in (prime.get("references_fqn") or [])[:12]
                if isinstance(r, str) and r.startswith(internal_prefix)]

        async def _subclasses():
            if not inh_keys:
                return []
            try:
                sub = await client.scroll(
                    collection_name=collection,
                    scroll_filter=models.Filter(must=[models.FieldCondition(
                        key="inherits_from", match=models.MatchAny(any=inh_keys))]),
                    limit=40, with_payload=True,
                )
                return [((pt.payload or {}), "subclass") for pt in (sub[0] or [])]
            except Exception:
                return []

        async def _callers():
            if not fqn:
                return []
            return [(vp, "subclass_or_caller")
                    for vp in await _scroll("references_fqn", fqn, lim=40)]

        async def _collaborators():
            if not refs:
                return []
            try:
                res = await client.scroll(
                    collection_name=collection,
                    scroll_filter=models.Filter(must=[models.FieldCondition(
                        key="defines_fqn", match=models.MatchAny(any=refs))]),
                    limit=40, with_payload=True,
                )
                return [((pt.payload or {}), "collaborator") for pt in (res[0] or [])]
            except Exception:
                return []

        async def _siblings():
            if not pkg:
                return []
            sibs = [sp for sp in (await _scroll("file_path", pkg, match_text=True, lim=80))
                    if str(Path(sp.get("file_path", "")).parent) == pkg]
            sibs.sort(key=lambda s: not _name_related(s.get("file_path", "")))
            return [(sp, "sibling") for sp in sibs]

        parts = await asyncio.gather(
            _subclasses(), _callers(), _collaborators(), _siblings())
        return [edge for part in parts for edge in part]

    # Process all anchors concurrently, then apply _add in deterministic
    # order (preserves the original first-seen priority semantics).
    for edges in await asyncio.gather(*[_edges_for(p) for p in anchors]):
        for payload, relation in edges:
            _add(payload, relation)

    ordered = sorted(ranked.values(), key=lambda t: t[0])
    return [link for _, link in ordered][:limit]
