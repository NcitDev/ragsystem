"""Design pattern detection for code chunks.

Detects: Repository, Factory, Singleton, Builder, Observer, Strategy,
Adapter, Decorator, Command, Middleware, plus concurrency, domains, layers,
and code quality metrics.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any


@dataclass
class PatternMatch:
    pattern: str
    role: str
    confidence: float
    evidence: str = ""


# --- Name-based pattern detection ---

NAME_PATTERNS: dict[str, list[str]] = {
    "repository": ["repository", "repo", "dao", "dataaccess", "store", "crud"],
    "factory": ["factory", "creator", "builder", "maker"],
    "singleton": ["singleton", "instance", "shared"],
    "observer": ["observer", "listener", "subscriber", "handler", "watcher", "callback"],
    "strategy": ["strategy", "policy", "algorithm"],
    "adapter": ["adapter", "wrapper", "bridge", "proxy", "facade"],
    "decorator": ["decorator", "middleware", "interceptor", "wrapper"],
    "command": ["command", "action", "task", "job", "executor"],
    "builder": ["builder", "config", "configurator"],
    "service": ["service", "manager", "controller", "coordinator", "orchestrator"],
    "model": ["model", "entity", "schema", "dto", "dataclass"],
    "provider": ["provider", "supplier", "source", "client", "connector"],
    "validator": ["validator", "checker", "verifier", "sanitizer"],
    "serializer": ["serializer", "encoder", "decoder", "parser", "formatter"],
    "state_machine": ["state", "transition", "fsm", "machine"],
}

INHERITANCE_PATTERNS: dict[str, list[str]] = {
    "repository": ["BaseRepository", "CRUDBase", "Repository"],
    "factory": ["BaseFactory", "AbstractFactory"],
    "observer": ["EventHandler", "BaseHandler", "Listener"],
    "strategy": ["BaseStrategy", "Strategy", "Policy"],
    "adapter": ["BaseAdapter", "Adapter"],
    "provider": ["Protocol", "ABC", "BaseProvider"],
    "middleware": ["BaseHTTPMiddleware", "Middleware"],
}

DECORATOR_PATTERNS: dict[str, list[str]] = {
    "singleton": ["@singleton", "@lru_cache"],
    "route": ["@router.", "@app.", "@get", "@post", "@put", "@delete"],
    "inject": ["@inject", "@Inject", "@Depends", "@dependency"],
    "test": ["@pytest.mark", "@test", "@unittest", "@mock.patch"],
    "cached": ["@cached", "@cache", "@lru_cache", "@memoize"],
    "retry": ["@retry", "@tenacity", "@backoff"],
    "async_task": ["@celery", "@task", "@background_task"],
    "scheduled": ["@scheduled", "@cron", "@periodic_task"],
    "deprecated": ["@deprecated", "@warn_deprecated"],
    "validated": ["@validator", "@field_validator", "@validate"],
}

CONCURRENCY_IMPORTS: dict[str, str] = {
    "asyncio": "async_await",
    "threading": "threading",
    "multiprocessing": "multiprocessing",
    "concurrent.futures": "thread_pool",
    "queue": "queue",
    "aiohttp": "async_http",
    "httpx": "async_http",
    "asyncpg": "async_db",
    "aiofiles": "async_io",
    "trio": "async_await",
    "anyio": "async_await",
    "gevent": "green_threads",
    "celery": "task_queue",
}

LOCK_PATTERNS = ["Lock(", "RLock(", "Semaphore(", "Event(", "Condition(", "Barrier("]

DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "auth": ["auth", "login", "logout", "token", "password", "session", "oauth", "jwt", "permission", "role"],
    "payment": ["payment", "billing", "charge", "refund", "invoice", "subscription", "stripe", "paypal"],
    "notification": ["notification", "notify", "email", "sms", "push", "alert", "webhook"],
    "database": ["database", "query", "migration", "schema", "table", "column", "index", "orm"],
    "api": ["endpoint", "route", "handler", "request", "response", "middleware", "cors"],
    "cache": ["cache", "redis", "memcached", "ttl", "invalidate", "memoize"],
    "search": ["search", "index", "query", "filter", "sort", "paginate", "elastic", "qdrant"],
    "file": ["file", "upload", "download", "storage", "s3", "blob", "stream"],
    "test": ["test", "mock", "fixture", "assert", "spec", "stub"],
    "config": ["config", "settings", "environment", "env", "dotenv", "secret"],
    "logging": ["log", "logger", "trace", "debug", "structlog", "sentry"],
    "queue": ["queue", "message", "kafka", "rabbitmq", "event", "pubsub", "broker"],
}

LAYER_KEYWORDS: dict[str, list[str]] = {
    "controller": ["router", "endpoint", "handler", "view", "controller", "api"],
    "service": ["service", "usecase", "interactor", "manager", "orchestrator"],
    "repository": ["repository", "repo", "dao", "store", "crud", "persistence"],
    "model": ["model", "entity", "schema", "dto", "dataclass", "table"],
    "utility": ["util", "helper", "common", "shared", "tools", "misc"],
    "config": ["config", "settings", "constants", "env"],
    "middleware": ["middleware", "interceptor", "filter", "guard"],
    "migration": ["migration", "alembic", "flyway", "schema_change"],
}


def detect_patterns_from_name(name: str, parent_name: str = "") -> list[PatternMatch]:
    matches: list[PatternMatch] = []
    name_lower = (name + " " + parent_name).lower()

    for pattern, keywords in NAME_PATTERNS.items():
        for kw in keywords:
            if kw in name_lower:
                matches.append(PatternMatch(
                    pattern=pattern, role="implementation", confidence=0.7,
                    evidence=f"Name contains '{kw}'",
                ))
                break

    return matches


def _cyclomatic_complexity(tree: ast.Module) -> int:
    """Count cyclomatic complexity: 1 + number of decision points."""
    complexity = 1
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.For, ast.While, ast.AsyncFor)):
            complexity += 1
        elif isinstance(node, ast.ExceptHandler):
            complexity += 1
        elif isinstance(node, ast.BoolOp):
            complexity += len(node.values) - 1
        elif isinstance(node, ast.Assert):
            complexity += 1
    return complexity


def _cognitive_complexity(node: ast.AST, nesting: int = 0) -> int:
    """Weighted complexity accounting for nesting depth."""
    total = 0
    nesting_types = (ast.If, ast.For, ast.While, ast.AsyncFor, ast.With, ast.AsyncWith)
    try_types = (ast.Try,)

    for child in ast.iter_child_nodes(node):
        if isinstance(child, nesting_types):
            total += 1 + nesting
            total += _cognitive_complexity(child, nesting + 1)
        elif isinstance(child, try_types):
            total += 1 + nesting
            total += _cognitive_complexity(child, nesting + 1)
        elif isinstance(child, ast.BoolOp):
            total += 1
            total += _cognitive_complexity(child, nesting)
        else:
            total += _cognitive_complexity(child, nesting)

    return total


def detect_patterns_from_source(
    source: str,
    name: str = "",
    test_files: set[str] | None = None,
) -> dict[str, Any]:
    """Extract rich pattern metadata from Python source code."""
    meta: dict[str, Any] = {}

    patterns: list[str] = []
    pattern_roles: list[str] = []

    name_matches = detect_patterns_from_name(name)
    for m in name_matches:
        if m.pattern not in patterns:
            patterns.append(m.pattern)
            pattern_roles.append(m.role)

    try:
        tree = ast.parse(source)
    except SyntaxError:
        meta["patterns"] = patterns
        meta["pattern_roles"] = pattern_roles
        return meta

    # Complexity metrics
    meta["complexity_cyclomatic"] = _cyclomatic_complexity(tree)
    meta["complexity_cognitive"] = _cognitive_complexity(tree)

    imports: list[str] = []
    external_deps: list[str] = []
    decorators_found: list[str] = []
    is_async = False
    concurrency_patterns: list[str] = []
    return_types: list[str] = []
    parameter_types: list[str] = []
    has_docstring = False
    is_public = not name.startswith("_")
    is_abstract = False
    inherits_from: list[str] = []
    calls: list[str] = []
    nesting_depth = 0
    parameter_count = 0

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module.split(".")[0])
                for alias in node.names:
                    imports.append(alias.name)

        if isinstance(node, (ast.AsyncFunctionDef, ast.AsyncFor, ast.AsyncWith)):
            is_async = True

        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                base_name = _get_name(base)
                if base_name:
                    inherits_from.append(base_name)
                    for pattern, bases in INHERITANCE_PATTERNS.items():
                        if base_name in bases and pattern not in patterns:
                            patterns.append(pattern)
                            pattern_roles.append("implementation")

            if any(b in ["ABC", "Protocol"] for b in inherits_from):
                is_abstract = True
                if "interface" not in pattern_roles:
                    pattern_roles.append("interface")

            for dec in node.decorator_list:
                dec_name = _get_decorator_name(dec)
                if dec_name:
                    decorators_found.append(dec_name)

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                has_docstring = True

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node is (tree.body[0] if tree.body else None):
                parameter_count = len(node.args.args)
                for arg in node.args.args:
                    if arg.annotation:
                        param_type = _get_name(arg.annotation)
                        if param_type:
                            parameter_types.append(param_type)

            if node.returns:
                rt = _get_name(node.returns)
                if rt:
                    return_types.append(rt)

            for dec in node.decorator_list:
                dec_name = _get_decorator_name(dec)
                if dec_name:
                    decorators_found.append(dec_name)

            depth = _max_nesting_depth(node)
            nesting_depth = max(nesting_depth, depth)

        if isinstance(node, ast.Call):
            call_name = _get_call_name(node)
            if call_name and len(calls) < 20:
                calls.append(call_name)

    # Concurrency from imports
    for imp in imports:
        if imp in CONCURRENCY_IMPORTS:
            cp = CONCURRENCY_IMPORTS[imp]
            if cp not in concurrency_patterns:
                concurrency_patterns.append(cp)

    for lock in LOCK_PATTERNS:
        if lock in source:
            if "locks" not in concurrency_patterns:
                concurrency_patterns.append("locks")

    # Decorator tags
    decorator_tags: list[str] = []
    for dec in decorators_found:
        for tag, dec_patterns in DECORATOR_PATTERNS.items():
            if any(dp in dec for dp in dec_patterns):
                if tag not in decorator_tags:
                    decorator_tags.append(tag)

    # External deps
    stdlib = {
        "os", "sys", "re", "json", "typing", "dataclasses", "enum", "abc",
        "pathlib", "datetime", "collections", "functools", "itertools",
        "hashlib", "uuid", "ast", "importlib", "subprocess",
    }
    external_deps = sorted(set(imp for imp in imports if imp not in stdlib))

    # Domain detection
    source_lower = source.lower()
    domains: list[str] = []
    for domain, keywords in DOMAIN_KEYWORDS.items():
        if sum(1 for kw in keywords if kw in source_lower) >= 2:
            domains.append(domain)

    # Layer detection
    layers: list[str] = []
    name_lower = name.lower()
    for layer, keywords in LAYER_KEYWORDS.items():
        if any(kw in name_lower for kw in keywords):
            layers.append(layer)

    # Unit test detection
    has_unit_test = False
    if test_files and name:
        test_variants = [f"test_{name.lower()}", f"{name.lower()}_test"]
        has_unit_test = any(
            any(tv in tf.lower() for tv in test_variants)
            for tf in test_files
        )

    line_count = source.count("\n") + 1

    meta["patterns"] = patterns[:5]
    meta["pattern_roles"] = pattern_roles[:5]
    meta["is_async"] = is_async
    meta["concurrency_patterns"] = concurrency_patterns[:5]
    meta["imports"] = list(set(imports))[:15]
    meta["external_deps"] = external_deps[:10]
    meta["decorators"] = decorators_found[:10]
    meta["decorator_tags"] = decorator_tags[:5]
    meta["has_docstring"] = has_docstring
    meta["is_public"] = is_public
    meta["is_abstract"] = is_abstract
    meta["inherits_from"] = inherits_from[:5]
    meta["return_types"] = list(set(return_types))[:5]
    meta["parameter_types"] = list(set(parameter_types))[:10]
    meta["parameter_count"] = parameter_count
    meta["nesting_depth"] = nesting_depth
    meta["line_count"] = line_count
    meta["calls"] = list(set(calls))[:15]
    meta["domains"] = domains[:3]
    meta["layers"] = layers[:3]
    meta["has_unit_test"] = has_unit_test
    meta["dead_code_candidate"] = False  # Set by LSP enrichment later

    return meta


def _get_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        value = _get_name(node.value)
        return f"{value}.{node.attr}" if value else node.attr
    if isinstance(node, ast.Subscript):
        return _get_name(node.value)
    if isinstance(node, ast.Constant):
        return str(node.value)
    return ""


def _get_decorator_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return f"@{node.id}"
    if isinstance(node, ast.Attribute):
        value = _get_name(node.value)
        return f"@{value}.{node.attr}" if value else f"@{node.attr}"
    if isinstance(node, ast.Call):
        return _get_decorator_name(node.func)
    return ""


def _get_call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        value = _get_name(node.func.value)
        return f"{value}.{node.func.attr}" if value else node.func.attr
    return ""


def _max_nesting_depth(node: ast.AST, current: int = 0) -> int:
    max_depth = current
    nesting_types = (ast.If, ast.For, ast.While, ast.AsyncFor, ast.With, ast.AsyncWith, ast.Try)

    for child in ast.iter_child_nodes(node):
        if isinstance(child, nesting_types):
            depth = _max_nesting_depth(child, current + 1)
            max_depth = max(max_depth, depth)
        else:
            depth = _max_nesting_depth(child, current)
            max_depth = max(max_depth, depth)

    return max_depth
