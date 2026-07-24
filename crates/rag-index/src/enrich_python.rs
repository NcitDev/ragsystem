//! Port of Python `core/patterns.py::detect_patterns_from_source` on top of
//! tree-sitter-python: pattern/domain/layer tagging, complexity metrics,
//! imports/decorators/calls, and quality flags for python-language chunks.

use std::collections::{BTreeMap, BTreeSet};

use serde_json::{json, Value};
use tree_sitter::{Node, Parser};

const NAME_PATTERNS: [(&str, &[&str]); 15] = [
    (
        "repository",
        &["repository", "repo", "dao", "dataaccess", "store", "crud"],
    ),
    ("factory", &["factory", "creator", "builder", "maker"]),
    ("singleton", &["singleton", "instance", "shared"]),
    (
        "observer",
        &[
            "observer",
            "listener",
            "subscriber",
            "handler",
            "watcher",
            "callback",
        ],
    ),
    ("strategy", &["strategy", "policy", "algorithm"]),
    (
        "adapter",
        &["adapter", "wrapper", "bridge", "proxy", "facade"],
    ),
    (
        "decorator",
        &["decorator", "middleware", "interceptor", "wrapper"],
    ),
    ("command", &["command", "action", "task", "job", "executor"]),
    ("builder", &["builder", "config", "configurator"]),
    (
        "service",
        &[
            "service",
            "manager",
            "controller",
            "coordinator",
            "orchestrator",
        ],
    ),
    ("model", &["model", "entity", "schema", "dto", "dataclass"]),
    (
        "provider",
        &["provider", "supplier", "source", "client", "connector"],
    ),
    (
        "validator",
        &["validator", "checker", "verifier", "sanitizer"],
    ),
    (
        "serializer",
        &["serializer", "encoder", "decoder", "parser", "formatter"],
    ),
    ("state_machine", &["state", "transition", "fsm", "machine"]),
];

const INHERITANCE_PATTERNS: [(&str, &[&str]); 7] = [
    ("repository", &["BaseRepository", "CRUDBase", "Repository"]),
    ("factory", &["BaseFactory", "AbstractFactory"]),
    ("observer", &["EventHandler", "BaseHandler", "Listener"]),
    ("strategy", &["BaseStrategy", "Strategy", "Policy"]),
    ("adapter", &["BaseAdapter", "Adapter"]),
    ("provider", &["Protocol", "ABC", "BaseProvider"]),
    ("middleware", &["BaseHTTPMiddleware", "Middleware"]),
];

const DECORATOR_PATTERNS: [(&str, &[&str]); 10] = [
    ("singleton", &["@singleton", "@lru_cache"]),
    (
        "route",
        &["@router.", "@app.", "@get", "@post", "@put", "@delete"],
    ),
    ("inject", &["@inject", "@Inject", "@Depends", "@dependency"]),
    (
        "test",
        &["@pytest.mark", "@test", "@unittest", "@mock.patch"],
    ),
    ("cached", &["@cached", "@cache", "@lru_cache", "@memoize"]),
    ("retry", &["@retry", "@tenacity", "@backoff"]),
    ("async_task", &["@celery", "@task", "@background_task"]),
    ("scheduled", &["@scheduled", "@cron", "@periodic_task"]),
    ("deprecated", &["@deprecated", "@warn_deprecated"]),
    (
        "validated",
        &["@validator", "@field_validator", "@validate"],
    ),
];

const CONCURRENCY_IMPORTS: [(&str, &str); 13] = [
    ("asyncio", "async_await"),
    ("threading", "threading"),
    ("multiprocessing", "multiprocessing"),
    ("concurrent.futures", "thread_pool"),
    ("queue", "queue"),
    ("aiohttp", "async_http"),
    ("httpx", "async_http"),
    ("asyncpg", "async_db"),
    ("aiofiles", "async_io"),
    ("trio", "async_await"),
    ("anyio", "async_await"),
    ("gevent", "green_threads"),
    ("celery", "task_queue"),
];

