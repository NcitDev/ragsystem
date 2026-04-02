"""Cross-encoder reranking using FastEmbed."""

from __future__ import annotations

from typing import Any

import structlog

from rag.config import get_settings
from rag.core.vectorstore import SearchResult

logger = structlog.get_logger()


class Reranker:
    """Cross-encoder reranker using FastEmbed (Qwen3-Reranker-4B or fallback).

    Two-stage retrieval: first retrieve top-K candidates via vector search,
    then rerank with cross-encoder for higher precision.
    """

    def __init__(self, model_name: str | None = None) -> None:
        settings = get_settings()
        self._model_name = model_name or settings.reranker.model
        self._enabled = settings.reranker.enabled
        self._top_k = settings.reranker.top_k
        self._model: Any = None

    def _get_model(self) -> Any:
        if self._model is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            try:
                self._model = TextCrossEncoder(model_name=self._model_name)
            except Exception:
                fallback = "Xenova/ms-marco-MiniLM-L-6-v2"
                logger.warning(
                    "reranker_model_fallback",
                    requested=self._model_name,
                    fallback=fallback,
                )
                self._model = TextCrossEncoder(model_name=fallback)
            logger.info("reranker_loaded", model=self._model_name)
        return self._model

    def rerank(
        self,
        query: str,
        results: list[SearchResult],
        top_k: int | None = None,
    ) -> list[SearchResult]:
        """Rerank search results using cross-encoder."""
        if not self._enabled or not results:
            return results[:top_k] if top_k else results

        top_k = top_k or self._top_k
        model = self._get_model()

        try:
            scores = list(model.rerank(query, [r.content for r in results]))

            scored_results: list[tuple[float, SearchResult]] = []
            for result_obj, score_obj in zip(results, scores):
                rerank_score = float(score_obj.score) if hasattr(score_obj, "score") else float(score_obj)
                result_obj.score = rerank_score
                result_obj.payload["rerank_score"] = rerank_score
                scored_results.append((rerank_score, result_obj))

            scored_results.sort(key=lambda x: x[0], reverse=True)
            return [r for _, r in scored_results[:top_k]]

        except Exception as e:
            logger.warning("rerank_failed", error=str(e))
            return results[:top_k]
