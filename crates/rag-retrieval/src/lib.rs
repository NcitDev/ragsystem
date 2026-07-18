//! Deterministic, provider-independent retrieval primitives.

use std::collections::{BTreeMap, BTreeSet, HashSet};

use chrono::{DateTime, Utc};
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

pub mod ast_index;
pub mod repo_agent;

const RECENCY_WEIGHT: f64 = 0.15;
const PATTERN_WEIGHT: f64 = 0.10;
const QUALITY_WEIGHT: f64 = 0.05;
const MAX_RECENCY_DAYS: i64 = 90;
const HIGH_VALUE_PATTERNS: &[&str] = &[
    "repository",
    "service",
    "factory",
    "middleware",
    "strategy",
    "observer",
];

/// A storage-neutral search result used by deterministic ranking.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SearchHit {
    /// Stable storage identifier.
    pub point_id: String,
    /// Source/document body.
    pub content: String,
    /// Mutable relevance score.
    pub score: f64,
    /// Persisted payload fields.
    #[serde(default)]
    pub payload: Map<String, Value>,
}

/// Apply the Python scoring weights and deterministic tie-breakers.
pub fn score_hits(hits: &mut [SearchHit], query: &str, now: DateTime<Utc>) {
    for hit in hits.iter_mut() {
        hit.score += recency_score(&hit.payload, now) * RECENCY_WEIGHT
            + pattern_score(&hit.payload, query) * PATTERN_WEIGHT
            + quality_score(&hit.payload) * QUALITY_WEIGHT;
    }
    hits.sort_by(|left, right| {
        right
            .score
            .total_cmp(&left.score)
            .then_with(|| left.point_id.cmp(&right.point_id))
    });
}

fn recency_score(payload: &Map<String, Value>, now: DateTime<Utc>) -> f64 {
    let Some(raw) = payload.get("git_last_modified").and_then(Value::as_str) else {
        return 0.0;
    };
    let Ok(modified) = DateTime::parse_from_rfc3339(raw) else {
        return 0.0;
    };
    let days = now
        .signed_duration_since(modified.with_timezone(&Utc))
        .num_days();
    if days <= 0 {
        1.0
    } else if days >= MAX_RECENCY_DAYS {
        0.0
    } else {
        (-(days as f64) / (MAX_RECENCY_DAYS as f64 / 3.0)).exp()
    }
}

fn pattern_score(payload: &Map<String, Value>, query: &str) -> f64 {
    let patterns = string_values(payload.get("patterns"));
    if patterns.is_empty() {
        return 0.0;
    }
    let query = query.to_lowercase();
    if patterns.iter().any(|pattern| query.contains(pattern)) {
        1.0
    } else if patterns
        .iter()
        .any(|pattern| HIGH_VALUE_PATTERNS.contains(&pattern.as_str()))
    {
        0.5
    } else {
        0.2
    }
}

fn string_values(value: Option<&Value>) -> Vec<String> {
    match value {
        Some(Value::String(value)) => vec![value.clone()],
        Some(Value::Array(values)) => values
            .iter()
            .filter_map(Value::as_str)
            .map(ToOwned::to_owned)
            .collect(),
        _ => Vec::new(),
    }
}

/// Normalize string-encoded Qdrant flags like the Python implementation.
#[must_use]
pub fn truthy(value: Option<&Value>, default: bool) -> bool {
    match value {
        Some(Value::Bool(value)) => *value,
        Some(Value::String(value)) => matches!(
            value.trim().to_ascii_lowercase().as_str(),
            "true" | "1" | "yes"
        ),
        Some(Value::Null) | None => default,
        Some(Value::Number(value)) => value.as_f64().is_some_and(|number| number != 0.0),
        Some(Value::Array(value)) => !value.is_empty(),
        Some(Value::Object(value)) => !value.is_empty(),
    }
}

/// Compute Python-compatible code quality adjustment in `[-1, 1]`.
#[must_use]
pub fn quality_score(payload: &Map<String, Value>) -> f64 {
    let mut score: f64 = 0.0;
    if truthy(payload.get("dead_code_candidate"), false) {
        score -= 0.5;
    }
    if truthy(payload.get("has_docstring"), false) {
        score += 0.2;
    }
    if truthy(payload.get("is_public"), true) {
        score += 0.1;
    }
    if payload
        .get("complexity_cyclomatic")
        .and_then(Value::as_f64)
        .is_some_and(|complexity| complexity > 20.0)
    {
        score -= 0.2;
    }
    if truthy(payload.get("has_unit_test"), false) {
        score += 0.3;
    }
    score.clamp(-1.0, 1.0)
}