const LOCK_PATTERNS: [&str; 6] = [
    "Lock(",
    "RLock(",
    "Semaphore(",
    "Event(",
    "Condition(",
    "Barrier(",
];

const DOMAIN_KEYWORDS: [(&str, &[&str]); 12] = [
    (
        "auth",
        &[
            "auth",
            "login",
            "logout",
            "token",
            "password",
            "session",
            "oauth",
            "jwt",
            "permission",
            "role",
        ],
    ),
    (
        "payment",
        &[
            "payment",
            "billing",
            "charge",
            "refund",
            "invoice",
            "subscription",
            "stripe",
            "paypal",
        ],
    ),
    (
        "notification",
        &[
            "notification",
            "notify",
            "email",
            "sms",
            "push",
            "alert",
            "webhook",
        ],
    ),
    (
        "database",
        &[
            "database",
            "query",
            "migration",
            "schema",
            "table",
            "column",
            "index",
            "orm",
        ],
    ),
    (
        "api",
        &[
            "endpoint",
            "route",
            "handler",
            "request",
            "response",
            "middleware",
            "cors",
        ],
    ),
    (
        "cache",
        &[
            "cache",
            "redis",
            "memcached",
            "ttl",
            "invalidate",
            "memoize",
        ],
    ),
    (
        "search",
        &[
            "search", "index", "query", "filter", "sort", "paginate", "elastic", "qdrant",
        ],
    ),
    (
        "file",
        &[
            "file", "upload", "download", "storage", "s3", "blob", "stream",
        ],
    ),
    (
        "test",
        &["test", "mock", "fixture", "assert", "spec", "stub"],
    ),
    (
        "config",
        &[
            "config",
            "settings",
            "environment",
            "env",
            "dotenv",
            "secret",
        ],
    ),
    (
        "logging",
        &["log", "logger", "trace", "debug", "structlog", "sentry"],
    ),
    (
        "queue",
        &[
            "queue", "message", "kafka", "rabbitmq", "event", "pubsub", "broker",
        ],
    ),
];

const LAYER_KEYWORDS: [(&str, &[&str]); 8] = [
    (
        "controller",
        &["router", "endpoint", "handler", "view", "controller", "api"],
    ),
    (
        "service",
        &[
            "service",
            "usecase",
            "interactor",
            "manager",
            "orchestrator",
        ],
    ),
    (
        "repository",
        &["repository", "repo", "dao", "store", "crud", "persistence"],
    ),
    (
        "model",
        &["model", "entity", "schema", "dto", "dataclass", "table"],
    ),
    (
        "utility",
        &["util", "helper", "common", "shared", "tools", "misc"],
    ),
    ("config", &["config", "settings", "constants", "env"]),
    (
        "middleware",
        &["middleware", "interceptor", "filter", "guard"],
    ),
    (
        "migration",
        &["migration", "alembic", "flyway", "schema_change"],
    ),
];

const STDLIB: [&str; 17] = [
    "os",
    "sys",
    "re",
    "json",
    "typing",
    "dataclasses",
    "enum",
    "abc",
    "pathlib",
    "datetime",
    "collections",
    "functools",
    "itertools",
    "hashlib",
    "uuid",
    "ast",
    "importlib",
];

#[derive(Default)]
struct Analysis {
    imports: Vec<String>,
    decorators: Vec<String>,
    inherits_from: Vec<String>,
    return_types: BTreeSet<String>,
    parameter_types: BTreeSet<String>,
    calls: Vec<String>,
    is_async: bool,
    has_docstring: bool,
    is_abstract: bool,
    interface_role: bool,
    parameter_count: usize,
    nesting_depth: usize,
    cyclomatic: usize,
    cognitive: usize,
}

