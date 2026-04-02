"""Tests for LSP server detection."""

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