/// Squash unbounded lexical scores into the dense-score band.
#[must_use]
pub fn lexical_score(raw: f64) -> f64 {
    if raw <= 0.0 {
        0.0
    } else {
        0.75 * raw / (raw + 3.0)
    }
}

/// Stable identity used to deduplicate semantic and lexical results.
#[must_use]
pub fn result_key(payload: &Map<String, Value>) -> (String, i64, i64, String, String) {
    (
        string_field(payload, "file_path"),
        integer_field(payload, "start_line"),
        integer_field(payload, "end_line"),
        string_field(payload, "chunk_type"),
        string_field(payload, "name"),
    )
}

fn string_field(payload: &Map<String, Value>, key: &str) -> String {
    payload
        .get(key)
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_owned()
}

fn integer_field(payload: &Map<String, Value>, key: &str) -> i64 {
    payload.get(key).and_then(Value::as_i64).unwrap_or_default()
}

/// Deduplicate by point ID while preserving first-hit order and query matches.
#[must_use]
pub fn merge_query_hits(
    query_hits: Vec<Vec<SearchHit>>,
) -> (Vec<SearchHit>, BTreeMap<String, Vec<usize>>) {
    let mut hits = Vec::new();
    let mut positions = BTreeMap::new();
    let mut matches = BTreeMap::<String, Vec<usize>>::new();
    for (query_index, query) in query_hits.into_iter().enumerate() {
        for hit in query {
            matches
                .entry(hit.point_id.clone())
                .or_default()
                .push(query_index);
            if !positions.contains_key(&hit.point_id) {
                positions.insert(hit.point_id.clone(), hits.len());
                hits.push(hit);
            }
        }
    }
    (hits, matches)
}

/// Keep symbol-grounded hits, with the Python safety net that never erases all evidence.
#[must_use]
pub fn apply_symbol_sanity_filter(hits: Vec<SearchHit>, query: &str) -> Vec<SearchHit> {
    let symbol_regex = Regex::new(r"\b([A-Z][a-zA-Z0-9_]{3,})\b").expect("static regex");
    let stopwords: HashSet<&str> = [
        "show", "find", "rename", "trace", "list", "give", "tell", "what", "which", "where",
        "when", "who", "whom", "whose", "how", "why", "this", "that", "these", "those", "there",
        "here", "with", "from", "into", "your", "their", "have", "does", "code", "class", "base",
        "main", "should", "would", "could", "about",
    ]
    .into_iter()
    .collect();
    let symbols: BTreeSet<String> = symbol_regex
        .captures_iter(query)
        .filter_map(|capture| capture.get(1).map(|value| value.as_str().to_owned()))
        .filter(|symbol| !stopwords.contains(symbol.to_ascii_lowercase().as_str()))
        .collect();
    if symbols.is_empty() {
        return hits;
    }
    let filtered: Vec<SearchHit> = hits
        .iter()
        .filter(|hit| {
            symbols
                .iter()
                .any(|symbol| hit_contains_symbol(hit, symbol))
        })
        .cloned()
        .collect();
    if filtered.is_empty() {
        hits
    } else {
        filtered
    }
}

fn hit_contains_symbol(hit: &SearchHit, symbol: &str) -> bool {
    let word = Regex::new(&format!(r"\b{}\b", regex::escape(symbol))).expect("escaped regex");
    if word.is_match(&hit.content) {
        return true;
    }
    let symbol = symbol.to_ascii_lowercase();
    ["name", "parent_name", "file_path"].iter().any(|key| {
        string_field(&hit.payload, key)
            .to_ascii_lowercase()
            .contains(&symbol)
    }) || ["references_fqn", "inherits_from"].iter().any(|key| {
        string_values(hit.payload.get(*key))
            .iter()
            .any(|value| value.to_ascii_lowercase().contains(&symbol))
    })
}