/// Extract rich pattern metadata from Python source, mirroring
/// `detect_patterns_from_source`. Returns only name-pattern tags when the
/// source fails to parse (Python's `SyntaxError` branch).
pub fn detect_python_patterns(
    source: &str,
    name: &str,
    test_files: Option<&BTreeSet<String>>,
) -> BTreeMap<String, Value> {
    let mut meta = BTreeMap::new();

    let mut patterns: Vec<String> = Vec::new();
    let mut pattern_roles: Vec<String> = Vec::new();
    let name_lower = format!("{name} ").to_lowercase();
    for (pattern, keywords) in NAME_PATTERNS {
        if keywords.iter().any(|keyword| name_lower.contains(keyword))
            && !patterns.iter().any(|existing| existing == pattern)
        {
            patterns.push(pattern.to_owned());
            pattern_roles.push("implementation".to_owned());
        }
    }

    let mut parser = Parser::new();
    if parser
        .set_language(&tree_sitter_python::LANGUAGE.into())
        .is_err()
    {
        meta.insert("patterns".to_owned(), json!(patterns));
        meta.insert("pattern_roles".to_owned(), json!(pattern_roles));
        return meta;
    }
    let Some(tree) = parser.parse(source, None) else {
        meta.insert("patterns".to_owned(), json!(patterns));
        meta.insert("pattern_roles".to_owned(), json!(pattern_roles));
        return meta;
    };
    let root = tree.root_node();
    // Python `ast.parse` is all-or-nothing: any syntax error yields only the
    // name-derived pattern tags. Match that, even though tree-sitter could
    // salvage partial trees.
    if root.has_error() {
        meta.insert("patterns".to_owned(), json!(patterns));
        meta.insert("pattern_roles".to_owned(), json!(pattern_roles));
        return meta;
    }

    let bytes = source.as_bytes();
    let mut analysis = Analysis {
        cyclomatic: 1,
        ..Analysis::default()
    };
    walk(root, bytes, &mut analysis, first_definition(root));
    analysis.cognitive = cognitive(root, 0);

    for base in &analysis.inherits_from {
        for (pattern, bases) in INHERITANCE_PATTERNS {
            if bases.iter().any(|candidate| candidate == base)
                && !patterns.iter().any(|existing| existing == pattern)
            {
                patterns.push(pattern.to_owned());
                pattern_roles.push("implementation".to_owned());
            }
        }
    }
    if analysis.interface_role && !pattern_roles.iter().any(|role| role == "interface") {
        pattern_roles.push("interface".to_owned());
    }

    let mut concurrency: Vec<String> = Vec::new();
    for import in &analysis.imports {
        for (module, tag) in CONCURRENCY_IMPORTS {
            if import == module && !concurrency.iter().any(|existing| existing == tag) {
                concurrency.push(tag.to_owned());
            }
        }
    }
    if LOCK_PATTERNS.iter().any(|pattern| source.contains(pattern))
        && !concurrency.iter().any(|existing| existing == "locks")
    {
        concurrency.push("locks".to_owned());
    }

    let mut decorator_tags: Vec<String> = Vec::new();
    for decorator in &analysis.decorators {
        for (tag, decorator_patterns) in DECORATOR_PATTERNS {
            if decorator_patterns
                .iter()
                .any(|pattern| decorator.contains(pattern))
                && !decorator_tags.iter().any(|existing| existing == tag)
            {
                decorator_tags.push(tag.to_owned());
            }
        }
    }

    let external_deps: Vec<String> = analysis
        .imports
        .iter()
        .filter(|import| !STDLIB.contains(&import.as_str()) && *import != "subprocess")
        .cloned()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .take(10)
        .collect();

    let source_lower = source.to_lowercase();
    let domains: Vec<String> = DOMAIN_KEYWORDS
        .iter()
        .filter(|(_, keywords)| {
            keywords
                .iter()
                .filter(|keyword| source_lower.contains(*keyword))
                .count()
                >= 2
        })
        .map(|(domain, _)| (*domain).to_owned())
        .take(3)
        .collect();

    let chunk_name_lower = name.to_lowercase();
    let layers: Vec<String> = LAYER_KEYWORDS
        .iter()
        .filter(|(_, keywords)| {
            keywords
                .iter()
                .any(|keyword| chunk_name_lower.contains(keyword))
        })
        .map(|(layer, _)| (*layer).to_owned())
        .take(3)
        .collect();

    let has_unit_test = match test_files {
        Some(files) if !name.is_empty() => {
            let lowered = name.to_lowercase();
            let variants = [format!("test_{lowered}"), format!("{lowered}_test")];
            files.iter().any(|file| {
                let file = file.to_lowercase();
                variants.iter().any(|variant| file.contains(variant))
            })
        }
        _ => false,
    };

    let sorted_imports: Vec<String> = analysis
        .imports
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .take(15)
        .collect();
    let sorted_calls: Vec<String> = analysis
        .calls
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .take(15)
        .collect();

    patterns.truncate(5);
    pattern_roles.truncate(5);
    meta.insert("patterns".to_owned(), json!(patterns));
    meta.insert("pattern_roles".to_owned(), json!(pattern_roles));
    meta.insert(
        "complexity_cyclomatic".to_owned(),
        json!(analysis.cyclomatic),
    );
    meta.insert("complexity_cognitive".to_owned(), json!(analysis.cognitive));
    meta.insert("is_async".to_owned(), json!(analysis.is_async));
    meta.insert(
        "concurrency_patterns".to_owned(),
        json!(concurrency.into_iter().take(5).collect::<Vec<_>>()),
    );
    meta.insert("imports".to_owned(), json!(sorted_imports));
    meta.insert("external_deps".to_owned(), json!(external_deps));
    meta.insert(
        "decorators".to_owned(),
        json!(analysis.decorators.iter().take(10).collect::<Vec<_>>()),
    );
    meta.insert(
        "decorator_tags".to_owned(),
        json!(decorator_tags.into_iter().take(5).collect::<Vec<_>>()),
    );
    meta.insert("has_docstring".to_owned(), json!(analysis.has_docstring));
    meta.insert("is_public".to_owned(), json!(!name.starts_with('_')));
    meta.insert("is_abstract".to_owned(), json!(analysis.is_abstract));
    meta.insert(
        "inherits_from".to_owned(),
        json!(analysis.inherits_from.iter().take(5).collect::<Vec<_>>()),
    );
    meta.insert(
        "return_types".to_owned(),
        json!(analysis.return_types.iter().take(5).collect::<Vec<_>>()),
    );
    meta.insert(
        "parameter_types".to_owned(),
        json!(analysis.parameter_types.iter().take(10).collect::<Vec<_>>()),
    );
    meta.insert(
        "parameter_count".to_owned(),
        json!(analysis.parameter_count),
    );
    meta.insert("nesting_depth".to_owned(), json!(analysis.nesting_depth));
    meta.insert(
        "line_count".to_owned(),
        json!(source.matches('\n').count() + 1),
    );
    meta.insert("calls".to_owned(), json!(sorted_calls));
    meta.insert("domains".to_owned(), json!(domains));
    meta.insert("layers".to_owned(), json!(layers));
    meta.insert("has_unit_test".to_owned(), json!(has_unit_test));
    meta.insert("dead_code_candidate".to_owned(), json!(false));
    meta
}

