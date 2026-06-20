import pytest
from rag.core.lsp import detect_lsp_servers, LSP_SERVERS


def test_detect_lsp_servers_returns_results():
    results = detect_lsp_servers()
    assert len(results) > 0
    assert all(hasattr(r, "language") for r in results)
    assert all(hasattr(r, "found") for r in results)


def test_detect_lsp_servers_filter_by_language():
    results = detect_lsp_servers(["python"])
    assert len(results) == 1
    assert results[0].language == "python"


def test_detect_lsp_servers_unknown_language():
    results = detect_lsp_servers(["brainfuck"])
    assert len(results) == 0


def test_lsp_server_config_complete():
    for lang, config in LSP_SERVERS.items():
        assert "binary" in config
        assert "name" in config
        assert "install" in config


@pytest.mark.asyncio
async def test_enrich_chunks_with_running_clients():
    import pytest
    from unittest.mock import AsyncMock, MagicMock
    from rag.core.lsp import enrich_chunks_with_running_clients, LSPClient

    # Create a mock LSPClient
    client = MagicMock(spec=LSPClient)
    client.get_references = AsyncMock(return_value=[
        {"uri": "file:///path/to/caller.py", "range": {"start": {"line": 10, "character": 5}}}
    ])

    chunks = [
        {
            "language": "python",
            "file_path": "test.py",
            "start_line": 5,
            "name": "my_function",
            "chunk_type": "function",
            "is_public": True,
        }
    ]

    clients = {"python": client}

    enriched_chunks = await enrich_chunks_with_running_clients(chunks, clients)

    assert len(enriched_chunks) == 1
    assert enriched_chunks[0]["fan_in"] == 1
    assert enriched_chunks[0]["called_by"] == ["/path/to/caller.py:10"]
    client.get_references.assert_called_once_with("test.py", 5, 4)