/// Estimate source tokens using the current four-characters-per-token contract.
#[must_use]
pub fn estimate_tokens(text: &str) -> usize {
    text.len().div_ceil(4).max(1)
}

/// Trim source by whole lines to a source-token budget.
#[must_use]
pub fn trim_to_token_budget(code: &str, token_budget: usize) -> (String, usize) {
    if token_budget == 0 {
        return (String::new(), 0);
    }
    let max_chars = token_budget * 4;
    if code.len() <= max_chars {
        return (code.to_owned(), estimate_tokens(code));
    }
    let mut output = String::new();
    for line in code.lines() {
        let separator = usize::from(!output.is_empty());
        if !output.is_empty() && output.len() + separator + line.len() > max_chars {
            break;
        }
        if output.is_empty() && line.len() > max_chars {
            output.push_str(&line[..max_chars]);
            break;
        }
        if !output.is_empty() {
            output.push('\n');
        }
        output.push_str(line);
    }
    let output = output.trim_end().to_owned();
    let tokens = estimate_tokens(&output);
    (output, tokens)
}

/// Expand common code-search shorthand with Python-compatible ordering.
#[must_use]
pub fn expand_query(query: &str) -> String {
    const EXPANSIONS: &[(&str, &[&str])] = &[
        (
            "auth",
            &[
                "auth",
                "authentication",
                "login",
                "signin",
                "security",
                "oauth",
                "jwt",
            ],
        ),
        (
            "db",
            &[
                "db",
                "database",
                "repository",
                "dao",
                "storage",
                "persistence",
                "orm",
            ],
        ),
        (
            "api",
            &["api", "endpoint", "route", "handler", "controller", "rest"],
        ),
        (
            "test",
            &[
                "test",
                "spec",
                "assertion",
                "mock",
                "fixture",
                "pytest",
                "junit",
            ],
        ),
        (
            "config",
            &[
                "config",
                "configuration",
                "settings",
                "environment",
                "env",
                "properties",
            ],
        ),
        (
            "log",
            &["log", "logging", "logger", "trace", "debug", "structlog"],
        ),
        (
            "cache",
            &[
                "cache",
                "caching",
                "redis",
                "memcached",
                "ttl",
                "invalidation",
            ],
        ),
        (
            "queue",
            &[
                "queue", "message", "kafka", "rabbitmq", "event", "pubsub", "broker",
            ],
        ),
        (
            "error",
            &[
                "error",
                "exception",
                "failure",
                "catch",
                "throw",
                "raise",
                "fault",
            ],
        ),
        (
            "async",
            &[
                "async",
                "await",
                "coroutine",
                "future",
                "promise",
                "concurrent",
                "parallel",
            ],
        ),
        (
            "deploy",
            &[
                "deploy",
                "deployment",
                "ci",
                "cd",
                "pipeline",
                "release",
                "docker",
            ],
        ),
        (
            "migrate",
            &[
                "migrate",
                "migration",
                "schema",
                "alembic",
                "flyway",
                "upgrade",
            ],
        ),
        (
            "validate",
            &[
                "validate",
                "validation",
                "check",
                "verify",
                "sanitize",
                "constraint",
            ],
        ),
        (
            "serialize",
            &[
                "serialize",
                "serialization",
                "json",
                "marshal",
                "encode",
                "decode",
                "parse",
            ],
        ),
        (
            "di",
            &[
                "di",
                "dependency",
                "injection",
                "inject",
                "provider",
                "container",
                "factory",
            ],
        ),
        (
            "ui",
            &[
                "ui",
                "view",
                "component",
                "widget",
                "screen",
                "layout",
                "fragment",
            ],
        ),
        (
            "perf",
            &[
                "perf",
                "performance",
                "optimize",
                "optimization",
                "latency",
                "throughput",
                "profile",
            ],
        ),
        (
            "debt",
            &[
                "debt",
                "technical debt",
                "tech debt",
                "legacy",
                "refactor",
                "cleanup",
                "deprecated",
            ],
        ),
        (
            "complexity",
            &[
                "complexity",
                "cyclomatic",
                "cognitive",
                "nesting",
                "coupling",
            ],
        ),
        (
            "pattern",
            &[
                "pattern",
                "singleton",
                "factory",
                "repository",
                "observer",
                "strategy",
            ],
        ),
    ];
    let lower = query.to_ascii_lowercase();
    let mut extras = Vec::new();
    for (key, synonyms) in EXPANSIONS {
        if lower.contains(key) {
            for synonym in *synonyms {
                if !lower.contains(synonym) {
                    extras.push(*synonym);
                }
            }
        }
    }
    if extras.is_empty() {
        query.to_owned()
    } else {
        format!(
            "{query} {}",
            extras.into_iter().take(10).collect::<Vec<_>>().join(" ")
        )
    }
}

