"""Tests for the embedder's bounded retry behavior."""

from __future__ import annotations

import httpx
import pytest

from rag.core.embedder import OllamaEmbedder
from rag.core.errors import EmbeddingError


class _AlwaysTimeoutClient:
    """Stand-in httpx client whose POST always times out."""

    def __init__(self):
        self.calls = 0

    async def post(self, *args, **kwargs):
        self.calls += 1
        raise httpx.TimeoutException("simulated timeout")


async def test_retry_gives_up_and_raises():
    emb = OllamaEmbedder()
    client = _AlwaysTimeoutClient()
    with pytest.raises(EmbeddingError):
        await emb._embed_batch_request(client, ["text"], max_retries=3)
    # max_retries attempts, no more.
    assert client.calls == 3


async def test_retry_budget_caps_total_wait(monkeypatch):
    """When the retry budget is exhausted, it must stop early rather than
    sleeping through every attempt."""
    import rag.core.embedder as emb_mod

    # Make the per-attempt backoff "cost" more than the whole budget so the
    # budget check trips before exhausting max_retries.
    monkeypatch.setattr(emb_mod, "MAX_RETRY_SECONDS", 0.0)

    sleeps: list[float] = []

    async def _fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(emb_mod.asyncio, "sleep", _fake_sleep)

    emb = OllamaEmbedder()
    client = _AlwaysTimeoutClient()
    with pytest.raises(EmbeddingError, match="budget"):
        await emb._embed_batch_request(client, ["t"], max_retries=5)
    # With a zero budget, it should bail after the first failed attempt without
    # ever sleeping.
    assert client.calls == 1
    assert sleeps == []


async def test_successful_request_no_retry():
    class _OkClient:
        def __init__(self):
            self.calls = 0

        async def post(self, *args, **kwargs):
            self.calls += 1

            class _Resp:
                def raise_for_status(self_inner):
                    return None

                def json(self_inner):
                    return {"embeddings": [[0.1, 0.2]]}

            return _Resp()

    emb = OllamaEmbedder()
    client = _OkClient()
    out = await emb._embed_batch_request(client, ["t"], max_retries=3)
    assert out == [[0.1, 0.2]]
    assert client.calls == 1
