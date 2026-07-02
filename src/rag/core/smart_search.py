"""Smart-search (agentic retrieval) pipeline + shared response models.

Extracted from the ``/smart-search`` route in ``rag.server`` — pure
move-and-rewire, no behavior changes. This module must not import from
``rag.server``; the route passes in the vectorstore, collection, and repo
path. The shared request/response models (and the ``MAX_QUERY_LENGTH`` /
``MAX_TOP_K`` limits) live here so both this module and ``rag.server`` can
use them without an import cycle — ``rag.server`` imports them back.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, Field

from rag.core.structural import (
    RelatedLink,
    query_structural_usages_from_qdrant,
    related_files,
)

logger = structlog.get_logger()

MAX_QUERY_LENGTH = 2000
MAX_TOP_K = 200


# --- Shared response models (used by rag.server routes too) ---


class SearchResultItem(BaseModel):
    file_path: str
    name: str
    parent_name: str
    chunk_type: str
    language: str
    lines: str
    code: str
    score: float
    matched_queries: list[int] = []
    citation: str = ""  # Human-readable source reference
    repo: str = ""  # set on cross-repo fan-out so callers can tell origins apart


class ContextSlice(BaseModel):
    file_path: str
    name: str
    parent_name: str
    chunk_type: str
    language: str
    lines: str
    code: str
    score: float
    token_estimate: int
    citation: str
    why_included: str
    repo: str = ""  # set on cross-repo fan-out


class SmartSearchRequest(BaseModel):
    """Agentic retrieval: LLM infers symbols → exact /resolve + semantic."""

    question: str = Field(..., min_length=1, max_length=MAX_QUERY_LENGTH)
    # Single-repo target. Required unless ``repos`` is set.
    repo: str = ""
    # Cross-repo fan-out: search these repos concurrently and merge the
    # buckets (each item carries a ``repo`` tag). ``["*"]`` = all registered
    # repos. When set, ``repo`` is ignored.
    repos: list[str] | None = Field(None, max_length=10)
    top_k: int = Field(15, ge=1, le=MAX_TOP_K)
    definitions_limit: int = Field(20, ge=1, le=100)
    # usages_limit=0 → auto: bumped to 100 when the question reads like a
    # blast-radius question ("what breaks", "who calls", "usages"...).
    usages_limit: int = Field(0, ge=0, le=200)
    include_semantic: bool = True
    # Structural expansion (siblings/collaborators/callers) as token-light links.
    include_related: bool = True
    related_limit: int = Field(40, ge=0, le=100)
    # Vocab (summary) anchor channel — set False to A/B the layer's contribution.
    include_vocab: bool = True
    # Paginated "show more" candidate link-list (token-light, no code). The
    # caller pages with candidate_offset across turns and reads full bodies only
    # for the files it actually wants.
    candidate_offset: int = Field(0, ge=0)
    candidate_limit: int = Field(25, ge=0, le=200)
    # Lazy mode: when False, strip full `code` from definitions/usages/semantic
    # so the response is links-only (~75% fewer tokens). The caller reads bodies
    # on demand for the files it picks from `candidates`.
    include_bodies: bool = True


class VocabFile(BaseModel):
    """A file surfaced by the vocab (summary) layer — the concept→symbol anchor.

    Returned with its summary + path directly so the caller can use it even when
    exact symbol-resolve (ast-index) is unavailable.
    """

    file_path: str
    name: str
    summary: str
    score: float
    repo: str = ""  # set on cross-repo fan-out


class Candidate(BaseModel):
    """A token-light candidate LINK (no code) for the paginated 'show more' list.

    The caller scans these across turns (via candidate_offset) and reads full
    bodies only for the files it decides it needs.
    """

    file_path: str
    name: str
    lines: str = ""
    source: str          # vocab | definition | usage | related | semantic
    summary: str = ""    # populated for vocab-sourced candidates
    repo: str = ""       # set on cross-repo fan-out


class SmartSearchResponse(BaseModel):
    question: str
    inferred_symbols: list[str]          # raw from the LLM (may include hallucinations)
    grounded_symbols: list[str] = []     # inferred ∩ index + real names from semantic (NOT vocab)
    vocab_anchors: list[str] = []        # file stems surfaced by the vocab (summary) layer
    vocab_files: list[VocabFile] = []    # vocab hits with path + summary (separate, additive)
    definitions: list[ContextSlice]      # prime files — full code
    usages: list[ContextSlice]
    related: list[RelatedLink]           # siblings/collaborators/callers — links only
    semantic: list[SearchResultItem]
    candidates: list[Candidate] = []     # paginated 'show more' link list (this page)
    candidates_total: int = 0            # full pool size — page with candidate_offset
    repos_searched: list[str] = []       # populated on cross-repo fan-out
    symbol_inference_ms: float
    latency_ms: float


# Question phrasings that imply a blast-radius query → pull symbol usages.
_BLAST_RADIUS_SIGNALS = (
    "what breaks", "who calls", "blast radius", "all usages", "usages",
    "implementors", "callers", "subclass", "impact", "depends", "references",
    "affected", "what code breaks",
)


# --- Slice helpers (used by rag.server routes too) ---


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text or "") + 3) // 4)


def _trim_to_token_budget(code: str, token_budget: int) -> tuple[str, int]:
    if token_budget <= 0:
        return "", 0
    max_chars = token_budget * 4
    if len(code) <= max_chars:
        return code, _estimate_tokens(code)
    out_lines: list[str] = []
    used = 0
    for line in code.splitlines():
        line_len = len(line) + 1
        if out_lines and used + line_len > max_chars:
            break
        if not out_lines and line_len > max_chars:
            out_lines.append(line[:max_chars])
            used = max_chars
            break
        out_lines.append(line)
        used += line_len
    trimmed = "\n".join(out_lines).rstrip()
    return trimmed, _estimate_tokens(trimmed)


def _context_slice_from_candidate(candidate: dict[str, Any], token_budget: int | None = None) -> ContextSlice | None:
    code = str(candidate.get("code", ""))
    if token_budget is not None:
        code, token_estimate = _trim_to_token_budget(code, token_budget)
    else:
        token_estimate = int(candidate.get("token_estimate") or _estimate_tokens(code))
    if not code.strip() or token_estimate <= 0:
        return None
    return ContextSlice(
        file_path=str(candidate.get("file_path", "")),
        name=str(candidate.get("name", "")),
        parent_name=str(candidate.get("parent_name", "")),
        chunk_type=str(candidate.get("chunk_type", "")),
        language=str(candidate.get("language", "")),
        lines=str(candidate.get("lines") or f"{candidate.get('start_line', '?')}-{candidate.get('end_line', '?')}"),
        code=code,
        score=round(float(candidate.get("score", 0.0)), 4),
        token_estimate=token_estimate,
        citation=str(candidate.get("citation", "")),
        why_included=str(candidate.get("why_included", "")),
    )


# --- Smart-search internals ---


async def _noop_related() -> list[RelatedLink]:
    return []


async def _ast_index_related(
    repo_path: str, symbols: list[str], prime_paths: set[str], limit: int = 25,
) -> list[RelatedLink]:
    """Structural relatives via the ast-index CLI — implementors + cross-refs.
    AST-based (no LSP/graphify), returns paths not code. This is the channel
    that catches interface implementors and cross-package collaborators."""
    import asyncio
    import json

    async def _run(args: list[str]):
        try:
            proc = await asyncio.create_subprocess_exec(
                "ast-index", *args, cwd=repo_path,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            return json.loads(out.decode()) if out and out.strip() else None
        except (asyncio.TimeoutError, FileNotFoundError, OSError, json.JSONDecodeError):
            return None

    ranked: dict[str, tuple[int, RelatedLink]] = {}

    def _add(item: dict, relation: str, pr: int) -> None:
        fp = item.get("path", "")
        if not fp or fp in prime_paths or (fp in ranked and ranked[fp][0] <= pr):
            return
        line = item.get("line", "?")
        ranked[fp] = (pr, RelatedLink(
            file_path=fp, name=item.get("name", "") or Path(fp).stem,
            lines=f"{line}-{line}", relation=relation,
        ))

    # Run all ast-index subprocesses concurrently (was 2×N sequential calls
    # — the dominant cost of the ast-index channel). Separate processes, so
    # they genuinely parallelize.
    syms = symbols[:5]
    impl_results, refs_results = await asyncio.gather(
        asyncio.gather(*[_run(["implementations", "--format", "json", "--limit", "25", s])
                        for s in syms]),
        asyncio.gather(*[_run(["refs", "--format", "json", "--limit", "25", s])
                        for s in syms]),
    )
    for res in impl_results:
        for it in (res or []):
            _add(it, "implementor", 0)
    for refs in refs_results:
        if isinstance(refs, dict):
            for it in refs.get("usages", []):
                _add(it, "usage", 1)
            for it in refs.get("definitions", []):
                _add(it, "reference", 2)
    return [link for _, link in sorted(ranked.values(), key=lambda t: t[0])][:limit]


async def _symbol_exists(vectorstore, collection: str, name: str) -> bool:
    """True if any indexed chunk is named `name` — used to discard the LLM's
    hallucinated symbols before they reach resolve/expansion."""
    from qdrant_client import models

    client = await vectorstore._get_client()
    try:
        r = await client.scroll(
            collection_name=collection,
            scroll_filter=models.Filter(must=[
                models.FieldCondition(key="name", match=models.MatchValue(value=name))]),
            limit=1, with_payload=False,
        )
        return bool(r[0])
    except Exception:
        return False


async def run_smart_search(
    req: SmartSearchRequest, vectorstore, collection: str, repo_path: str
) -> SmartSearchResponse:
    """Execute the smart-search pipeline (see the ``/smart-search`` route in
    ``rag.server`` for the endpoint docs). The route resolves the repo's
    collection and path and wraps errors in HTTPException."""
    start = time.time()
    from rag.agents.retrieval import infer_symbols
    from rag.core.scoring import score_results

    coll = collection

    # 1. LLM symbol inference (raw — may include hallucinated names).
    s_start = time.time()
    inferred = await infer_symbols(req.question)
    symbol_ms = (time.time() - s_start) * 1000

    # 2. Semantic search. Doubles as the GROUNDING source: real symbol
    #    names from the top hits anchor the inference in the index.
    sresults = await vectorstore.search(
        collection=coll, query=req.question, top_k=req.top_k,
    )
    sresults = score_results(sresults, req.question, reranked=False)[: req.top_k]
    semantic_items = (
        [SearchResultItem(**r.slim(), matched_queries=[0]) for r in sresults]
        if req.include_semantic else []
    )

    # 3. Ground the symbols: keep inferred names that actually EXIST in
    #    the index, then add real names from the top semantic hits. This
    #    discards the LLM's hallucinations (e.g. "BackupEncryptionManager")
    #    so every resolve/expansion anchors on a real indexed symbol.
    verified = [s for s in inferred if await _symbol_exists(vectorstore, coll, s)]

    # 3b. VOCAB channel: search the per-file summary collection. A vague
    #     question embeds near the right file's SUMMARY (which names the
    #     symbol + domain concepts) even when it embeds far from raw code,
    #     so this surfaces canonical anchors that semantic code search
    #     buries — the concept→symbol "anchor" fix.
    vocab_anchors: list[str] = []
    vocab_hits: list[dict[str, Any]] = []
    if req.include_vocab:
        try:
            from rag.core.vocab import search_vocab, vocab_collection_for

            vocab_hits = await search_vocab(
                vectorstore, vocab_collection_for(coll), req.question, top_k=5,
            )
            for hit in vocab_hits:
                nm = hit.get("name") or ""
                if (nm and nm[0].isupper() and len(nm) >= 4
                        and "." not in nm and nm not in vocab_anchors):
                    vocab_anchors.append(nm)
        except Exception as e:
            logger.warning("smart_search_vocab_failed", error=str(e))

    sem_names: list[str] = []
    for r in sresults[:10]:
        nm = (r.payload or {}).get("name") or ""
        # Only type-like names (PascalCase, >=4 chars, no dot) — skip
        # generic method names (get/set) and file-level chunk names
        # ("Foo.kt") that resolve to noise.
        if (nm and nm[0].isupper() and len(nm) >= 4
                and "." not in nm and nm not in sem_names):
            sem_names.append(nm)
    # Grounding is BASELINE-first (inferred ∩ index + semantic names).
    # Injecting vocab anchors unconditionally drifted resolve/related off
    # the exact named symbol and cost ~5% on precise questions. So vocab
    # anchors are a GATED FALLBACK: used for grounding only when the
    # baseline produced little/nothing (e.g. no LLM symbol inference
    # available), where they can't displace a stronger signal — they just
    # give exact resolve (ast-index) something real to resolve.
    grounded = list(dict.fromkeys(verified + sem_names))
    if len(grounded) < 2 and vocab_anchors:
        vocab_grounded = [s for s in vocab_anchors if await _symbol_exists(vectorstore, coll, s)]
        grounded = list(dict.fromkeys(grounded + vocab_grounded))
    grounded = grounded[:8]

    # 4. Exact resolve on the grounded symbols.
    definitions: list[ContextSlice] = []
    usages: list[ContextSlice] = []
    if grounded:
        from rag.core.ast_index import resolve_symbols

        usages_limit = req.usages_limit
        if usages_limit == 0 and any(
            sig in req.question.lower() for sig in _BLAST_RADIUS_SIGNALS
        ):
            usages_limit = 100

        resolved = resolve_symbols(
            repo_path, grounded,
            definitions_limit=req.definitions_limit, usages_limit=usages_limit,
        )
        definitions = [
            s for item in resolved.get("definitions", [])
            if (s := _context_slice_from_candidate(item)) is not None
        ]
        usages = [
            s for item in resolved.get("usages", [])
            if (s := _context_slice_from_candidate(item)) is not None
        ]
        if usages_limit:
            try:
                structural = await query_structural_usages_from_qdrant(
                    vectorstore, coll, grounded, req.repo
                )
                # Structural usages come back as dicts — convert to
                # ContextSlice so they match the rest of `usages`.
                usages.extend(
                    s for item in structural
                    if (s := _context_slice_from_candidate(item)) is not None
                )
            except Exception as e:
                logger.warning("smart_search_structural_usages_failed", error=str(e))

            # Two-phase relevance trim: a blast-radius query can yield
            # hundreds of usages. Keep only the most relevant, capped.
            if usages:
                def_dirs = {str(Path(s.file_path).parent) for s in definitions}
                syms_lower = {s.lower() for s in grounded}
                trimmed: list[ContextSlice] = []
                for idx, u in enumerate(usages):
                    stem = Path(u.file_path).stem.lower()
                    if (str(Path(u.file_path).parent) in def_dirs
                            or any(s in stem for s in syms_lower) or idx < 10):
                        trimmed.append(u)
                    if len(trimmed) >= 15:
                        break
                usages = trimmed

    # 5. Structural expansion (deterministic, no LLM) on grounded symbols.
    related: list[RelatedLink] = []
    if grounded and req.include_related:
        try:
            prime_paths = {s.file_path for s in definitions}
            anchor_files = {r.payload.get("file_path") for r in sresults[:5]
                            if (r.payload or {}).get("file_path")}
            # Run the Qdrant and ast-index channels concurrently — they're
            # independent; serial execution doubled the expansion latency.
            # The Qdrant payload channel does ~45 filtered scrolls that run
            # as full scans in embedded mode (~14s); now that ast-index is
            # available it covers the same structural edges far faster, so
            # the Qdrant channel is opt-in via RAG_QDRANT_RELATED=1.
            _use_qdrant_rel = os.environ.get("RAG_QDRANT_RELATED", "0") == "1"
            qdrant_rel, ast_rel = await asyncio.gather(
                related_files(vectorstore, coll, grounded, prime_paths,
                              anchor_files=anchor_files, limit=80)
                if _use_qdrant_rel else _noop_related(),
                _ast_index_related(repo_path, grounded, prime_paths, limit=80),
            )
            # Merge by file, keeping the strongest relation, and rank so
            # structural edges (implementor/subclass/usage) survive the cap
            # over generic same-package siblings.
            _REL_PRI = {
                "implementor": 0, "subclass": 0, "subclass_or_caller": 1,
                "usage": 1, "collaborator": 2, "reference": 2, "sibling": 3,
            }
            merged: dict[str, RelatedLink] = {}
            for r in ast_rel + qdrant_rel:
                cur = merged.get(r.file_path)
                if cur is None or _REL_PRI.get(r.relation, 9) < _REL_PRI.get(cur.relation, 9):
                    merged[r.file_path] = r
            # Per-relation cap so no single channel (e.g. 150 interface
            # implementors) floods the cap and crowds out siblings/usages.
            from collections import Counter as _Counter
            _rel_seen: _Counter = _Counter()
            related = []
            for r in sorted(merged.values(), key=lambda r: _REL_PRI.get(r.relation, 9)):
                if _rel_seen[r.relation] >= 12:
                    continue
                _rel_seen[r.relation] += 1
                related.append(r)
                if len(related) >= req.related_limit:
                    break
        except Exception as e:
            logger.warning("smart_search_related_failed", error=str(e))

    latency = (time.time() - start) * 1000
    logger.info(
        "smart_search_executed", repo=req.repo, question=req.question,
        inferred=inferred, vocab_anchors=vocab_anchors, grounded=grounded,
        definitions=len(definitions), usages=len(usages), related=len(related),
        latency_ms=round(latency, 1),
    )
    vocab_files = [
        VocabFile(
            file_path=h.get("file_path", ""), name=h.get("name", ""),
            summary=h.get("summary", ""), score=float(h.get("score", 0.0)),
        )
        for h in vocab_hits if h.get("file_path")
    ]

    # Paginated 'show more' candidate pool: all signals as token-light
    # LINKS (no code), deduped, precision-first. The caller pages with
    # candidate_offset and reads full bodies only for what it picks.
    pool: list[Candidate] = []
    seen_paths: set[str] = set()

    def _add_candidate(fp: str, name: str, lines: str, source: str, summary: str = "") -> None:
        if fp and fp not in seen_paths:
            seen_paths.add(fp)
            pool.append(Candidate(file_path=fp, name=name, lines=lines,
                                  source=source, summary=summary))

    for s in definitions:
        _add_candidate(s.file_path, getattr(s, "name", ""), getattr(s, "lines", ""), "definition")
    for vf in vocab_files:
        _add_candidate(vf.file_path, vf.name, "", "vocab", vf.summary)
    for s in usages:
        _add_candidate(s.file_path, getattr(s, "name", ""), getattr(s, "lines", ""), "usage")
    for r in related:
        _add_candidate(r.file_path, r.name, r.lines, "related")
    for it in semantic_items:
        _add_candidate(it.file_path, it.name, it.lines, "semantic")

    candidates_total = len(pool)
    page = pool[req.candidate_offset: req.candidate_offset + req.candidate_limit]

    # Lazy mode: drop full code bodies — candidates/links carry path+lines
    # so the caller fetches bodies on demand. Cuts response tokens ~75%.
    if not req.include_bodies:
        for s in definitions:
            s.code = ""
        for s in usages:
            s.code = ""
        for it in semantic_items:
            it.code = ""

    return SmartSearchResponse(
        question=req.question, inferred_symbols=inferred, grounded_symbols=grounded,
        vocab_anchors=vocab_anchors, vocab_files=vocab_files,
        definitions=definitions, usages=usages, related=related,
        semantic=semantic_items,
        candidates=page, candidates_total=candidates_total,
        symbol_inference_ms=round(symbol_ms, 1), latency_ms=round(latency, 1),
    )


async def run_smart_search_multi(
    req: SmartSearchRequest,
    vectorstore,
    targets: list[tuple[str, str, str]],
) -> SmartSearchResponse:
    """Cross-repo fan-out: run the pipeline once per (repo_name, collection,
    repo_path) target concurrently, tag every item with its repo, and merge
    the buckets. Per-bucket limits from the request apply to the MERGED lists
    (semantic re-sorted by score; the rest concatenated in target order)."""
    start = time.time()

    async def _one(name: str, collection: str, repo_path: str) -> tuple[str, SmartSearchResponse | None]:
        sub_req = req.model_copy(update={"repo": name, "repos": None})
        try:
            return name, await run_smart_search(sub_req, vectorstore, collection, repo_path)
        except Exception as e:
            logger.warning("smart_search_repo_failed", repo=name, error=str(e))
            return name, None

    results = await asyncio.gather(*(_one(*t) for t in targets))

    merged = SmartSearchResponse(
        question=req.question, inferred_symbols=[], definitions=[], usages=[],
        related=[], semantic=[], symbol_inference_ms=0.0, latency_ms=0.0,
    )
    for name, resp in results:
        if resp is None:
            continue
        merged.repos_searched.append(name)
        for sym in resp.inferred_symbols:
            if sym not in merged.inferred_symbols:
                merged.inferred_symbols.append(sym)
        for sym in resp.grounded_symbols:
            if sym not in merged.grounded_symbols:
                merged.grounded_symbols.append(sym)
        for anchor in resp.vocab_anchors:
            if anchor not in merged.vocab_anchors:
                merged.vocab_anchors.append(anchor)
        for bucket in ("vocab_files", "definitions", "usages", "related", "semantic", "candidates"):
            for item in getattr(resp, bucket):
                item.repo = name
                getattr(merged, bucket).append(item)
        merged.candidates_total += resp.candidates_total
        merged.symbol_inference_ms += resp.symbol_inference_ms

    merged.semantic.sort(key=lambda it: it.score, reverse=True)
    merged.semantic = merged.semantic[: req.top_k]
    merged.definitions = merged.definitions[: req.definitions_limit]
    if req.usages_limit:
        merged.usages = merged.usages[: req.usages_limit]
    merged.related = merged.related[: req.related_limit]
    merged.vocab_files.sort(key=lambda v: v.score, reverse=True)
    merged.latency_ms = round((time.time() - start) * 1000, 1)

    logger.info(
        "smart_search_multi_executed",
        repos=merged.repos_searched, question=req.question,
        definitions=len(merged.definitions), semantic=len(merged.semantic),
    )
    return merged
