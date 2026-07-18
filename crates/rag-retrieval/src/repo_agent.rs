//! Deterministic repo-agent planning and compact evaluation metrics.

use rag_contracts::SearchPlan;
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet, HashSet};

const STOPWORDS: &[&str] = &[
    "add",
    "after",
    "all",
    "always",
    "and",
    "another",
    "app",
    "around",
    "before",
    "being",
    "can",
    "case",
    "change",
    "checkout",
    "code",
    "complex",
    "created",
    "developers",
    "domain",
    "edit",
    "event",
    "evaluate",
    "exact",
    "feature",
    "files",
    "find",
    "flow",
    "for",
    "from",
    "fully",
    "handling",
    "into",
    "logic",
    "make",
    "minimal",
    "module",
    "needed",
    "public",
    "apis",
    "new",
    "not",
    "only",
    "order",
    "paid",
    "payment",
    "plan",
    "propose",
    "refactor",
    "report",
    "reset",
    "safe",
    "separate",
    "state",
    "still",
    "success",
    "successful",
    "tests",
    "the",
    "this",
    "tracking",
    "when",
    "without",
];
const REUSE_TRIGGERS: &[&str] = &[
    "add", "create", "event", "feature", "new", "reuse", "verify",
];
const ARCHITECTURE_TRIGGERS: &[&str] = &[
    "architecture",
    "boundary",
    "boundaries",
    "dependencies",
    "dependency",
    "extract",
    "module",
    "modules",
    "move",
    "public",
    "refactor",
    "risks",
];

/// Deterministic execution plan for the local repo-agent workflow.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RepoAgentPlan {
    /// Original developer task.
    pub query: String,
    /// Validated planner output.
    pub planner: SearchPlan,
    /// Combined exact/lexical context query.
    pub context_query: String,
    /// Candidate exact symbols.
    pub symbols: Vec<String>,
    /// Existing-code reuse probes.
    pub reuse_queries: Vec<String>,
    /// Indexed documentation probes.
    pub documentation_queries: Vec<String>,
    /// Optional module-boundary query.
    pub architecture_query: Option<String>,
    /// Likely callable symbols for call-tree lookup.
    pub call_tree_symbols: Vec<String>,
    /// Whether embedding retrieval may fill thin exact evidence.
    pub semantic_fallback_allowed: bool,
}

/// Stable navigation metrics emitted with an evidence bundle.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EvalMetrics {
    /// First relevant one-based rank.
    pub first_relevant_rank: Option<usize>,
    /// First relevant source path.
    pub first_relevant_file: String,
    /// Total bounded source tokens.
    pub source_tokens: usize,
    /// Whether embedding-only evidence was used.
    pub embeddings_used: bool,
    /// Whether all evidence came from bounded slices.
    pub whole_file_reads_avoided: bool,
    /// Explicit whole-file read count.
    pub whole_file_reads: usize,
    /// Evaluation label filled by benchmark callers.
    pub answer_correctness: String,
}