/// The first top-level definition (unwrapping decorated_definition), matching
/// Python's `tree.body[0]` parameter-count quirk.
fn first_definition(root: Node<'_>) -> Option<usize> {
    let mut cursor = root.walk();
    for child in root.named_children(&mut cursor) {
        let node = if child.kind() == "decorated_definition" {
            child.child_by_field_name("definition").unwrap_or(child)
        } else {
            child
        };
        if node.kind() == "function_definition" {
            return Some(node.id());
        }
        if node.kind() == "comment" {
            continue;
        }
        return None;
    }
    None
}

fn walk(node: Node<'_>, bytes: &[u8], analysis: &mut Analysis, first_fn: Option<usize>) {
    match node.kind() {
        "if_statement" | "elif_clause" | "for_statement" | "while_statement" => {
            analysis.cyclomatic += 1;
        }
        "except_clause" | "except_group_clause" | "assert_statement" | "boolean_operator" => {
            analysis.cyclomatic += 1;
        }
        "import_statement" => {
            let mut cursor = node.walk();
            for child in node.named_children(&mut cursor) {
                let target = if child.kind() == "aliased_import" {
                    child.child_by_field_name("name")
                } else {
                    Some(child)
                };
                if let Some(target) = target {
                    let text = node_text(target, bytes);
                    if let Some(head) = text.split('.').next() {
                        if !head.is_empty() {
                            analysis.imports.push(head.to_owned());
                        }
                    }
                }
            }
        }
        "import_from_statement" => {
            if let Some(module) = node.child_by_field_name("module_name") {
                let text = node_text(module, bytes);
                if let Some(head) = text.split('.').next() {
                    if !head.is_empty() {
                        analysis.imports.push(head.to_owned());
                    }
                }
            }
            let mut cursor = node.walk();
            for child in node.children_by_field_name("name", &mut cursor) {
                let target = if child.kind() == "aliased_import" {
                    child.child_by_field_name("name")
                } else {
                    Some(child)
                };
                if let Some(target) = target {
                    let text = node_text(target, bytes);
                    if !text.is_empty() {
                        analysis.imports.push(text);
                    }
                }
            }
        }
        "function_definition" => {
            if is_async(node) {
                analysis.is_async = true;
            }
            if body_has_docstring(node) {
                analysis.has_docstring = true;
            }
            if Some(node.id()) == first_fn {
                if let Some(parameters) = node.child_by_field_name("parameters") {
                    let mut cursor = parameters.walk();
                    for parameter in parameters.named_children(&mut cursor) {
                        match parameter.kind() {
                            "identifier" => analysis.parameter_count += 1,
                            "typed_parameter" | "default_parameter" | "typed_default_parameter" => {
                                analysis.parameter_count += 1;
                                if let Some(annotation) = parameter.child_by_field_name("type") {
                                    let text = type_name(annotation, bytes);
                                    if !text.is_empty() {
                                        analysis.parameter_types.insert(text);
                                    }
                                }
                            }
                            _ => {}
                        }
                    }
                }
            }
            if let Some(return_type) = node.child_by_field_name("return_type") {
                let text = type_name(return_type, bytes);
                if !text.is_empty() {
                    analysis.return_types.insert(text);
                }
            }
            let depth = max_nesting(node, 0);
            analysis.nesting_depth = analysis.nesting_depth.max(depth);
        }
        "class_definition" => {
            if body_has_docstring(node) {
                analysis.has_docstring = true;
            }
            if let Some(superclasses) = node.child_by_field_name("superclasses") {
                let mut cursor = superclasses.walk();
                for base in superclasses.named_children(&mut cursor) {
                    if base.kind() == "keyword_argument" {
                        continue;
                    }
                    let text = type_name(base, bytes);
                    if !text.is_empty() {
                        analysis.inherits_from.push(text.clone());
                        if text == "ABC" || text == "Protocol" {
                            analysis.is_abstract = true;
                            analysis.interface_role = true;
                        }
                    }
                }
            }
        }
        "decorator" => {
            let text = node_text(node, bytes);
            let normalized = text.trim().split('(').next().unwrap_or_default().to_owned();
            if !normalized.is_empty() {
                analysis.decorators.push(normalized);
            }
        }
        "for_in_clause" => {
            // comprehension `for` — Python ast counts comprehensions via
            // their own node types, which the cyclomatic walk skips; nothing
            // to do, but keep the arm so intent is explicit.
        }
        "call" => {
            if let Some(function) = (analysis.calls.len() < 20)
                .then(|| node.child_by_field_name("function"))
                .flatten()
            {
                let text = node_text(function, bytes);
                if !text.is_empty() && text.len() <= 120 {
                    analysis.calls.push(text);
                }
            }
        }
        _ => {}
    }
    if (node.kind() == "for_statement" || node.kind() == "with_statement") && is_async(node) {
        analysis.is_async = true;
    }
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        walk(child, bytes, analysis, first_fn);
    }
}

