"""Dense embeddings (Qwen3 via Ollama) + sparse BM25 via FastEmbed.

Requires Ollama running with the configured embedding model.
No fallback — fails fast if Ollama is unavailable.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

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

    async def _embed_batch(self, texts: list[str], max_concurrent: int = 10) -> list[list[float]]:
        """Embed texts in parallel with bounded concurrency."""
        semaphore = asyncio.Semaphore(max_concurrent)
        async with httpx.AsyncClient(timeout=120) as client:
            async def _bounded(text: str) -> list[float]:
                async with semaphore:
                    return await self._embed_single(client, text)

            return list(await asyncio.gather(*[_bounded(t) for t in texts]))

    async def _embed_single(
        self, client: httpx.AsyncClient, text: str, max_retries: int = 3
    ) -> list[float]:
        for attempt in range(max_retries):
            try:
                resp = await client.post(
                    f"{self._base_url}/api/embed",
                    json={"model": self._model, "input": text},
                )
                resp.raise_for_status()
                data = resp.json()
                embeddings = data.get("embeddings", [])
                if embeddings:
                    return embeddings[0]
                raise EmbeddingError(f"Empty embedding returned for text of length {len(text)}")
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


class SparseEmbedder:
    """Sparse BM25 embeddings via FastEmbed."""

    def __init__(self) -> None:
        self._model: Any = None

    def _get_model(self) -> Any:
        if self._model is None:
            from fastembed import SparseTextEmbedding

            settings = get_settings()
            self._model = SparseTextEmbedding(model_name=settings.sparse.model)
            logger.info("sparse_model_loaded", model=settings.sparse.model)
        return self._model

    def embed_documents(self, texts: list[str]) -> list[dict]:
        model = self._get_model()
        results = []
        for sparse_vec in model.embed(texts):
            results.append({
                "indices": sparse_vec.indices.tolist(),
                "values": sparse_vec.values.tolist(),
            })
        return results

    def embed_query(self, text: str) -> dict:
        return self.embed_documents([text])[0]


class HybridEmbedder:
    """Combines dense (Ollama) + sparse (BM25) embeddings.

    Requires Ollama with the configured model. Fails fast if unavailable.
    """

    def __init__(self) -> None:
        self._dense: OllamaEmbedder | None = None
        self._sparse = SparseEmbedder()
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
        """Verify Ollama is running with the required model."""
        self._dense = OllamaEmbedder()
        await self._dense.verify_model()
        self._provider = "ollama"
        logger.info("embedder_ready", provider="ollama", model=get_settings().embeddings.model)

    async def embed_documents(self, texts: list[str]) -> list[EmbeddingResult]:
        if self._dense is None:
            await self.initialize()

        dense_vecs = await self._dense.embed_documents(texts)
        sparse_vecs = self._sparse.embed_documents(texts)

        return [
            EmbeddingResult(dense=d, sparse_indices=s["indices"], sparse_values=s["values"])
            for d, s in zip(dense_vecs, sparse_vecs)
        ]

    async def embed_query(self, text: str) -> EmbeddingResult:
        if self._dense is None:
            await self.initialize()

        dense = await self._dense.embed_query(text)
        sparse = self._sparse.embed_query(text)
        return EmbeddingResult(
            dense=dense,
            sparse_indices=sparse["indices"],
            sparse_values=sparse["values"],
        )
