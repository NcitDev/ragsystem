"""Tests for robust JSON extraction from agent responses."""

from rag.agents.retrieval import _extract_json_object


def test_plain_json():
    assert _extract_json_object('{"a": 1}') == {"a": 1}


def test_fenced_json_block():
    assert _extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}


def test_fenced_block_no_lang():
    assert _extract_json_object('```\n{"a": 1}\n```') == {"a": 1}


def test_json_with_surrounding_prose():
    text = 'Here is the plan:\n```json\n{"queries": ["x"]}\n```\nHope that helps!'
    assert _extract_json_object(text) == {"queries": ["x"]}


def test_bare_object_in_prose():
    assert _extract_json_object('prefix {"a": 2} suffix') == {"a": 2}


def test_first_of_multiple_fenced_blocks():
    text = '```\n{"a": 3}\n``` then ```\n{"b": 4}\n```'
    assert _extract_json_object(text) == {"a": 3}


def test_unparseable_returns_none():
    assert _extract_json_object("not json at all") is None
    assert _extract_json_object("") is None


def test_json_array_not_accepted_as_object():
    # We require a dict (the SearchPlan shape); a bare array is not valid.
    assert _extract_json_object("[1, 2, 3]") is None