fn identifier_regex() -> Regex {
    Regex::new(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b").expect("static identifier regex")
}

fn tokens(text: &str) -> Vec<String> {
    identifier_regex()
        .find_iter(text)
        .map(|found| found.as_str().to_owned())
        .collect()
}

fn word_set(text: &str) -> HashSet<String> {
    tokens(text)
        .into_iter()
        .map(|token| token.to_ascii_lowercase())
        .collect()
}

/// Extract code-like identifiers while ignoring ordinary lowercase prose.
#[must_use]
pub fn extract_symbol_candidates(query: &str, limit: usize) -> Vec<String> {
    let stopwords: HashSet<&str> = STOPWORDS.iter().copied().collect();
    let mut seen = BTreeSet::new();
    tokens(query)
        .into_iter()
        .filter(|value| !stopwords.contains(value.to_ascii_lowercase().as_str()))
        .filter(|value| value.chars().any(char::is_uppercase) || value.contains('_'))
        .filter(|value| seen.insert(value.clone()))
        .take(limit)
        .collect()
}

/// Expand known product wording into deterministic code vocabulary anchors.
#[must_use]
pub fn expand_domain_terms(query: &str) -> Vec<String> {
    let words = word_set(query);
    let expansions: &[(&[&str], &[&str])] = &[
        (
            &["paid", "order"],
            &["waitForPayedOrder", "PaidOrderResponse", "OrderResult"],
        ),
        (
            &["successful", "order"],
            &["OrderCreated", "OrderIsBeingCreated"],
        ),
        (
            &["success", "order"],
            &["OrderCreated", "OrderIsBeingCreated"],
        ),
        (&["fully", "created"], &["OrderCreated"]),
        (&["still", "created"], &["OrderIsBeingCreated"]),
        (
            &["reset", "state"],
            &[
                "setupAppStateForNewOrder",
                "StateAnalyzer",
                "CheckoutService",
            ],
        ),
        (
            &["resets", "state"],
            &[
                "setupAppStateForNewOrder",
                "StateAnalyzer",
                "CheckoutService",
            ],
        ),
        (
            &["analytics"],
            &[
                "AnalyticsHelper",
                "PaymentAnalytics",
                "trackPaymentFinished",
                "trackPaymentFailed",
            ],
        ),
        (
            &["payment", "completion"],
            &["trackPaymentFinished", "PaymentAnalytics"],
        ),
        (
            &["still", "being", "created"],
            &["OrderIsBeingCreated", "PaidOrderState.ALMOST_OK"],
        ),
        (
            &["analytics", "event"],
            &[
                "PaymentAnalytics",
                "orderPollingAfterPaymentStart",
                "START_ORDER_POLLING_AFTER_PAYMENT",
                "STOP_ORDER_POLLING_AFTER_PAYMENT",
            ],
        ),
    ];
    let mut expanded = Vec::new();
    for (required, terms) in expansions {
        if required.iter().all(|word| words.contains(*word)) {
            for term in *terms {
                if !expanded.contains(&(*term).to_owned()) {
                    expanded.push((*term).to_owned());
                }
            }
        }
    }
    expanded
}

/// Combine symbols, task wording, planner queries, and domain anchors.
#[must_use]
pub fn build_context_query(
    query: &str,
    plan: &SearchPlan,
    symbols: &[String],
    max_terms: usize,
) -> String {
    let stopwords: HashSet<&str> = STOPWORDS.iter().copied().collect();
    let mut terms = Vec::new();
    let sources = symbols
        .iter()
        .cloned()
        .chain(std::iter::once(query.to_owned()))
        .chain(plan.queries.iter().cloned())
        .chain(expand_domain_terms(query));
    for source in sources {
        for token in tokens(&source) {
            if stopwords.contains(token.to_ascii_lowercase().as_str()) {
                continue;
            }
            if !terms.contains(&token) {
                terms.push(token);
            }
            if terms.len() >= max_terms {
                return terms.join(" ");
            }
        }
    }
    if terms.is_empty() {
        query.to_owned()
    } else {
        terms.join(" ")
    }
}

/// Build exact searches for existing concepts before adding new APIs/events.
#[must_use]
pub fn build_reuse_queries(query: &str, symbols: &[String], limit: usize) -> Vec<String> {
    let words = word_set(query);
    let has_reuse_trigger = REUSE_TRIGGERS.iter().any(|word| words.contains(*word));
    let has_architecture_trigger = ARCHITECTURE_TRIGGERS
        .iter()
        .any(|word| words.contains(*word));
    let mut queries = Vec::new();
    if (words.contains("analytics") || words.contains("event")) && has_reuse_trigger {
        queries.push(
            "AnalyticsHelper PaymentAnalytics payment analytics event orderPollingAfterPaymentStart START_ORDER_POLLING_AFTER_PAYMENT STOP_ORDER_POLLING_AFTER_PAYMENT trackPaymentFinished OrderIsBeingCreated PaidOrderState.ALMOST_OK".to_owned(),
        );
    }
    if has_architecture_trigger {
        queries.push(format!(
            "{} build.gradle dependencies FeatureDependencies Module Component public API",
            symbols.join(" ")
        ));
    }
    if has_reuse_trigger && !symbols.is_empty() {
        queries.push(format!(
            "existing reusable API helper event {}",
            symbols.join(" ")
        ));
    }
    compact_deduplicated(queries, limit)
}

/// Build documentation searches for events and module ownership.
#[must_use]
pub fn build_documentation_queries(query: &str, symbols: &[String], limit: usize) -> Vec<String> {
    let words = word_set(query);
    let mut queries = Vec::new();
    if words.contains("analytics") || words.contains("event") {
        queries.push(format!(
            "analytics event catalog payment order polling after payment still being created {}",
            symbols.join(" ")
        ));
    }
    if ARCHITECTURE_TRIGGERS
        .iter()
        .any(|word| words.contains(*word))
    {
        queries.push(format!(
            "module ownership dependency rules public API boundaries {}",
            symbols.join(" ")
        ));
    }
    compact_deduplicated(queries, limit)
}

fn compact_deduplicated(queries: Vec<String>, limit: usize) -> Vec<String> {
    let mut output = Vec::new();
    for query in queries {
        let compact = tokens(&query).join(" ");
        if !compact.is_empty() && !output.contains(&compact) {
            output.push(compact);
        }
        if output.len() >= limit {
            break;
        }
    }
    output
}

/// Detect module/dependency/boundary-oriented prompts.
#[must_use]
pub fn is_architecture_task(query: &str) -> bool {
    let words = word_set(query);
    ARCHITECTURE_TRIGGERS
        .iter()
        .any(|word| words.contains(*word))
}

/// Build a compact architecture/project-understanding query.
#[must_use]
pub fn build_architecture_query(query: &str, symbols: &[String]) -> Option<String> {
    if !is_architecture_task(query) {
        return None;
    }
    let mut seen = Vec::new();
    let text = format!(
        "{} {query} module dependencies Gradle build.gradle public API FeatureDependencies Component Module provider DI boundary risks",
        symbols.join(" ")
    );
    for token in tokens(&text) {
        let lower = token.to_ascii_lowercase();
        if STOPWORDS.contains(&lower.as_str()) && lower != "module" && lower != "public" {
            continue;
        }
        if !seen.contains(&token) {
            seen.push(token);
        }
    }
    Some(seen.into_iter().take(64).collect::<Vec<_>>().join(" "))
}

/// Select likely function/method symbols for bounded call-tree lookup.
#[must_use]
pub fn build_call_tree_symbols(symbols: &[String], limit: usize) -> Vec<String> {
    symbols
        .iter()
        .filter(|symbol| !symbol.contains('.'))
        .filter(|symbol| {
            symbol.chars().next().is_some_and(char::is_lowercase) || symbol.starts_with("setup")
        })
        .take(limit)
        .cloned()
        .collect()
}

/// Build all deterministic repo-agent probes.
#[must_use]
pub fn build_repo_agent_plan(
    query: &str,
    planner: SearchPlan,
    allow_semantic_fallback: bool,
) -> RepoAgentPlan {
    let mut symbols = extract_symbol_candidates(query, 12);
    for symbol in expand_domain_terms(query) {
        if !symbols.contains(&symbol) {
            symbols.push(symbol);
        }
    }
    RepoAgentPlan {
        query: query.to_owned(),
        context_query: build_context_query(query, &planner, &symbols, 48),
        reuse_queries: build_reuse_queries(query, &symbols, 3),
        documentation_queries: build_documentation_queries(query, &symbols, 3),
        architecture_query: build_architecture_query(query, &symbols),
        call_tree_symbols: build_call_tree_symbols(&symbols, 4),
        symbols,
        planner,
        semantic_fallback_allowed: allow_semantic_fallback,
    }
}

/// Use embeddings only when exact evidence is thin or lacks exact/AST provenance.
#[must_use]
pub fn should_use_semantic_fallback(exact_pack: &Value, min_exact_slices: usize) -> bool {
    let slices = exact_pack
        .get("slices")
        .and_then(Value::as_array)
        .map(Vec::as_slice)
        .unwrap_or_default();
    slices.len() < min_exact_slices
        || !slices.iter().any(|item| {
            item.get("why_included")
                .and_then(Value::as_str)
                .is_some_and(|reason| {
                    reason.starts_with("ast_index") || reason == "exact_or_lexical_match"
                })
        })
}

/// Sum bounded source-token counts across present packs.
#[must_use]
pub fn total_source_tokens(packs: &[Option<&Value>]) -> usize {
    packs
        .iter()
        .filter_map(|pack| *pack)
        .filter_map(|pack| pack.get("total_source_tokens").and_then(Value::as_u64))
        .filter_map(|count| usize::try_from(count).ok())
        .sum()
}

/// Reduce a slice to the stable fields used by evidence bundles and reports.
#[must_use]
pub fn compact_slice(item: &Value) -> Value {
    let mut out = serde_json::Map::new();
    for key in [
        "file_path",
        "name",
        "parent_name",
        "chunk_type",
        "language",
        "lines",
        "score",
        "token_estimate",
        "citation",
        "why_included",
        "repo",
        "depth",
    ] {
        if let Some(value) = item.get(key) {
            out.insert(key.to_owned(), value.clone());
        }
    }
    if !out.contains_key("chunk_type") {
        out.insert("chunk_type".to_owned(), Value::String(String::new()));
    }
    if !out.contains_key("token_estimate") {
        out.insert("token_estimate".to_owned(), Value::from(0));
    }
    Value::Object(out)
}

fn file_path(item: &Value) -> String {
    item.get("file_path")
        .or_else(|| item.get("path"))
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_owned()
}

fn is_test_path(path: &str) -> bool {
    let lower = path.to_ascii_lowercase();
    lower.starts_with("test_")
        || lower.ends_with("_test.py")
        || lower.contains("/test/")
        || lower.contains("/tests/")
        || lower.contains("tests/")
        || lower.ends_with("test.py")
        || lower.contains("test.")
        || lower.contains("spec.")
}

/// Collect test slices from packs in a stable order.
#[must_use]
pub fn collect_tests(packs: &[Option<&Value>], limit: usize) -> Vec<Value> {
    let mut tests = Vec::new();
    let mut seen: BTreeSet<(String, String, String)> = BTreeSet::new();
    for pack in packs.iter().filter_map(|pack| *pack) {
        for item in pack
            .get("slices")
            .and_then(Value::as_array)
            .map(Vec::as_slice)
            .unwrap_or_default()
        {
            let path = file_path(item);
            if !is_test_path(&path) {
                continue;
            }
            let key = (
                path.clone(),
                item.get("lines")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_owned(),
                item.get("name")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_owned(),
            );
            if seen.insert(key) {
                tests.push(compact_slice(item));
                if tests.len() >= limit {
                    return tests;
                }
            }
        }
    }
    tests
}

/// Compact project-understanding module data into the stable report shape.
#[must_use]
pub fn collect_modules(understand_data: Option<&Value>, limit: usize) -> Vec<Value> {
    let Some(understand_data) = understand_data else {
        return Vec::new();
    };
    understand_data
        .get("modules")
        .and_then(Value::as_array)
        .map(Vec::as_slice)
        .unwrap_or_default()
        .iter()
        .take(limit)
        .map(|item| {
            let mut out = serde_json::Map::new();
            for key in ["path", "file_count", "score", "kinds"] {
                if let Some(value) = item.get(key) {
                    out.insert(key.to_owned(), value.clone());
                }
            }
            Value::Object(out)
        })
        .collect()
}

/// Infer retrieval and planning risks from a compact evidence bundle.
#[must_use]
pub fn infer_risks(
    query: &str,
    semantic_used: bool,
    ambiguities: &[Value],
    tests: &[Value],
) -> Vec<String> {
    let mut risks = Vec::new();
    let lowered = query.to_ascii_lowercase();
    if semantic_used {
        risks.push(
            "Semantic fallback was used; verify embedding-only hits before editing.".to_owned(),
        );
    }
    if !ambiguities.is_empty() {
        let names = ambiguities
            .iter()
            .take(3)
            .filter_map(|item| item.get("symbol").and_then(Value::as_str))
            .collect::<Vec<_>>()
            .join(", ");
        risks.push(format!(
            "Same-name symbols need caller/path disambiguation: {names}."
        ));
    }
    if (lowered.contains("analytics") || lowered.contains("event")) && tests.is_empty() {
        risks
            .push("No test slice was retrieved; locate analytics tests before editing.".to_owned());
    }
    if lowered.contains("module")
        || lowered.contains("dependency")
        || lowered.contains("extract")
        || lowered.contains("move")
    {
        risks.push(
            "Module-boundary task; verify Gradle dependencies and DI providers before editing."
                .to_owned(),
        );
    }
    risks
}

/// Build stable evaluation metrics from exact and optional semantic packs.
#[must_use]
pub fn build_eval_metrics(
    first_slice: Option<&Value>,
    exact_pack: &Value,
    semantic_pack: Option<&Value>,
    total_tokens: usize,
    whole_file_reads: usize,
) -> EvalMetrics {
    let candidate_pack = semantic_pack.unwrap_or(exact_pack);
    let first_relevant_rank = first_slice.map(|first| {
        candidate_pack
            .get("slices")
            .and_then(Value::as_array)
            .and_then(|slices| slices.iter().position(|item| item == first))
            .map_or(1, |index| index + 1)
    });
    let first_relevant_file = first_slice
        .and_then(|slice| slice.get("file_path").or_else(|| slice.get("path")))
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_owned();
    let embeddings_used = semantic_pack.is_some_and(|pack| {
        pack.get("slices")
            .and_then(Value::as_array)
            .is_some_and(|slices| {
                slices.iter().any(|item| {
                    item.get("why_included").and_then(Value::as_str) == Some("semantic_match")
                })
            })
    });
    EvalMetrics {
        first_relevant_rank,
        first_relevant_file,
        source_tokens: total_tokens,
        embeddings_used,
        whole_file_reads_avoided: whole_file_reads == 0,
        whole_file_reads,
        answer_correctness: "not_evaluated".to_owned(),
    }
}

/// Group same-name definitions across paths for explicit disambiguation.
#[must_use]
pub fn disambiguate_symbols(resolve_data: &Value) -> BTreeMap<String, Vec<Value>> {
    let mut grouped = BTreeMap::<String, Vec<Value>>::new();
    for item in resolve_data
        .get("definitions")
        .and_then(Value::as_array)
        .map(Vec::as_slice)
        .unwrap_or_default()
    {
        if let Some(name) = item
            .get("name")
            .and_then(Value::as_str)
            .filter(|name| !name.is_empty())
        {
            grouped
                .entry(name.to_owned())
                .or_default()
                .push(item.clone());
        }
    }
    grouped.retain(|_, definitions| {
        let paths: BTreeSet<&str> = definitions
            .iter()
            .filter_map(|item| item.get("file_path").and_then(Value::as_str))
            .collect();
        definitions.len() > 1 && paths.len() > 1
    });
    grouped
}

#[cfg(test)]
mod tests {
    use rag_contracts::{SearchPlan, SearchStrategy};
    use serde_json::json;

    use super::{
        build_documentation_queries, build_eval_metrics, build_repo_agent_plan, collect_modules,
        collect_tests, compact_slice, disambiguate_symbols, expand_domain_terms,
        extract_symbol_candidates, infer_risks, should_use_semantic_fallback, total_source_tokens,
    };

    #[test]
    fn symbols_and_domain_expansion_match_python_oracle() {
        assert_eq!(
            extract_symbol_candidates(
                "Make successful paid order handling call setupAppStateForNewOrder before trackPaymentFinished",
                12
            ),
            ["setupAppStateForNewOrder", "trackPaymentFinished"]
        );
        let terms =
            expand_domain_terms("successful paid order resets state before tracking analytics");
        assert!(terms.contains(&"waitForPayedOrder".to_owned()));
        assert!(terms.contains(&"setupAppStateForNewOrder".to_owned()));
    }

    #[test]
    fn plan_adds_reuse_docs_architecture_and_call_trees() {
        let planner = SearchPlan {
            queries: vec!["paid order analytics".into()],
            strategy: SearchStrategy::GraphWalk,
            ..SearchPlan::default()
        };
        let plan = build_repo_agent_plan(
            "Add analytics event only for still being created paid order and move setupAppStateForNewOrder into another module",
            planner,
            true,
        );
        assert!(!plan.reuse_queries.is_empty());
        assert!(!plan.documentation_queries.is_empty());
        assert!(plan.architecture_query.is_some());
        assert!(plan
            .call_tree_symbols
            .contains(&"setupAppStateForNewOrder".to_owned()));
        assert_eq!(
            build_documentation_queries(
                "Extract code into another module and report public API boundaries",
                &["CheckoutService".to_owned()],
                3
            ),
            ["module ownership dependency rules public API boundaries CheckoutService"]
        );
    }

    #[test]
    fn evidence_metrics_match_python_contract() {
        let first = json!({"file_path": "src/Foo.kt", "why_included": "ast_index_symbol"});
        let exact = json!({"slices": [first.clone()], "total_source_tokens": 50});
        let metrics = build_eval_metrics(Some(&first), &exact, None, 50, 0);
        assert_eq!(metrics.first_relevant_rank, Some(1));
        assert_eq!(metrics.first_relevant_file, "src/Foo.kt");
        assert!(!metrics.embeddings_used);
        assert!(metrics.whole_file_reads_avoided);
        assert_eq!(total_source_tokens(&[Some(&exact), None]), 50);
    }

    #[test]
    fn fallback_and_ambiguity_decisions_are_deterministic() {
        assert!(should_use_semantic_fallback(
            &json!({"slices": [{"why_included": "exact_or_lexical_match"}]}),
            3
        ));
        let ambiguities = disambiguate_symbols(&json!({"definitions": [
            {"name": "same", "file_path": "a/Foo.kt"},
            {"name": "same", "file_path": "b/Foo.kt"}
        ]}));
        assert!(ambiguities.contains_key("same"));
    }

    #[test]
    fn evidence_bundle_helpers_match_python_shape() {
        let exact = json!({
            "slices": [
                {"file_path": "src/main.py", "name": "main", "lines": "1-3", "score": 1.0},
                {"file_path": "tests/test_main.py", "name": "test_main", "lines": "1-3", "score": 1.0}
            ],
            "total_source_tokens": 44
        });
        let understand = json!({
            "modules": [
                {"path": "src", "file_count": 12, "score": 0.9, "kinds": {"py": 3}},
                {"path": "tests", "file_count": 2, "score": 0.2, "kinds": {"py": 1}}
            ]
        });
        let ambiguities = vec![
            json!({"symbol": "CheckoutService", "definitions": []}),
            json!({"symbol": "CheckoutService", "definitions": []}),
        ];
        let tests = collect_tests(&[Some(&exact)], 8);
        let modules = collect_modules(Some(&understand), 1);
        let risks = infer_risks("analytics event module move", true, &ambiguities, &tests);
        let compact = compact_slice(&json!({
            "file_path": "src/main.py",
            "name": "main",
            "lines": "1-3",
            "score": 1.0,
            "why_included": "exact_or_lexical_match",
            "ignored": "x"
        }));

        assert_eq!(tests.len(), 1);
        assert_eq!(modules.len(), 1);
        assert!(risks.iter().any(|line| line.contains("Semantic fallback")));
        assert_eq!(compact["file_path"], "src/main.py");
        assert!(compact.get("ignored").is_none());
    }
}