/// Split compound queries on the same conjunction vocabulary as Python.
#[must_use]
pub fn decompose_query(query: &str, max_subqueries: usize) -> Vec<String> {
    let conjunction = Regex::new(r"(?i)\b(?:and|or|plus|with|also)\b").expect("static regex");
    let parts: Vec<String> = conjunction
        .split(query)
        .map(str::trim)
        .filter(|part| !part.is_empty())
        .take(max_subqueries)
        .map(ToOwned::to_owned)
        .collect();
    if parts.len() > 1 {
        parts
    } else {
        vec![query.to_owned()]
    }
}

#[cfg(test)]
mod tests {
    use chrono::{TimeZone, Utc};
    use serde_json::{json, Map};

    use super::{
        apply_symbol_sanity_filter, decompose_query, estimate_tokens, expand_query, lexical_score,
        merge_query_hits, quality_score, score_hits, trim_to_token_budget, truthy, SearchHit,
    };

    #[test]
    fn string_flags_match_python() {
        assert!(truthy(Some(&json!("true")), false));
        assert!(!truthy(Some(&json!("false")), false));
        assert!(truthy(None, true));
        let payload: Map<String, serde_json::Value> = serde_json::from_value(json!({
            "has_docstring": "true", "has_unit_test": "true", "is_public": "true"
        }))
        .expect("object");
        assert!((quality_score(&payload) - 0.6).abs() < f64::EPSILON);
    }

    #[test]
    fn deterministic_scoring_uses_point_id_tie_breaker() {
        let payload = Map::new();
        let mut hits = vec![
            SearchHit {
                point_id: "b".into(),
                content: String::new(),
                score: 0.5,
                payload: payload.clone(),
            },
            SearchHit {
                point_id: "a".into(),
                content: String::new(),
                score: 0.5,
                payload,
            },
        ];
        score_hits(
            &mut hits,
            "",
            Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0).unwrap(),
        );
        assert_eq!(hits[0].point_id, "a");
    }

    #[test]
    fn lexical_score_matches_python_formula() {
        assert!((lexical_score(5.0) - 0.46875).abs() < f64::EPSILON);
    }

    #[test]
    fn merge_preserves_first_hit_order_and_query_indices() {
        let hit = |id: &str| SearchHit {
            point_id: id.into(),
            content: String::new(),
            score: 1.0,
            payload: Map::new(),
        };
        let (hits, matched) = merge_query_hits(vec![vec![hit("a"), hit("b")], vec![hit("b")]]);
        assert_eq!(
            hits.iter()
                .map(|hit| hit.point_id.as_str())
                .collect::<Vec<_>>(),
            ["a", "b"]
        );
        assert_eq!(matched["b"], [0, 1]);
    }

    #[test]
    fn sanity_filter_has_empty_result_safety_net() {
        let hits = vec![SearchHit {
            point_id: "a".into(),
            content: "unrelated".into(),
            score: 1.0,
            payload: Map::new(),
        }];
        assert_eq!(
            apply_symbol_sanity_filter(hits.clone(), "Find PaymentService").len(),
            1
        );
        let matching = SearchHit {
            point_id: "b".into(),
            content: "class PaymentService".into(),
            score: 1.0,
            payload: Map::new(),
        };
        assert_eq!(
            apply_symbol_sanity_filter(vec![hits[0].clone(), matching], "Find PaymentService")[0]
                .point_id,
            "b"
        );
    }

    #[test]
    fn token_budget_and_query_expansion_match_oracle() {
        assert_eq!(estimate_tokens("12345"), 2);
        assert_eq!(trim_to_token_budget("abcd\nefgh\nijkl", 2).0, "abcd");
        assert!(expand_query("find auth").contains("authentication"));
        assert_eq!(decompose_query("auth and payment", 3), ["auth", "payment"]);
    }
}
