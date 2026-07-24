//! Application-owned planner boundary and deterministic fallbacks.

use std::{
    collections::{BTreeMap, HashMap},
    process::Stdio,
    sync::{Arc, Mutex, OnceLock},
    time::{Duration, Instant},
};

use async_trait::async_trait;
use rag_contracts::{SearchPlan, SearchStrategy};
use rag_retrieval::repo_agent::{
    build_context_query, expand_domain_terms, extract_symbol_candidates,
};
use regex::Regex;
#[cfg(feature = "cloud-planners")]
use rig::{
    client::CompletionClient,
    completion::Prompt,
    providers::{anthropic, gemini, ollama, openai},
};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use thiserror::Error;
use tokio::{process::Command, time::timeout};

const CHUNK_TYPES: &[&str] = &[
    "file_summary",
    "class_declaration",
    "interface_declaration",
    "function",
    "method",
    "property",
    "doc_section",
];

/// Python `agents/retrieval._RETRIEVAL_INSTRUCTIONS`, joined verbatim with
/// `"\n"` — the exact prompt the agy planner receives.
pub const RETRIEVAL_INSTRUCTIONS: &str = concat!(
    "You are a code search strategy planner.\n",
    "Given a user query about code, output a JSON search plan.\n",
    "The plan must have these fields:\n",
    "  - \"queries\": list of search queries (expanded with synonyms)\n",
    "  - \"filters\": dict of Qdrant payload filters (e.g. {\"language\": \"python\", \"patterns\": \"repository\"})\n",
    "  - \"strategy\": one of \"lod_drill\", \"hybrid\", \"graph_walk\", \"global\"\n",
    "  - \"top_k\": number of results (default 20)\n",
    "\n",
    "Strategy guide (only these four execute differently — pick one):\n",
    "  - \"lod_drill\": DEFAULT — hierarchical drill-down (module → file → chunk).\n",
    "       Best for most queries. Cheaper than flat search; reads ~100-token\n",
    "       summaries before fetching full code.\n",
    "  - \"hybrid\": flat multi-query vector search across all chunks, with any\n",
    "       payload filters applied. Use for pattern/language/complexity asks.\n",
    "  - \"graph_walk\": when user asks about call chains or relationships\n",
    "  - \"global\": when user asks for overview/summary of a module or architecture\n",
    "\n",
    "Available filter fields: language, chunk_type, patterns, domains, layers,\n",
    "  is_async, complexity_cyclomatic, nesting_depth, has_docstring, decorator_tags\n",
    "\n",
    "Output ONLY valid JSON, no markdown, no explanation.",
);

/// Python `agents/retrieval._SYMBOL_PROMPT` verbatim.
pub const SYMBOL_PROMPT: &str = concat!(
    "Output a JSON array of up to 5 likely PascalCase class/interface names that ",
    "would DEFINE what this question is about (infer them even if not literally ",
    "present in the question). Array only, no prose: ",
);

/// Provider-independent planner contract owned by the application.
#[async_trait]
pub trait Planner: Send + Sync {
    /// Produce a validated deterministic search plan.
    async fn plan_search(&self, query: &str) -> Result<SearchPlan, PlannerError>;

    /// Infer likely code symbols from natural-language wording.
    async fn infer_symbols(&self, question: &str) -> Result<Vec<String>, PlannerError>;
}

/// Planner failures safe to expose without provider output or secrets.
#[derive(Debug, Error)]
pub enum PlannerError {
    /// Provider command is not installed or cannot start.
    #[error("planner provider unavailable")]
    Unavailable,
    /// Provider exceeded the configured deadline.
    #[error("planner provider timed out")]
    Timeout,
    /// Provider output did not contain the typed contract.
    #[error("planner provider returned an invalid response")]
    InvalidResponse,
    /// Provider process returned unsuccessfully.
    #[error("planner provider failed")]
    ProviderFailed,
}

/// Run any provider while guaranteeing deterministic fallback on every failure.
pub async fn plan_with_fallback(planner: &dyn Planner, query: &str) -> SearchPlan {
    planner
        .plan_search(query)
        .await
        .unwrap_or_else(|_| fallback_plan(query))
}

/// Antigravity CLI planner retaining subscription authentication behavior.
#[derive(Debug, Clone)]
pub struct AgyPlanner {
    model: String,
    timeout: Duration,
    executable: String,
}

impl AgyPlanner {
    /// Construct an adapter with the production-compatible 90 second deadline.
    #[must_use]
    pub fn new(model: impl Into<String>) -> Self {
        Self {
            model: model.into(),
            timeout: Duration::from_secs(90),
            executable: "agy".to_owned(),
        }
    }

    /// Override the deadline, primarily for deterministic tests and operations.
    #[must_use]
    pub fn with_timeout(mut self, timeout: Duration) -> Self {
        self.timeout = timeout;
        self
    }

    /// Override the executable without invoking a shell.
    #[must_use]
    pub fn with_executable(mut self, executable: impl Into<String>) -> Self {
        self.executable = executable.into();
        self
    }

    async fn execute(&self, prompt: &str, cwd: Option<&str>) -> Result<String, PlannerError> {
        let mut command = Command::new(&self.executable);
        command.arg("-p").arg(prompt);
        if !self.model.is_empty() {
            command.arg("--model").arg(&self.model);
        }
        if let Some(cwd) = cwd {
            command.current_dir(cwd);
        }
        command
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .process_group(0)
            .kill_on_drop(true);
        let child = command.spawn().map_err(|_| PlannerError::Unavailable)?;
        let pid = child.id().ok_or(PlannerError::ProviderFailed)?;
        let mut guard = ProcessTreeGuard::new(pid);
        let output = timeout(self.timeout, async {
            let output = child.wait_with_output().await;
            guard.disarm();
            output
        })
        .await
        .map_err(|_| PlannerError::Timeout)?
        .map_err(|_| PlannerError::ProviderFailed)?;
        if !output.status.success() {
            return Err(PlannerError::ProviderFailed);
        }
        String::from_utf8(output.stdout).map_err(|_| PlannerError::InvalidResponse)
    }
}

