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
    # start_line is 1-based; LSP positions are 0-based (legacy column fallback = 4)
    client.get_references.assert_called_once_with("test.py", 4, 4)


@pytest.mark.asyncio
async def test_enrich_uses_precise_name_position():
    from unittest.mock import AsyncMock, MagicMock
    from rag.core.lsp import enrich_chunks_with_running_clients, LSPClient

    client = MagicMock(spec=LSPClient)
    client.get_references = AsyncMock(return_value=[])

    chunks = [
        {
            "language": "python",
            "file_path": "test.py",
            "start_line": 3,       # decorator line (1-based)
            "name_line": 4,        # 0-based row of the `def` name identifier
            "name_col": 4,
            "name": "cached_fn",
            "chunk_type": "function",
            "is_public": True,
        }
    ]

    enriched = await enrich_chunks_with_running_clients(chunks, {"python": client})
    client.get_references.assert_called_once_with("test.py", 4, 4)
    # zero refs at a precise position → dead-code candidate
    assert enriched[0]["dead_code_candidate"] is True


@pytest.mark.asyncio
async def test_no_dead_code_flag_without_precise_position():
    from unittest.mock import AsyncMock, MagicMock
    from rag.core.lsp import enrich_chunks_with_running_clients, LSPClient

    client = MagicMock(spec=LSPClient)
    client.get_references = AsyncMock(return_value=[])

    chunks = [
        {
            "language": "python",
            "file_path": "test.py",
            "start_line": 5,
            "name": "maybe_used",
            "chunk_type": "function",
            "is_public": True,
        }
    ]

    enriched = await enrich_chunks_with_running_clients(chunks, {"python": client})
    # position was guessed → empty refs must NOT mark dead code
    assert "dead_code_candidate" not in enriched[0]

