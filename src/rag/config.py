"""TOML-based configuration with Pydantic validation."""

from __future__ import annotations

import os
import secrets
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]


RAG_HOME = Path.home() / ".rag"
CONFIG_PATH = RAG_HOME / "config.toml"
TOKEN_PATH = RAG_HOME / "token"
DEFAULT_CONFIG = Path(__file__).parent.parent.parent / "config" / "default.toml"


class ServerSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=7890, ge=1, le=65535)

    @field_validator("host")
    @classmethod
    def reject_wildcard_bind(cls, v: str) -> str:
        # The daemon has no TLS and a single bearer token; binding to all
        # interfaces exposes it (and the token, in plaintext over the wire) to
        # the whole network. Force loopback; expose via a reverse proxy instead.
        if v.strip() in ("0.0.0.0", "::", "[::]"):
            raise ValueError(
                f"server.host={v!r} binds all interfaces and exposes the daemon "
                "publicly. Use 127.0.0.1 and put a TLS reverse proxy in front."
            )
        return v


class EmbeddingSettings(BaseModel):
    model: str = "Qwen/Qwen3-Embedding-4B"
    # ``provider`` is deprecated — FastEmbed was removed and the runtime
    # is Ollama-only. Field is kept so existing user configs (with
    # provider="auto"|"ollama"|"fastembed") still parse without error.
    provider: str = Field(default="ollama", pattern=r"^(auto|ollama|fastembed)$")
    dim: int = Field(default=2560, ge=32, le=8192)


class QdrantSettings(BaseModel):
    path: str = "~/.rag/qdrant_data"
    code_collection: str = "code_chunks"
    docs_collection: str = "doc_chunks"

    @property
    def resolved_path(self) -> Path:
        return Path(self.path).expanduser()


class IndexSettings(BaseModel):
    max_chunk_chars: int = Field(default=8000, ge=500, le=100000)
    retrieval_top_k: int = Field(default=20, ge=1, le=500)
    skip_dirs: list[str] = [
        ".git", "node_modules", ".venv", "venv", "__pycache__",
        "build", "dist", ".tox", ".mypy_cache", ".ruff_cache",
    ]


class RerankerSettings(BaseModel):
    model: str = "dengcao/Qwen3-Reranker-4B:Q8_0"
    enabled: bool = True
    top_k: int = Field(default=5, ge=1, le=100)


class LLMSettings(BaseModel):
    ollama_url: str = "http://localhost:11434"
    agent_model: str = "qwen3:8b"
    # Generation model for /ask (RAG synthesis). Defaults to agent_model when unset.
    gen_model: str = ""

    @field_validator("ollama_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("ollama_url must start with http:// or https://")
        return v.rstrip("/")


class LSPSettings(BaseModel):
    enabled: bool = True
    auto_detect: bool = True
    timeout: int = Field(default=5000, ge=1000, le=60000)


class Settings(BaseModel):
    # Pydantic by default rejects unknown top-level keys. After the
    # FastEmbed nuke, ``[reranker]`` and ``[sparse]`` sections may still
    # linger in user configs; allow and ignore them silently.
    model_config = {"extra": "allow"}

    server: ServerSettings = ServerSettings()
    embeddings: EmbeddingSettings = EmbeddingSettings()
    reranker: RerankerSettings = RerankerSettings()
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


def get_or_create_token() -> str:
    """Return the daemon's bearer token, creating one if it doesn't exist.

    The token lives at ~/.rag/token with mode 0600. Used by the daemon to
    authenticate API requests; the CLI reads the same file.
    """
    ensure_rag_home()
    if TOKEN_PATH.exists():
        try:
            existing = TOKEN_PATH.read_text().strip()
            if existing:
                return existing
        except OSError:
            pass
    token = secrets.token_urlsafe(32)
    TOKEN_PATH.write_text(token)
    try:
        os.chmod(TOKEN_PATH, 0o600)
    except OSError:
        # Non-POSIX filesystems may not support chmod; tolerate it.
        pass
    return token


def reload_settings() -> None:
    """Force ``get_settings`` to re-read config files on next call."""
    get_settings.cache_clear()