#[async_trait]
impl Planner for AgyPlanner {
    async fn plan_search(&self, query: &str) -> Result<SearchPlan, PlannerError> {
        // Python parity: full instruction block + the exact suffix.
        let prompt = format!("{RETRIEVAL_INSTRUCTIONS}\n\nUser query: {query}\n\nJSON plan:");
        let output = self.execute(&prompt, None).await?;
        let data = extract_json_object(&output).ok_or(PlannerError::InvalidResponse)?;
        plan_from_value(&data, query).ok_or(PlannerError::InvalidResponse)
    }

    async fn infer_symbols(&self, question: &str) -> Result<Vec<String>, PlannerError> {
        // Python parity: `_SYMBOL_PROMPT` verbatim, run from /tmp.
        let prompt = format!("{SYMBOL_PROMPT}{question}");
        let output = self.execute(&prompt, Some("/tmp")).await?;
        extract_symbol_array(&output).ok_or(PlannerError::InvalidResponse)
    }
}

/// Parse the first viable JSON object from fenced, raw, or prose-wrapped output.
#[must_use]
pub fn extract_json_object(text: &str) -> Option<Value> {
    let fence = Regex::new(r"(?s)```(?:json)?\s*(.*?)```").expect("static regex");
    let mut candidates = Vec::new();
    if let Some(capture) = fence.captures(text).and_then(|captures| captures.get(1)) {
        candidates.push(capture.as_str().trim());
    }
    candidates.push(text.trim());
    if let (Some(start), Some(end)) = (text.find('{'), text.rfind('}')) {
        if end > start {
            candidates.push(&text[start..=end]);
        }
    }
    candidates.into_iter().find_map(|candidate| {
        let value: Value = serde_json::from_str(candidate).ok()?;
        value.is_object().then_some(value)
    })
}

fn extract_symbol_array(text: &str) -> Option<Vec<String>> {
    let start = text.find('[')?;
    let end = text.rfind(']')?;
    let values: Vec<Value> = serde_json::from_str(&text[start..=end]).ok()?;
    Some(
        values
            .into_iter()
            .filter_map(|value| value.as_str().map(ToOwned::to_owned))
            .filter(|value| !value.is_empty())
            .take(5)
            .collect(),
    )
}