fn cognitive(node: Node<'_>, nesting: usize) -> usize {
    let mut total = 0;
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "if_statement" | "elif_clause" | "for_statement" | "while_statement"
            | "with_statement" | "try_statement" => {
                total += 1 + nesting + cognitive(child, nesting + 1);
            }
            "boolean_operator" => {
                total += 1 + cognitive(child, nesting);
            }
            _ => total += cognitive(child, nesting),
        }
    }
    total
}

fn max_nesting(node: Node<'_>, current: usize) -> usize {
    let mut max_depth = current;
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        let depth = match child.kind() {
            "if_statement" | "elif_clause" | "for_statement" | "while_statement"
            | "with_statement" | "try_statement" => max_nesting(child, current + 1),
            _ => max_nesting(child, current),
        };
        max_depth = max_depth.max(depth);
    }
    max_depth
}

fn is_async(node: Node<'_>) -> bool {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if !child.is_named() && node_kind_is_async(child) {
            return true;
        }
    }
    false
}

fn node_kind_is_async(node: Node<'_>) -> bool {
    node.kind() == "async"
}

fn body_has_docstring(node: Node<'_>) -> bool {
    let Some(body) = node.child_by_field_name("body") else {
        return false;
    };
    let Some(first) = body.named_child(0) else {
        return false;
    };
    first.kind() == "expression_statement"
        && first
            .named_child(0)
            .is_some_and(|child| child.kind() == "string")
}

