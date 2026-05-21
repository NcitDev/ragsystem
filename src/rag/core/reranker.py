"""Ollama-backed cross-encoder reranker using Qwen3-Reranker.

Wraps Ollama /api/generate with a yes/no relevance prompt and the /no_think
directive (Qwen3-Reranker is a reasoning model). ~200ms per pair on M-series
with the 4B Q8 quant. Reranks the top-K candidates from dense search.
"""

from __future__ import annotations

import asyncio

import httpx
import structlog

from rag.config import get_settings
from rag.core.vectorstore import SearchResult

logger = structlog.get_logger()


_PROMPT_TEMPLATE = (
    "<|im_start|>system\n"
    "You are a relevance judge. Output exactly one token: yes or no.<|im_end|>\n"
    "<|im_start|>user\n"
    "Query: {query}\n"
    "Document: {doc}\n"
    "Is this document relevant to the query? Answer yes or no. /no_think<|im_end|>\n"
    "<|im_start|>assistant\n<think>\n\n</think>\n\n"
)


class OllamaReranker:
    """Cross-encoder reranker via Ollama yes/no scoring."""

    def __init__(self, model_name: str | None = None) -> None:
        settings = get_settings()
        self._model = model_name or settings.reranker.model
        self._enabled = settings.reranker.enabled
        self._top_k = settings.reranker.top_k
        self._url = settings.llm.ollama_url
        self._max_doc_chars = 4000

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def warmup(self) -> None:
        try:
            await self._score_pair("warmup", "warmup")
            logger.info("reranker_warmed_up", model=self._model)
        except Exception as e:
            logger.warning("reranker_warmup_failed", error=repr(e))

    async def _score_pair(self, query: str, doc: str) -> float:
        """Return 1.0 (yes), 0.0 (no), or 0.5 (unparseable)."""
        prompt = _PROMPT_TEMPLATE.format(
            query=query[:500],
            doc=doc[: self._max_doc_chars],
        )
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self._url}/api/generate",
                    json={
                        "model": self._model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"num_predict": 3, "temperature": 0},
                    },
                )
                resp.raise_for_status()
                out = resp.json().get("response", "").strip().lower()
            if out.startswith("yes"):
                return 1.0
            if out.startswith("no"):
                return 0.0
            return 0.5
        except Exception as e:
            logger.warning("reranker_score_failed", error=repr(e))
            return 0.5

    async def rerank(
        self,
        query: str,
        results: list[SearchResult],
        top_k: int | None = None,
        max_concurrent: int = 4,
    ) -> list[SearchResult]:
        if not self._enabled or not results:
            return results[: top_k or self._top_k]

        sem = asyncio.Semaphore(max_concurrent)

        async def _bound(r: SearchResult) -> tuple[float, SearchResult]:
            async with sem:
                s = await self._score_pair(query, r.content)
                return s, r

        scored = await asyncio.gather(*[_bound(r) for r in results])
        scored.sort(key=lambda x: (x[0], x[1].score), reverse=True)
        out: list[SearchResult] = []
        for new_score, r in scored:
            r.score = new_score
            out.append(r)
        return out[: top_k or self._top_k]