/// Convert untrusted planner JSON into a validated application contract.
#[must_use]
pub fn plan_from_value(data: &Value, query: &str) -> Option<SearchPlan> {
    let data = data.as_object()?;
    let queries = data
        .get("queries")
        .and_then(Value::as_array)
        .map(|values| {
            values
                .iter()
                .filter_map(Value::as_str)
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .map(ToOwned::to_owned)
                .take(8)
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    let filters = data
        .get("filters")
        .and_then(Value::as_object)
        .map(sanitize_filters)
        .unwrap_or_default();
    let strategy = data
        .get("strategy")
        .and_then(Value::as_str)
        .map(SearchStrategy::from_compatible_name)
        .unwrap_or_default();
    let top_k = data
        .get("top_k")
        .and_then(Value::as_u64)
        .and_then(|value| usize::try_from(value).ok())
        .unwrap_or(20)
        .clamp(1, 200);
    Some(SearchPlan {
        queries: normalize_queries(queries, query),
        filters,
        strategy,
        top_k,
    })
}

/// Python-compatible deterministic planner used when every provider fails.
#[must_use]
pub fn fallback_plan(query: &str) -> SearchPlan {
    let queries = rag_retrieval::decompose_query(query, 3)
        .iter()
        .map(|query| rag_retrieval::expand_query(query))
        .collect();
    let lower = query.to_ascii_lowercase();
    let words: Vec<&str> = lower.split_whitespace().collect();
    let languages = [
        ("python", "python"),
        ("py", "python"),
        ("typescript", "typescript"),
        ("ts", "typescript"),
        ("javascript", "javascript"),
        ("js", "javascript"),
        ("go", "go"),
        ("golang", "go"),
        ("rust", "rust"),
        ("rs", "rust"),
        ("java", "java"),
        ("kotlin", "kotlin"),
        ("c++", "cpp"),
        ("cpp", "cpp"),
    ];
    let mut filters = Map::new();
    if let Some((_, language)) = languages.iter().find(|(hint, _)| words.contains(hint)) {
        filters.insert("language".to_owned(), Value::String((*language).to_owned()));
    }
    if let Some(pattern) = [
        "singleton",
        "factory",
        "repository",
        "observer",
        "strategy",
        "adapter",
        "decorator",
        "command",
        "builder",
        "middleware",
    ]
    .iter()
    .find(|pattern| lower.contains(**pattern))
    {
        filters.insert("patterns".to_owned(), Value::String((*pattern).to_owned()));
    }
    if ["complex", "complicated", "deeply nested"]
        .iter()
        .any(|signal| lower.contains(signal))
    {
        filters.insert("complexity_cyclomatic".to_owned(), Value::from(10));
    }
    filters = sanitize_filters(&filters);

    let mut strategy = if filters.is_empty() {
        SearchStrategy::LodDrill
    } else {
        SearchStrategy::Hybrid
    };
    if ["calls", "uses", "depends", "flow", "chain", "trace"]
        .iter()
        .any(|signal| lower.contains(signal))
    {
        strategy = SearchStrategy::GraphWalk;
    }
    if ["how many", "count", "all patterns", "statistics"]
        .iter()
        .any(|signal| lower.contains(signal))
    {
        strategy = SearchStrategy::Hybrid;
    }
    if [
        "overview",
        "summary",
        "what does this",
        "architecture",
        "main purpose",
        "module",
    ]
    .iter()
    .any(|signal| lower.contains(signal))
    {
        strategy = SearchStrategy::Global;
    }
    if ["exact", "literal", "raw search"]
        .iter()
        .any(|signal| lower.contains(signal))
    {
        strategy = SearchStrategy::Hybrid;
    }

    SearchPlan {
        queries,
        filters,
        strategy,
        top_k: 20,
    }
}

/// A tiny TTL cache with explicit invalidation hooks.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CacheEvent {
    /// The entry was replaced by a newer value.
    Replaced,
    /// The entry expired and was evicted on read or purge.
    Expired,
    /// The entry was removed manually.
    Invalidated,
    /// The entire cache was cleared.
    Cleared,
}

type CacheHook<K, V> = Arc<dyn Fn(&K, &V, CacheEvent) + Send + Sync>;

#[derive(Debug)]
struct CacheEntry<V> {
    value: V,
    inserted_at: Instant,
}

/// A mutex-protected TTL cache suitable for planner and grounding memoization.
pub struct TtlCache<K, V> {
    ttl: Duration,
    entries: Mutex<HashMap<K, CacheEntry<V>>>,
    hook: Option<CacheHook<K, V>>,
}

impl<K, V> TtlCache<K, V>
where
    K: Eq + std::hash::Hash,
{
    /// Create a cache with the given TTL.
    #[must_use]
    pub fn new(ttl: Duration) -> Self {
        Self {
            ttl,
            entries: Mutex::new(HashMap::new()),
            hook: None,
        }
    }

    /// Attach a side-effect hook for invalidations and evictions.
    #[must_use]
    pub fn with_hook(mut self, hook: impl Fn(&K, &V, CacheEvent) + Send + Sync + 'static) -> Self {
        self.hook = Some(Arc::new(hook));
        self
    }

    /// Insert a value, replacing any prior entry.
    pub fn insert(&self, key: K, value: V)
    where
        K: Clone,
    {
        let mut entries = self.entries.lock().expect("cache mutex");
        if let Some(previous) = entries.insert(
            key.clone(),
            CacheEntry {
                value,
                inserted_at: Instant::now(),
            },
        ) {
            self.emit(&key, &previous.value, CacheEvent::Replaced);
        }
    }

    /// Retrieve a cached value, evicting it if it expired.
    #[must_use]
    pub fn get(&self, key: &K) -> Option<V>
    where
        V: Clone,
    {
        let mut entries = self.entries.lock().expect("cache mutex");
        let expired = entries
            .get(key)
            .is_some_and(|entry| entry.inserted_at.elapsed() > self.ttl);
        if expired {
            if let Some(entry) = entries.remove(key) {
                self.emit(key, &entry.value, CacheEvent::Expired);
            }
            return None;
        }
        entries.get(key).map(|entry| entry.value.clone())
    }

    /// Remove a single entry if present.
    pub fn invalidate(&self, key: &K) -> Option<V> {
        let mut entries = self.entries.lock().expect("cache mutex");
        let removed = entries.remove(key)?;
        self.emit(key, &removed.value, CacheEvent::Invalidated);
        Some(removed.value)
    }

    /// Remove entries that satisfy the predicate.
    pub fn invalidate_where(&self, mut predicate: impl FnMut(&K, &V) -> bool)
    where
        K: Clone,
    {
        let keys = {
            let entries = self.entries.lock().expect("cache mutex");
            entries
                .iter()
                .filter_map(|(key, entry)| predicate(key, &entry.value).then_some(key.clone()))
                .collect::<Vec<_>>()
        };
        for key in keys {
            let _ = self.invalidate(&key);
        }
    }

    /// Remove all cached values.
    pub fn clear(&self)
    where
        K: Clone,
        V: Clone,
    {
        let entries = {
            let entries = self.entries.lock().expect("cache mutex");
            entries
                .iter()
                .map(|(key, entry)| (key.clone(), entry.value.clone()))
                .collect::<Vec<_>>()
        };
        for (key, value) in &entries {
            self.emit(key, value, CacheEvent::Cleared);
        }
        self.entries.lock().expect("cache mutex").clear();
    }

    /// Count live entries, dropping expired ones first.
    #[must_use]
    pub fn len(&self) -> usize
    where
        K: Clone,
        V: Clone,
    {
        self.purge_expired();
        self.entries.lock().expect("cache mutex").len()
    }

    /// Check whether the cache has any live entries.
    #[must_use]
    pub fn is_empty(&self) -> bool
    where
        K: Clone,
        V: Clone,
    {
        self.len() == 0
    }

    fn purge_expired(&self)
    where
        K: Clone,
    {
        let keys = {
            let entries = self.entries.lock().expect("cache mutex");
            entries
                .iter()
                .filter_map(|(key, entry)| {
                    (entry.inserted_at.elapsed() > self.ttl).then_some(key.clone())
                })
                .collect::<Vec<_>>()
        };
        for key in keys {
            let _ = self.invalidate(&key);
        }
    }

    fn emit(&self, key: &K, value: &V, event: CacheEvent) {
        if let Some(hook) = &self.hook {
            hook(key, value, event);
        }
    }
}

fn redact_sensitive(text: &str) -> String {
    static BEARER: OnceLock<Regex> = OnceLock::new();
    static SECRET_ASSIGNMENT: OnceLock<Regex> = OnceLock::new();
    static OPENAI_KEY: OnceLock<Regex> = OnceLock::new();
    static GOOGLE_KEY: OnceLock<Regex> = OnceLock::new();
    let mut redacted = text.to_owned();
    let bearer = BEARER
        .get_or_init(|| Regex::new(r"(?i)\bBearer\s+[A-Za-z0-9._\-+/=]+\b").expect("static regex"));
    redacted = bearer
        .replace_all(&redacted, "Bearer <redacted>")
        .into_owned();
    let secret_assignment = SECRET_ASSIGNMENT.get_or_init(|| {
        Regex::new(r"(?i)\b(api[_-]?key|token|secret|password)\b\s*[:=]\s*([^\s,;]+)")
            .expect("static regex")
    });
    redacted = secret_assignment
        .replace_all(&redacted, "$1=<redacted>")
        .into_owned();
    let openai_key =
        OPENAI_KEY.get_or_init(|| Regex::new(r"\bsk-[A-Za-z0-9]{16,}\b").expect("static regex"));
    redacted = openai_key.replace_all(&redacted, "<redacted>").into_owned();
    let google_key =
        GOOGLE_KEY.get_or_init(|| Regex::new(r"\bAIza[0-9A-Za-z_-]{20,}\b").expect("static regex"));
    google_key.replace_all(&redacted, "<redacted>").into_owned()
}

/// Errors returned by the Rig-backed provider adapters.
#[derive(Debug, Error)]
pub enum GenerationError {
    /// The provider request timed out.
    #[error("provider request timed out")]
    Timeout,
    /// The provider returned something that did not parse into the contract.
    #[error("provider returned an invalid response")]
    InvalidResponse,
    /// The provider failed, with redacted details safe for logs and tests.
    #[error("{provider} provider failed: {message}")]
    Provider {
        provider: &'static str,
        message: String,
    },
}

impl GenerationError {
    pub fn provider(provider: &'static str, error: impl std::fmt::Display) -> Self {
        Self::Provider {
            provider,
            message: redact_sensitive(&error.to_string()),
        }
    }
}

impl From<GenerationError> for PlannerError {
    fn from(value: GenerationError) -> Self {
        match value {
            GenerationError::Timeout => PlannerError::Timeout,
            GenerationError::InvalidResponse => PlannerError::InvalidResponse,
            GenerationError::Provider { .. } => PlannerError::ProviderFailed,
        }
    }
}

#[cfg(feature = "cloud-planners")]
#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema, PartialEq)]
struct AskWireCitation {
    file_path: String,
    lines: String,
    name: String,
    score: f64,
}

#[cfg(feature = "cloud-planners")]
#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema, PartialEq)]
struct AskWireResponse {
    answer: String,
    #[serde(default)]
    citations: Vec<AskWireCitation>,
    #[serde(default)]
    insufficient_context: bool,
}

/// Public ask-generation response contract.
#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema, PartialEq)]
pub struct AskResponse {
    pub answer: String,
    pub citations: Vec<AskCitation>,
    pub insufficient_context: bool,
}

/// Source citation emitted by ask-generation.
#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema, PartialEq)]
pub struct AskCitation {
    pub file_path: String,
    pub lines: String,
    pub name: String,
    pub score: f64,
}

/// Code snippet used to ground ask-generation.
#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema, PartialEq)]
pub struct AskSnippet {
    pub file_path: String,
    pub lines: String,
    pub name: String,
    pub language: String,
    pub code: String,
    pub score: f64,
}

fn normalize_queries(mut queries: Vec<String>, fallback: &str) -> Vec<String> {
    let mut seen = std::collections::BTreeSet::new();
    queries
        .drain(..)
        .map(|item| item.trim().to_owned())
        .filter(|item| !item.is_empty())
        .filter(|item| seen.insert(item.to_ascii_lowercase()))
        .take(8)
        .collect::<Vec<_>>()
        .into_iter()
        .chain((seen.is_empty()).then_some(fallback.to_owned()))
        .collect()
}

const CONTROLLED_STRING_FILTERS: &[&str] = &[
    "language",
    "chunk_type",
    "patterns",
    "decorator_tags",
    "domains",
    "layers",
];
const CONTROLLED_NUMERIC_FILTERS: &[&str] = &["complexity_cyclomatic", "nesting_depth"];
const CONTROLLED_BOOL_FILTERS: &[&str] = &["is_async", "has_docstring"];

/// Convert untrusted planner filters into the strict contract expected by Qdrant.
#[must_use]
pub fn sanitize_filters(filters: &Map<String, Value>) -> Map<String, Value> {
    let language_values = [
        "python",
        "java",
        "kotlin",
        "typescript",
        "javascript",
        "go",
        "rust",
        "c",
        "cpp",
        "dart",
    ];
    let chunk_types = CHUNK_TYPES;
    let patterns = [
        "repository",
        "factory",
        "singleton",
        "observer",
        "strategy",
        "adapter",
        "decorator",
        "command",
        "builder",
        "service",
        "model",
        "provider",
        "validator",
        "serializer",
        "state_machine",
    ];
    let decorator_tags = [
        "singleton",
        "route",
        "inject",
        "test",
        "cached",
        "retry",
        "async_task",
        "scheduled",
        "deprecated",
        "validated",
    ];
    let domains = [
        "auth",
        "payment",
        "notification",
        "database",
        "api",
        "cache",
        "search",
        "file",
        "test",
        "config",
        "logging",
        "queue",
    ];
    let layers = [
        "controller",
        "service",
        "repository",
        "model",
        "utility",
        "config",
        "middleware",
        "migration",
    ];
    let allowed = BTreeMap::from([
        ("language", language_values.as_slice()),
        ("chunk_type", chunk_types),
        ("patterns", &patterns),
        ("decorator_tags", &decorator_tags),
        ("domains", &domains),
        ("layers", &layers),
    ]);

    let mut cleaned = Map::new();
    for (key, value) in filters {
        match key.as_str() {
            k if CONTROLLED_STRING_FILTERS.contains(&k) => {
                let Some(valid) = allowed.get(k) else {
                    continue;
                };
                match value {
                    Value::String(item) if valid.contains(&item.as_str()) => {
                        cleaned.insert(key.clone(), Value::String(item.clone()));
                    }
                    Value::Array(items) => {
                        let kept = items
                            .iter()
                            .filter_map(Value::as_str)
                            .filter(|item| valid.contains(item))
                            .map(|item| Value::String(item.to_owned()))
                            .collect::<Vec<_>>();
                        match kept.as_slice() {
                            [] => {}
                            [only] => {
                                cleaned.insert(key.clone(), only.clone());
                            }
                            _ => {
                                cleaned.insert(key.clone(), Value::Array(kept));
                            }
                        }
                    }
                    _ => {}
                }
            }
            k if CONTROLLED_NUMERIC_FILTERS.contains(&k) => {
                if matches!(value, Value::Number(_)) {
                    cleaned.insert(key.clone(), value.clone());
                }
            }
            k if CONTROLLED_BOOL_FILTERS.contains(&k) => {
                if matches!(value, Value::Bool(_)) {
                    cleaned.insert(key.clone(), value.clone());
                }
            }
            _ => {}
        }
    }
    cleaned
}

/// Build a grounded search query using deterministic symbol and domain hints.
#[must_use]
pub fn grounded_search_query(query: &str, plan: &SearchPlan, symbols: &[String]) -> String {
    build_context_query(query, plan, symbols, 20)
}

/// Return symbol candidates grounded by the repo-agent heuristics.
#[must_use]
pub fn grounded_symbols(query: &str, limit: usize) -> Vec<String> {
    let mut symbols = extract_symbol_candidates(query, limit);
    for symbol in expand_domain_terms(query) {
        if symbols.len() >= limit {
            break;
        }
        if !symbols
            .iter()
            .any(|item| item.eq_ignore_ascii_case(&symbol))
        {
            symbols.push(symbol);
        }
    }
    symbols.truncate(limit);
    symbols
}

// ---------------------------------------------------------------------------
// Cloud provider adapters (feature `cloud-planners`, off by default).
//
// Everything from here to the end of this file is compiled only when the
// feature is enabled. See the rationale in Cargo.toml: the daemon reaches none
// of it, and linking it cost 38 crates nothing else in the workspace needs.
//
// The `Planner` trait, `AgyPlanner`, `fallback_plan`, `plan_from_value`,
// `extract_json_object`, `grounded_symbols`, the prompts, `GenerationError`
// and the `AskGenerator`/`AskResponse`/`AskSnippet` contracts above are *not*
// gated -- the daemon depends on them, and the contracts are what a future
// non-rig ask generator would implement.
// ---------------------------------------------------------------------------

#[cfg(feature = "cloud-planners")]
fn parse_planner_response(raw: &str, query: &str) -> Result<SearchPlan, GenerationError> {
    let value = extract_json_object(raw).ok_or(GenerationError::InvalidResponse)?;
    let plan = plan_from_value(&value, query).ok_or(GenerationError::InvalidResponse)?;
    Ok(plan)
}

#[cfg(feature = "cloud-planners")]
fn parse_ask_response(raw: &str) -> Result<AskResponse, GenerationError> {
    let value = extract_json_object(raw).ok_or(GenerationError::InvalidResponse)?;
    let wire: AskWireResponse =
        serde_json::from_value(value).map_err(|_| GenerationError::InvalidResponse)?;
    let citations = if wire.insufficient_context {
        Vec::new()
    } else {
        wire.citations
            .into_iter()
            .map(|citation| AskCitation {
                file_path: citation.file_path,
                lines: citation.lines,
                name: citation.name,
                score: citation.score,
            })
            .collect::<Vec<_>>()
    };
    if !wire.insufficient_context && citations.is_empty() {
        return Err(GenerationError::InvalidResponse);
    }
    Ok(AskResponse {
        answer: if wire.insufficient_context {
            "The indexed code retrieved for this question does not contain enough information to answer it reliably.".to_owned()
        } else {
            wire.answer.trim().to_owned()
        },
        citations,
        insufficient_context: wire.insufficient_context,
    })
}

#[cfg(feature = "cloud-planners")]
async fn prompt_text_with_timeout<M>(
    agent: &rig::agent::Agent<M>,
    provider: &'static str,
    timeout_duration: Duration,
    prompt: String,
) -> Result<String, GenerationError>
where
    M: rig::completion::CompletionModel + 'static,
{
    let result = timeout(timeout_duration, async {
        agent
            .prompt(prompt)
            .await
            .map_err(|error| GenerationError::provider(provider, error))
    })
    .await
    .map_err(|_| GenerationError::Timeout)??;
    Ok(result)
}

/// Rig-backed planner adapter shared by the provider-specific constructors.
#[cfg(feature = "cloud-planners")]
#[derive(Clone)]
pub struct RigPlanner<M>
where
    M: rig::completion::CompletionModel,
{
    agent: rig::agent::Agent<M>,
    provider: &'static str,
    timeout: Duration,
}

#[cfg(feature = "cloud-planners")]
impl<M> RigPlanner<M>
where
    M: rig::completion::CompletionModel + 'static,
{
    fn new(agent: rig::agent::Agent<M>, provider: &'static str) -> Self {
        Self {
            agent,
            provider,
            timeout: Duration::from_secs(90),
        }
    }

    /// Override the timeout, primarily for tests.
    #[must_use]
    pub fn with_timeout(mut self, timeout: Duration) -> Self {
        self.timeout = timeout;
        self
    }

    async fn plan_search_raw(&self, query: &str) -> Result<SearchPlan, GenerationError> {
        let fallback = fallback_plan(query);
        let symbols = grounded_symbols(query, 8);
        let symbol_hints = if symbols.is_empty() {
            "(none)".to_owned()
        } else {
            symbols.join(", ")
        };
        let domain_hints = {
            let domains = expand_domain_terms(query);
            if domains.is_empty() {
                "(none)".to_owned()
            } else {
                domains.join(", ")
            }
        };
        let grounded = grounded_search_query(query, &fallback, &symbols);
        let prompt = format!(
            "{PLANNER_SYSTEM_PROMPT}\n\nQuery: {query}\nGrounded query: {grounded}\nSymbol hints: {}\nDomain hints: {}\nFallback strategy: {:?}\nReturn valid JSON only.",
            symbol_hints,
            domain_hints,
            fallback.strategy
        );
        let raw =
            prompt_text_with_timeout(&self.agent, self.provider, self.timeout, prompt).await?;
        parse_planner_response(&raw, query)
    }

    async fn infer_symbols_raw(&self, question: &str) -> Result<Vec<String>, GenerationError> {
        let prompt = format!(
            "{SYMBOL_SYSTEM_PROMPT}\n\nQuestion: {question}\nGrounded candidates: {}\nReturn a JSON array only.",
            {
                let symbols = grounded_symbols(question, 5);
                if symbols.is_empty() { "(none)".to_owned() } else { symbols.join(", ") }
            }
        );
        let raw =
            prompt_text_with_timeout(&self.agent, self.provider, self.timeout, prompt).await?;
        extract_symbol_array(&raw).ok_or(GenerationError::InvalidResponse)
    }
}

#[cfg(feature = "cloud-planners")]
#[async_trait]
impl<M> Planner for RigPlanner<M>
where
    M: rig::completion::CompletionModel + 'static,
{
    async fn plan_search(&self, query: &str) -> Result<SearchPlan, PlannerError> {
        self.plan_search_raw(query).await.map_err(Into::into)
    }

    async fn infer_symbols(&self, question: &str) -> Result<Vec<String>, PlannerError> {
        match self.infer_symbols_raw(question).await {
            Ok(symbols) => Ok(symbols),
            Err(_) => Ok(grounded_symbols(question, 5)),
        }
    }
}

/// Ask-generation contract around code snippets and citations.
#[async_trait]
pub trait AskGenerator: Send + Sync {
    /// Generate an answer grounded in code snippets.
    async fn answer(
        &self,
        question: &str,
        snippets: &[AskSnippet],
    ) -> Result<AskResponse, GenerationError>;
}

/// Rig-backed ask-generation adapter shared by provider constructors.
#[cfg(feature = "cloud-planners")]
#[derive(Clone)]
pub struct RigAskGenerator<M>
where
    M: rig::completion::CompletionModel,
{
    agent: rig::agent::Agent<M>,
    provider: &'static str,
    timeout: Duration,
}

#[cfg(feature = "cloud-planners")]
impl<M> RigAskGenerator<M>
where
    M: rig::completion::CompletionModel + 'static,
{
    fn new(agent: rig::agent::Agent<M>, provider: &'static str) -> Self {
        Self {
            agent,
            provider,
            timeout: Duration::from_secs(180),
        }
    }

    #[must_use]
    pub fn with_timeout(mut self, timeout: Duration) -> Self {
        self.timeout = timeout;
        self
    }

    async fn answer_raw(
        &self,
        question: &str,
        snippets: &[AskSnippet],
    ) -> Result<AskResponse, GenerationError> {
        if snippets.is_empty() {
            return Ok(AskResponse {
                answer: "The indexed code retrieved for this question does not contain enough information to answer it reliably.".to_owned(),
                citations: Vec::new(),
                insufficient_context: true,
            });
        }
        let mut blocks = Vec::with_capacity(snippets.len());
        for (index, snippet) in snippets.iter().enumerate() {
            blocks.push(format!(
                "[{}] {}:{} ({})\n```{}\n{}\n```",
                index + 1,
                snippet.file_path,
                snippet.lines,
                snippet.name,
                snippet.language,
                snippet.code
            ));
        }
        let prompt = format!(
            "{ASK_SYSTEM_PROMPT}\n\nQuestion: {question}\n\nCode snippets:\n{}\n\nReturn JSON with answer, citations, and insufficient_context.",
            blocks.join("\n\n")
        );
        let raw =
            prompt_text_with_timeout(&self.agent, self.provider, self.timeout, prompt).await?;
        parse_ask_response(&raw)
    }
}

#[cfg(feature = "cloud-planners")]
#[async_trait]
impl<M> AskGenerator for RigAskGenerator<M>
where
    M: rig::completion::CompletionModel + 'static,
{
    async fn answer(
        &self,
        question: &str,
        snippets: &[AskSnippet],
    ) -> Result<AskResponse, GenerationError> {
        self.answer_raw(question, snippets).await
    }
}

#[cfg(feature = "cloud-planners")]
const PLANNER_SYSTEM_PROMPT: &str = concat!(
    "You are a code search strategy planner.\n",
    "Output only JSON with fields queries, filters, strategy, and top_k.\n",
    "Use one of the strategies lod_drill, hybrid, graph_walk, or global.\n",
    "Only emit safe filter keys: language, chunk_type, patterns, decorator_tags, domains, layers, is_async, complexity_cyclomatic, nesting_depth, has_docstring.\n",
    "Drop invented values rather than inventing new keys.\n",
    "Keep top_k between 1 and 200."
);

#[cfg(feature = "cloud-planners")]
const SYMBOL_SYSTEM_PROMPT: &str = concat!(
    "Extract likely code symbols from the question.\n",
    "Return only a JSON array of up to five PascalCase or identifier-like names.\n",
    "Do not add prose."
);

#[cfg(feature = "cloud-planners")]
const ASK_SYSTEM_PROMPT: &str = concat!(
    "You are a code assistant.\n",
    "Answer using only the provided snippets.\n",
    "Cite sources inline as [N] matching the snippet numbers.\n",
    "If the snippets do not contain the answer, set insufficient_context to true, return an empty citations array, and set answer to a concise refusal.\n",
    "Return only JSON."
);

/// Build an OpenAI-backed planner using the pinned Rig client.
#[cfg(feature = "cloud-planners")]
pub fn openai_planner(
    api_key: impl Into<String>,
    base_url: Option<&str>,
    model: impl Into<String>,
) -> Result<Box<dyn Planner>, GenerationError> {
    let mut builder: openai::CompletionsClientBuilder =
        openai::CompletionsClient::builder().api_key(rig::client::BearerAuth::from(api_key.into()));
    if let Some(base_url) = base_url {
        builder = builder.base_url(base_url);
    }
    let client = builder
        .build()
        .map_err(|error| GenerationError::provider("openai", error))?;
    let agent = client
        .agent(model)
        .preamble(PLANNER_SYSTEM_PROMPT)
        .temperature(0.0)
        .build();
    Ok(Box::new(RigPlanner::new(agent, "openai")))
}

/// Build an Anthropic-backed planner using the pinned Rig client.
#[cfg(feature = "cloud-planners")]
pub fn anthropic_planner(
    api_key: impl Into<String>,
    base_url: Option<&str>,
    model: impl Into<String>,
) -> Result<Box<dyn Planner>, GenerationError> {
    let mut builder: anthropic::ClientBuilder = anthropic::Client::builder()
        .api_key(anthropic::client::AnthropicKey::from(api_key.into()))
        .anthropic_version(anthropic::completion::ANTHROPIC_VERSION_LATEST);
    if let Some(base_url) = base_url {
        builder = builder.base_url(base_url);
    }
    let client = builder
        .build()
        .map_err(|error| GenerationError::provider("anthropic", error))?;
    let agent = client
        .agent(model)
        .preamble(PLANNER_SYSTEM_PROMPT)
        .temperature(0.0)
        .max_tokens(256)
        .build();
    Ok(Box::new(RigPlanner::new(agent, "anthropic")))
}

/// Build a Gemini-backed planner using the pinned Rig client.
#[cfg(feature = "cloud-planners")]
pub fn gemini_planner(
    api_key: impl Into<String>,
    base_url: Option<&str>,
    model: impl Into<String>,
) -> Result<Box<dyn Planner>, GenerationError> {
    let mut builder: gemini::client::ClientBuilder =
        gemini::Client::builder().api_key(gemini::client::GeminiApiKey::from(api_key.into()));
    if let Some(base_url) = base_url {
        builder = builder.base_url(base_url);
    }
    let client = builder
        .build()
        .map_err(|error| GenerationError::provider("gemini", error))?;
    let agent = client
        .agent(model)
        .preamble(PLANNER_SYSTEM_PROMPT)
        .temperature(0.0)
        .build();
    Ok(Box::new(RigPlanner::new(agent, "gemini")))
}

/// Build an Ollama-backed planner using the pinned Rig client.
#[cfg(feature = "cloud-planners")]
pub fn ollama_planner(
    api_key: impl Into<String>,
    base_url: Option<&str>,
    model: impl Into<String>,
) -> Result<Box<dyn Planner>, GenerationError> {
    let mut builder: ollama::ClientBuilder =
        ollama::Client::builder().api_key(ollama::OllamaApiKey::from(api_key.into()));
    if let Some(base_url) = base_url {
        builder = builder.base_url(base_url);
    }
    let client = builder
        .build()
        .map_err(|error| GenerationError::provider("ollama", error))?;
    let agent = client
        .agent(model)
        .preamble(PLANNER_SYSTEM_PROMPT)
        .temperature(0.0)
        .build();
    Ok(Box::new(RigPlanner::new(agent, "ollama")))
}

/// Build an OpenAI-backed ask generator using the pinned Rig client.
#[cfg(feature = "cloud-planners")]
pub fn openai_ask_generator(
    api_key: impl Into<String>,
    base_url: Option<&str>,
    model: impl Into<String>,
) -> Result<Box<dyn AskGenerator>, GenerationError> {
    let mut builder: openai::CompletionsClientBuilder =
        openai::CompletionsClient::builder().api_key(rig::client::BearerAuth::from(api_key.into()));
    if let Some(base_url) = base_url {
        builder = builder.base_url(base_url);
    }
    let client = builder
        .build()
        .map_err(|error| GenerationError::provider("openai", error))?;
    let agent = client
        .agent(model)
        .preamble(ASK_SYSTEM_PROMPT)
        .temperature(0.2)
        .build();
    Ok(Box::new(RigAskGenerator::new(agent, "openai")))
}

/// Build an Anthropic-backed ask generator using the pinned Rig client.
#[cfg(feature = "cloud-planners")]
pub fn anthropic_ask_generator(
    api_key: impl Into<String>,
    base_url: Option<&str>,
    model: impl Into<String>,
) -> Result<Box<dyn AskGenerator>, GenerationError> {
    let mut builder: anthropic::ClientBuilder = anthropic::Client::builder()
        .api_key(anthropic::client::AnthropicKey::from(api_key.into()))
        .anthropic_version(anthropic::completion::ANTHROPIC_VERSION_LATEST);
    if let Some(base_url) = base_url {
        builder = builder.base_url(base_url);
    }
    let client = builder
        .build()
        .map_err(|error| GenerationError::provider("anthropic", error))?;
    let agent = client
        .agent(model)
        .preamble(ASK_SYSTEM_PROMPT)
        .temperature(0.2)
        .max_tokens(256)
        .build();
    Ok(Box::new(RigAskGenerator::new(agent, "anthropic")))
}

/// Build a Gemini-backed ask generator using the pinned Rig client.
#[cfg(feature = "cloud-planners")]
pub fn gemini_ask_generator(
    api_key: impl Into<String>,
    base_url: Option<&str>,
    model: impl Into<String>,
) -> Result<Box<dyn AskGenerator>, GenerationError> {
    let mut builder: gemini::client::ClientBuilder =
        gemini::Client::builder().api_key(gemini::client::GeminiApiKey::from(api_key.into()));
    if let Some(base_url) = base_url {
        builder = builder.base_url(base_url);
    }
    let client = builder
        .build()
        .map_err(|error| GenerationError::provider("gemini", error))?;
    let agent = client
        .agent(model)
        .preamble(ASK_SYSTEM_PROMPT)
        .temperature(0.2)
        .build();
    Ok(Box::new(RigAskGenerator::new(agent, "gemini")))
}

/// Build an Ollama-backed ask generator using the pinned Rig client.
#[cfg(feature = "cloud-planners")]
pub fn ollama_ask_generator(
    api_key: impl Into<String>,
    base_url: Option<&str>,
    model: impl Into<String>,
) -> Result<Box<dyn AskGenerator>, GenerationError> {
    let mut builder: ollama::ClientBuilder =
        ollama::Client::builder().api_key(ollama::OllamaApiKey::from(api_key.into()));
    if let Some(base_url) = base_url {
        builder = builder.base_url(base_url);
    }
    let client = builder
        .build()
        .map_err(|error| GenerationError::provider("ollama", error))?;
    let agent = client
        .agent(model)
        .preamble(ASK_SYSTEM_PROMPT)
        .temperature(0.2)
        .build();
    Ok(Box::new(RigAskGenerator::new(agent, "ollama")))
}

struct ProcessTreeGuard {
    pid: u32,
    armed: bool,
}

impl ProcessTreeGuard {
    fn new(pid: u32) -> Self {
        Self { pid, armed: true }
    }

    fn disarm(&mut self) {
        self.armed = false;
    }
}

impl Drop for ProcessTreeGuard {
    fn drop(&mut self) {
        if !self.armed {
            return;
        }
        terminate_process_tree(self.pid);
    }
}

#[cfg(unix)]
fn terminate_process_tree(pid: u32) {
    use nix::{
        sys::signal::{kill, killpg, Signal},
        unistd::Pid,
    };
    let pid = Pid::from_raw(pid as i32);
    let _ = killpg(pid, Signal::SIGKILL);
    let _ = kill(pid, Signal::SIGKILL);
}

#[cfg(not(unix))]
fn terminate_process_tree(pid: u32) {
    let _ = pid;
}

#[cfg(test)]
mod tests {
    use rag_contracts::SearchStrategy;
    use serde_json::json;

    use super::{extract_json_object, fallback_plan, plan_from_value, sanitize_filters};

    #[test]
    fn parses_fenced_and_prose_wrapped_objects() {
        assert_eq!(
            extract_json_object("```json\n{\"a\":1}\n```"),
            Some(json!({"a": 1}))
        );
        assert_eq!(
            extract_json_object("prefix {\"a\":2} suffix"),
            Some(json!({"a": 2}))
        );
        assert_eq!(extract_json_object("[1,2]"), None);
    }

    #[test]
    fn sanitizes_controlled_filters() {
        let filters =
            json!({"language": "kotlinx", "patterns": "repository", "complexity_cyclomatic": 10});
        let cleaned = sanitize_filters(filters.as_object().expect("object"));
        assert!(!cleaned.contains_key("language"));
        assert_eq!(cleaned["patterns"], "repository");
        assert_eq!(cleaned["complexity_cyclomatic"], 10);
    }

    #[test]
    fn normalizes_legacy_strategy_and_bounds_top_k() {
        let plan = plan_from_value(&json!({"strategy": "filtered", "top_k": 9999}), "query")
            .expect("plan");
        assert_eq!(plan.strategy, SearchStrategy::Hybrid);
        assert_eq!(plan.top_k, 200);
    }

    #[test]
    fn fallback_matches_python_signals() {
        let plan = fallback_plan("find python factory classes");
        assert_eq!(plan.strategy, SearchStrategy::Hybrid);
        assert_eq!(plan.filters["language"], "python");
        assert_eq!(plan.filters["patterns"], "factory");
        assert!(fallback_plan("what calls login").strategy == SearchStrategy::GraphWalk);
        assert!(fallback_plan("architecture overview").strategy == SearchStrategy::Global);
        assert!(fallback_plan("find auth code")
            .queries
            .iter()
            .any(|query| query.contains("authentication")));
    }
}
