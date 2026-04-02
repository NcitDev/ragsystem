"""Tests for query expansion and decomposition."""

from rag.core.query import expand_query, decompose_query


def test_expand_auth():
    result = expand_query("find auth")
    assert "authentication" in result
    assert "jwt" in result


def test_expand_no_match():
    result = expand_query("find xyz")
    assert result == "find xyz"


def test_decompose_and():
    parts = decompose_query("auth and payment")
    assert len(parts) == 2
    assert "auth" in parts[0]
    assert "payment" in parts[1]


def test_decompose_single():
    parts = decompose_query("simple query")
    assert len(parts) == 1
    assert parts[0] == "simple query"


def test_decompose_max():
    parts = decompose_query("a and b and c and d", max_subqueries=2)
    assert len(parts) == 2
