"""Tests for configuration loading and validation."""

from rag.config import Settings, ServerSettings, EmbeddingSettings, IndexSettings, LLMSettings


def test_default_settings():
    s = Settings()
    assert s.server.port == 7890
    assert s.embeddings.dim == 2560
    assert s.reranker.enabled is True
    assert s.qdrant.code_collection == "code_chunks"


def test_server_port_validation():
    import pytest

    with pytest.raises(Exception):
        ServerSettings(port=0)
    with pytest.raises(Exception):
        ServerSettings(port=70000)
    s = ServerSettings(port=8080)
    assert s.port == 8080


def test_embedding_provider_validation():
    import pytest

    s = EmbeddingSettings(provider="auto")
    assert s.provider == "auto"
    s = EmbeddingSettings(provider="ollama")
    assert s.provider == "ollama"
    with pytest.raises(Exception):
        EmbeddingSettings(provider="invalid")


def test_dim_validation():
    import pytest

    with pytest.raises(Exception):
        EmbeddingSettings(dim=0)
    s = EmbeddingSettings(dim=384)
    assert s.dim == 384


def test_ollama_url_validation():
    import pytest

    s = LLMSettings(ollama_url="http://localhost:11434")
    assert s.ollama_url == "http://localhost:11434"
    with pytest.raises(Exception):
        LLMSettings(ollama_url="ftp://bad")


def test_index_settings_bounds():
    import pytest

    with pytest.raises(Exception):
        IndexSettings(max_chunk_chars=10)
    s = IndexSettings(max_chunk_chars=1000)
    assert s.max_chunk_chars == 1000
