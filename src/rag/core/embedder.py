"""Dense embeddings (Qwen3 via Ollama/FastEmbed) + sparse BM25 via FastEmbed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from rag.config import get_settings

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

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=120) as client:
            results: list[list[float]] = []
            for text in texts:
                resp = await client.post(
                    f"{self._base_url}/api/embed",
                    json={"model": self._model, "input": text},
                )
                resp.raise_for_status()
                data = resp.json()
                embeddings = data.get("embeddings", [])
                if embeddings:
                    results.append(embeddings[0])
                else:
                    logger.warning("empty_embedding", text_len=len(text))
                    results.append([0.0] * self._dim)
            return results

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


class FastEmbedDenseEmbedder:
    """Dense embeddings via FastEmbed (ONNX) — fallback when Ollama unavailable."""

    def __init__(self, model: str | None = None) -> None:
        settings = get_settings()
        self._model_name = model or settings.embeddings.model
        self._dim = settings.embeddings.dim
        self._model: Any = None

    @property
    def dim(self) -> int:
        return self._dim

    def _get_model(self) -> Any:
        if self._model is None:
            self._init_model()
        return self._model

    def _init_model(self) -> None:
        from fastembed import TextEmbedding

        try:
            self._model = TextEmbedding(model_name=self._model_name)
            # Detect actual dimension from a test embedding
            test = list(self._model.embed(["test"]))[0]
            self._dim = len(test)
        except Exception:
            fallback = "BAAI/bge-small-en-v1.5"
            logger.warning(
                "fastembed_model_fallback",
                requested=self._model_name,
                fallback=fallback,
            )
            self._model_name = fallback
            self._model = TextEmbedding(model_name=fallback)
            self._dim = 384
        logger.info("fastembed_dense_loaded", model=self._model_name, dim=self._dim)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        model = self._get_model()
        return [emb.tolist() for emb in model.embed(texts)]

    async def embed_query(self, text: str) -> list[float]:
        results = await self.embed_documents([text])
        return results[0]


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
    """Combines dense (Ollama or FastEmbed) + sparse (BM25) embeddings.

    Auto-detects Ollama at init; falls back to FastEmbed ONNX.
    """

    def __init__(self) -> None:
        self._dense: OllamaEmbedder | FastEmbedDenseEmbedder | None = None
        self._sparse = SparseEmbedder()
        self._provider: str = "unknown"

    @property
    def dim(self) -> int:
        if self._dense is None:
            return get_settings().embeddings.dim
        return self._dense.dim

    @property
    def provider(self) -> str:
        return self._provider

    async def initialize(self) -> None:
        """Probe Ollama and select dense backend. Eagerly loads model to detect dim."""
        settings = get_settings()

        if settings.embeddings.provider == "ollama":
            self._dense = OllamaEmbedder()
            self._provider = "ollama"
        elif settings.embeddings.provider == "fastembed":
            fe = FastEmbedDenseEmbedder()
            fe._init_model()  # Eagerly load to detect actual dim
            self._dense = fe
            self._provider = "fastembed"
        else:
            # Auto-detect
            ollama = OllamaEmbedder()
            if await ollama.health_check():
                self._dense = ollama
                self._provider = "ollama"
                logger.info("embedder_selected", provider="ollama", model=settings.embeddings.model)
            else:
                fe = FastEmbedDenseEmbedder()
                fe._init_model()  # Eagerly load to detect actual dim
                self._dense = fe
                self._provider = "fastembed"
                logger.info("embedder_selected", provider="fastembed", model=fe._model_name, dim=fe.dim)

    async def embed_documents(self, texts: list[str]) -> list[EmbeddingResult]:
        if self._dense is None:
            await self.initialize()
        assert self._dense is not None

        dense_vecs = await self._dense.embed_documents(texts)
        sparse_vecs = self._sparse.embed_documents(texts)

        results = []
        for dense, sparse in zip(dense_vecs, sparse_vecs):
            results.append(EmbeddingResult(
                dense=dense,
                sparse_indices=sparse["indices"],
                sparse_values=sparse["values"],
            ))
        return results

    async def embed_query(self, text: str) -> EmbeddingResult:
        if self._dense is None:
            await self.initialize()
        assert self._dense is not None

        dense = await self._dense.embed_query(text)
        sparse = self._sparse.embed_query(text)
        return EmbeddingResult(
            dense=dense,
            sparse_indices=sparse["indices"],
            sparse_values=sparse["values"],
        )
