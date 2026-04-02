"""TOML-based configuration with Pydantic validation."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]


RAG_HOME = Path.home() / ".rag"
CONFIG_PATH = RAG_HOME / "config.toml"
DEFAULT_CONFIG = Path(__file__).parent.parent.parent / "config" / "default.toml"


class ServerSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 7890


class EmbeddingSettings(BaseModel):
    model: str = "Qwen/Qwen3-Embedding-4B"
    provider: str = "auto"
    dim: int = 2560


class RerankerSettings(BaseModel):
    model: str = "Qwen/Qwen3-Reranker-4B"
    enabled: bool = True
    top_k: int = 5


class SparseSettings(BaseModel):
    model: str = "Qdrant/bm25"


class QdrantSettings(BaseModel):
    path: str = "~/.rag/qdrant_data"
    code_collection: str = "code_chunks"
    docs_collection: str = "doc_chunks"

    @property
    def resolved_path(self) -> Path:
        return Path(self.path).expanduser()


class IndexSettings(BaseModel):
    max_chunk_chars: int = 8000
    retrieval_top_k: int = 20
    skip_dirs: list[str] = [
        ".git", "node_modules", ".venv", "venv", "__pycache__",
        "build", "dist", ".tox", ".mypy_cache", ".ruff_cache",
    ]


class LLMSettings(BaseModel):
    ollama_url: str = "http://localhost:11434"
    agent_model: str = "qwen3:8b"


class LSPSettings(BaseModel):
    enabled: bool = True
    auto_detect: bool = True
    timeout: int = 5000


class Settings(BaseModel):
    server: ServerSettings = ServerSettings()
    embeddings: EmbeddingSettings = EmbeddingSettings()
    reranker: RerankerSettings = RerankerSettings()
    sparse: SparseSettings = SparseSettings()
    qdrant: QdrantSettings = QdrantSettings()
    index: IndexSettings = IndexSettings()
    llm: LLMSettings = LLMSettings()
    lsp: LSPSettings = LSPSettings()


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


@lru_cache
def get_settings() -> Settings:
    """Load settings from default config + user config (if exists)."""
    data: dict[str, Any] = {}
    if DEFAULT_CONFIG.exists():
        data = _load_toml(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        user_data = _load_toml(CONFIG_PATH)
        data = _deep_merge(data, user_data)
    return Settings(**data)


def ensure_rag_home() -> None:
    """Create ~/.rag directory if it doesn't exist."""
    RAG_HOME.mkdir(parents=True, exist_ok=True)
