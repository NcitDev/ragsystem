"""Dense embeddings via Qwen3 on Ollama.

FastEmbed (and the BM25 sparse path that depended on it) was removed in
the post-launch refactor — the daemon is now Ollama-only. The legacy
``provider`` setting is retained on ``EmbeddingSettings`` for config
back-compat but is ignored at runtime.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any  # noqa: F401  (kept for back-compat type hints)

import httpx
import structlog

from rag.config import get_settings
from rag.core.errors import EmbeddingError

logger = structlog.get_logger()

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
        batch_size: int = 64,
        max_concurrent: int = 4,
    ) -> list[list[float]]:
        """Embed texts using native Ollama batching.

        Ollama's /api/embed accepts ``input`` as a list — one HTTP call per
        sub-batch beats one-per-text by a huge margin. We also run a small
        number of sub-batches concurrently to overlap CPU/network with GPU.
        Set ``OLLAMA_NUM_PARALLEL>=2`` on the Ollama side for real benefit.
        """
        if not texts:
            return []
        semaphore = asyncio.Semaphore(max_concurrent)
        sub_batches = [texts[i : i + batch_size] for i in range(0, len(texts), batch_size)]

        async with httpx.AsyncClient(timeout=300) as client:
            async def _run(batch: list[str]) -> list[list[float]]:
                async with semaphore:
                    return await self._embed_batch_request(client, batch)

            results = await asyncio.gather(*[_run(b) for b in sub_batches])

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
        for attempt in range(max_retries):
            try:
                resp = await client.post(
                    f"{self._base_url}/api/embed",
                    json={"model": self._model, "input": batch},
                )
                resp.raise_for_status()
                data = resp.json()
                embeddings = data.get("embeddings") or []
                if len(embeddings) != len(batch):
                    raise EmbeddingError(
                        f"Ollama returned {len(embeddings)} embeddings for batch of {len(batch)}"
                    )
                return embeddings
            except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as e:
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning("embed_retry", attempt=attempt + 1, wait=wait, error=str(e))
                    await asyncio.sleep(wait)
                else:
                    raise EmbeddingError(f"Embedding failed after {max_retries} retries: {e}") from e
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
