"""Tests for design pattern detection."""

from rag.core.patterns import (
    detect_patterns_from_name,
    detect_patterns_from_source,
    _cyclomatic_complexity,
    _cognitive_complexity,
)
import ast


def test_detect_repository_from_name():
    matches = detect_patterns_from_name("UserRepository")
    patterns = [m.pattern for m in matches]
    assert "repository" in patterns


def test_detect_factory_from_name():
    matches = detect_patterns_from_name("ConnectionFactory")
    patterns = [m.pattern for m in matches]
    assert "factory" in patterns


def test_detect_singleton_from_name():
    matches = detect_patterns_from_name("DatabaseSingleton")
    patterns = [m.pattern for m in matches]
    assert "singleton" in patterns


def test_detect_patterns_from_source_async():
    source = '''
import asyncio

async def fetch_data():
    await asyncio.sleep(1)
'''
    meta = detect_patterns_from_source(source, "fetch_data")
    assert meta["is_async"] is True
    assert "async_await" in meta["concurrency_patterns"]


def test_detect_patterns_from_source_inheritance():
    source = '''
from abc import ABC

class AuthProvider(ABC):
    pass
'''
    meta = detect_patterns_from_source(source, "AuthProvider")
    assert meta["is_abstract"] is True
    assert "ABC" in meta["inherits_from"]


def test_cyclomatic_complexity():
    source = '''
def complex_func(x):
    if x > 0:
        for i in range(x):
            if i % 2 == 0:
                pass
    elif x < 0:
        while x < 0:
            x += 1
'''
    tree = ast.parse(source)
    cc = _cyclomatic_complexity(tree)
    assert cc >= 5  # 1 + if + for + if + elif + while


def test_domain_detection():
    source = '''
def login(username, password):
    token = generate_jwt(username)
    session = create_session(token)
    return token
'''
    meta = detect_patterns_from_source(source, "login")
    assert "auth" in meta["domains"]


def test_layer_detection():
    meta = detect_patterns_from_source("pass", "UserController")
    assert "controller" in meta["layers"]


def test_has_unit_test_detection():
    meta = detect_patterns_from_source("pass", "auth_service", test_files={"test_auth_service"})
    assert meta["has_unit_test"] is True

    meta2 = detect_patterns_from_source("pass", "auth_service", test_files={"test_other"})
    assert meta2["has_unit_test"] is False
