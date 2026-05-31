"""Tests for relevance scoring — focus on the string-vs-bool flag normalization."""

import pytest

from rag.core.scoring import _truthy, _quality_score


def test_truthy_handles_string_flags():
    # Chunk enrichment stores flags as the strings "true"/"false".
    assert _truthy("true") is True
    assert _truthy("True") is True
    assert _truthy("false") is False   # the bug: non-empty "false" was truthy
    assert _truthy("") is False
    assert _truthy(True) is True
    assert _truthy(False) is False
    assert _truthy(1) is True
    assert _truthy(0) is False


def test_truthy_default_for_missing():
    assert _truthy(None) is False
    assert _truthy(None, default=True) is True


def test_quality_score_does_not_boost_on_string_false():
    """A 'false' docstring/test flag must not earn the boost it used to."""
    no_signals = _quality_score({"has_docstring": "false", "has_unit_test": "false", "is_public": "false"})
    # is_public defaults True; explicit "false" => no +0.1. No doc/test boosts.
    assert no_signals == pytest.approx(0.0)

    with_signals = _quality_score({"has_docstring": "true", "has_unit_test": "true", "is_public": "true"})
    # +0.2 doc +0.3 test +0.1 public
    assert with_signals == pytest.approx(0.6)


def test_quality_score_dead_code_penalty():
    assert _quality_score({"dead_code_candidate": "true"}) < _quality_score({})


def test_quality_score_high_complexity_penalty():
    assert _quality_score({"complexity_cyclomatic": 25}) < _quality_score({"complexity_cyclomatic": 5})
