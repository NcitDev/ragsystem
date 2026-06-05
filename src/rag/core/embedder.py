"""Dense embeddings via Qwen3 on Ollama.

FastEmbed (and the BM25 sparse path that depended on it) was removed in
the post-launch refactor — the daemon is now Ollama-only. The legacy
``provider`` setting is retained on ``EmbeddingSettings`` for config
back-compat but is ignored at runtime.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Any  # noqa: F401  (kept for back-compat type hints)

import httpx
import structlog

from rag.config import get_settings
from rag.core.errors import EmbeddingError

logger = structlog.get_logger()

# Per-request HTTP timeout to Ollama. Generous enough for a 64-text batch on
# CPU, but far below the old 300s so a stuck request fails fast and retries.
REQUEST_TIMEOUT = 60.0
# Hard ceiling on total time spent retrying a single sub-batch (across all
# attempts + backoff). Without this, three sequential request timeouts could
# block an index/search for ~15 minutes.
MAX_RETRY_SECONDS = 90.0
# Cap on a single backoff sleep so exponential growth can't overshoot.
MAX_BACKOFF = 8.0

# Qwen3-Embedding uses instruction-based prefixes
DOCUMENT_INSTRUCTION = "Instruct: Retrieve code that is semantically similar\nQuery: "
QUERY_INSTRUCTION = "Instruct: Given a code search query, retrieve relevant code snippets\nQuery: "


@dataclass
class EmbeddingResult:
    dense: list[float]
    # Sparse fields are kept for back-compat with the embedding cache
    # binary layout — they are always None now that the BM25 path is gone.
    sparse_indices: list[int] | None = None
    sparse_values: list[float] | None = None


class OllamaEmbedder:
    """Dense embeddings via Ollama API (Qwen3-Embedding-4B)."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        settings = get_settings()
        self._base_url = base_url or settings.llm.ollama_url
        self._model = model or settings.embeddings.model
        self._dim = settings.embeddings.dim

    @property
    def dim(self) -> int:
        return self._dim

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        prefixed = [f"{DOCUMENT_INSTRUCTION}{t}" for t in texts]
        return await self._embed_batch(prefixed)

    async def embed_query(self, text: str) -> list[float]:
        prefixed = f"{QUERY_INSTRUCTION}{text}"
        results = await self._embed_batch([prefixed])
        return results[0]

    async def _embed_batch(
        self,
        texts: list[str],
        batch_size: int | None = None,
    ) -> list[list[float]]:
        """Embed texts using native Ollama batching.

        Ollama's /api/embed accepts ``input`` as a list — one HTTP call per
        sub-batch beats one-per-text by a huge margin. Sub-batches are sent
        sequentially so indexing does not saturate a developer MacBook with
        competing local model requests.
        """
        if not texts:
            return []
        settings = get_settings()
        batch_size = batch_size or settings.embeddings.batch_size
        sub_batches = [texts[i : i + batch_size] for i in range(0, len(texts), batch_size)]

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            results = []
            for batch in sub_batches:
                results.append(await self._embed_batch_request(client, batch))

        flat: list[list[float]] = []
        for r in results:
            flat.extend(r)
        return flat

    async def _embed_batch_request(
        self,
        client: httpx.AsyncClient,
        batch: list[str],
        max_retries: int = 3,
    ) -> list[list[float]]:
        loop = asyncio.get_event_loop()
        deadline = loop.time() + MAX_RETRY_SECONDS
        for attempt in range(max_retries):
            try:
                resp = await client.post(
                    f"{self._base_url}/api/embed",
                    json={
                        "model": self._model,
                        "input": batch,
                        "keep_alive": get_settings().embeddings.keep_alive,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                embeddings = data.get("embeddings") or []
                if len(embeddings) != len(batch):
                    raise EmbeddingError(
                        f"Ollama returned {len(embeddings)} embeddings for batch of {len(batch)}"
                    )
                logger.debug(
                    "embed_batch_complete",
                    batch_size=len(batch),
                    total_ms=round(float(data.get("total_duration") or 0) / 1_000_000, 1),
                    load_ms=round(float(data.get("load_duration") or 0) / 1_000_000, 1),
                    prompt_eval_count=data.get("prompt_eval_count"),
                )
                return embeddings
            except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as e:
                remaining = deadline - loop.time()
                # Exponential backoff with full jitter, capped, and never longer
                # than the time we have left in the retry budget.
                wait = min(MAX_BACKOFF, 2 ** attempt)
                wait = random.uniform(0, wait)
                if attempt < max_retries - 1 and remaining > wait:
                    logger.warning(
                        "embed_retry",
                        attempt=attempt + 1,
                        wait=round(wait, 2),
                        remaining=round(remaining, 1),
                        error=str(e),
                    )
                    await asyncio.sleep(wait)
                else:
                    reason = "retry budget exhausted" if remaining <= wait else f"{max_retries} retries"
                    raise EmbeddingError(f"Embedding failed after {reason}: {e}") from e
        raise EmbeddingError("Embedding failed: exhausted retries")

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                if resp.status_code != 200:
                    return False
                models = [m["name"] for m in resp.json().get("models", [])]
                return any(self._model.split("/")[-1].lower() in m.lower() for m in models)
        except Exception:
            return False

    async def verify_model(self) -> None:
        """Verify Ollama is running and model is available. Raises EmbeddingError if not."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                if resp.status_code != 200:
                    raise EmbeddingError(
                        f"Ollama not responding at {self._base_url}. Start it with: ollama serve"
                    )
                models = [m["name"] for m in resp.json().get("models", [])]
                model_short = self._model.split("/")[-1].lower()
                if not any(model_short in m.lower() for m in models):
                    raise EmbeddingError(
                        f"Model '{self._model}' not found in Ollama. "
                        f"Pull it with: ollama pull {self._model}\n"
                        f"Available models: {', '.join(models)}"
                    )
        except httpx.ConnectError:
            raise EmbeddingError(
                f"Cannot connect to Ollama at {self._base_url}. Start it with: ollama serve"
            )


class HybridEmbedder:
    """Dense embedder facade.

    Historically wrapped a dense (Ollama or FastEmbed) + sparse (BM25)
    pair behind a single API. After the FastEmbed nuke this is dense-only
    via Ollama; the class name is kept so callers (vectorstore, server,
    cache, tests) don't need to change.

    ``settings.embeddings.provider`` is intentionally ignored — Ollama
    is the only supported runtime now.
    """

    def __init__(self) -> None:
        self._dense: OllamaEmbedder | None = None
        # Always Ollama after FastEmbed was nuked; the provider config
        # field is preserved for back-compat but no longer drives anything.
        self._provider: str = "ollama"

    @property
    def dim(self) -> int:
        if self._dense is None:
            return get_settings().embeddings.dim
        return self._dense.dim

    @property
    def provider(self) -> str:
        return self._provider

    async def initialize(self) -> None:
        """Initialize the Ollama-backed dense embedder.

        ``settings.embeddings.provider`` is ignored (FastEmbed is gone);
        we always create an ``OllamaEmbedder`` and verify the configured
        model is loaded. No fallback.
        """
        settings = get_settings()
        self._dense = OllamaEmbedder()
        await self._dense.verify_model()
        self._provider = "ollama"
        logger.info("embedder_ready", provider="ollama", model=settings.embeddings.model)

    async def embed_documents(self, texts: list[str]) -> list[EmbeddingResult]:
        if self._dense is None:
            await self.initialize()
        assert self._dense is not None

        dense_vecs = await self._dense.embed_documents(texts)
        return [EmbeddingResult(dense=d) for d in dense_vecs]

    async def embed_query(self, text: str) -> EmbeddingResult:
        if self._dense is None:
            await self.initialize()
        assert self._dense is not None

        dense = await self._dense.embed_query(text)
        return EmbeddingResult(dense=dense)