fn node_text(node: Node<'_>, bytes: &[u8]) -> String {
    node.utf8_text(bytes).unwrap_or_default().to_owned()
}

/// Python `_get_name`: identifier, dotted attribute, subscript base.
fn type_name(node: Node<'_>, bytes: &[u8]) -> String {
    match node.kind() {
        "identifier" => node_text(node, bytes),
        "attribute" => node_text(node, bytes),
        "subscript" => node
            .child_by_field_name("value")
            .map(|value| type_name(value, bytes))
            .unwrap_or_default(),
        "type" => node
            .named_child(0)
            .map(|inner| type_name(inner, bytes))
            .unwrap_or_else(|| node_text(node, bytes)),
        "string" => node_text(node, bytes),
        _ => node
            .named_child(0)
            .map(|inner| type_name(inner, bytes))
            .unwrap_or_default(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const SAMPLE: &str = r#"import asyncio
from fastapi import Depends

class UserRepository(BaseRepository):
    """Store users."""

    @lru_cache
    async def fetch(self, user_id: int) -> User:
        if user_id and user_id > 0:
            for attempt in range(3):
                return await self.db.get(user_id)
        return None
"#;

    #[test]
    fn python_enrichment_matches_reference_fields() {
        let meta = detect_python_patterns(SAMPLE, "UserRepository", None);
        assert_eq!(meta["patterns"], json!(["repository"]));
        // 1 base + if + for + boolean_operator = 4
        assert_eq!(meta["complexity_cyclomatic"], json!(4));
        assert_eq!(meta["is_async"], json!(true));
        assert_eq!(meta["has_docstring"], json!(true));
        assert_eq!(meta["inherits_from"], json!(["BaseRepository"]));
        assert_eq!(meta["is_public"], json!(true));
        assert!(meta["imports"]
            .as_array()
            .unwrap()
            .contains(&json!("asyncio")));
        assert!(meta["concurrency_patterns"]
            .as_array()
            .unwrap()
            .contains(&json!("async_await")));
        assert!(meta["decorator_tags"]
            .as_array()
            .unwrap()
            .contains(&json!("cached")));
        assert_eq!(meta["layers"], json!(["repository"]));
    }

    #[test]
    fn syntax_error_returns_name_patterns_only() {
        let meta = detect_python_patterns("def broken(:", "PaymentService", None);
        assert!(meta.contains_key("patterns"));
        assert!(!meta.contains_key("complexity_cyclomatic"));
    }
}
