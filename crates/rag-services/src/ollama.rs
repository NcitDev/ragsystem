//! Bounded Ollama embedding client.

use std::{
    collections::{HashMap, VecDeque},
    sync::Arc,
    time::Duration,
};

use serde::{Deserialize, Serialize};
use tokio::sync::RwLock;

use crate::{read_or_status, retry_async, trim_base_url, RetryPolicy, ServiceError};

const SERVICE: &str = "ollama";
const DOCUMENT_INSTRUCTION: &str = "Instruct: Retrieve code that is semantically similar\nQuery: ";
const QUERY_INSTRUCTION: &str =
    "Instruct: Given a code search query, retrieve relevant code snippets\nQuery: ";

/// Default number of query embeddings kept in the process cache.
///
/// At the packaged embedding dimension (2560 f32 = 10.24 KiB per vector) this
/// bounds the cache at roughly 21 MiB of vectors plus the (short) query keys.
const DEFAULT_CACHE_CAPACITY: usize = 2048;

/// Ollama client configuration.
#[derive(Debug, Clone)]
pub struct OllamaConfig {
    /// Base URL such as `http://localhost:11434`.
    pub base_url: String,
    /// Embedding model name.
    pub model: String,
    /// Expected embedding dimension.
    pub dim: usize,
    /// Maximum texts per `/api/embed` request.
    pub batch_size: usize,
    /// Ollama keep-alive value, for example `30m`.
    pub keep_alive: String,
    /// Per-request timeout.
    pub request_timeout: Duration,
    /// Retry settings for embedding requests.
    pub retry: RetryPolicy,
    /// Maximum concurrent sub-batches.
    ///
    /// Defaults to `1` to match Python's sequential batching and avoid
    /// saturating local Ollama on developer machines.
    pub max_concurrency: usize,
    /// Whether to cache embeddings by fully-prefixed input text.
    ///
    /// Only the interactive query path ([`OllamaClient::embed_query`]) and the
    /// generic [`OllamaClient::embed_prefixed`] entry point populate this
    /// cache. Bulk document embedding never does: the indexing write path
    /// already reads and writes a durable SQLite embed cache keyed by content
    /// hash, so retaining every chunk vector in the daemon would only duplicate
    /// that data for the life of the process.
    pub cache_embeddings: bool,
    /// Maximum number of vectors retained by the in-process cache.
    ///
    /// The cache evicts in insertion order once this many entries are live.
    /// `0` disables caching entirely, exactly like `cache_embeddings: false`.
    pub cache_capacity: usize,
}

impl Default for OllamaConfig {
    fn default() -> Self {
        Self {
            base_url: "http://localhost:11434".to_owned(),
            model: "Qwen/Qwen3-Embedding-4B".to_owned(),
            dim: 2560,
            batch_size: 64,
            keep_alive: "30m".to_owned(),
            request_timeout: Duration::from_secs(180),
            retry: RetryPolicy::default(),
            max_concurrency: 1,
            cache_embeddings: true,
            cache_capacity: DEFAULT_CACHE_CAPACITY,
        }
    }
}

/// Ollama tag response model entry.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct OllamaModel {
    /// Model name.
    pub name: String,
    /// Optional model size in bytes.
    #[serde(default)]
    pub size: Option<u64>,
    /// Optional digest.
    #[serde(default)]
    pub digest: Option<String>,
}

#[derive(Debug, Deserialize)]
struct TagsResponse {
    #[serde(default)]
    models: Vec<OllamaModel>,
}

#[derive(Debug, Serialize)]
struct EmbedRequest<'a> {
    model: &'a str,
    input: &'a [String],
    keep_alive: KeepAlive<'a>,
}

/// Ollama accepts `keep_alive` as a duration string ("24h") OR a number of
/// seconds (`-1` = forever, `0` = unload now). The string "-1" is rejected
/// with "missing unit in duration", so numeric values serialize as numbers.
#[derive(Debug)]
struct KeepAlive<'a>(&'a str);

impl serde::Serialize for KeepAlive<'_> {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        match self.0.trim().parse::<i64>() {
            Ok(seconds) => serializer.serialize_i64(seconds),
            Err(_) => serializer.serialize_str(self.0),
        }
    }
}

#[derive(Debug, Deserialize)]
struct EmbedResponse {
    #[serde(default)]
    embeddings: Vec<Vec<f32>>,
}

/// Whether a given embedding call may use the in-process cache.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum CachePolicy {
    /// Read cached vectors and store freshly computed ones (interactive path).
    ReadWrite,
    /// Ignore the cache in both directions (bulk indexing path: the caller's
    /// SQLite embed cache owns durability, so process-lifetime retention of
    /// every chunk vector would be pure memory growth).
    Bypass,
}

#[derive(Debug, Default)]
struct CacheInner {
    entries: HashMap<String, Vec<f32>>,
    /// Keys in insertion order; always exactly the keys of `entries`.
    order: VecDeque<String>,
}

impl CacheInner {
    fn put(&mut self, key: &str, vector: &[f32], capacity: usize) {
        if self
            .entries
            .insert(key.to_owned(), vector.to_vec())
            .is_none()
        {
            self.order.push_back(key.to_owned());
        }
        while self.order.len() > capacity {
            let Some(oldest) = self.order.pop_front() else {
                break;
            };
            self.entries.remove(&oldest);
        }
    }
}

/// Capacity-bounded embedding cache with first-in/first-out eviction.
///
/// FIFO (rather than LRU) keeps the write path to a single `push_back` and the
/// read path lock-free of bookkeeping, which matters because reads are batched
/// under one shared lock. Query embeddings are cheap to recompute, so the
/// bound - not the hit rate - is the property worth guaranteeing.
#[derive(Debug)]
struct BoundedEmbeddingCache {
    capacity: usize,
    inner: RwLock<CacheInner>,
}

impl BoundedEmbeddingCache {
    fn new(capacity: usize) -> Self {
        Self {
            capacity,
            inner: RwLock::new(CacheInner::default()),
        }
    }

    /// A zero capacity means "caching disabled"; no lock is ever taken.
    const fn is_enabled(&self) -> bool {
        self.capacity > 0
    }

    /// Look up every key under one read lock, `None` per miss.
    async fn get_many(&self, keys: &[String]) -> Vec<Option<Vec<f32>>> {
        if !self.is_enabled() {
            return vec![None; keys.len()];
        }
        let inner = self.inner.read().await;
        keys.iter()
            .map(|key| inner.entries.get(key).cloned())
            .collect()
    }

    /// Store every pair under one write lock, evicting oldest first.
    async fn insert_many(&self, keys: &[String], vectors: &[Vec<f32>]) {
        if !self.is_enabled() || keys.is_empty() {
            return;
        }
        let mut inner = self.inner.write().await;
        for (key, vector) in keys.iter().zip(vectors.iter()) {
            inner.put(key, vector, self.capacity);
        }
    }

    async fn entry_count(&self) -> usize {
        if !self.is_enabled() {
            return 0;
        }
        self.inner.read().await.entries.len()
    }

    async fn clear(&self) {
        if !self.is_enabled() {
            return;
        }
        let mut inner = self.inner.write().await;
        inner.entries.clear();
        inner.order.clear();
    }
}

/// Bounded Ollama HTTP client.
#[derive(Clone)]
pub struct OllamaClient {
    config: OllamaConfig,
    client: reqwest::Client,
    cache: Arc<BoundedEmbeddingCache>,
}

impl OllamaClient {
    /// Configured base URL (e.g. `http://localhost:11434`).
    #[must_use]
    pub fn base_url(&self) -> &str {
        &self.config.base_url
    }

    /// Create a client from explicit config.
    pub fn new(mut config: OllamaConfig) -> Result<Self, ServiceError> {
        config.base_url = trim_base_url(&config.base_url, "ollama.base_url")?;
        if config.model.trim().is_empty() {
            return Err(ServiceError::InvalidConfig(
                "ollama model must not be empty".to_owned(),
            ));
        }
        if config.dim == 0 {
            return Err(ServiceError::InvalidConfig(
                "embedding dim must be greater than zero".to_owned(),
            ));
        }
        if config.batch_size == 0 {
            return Err(ServiceError::InvalidConfig(
                "embedding batch_size must be greater than zero".to_owned(),
            ));
        }
        if config.max_concurrency == 0 {
            return Err(ServiceError::InvalidConfig(
                "max_concurrency must be greater than zero".to_owned(),
            ));
        }
        let client = reqwest::Client::builder()
            .timeout(config.request_timeout)
            .build()
            .map_err(|source| ServiceError::Transport {
                service: SERVICE,
                source,
            })?;
        let cache_capacity = if config.cache_embeddings {
            config.cache_capacity
        } else {
            0
        };
        Ok(Self {
            config,
            client,
            cache: Arc::new(BoundedEmbeddingCache::new(cache_capacity)),
        })
    }

    /// Return true when `/api/tags` is reachable and the configured model is present.
    pub async fn health(&self) -> bool {
        self.tags()
            .await
            .is_ok_and(|models| self.model_is_present(&models))
    }

    /// Fetch Ollama model tags.
    pub async fn tags(&self) -> Result<Vec<OllamaModel>, ServiceError> {
        let response = self
            .client
            .get(format!("{}/api/tags", self.config.base_url))
            .send()
            .await
            .map_err(|source| ServiceError::Transport {
                service: SERVICE,
                source,
            })?;
        let tags: TagsResponse = read_or_status(SERVICE, response).await?;
        Ok(tags.models)
    }

    /// Non-streaming `/api/chat` completion (Python parity: temperature +
    /// `num_ctx` options, no thinking). `model` overrides the embedding model
    /// so one client serves planner and generation calls.
    pub async fn chat(
        &self,
        model: &str,
        system: &str,
        user: &str,
        temperature: f64,
        num_ctx: u32,
        timeout: Duration,
    ) -> Result<String, ServiceError> {
        let body = serde_json::json!({
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": false,
            "options": {"temperature": temperature, "num_ctx": num_ctx},
        });
        let response = self
            .client
            .post(format!("{}/api/chat", self.config.base_url))
            .timeout(timeout)
            .json(&body)
            .send()
            .await
            .map_err(|source| ServiceError::Transport {
                service: SERVICE,
                source,
            })?;
        let value: serde_json::Value = read_or_status(SERVICE, response).await?;
        let content = value
            .get("message")
            .and_then(|message| message.get("content"))
            .and_then(serde_json::Value::as_str)
            .unwrap_or_default()
            .trim()
            .to_owned();
        if content.is_empty() {
            return Err(ServiceError::Contract {
                service: SERVICE,
                message: "Ollama chat returned no content".to_owned(),
            });
        }
        Ok(content)
    }

    /// Verify that the configured embedding model is available.
    pub async fn verify_model(&self) -> Result<(), ServiceError> {
        let models = self.tags().await?;
        if self.model_is_present(&models) {
            Ok(())
        } else {
            let available = models
                .iter()
                .map(|model| model.name.as_str())
                .collect::<Vec<_>>()
                .join(", ");
            Err(ServiceError::ModelUnavailable {
                model: self.config.model.clone(),
                available,
            })
        }
    }

    /// Embed documents with Python-compatible document instruction prefixing.
    ///
    /// This is the indexing path and deliberately bypasses the in-process
    /// cache: the indexer consults and writes through to the durable SQLite
    /// embed cache before calling here, so keeping every chunk vector resident
    /// for the lifetime of the daemon would duplicate that store and never
    /// release the memory.
    pub async fn embed_documents(&self, texts: &[String]) -> Result<Vec<Vec<f32>>, ServiceError> {
        let prefixed = texts
            .iter()
            .map(|text| format!("{DOCUMENT_INSTRUCTION}{text}"))
            .collect::<Vec<_>>();
        self.embed_with_policy(&prefixed, CachePolicy::Bypass).await
    }

    /// Embed one search query with Python-compatible query instruction prefixing.
    pub async fn embed_query(&self, text: &str) -> Result<Vec<f32>, ServiceError> {
        let prefixed = format!("{QUERY_INSTRUCTION}{text}");
        let mut embeddings = self.embed_prefixed(&[prefixed]).await?;
        embeddings.pop().ok_or_else(|| ServiceError::Contract {
            service: SERVICE,
            message: "Ollama returned no query embedding".to_owned(),
        })
    }

    /// Embed already-prefixed strings. This is useful for compatibility tests
    /// and cache callers that own prefixing. Cached vectors are reused and
    /// freshly computed ones are stored, subject to `cache_capacity`.
    pub async fn embed_prefixed(&self, texts: &[String]) -> Result<Vec<Vec<f32>>, ServiceError> {
        self.embed_with_policy(texts, CachePolicy::ReadWrite).await
    }

    /// Number of cached embedding vectors.
    pub async fn cache_len(&self) -> usize {
        self.cache.entry_count().await
    }

    /// Clear the in-memory embedding cache.
    pub async fn clear_cache(&self) {
        self.cache.clear().await;
    }

    /// Shared embedding path. Returns one vector per input, in input order.
    async fn embed_with_policy(
        &self,
        texts: &[String],
        policy: CachePolicy,
    ) -> Result<Vec<Vec<f32>>, ServiceError> {
        if texts.is_empty() {
            return Ok(Vec::new());
        }
        let use_cache = policy == CachePolicy::ReadWrite && self.cache.is_enabled();

        let mut output: Vec<Option<Vec<f32>>> = if use_cache {
            self.cache.get_many(texts).await
        } else {
            vec![None; texts.len()]
        };
        let missing_positions = output
            .iter()
            .enumerate()
            .filter_map(|(idx, slot)| slot.is_none().then_some(idx))
            .collect::<Vec<_>>();
        let missing_texts = missing_positions
            .iter()
            .map(|&idx| texts[idx].clone())
            .collect::<Vec<_>>();

        if !missing_texts.is_empty() {
            let embedded = self.embed_missing(&missing_texts).await?;
            if embedded.len() != missing_texts.len() {
                return Err(ServiceError::Contract {
                    service: SERVICE,
                    message: format!(
                        "Ollama returned {} embeddings for {} inputs",
                        embedded.len(),
                        missing_texts.len()
                    ),
                });
            }

            if use_cache {
                self.cache.insert_many(&missing_texts, &embedded).await;
            }
            for (idx, vector) in missing_positions.into_iter().zip(embedded) {
                output[idx] = Some(vector);
            }
        }

        output
            .into_iter()
            .map(|item| {
                item.ok_or_else(|| ServiceError::Contract {
                    service: SERVICE,
                    message: "embedding output slot was not filled".to_owned(),
                })
            })
            .collect()
    }

    fn model_is_present(&self, models: &[OllamaModel]) -> bool {
        let short = self
            .config
            .model
            .rsplit('/')
            .next()
            .unwrap_or(self.config.model.as_str())
            .to_ascii_lowercase();
        models
            .iter()
            .any(|model| model.name.to_ascii_lowercase().contains(&short))
    }

    async fn embed_missing(&self, texts: &[String]) -> Result<Vec<Vec<f32>>, ServiceError> {
        let chunks = texts
            .chunks(self.config.batch_size)
            .map(<[String]>::to_vec)
            .collect::<Vec<_>>();
        let semaphore = Arc::new(tokio::sync::Semaphore::new(self.config.max_concurrency));
        let mut handles = Vec::with_capacity(chunks.len());

        for (idx, batch) in chunks.into_iter().enumerate() {
            let permit =
                semaphore
                    .clone()
                    .acquire_owned()
                    .await
                    .map_err(|_| ServiceError::Contract {
                        service: SERVICE,
                        message: "embedding concurrency limiter closed".to_owned(),
                    })?;
            let client = self.clone();
            handles.push(tokio::spawn(async move {
                let result = client.embed_batch_request(&batch).await;
                drop(permit);
                (idx, result)
            }));
        }

        let mut batches = Vec::with_capacity(handles.len());
        for handle in handles {
            let (idx, result) = handle.await.map_err(|error| ServiceError::Contract {
                service: SERVICE,
                message: format!("embedding task join failed: {error}"),
            })?;
            batches.push((idx, result?));
        }
        batches.sort_by_key(|(idx, _)| *idx);

        let mut output = Vec::new();
        for (_, batch) in batches {
            output.extend(batch);
        }
        Ok(output)
    }

    async fn embed_batch_request(&self, batch: &[String]) -> Result<Vec<Vec<f32>>, ServiceError> {
        retry_async(SERVICE, &self.config.retry, || async {
            let request = EmbedRequest {
                model: &self.config.model,
                input: batch,
                keep_alive: KeepAlive(&self.config.keep_alive),
            };
            let response = self
                .client
                .post(format!("{}/api/embed", self.config.base_url))
                .json(&request)
                .send()
                .await
                .map_err(|source| ServiceError::Transport {
                    service: SERVICE,
                    source,
                })?;
            let body: EmbedResponse = read_or_status(SERVICE, response).await?;
            if body.embeddings.len() != batch.len() {
                return Err(ServiceError::Contract {
                    service: SERVICE,
                    message: format!(
                        "Ollama returned {} embeddings for batch of {}",
                        body.embeddings.len(),
                        batch.len()
                    ),
                });
            }
            for vector in &body.embeddings {
                if vector.len() != self.config.dim {
                    return Err(ServiceError::Contract {
                        service: SERVICE,
                        message: format!(
                            "embedding dim {} != expected {}",
                            vector.len(),
                            self.config.dim
                        ),
                    });
                }
            }
            Ok(body.embeddings)
        })
        .await
    }
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicUsize, Ordering};

    use axum::{extract::State, routing::post, Json, Router};
    use serde_json::{json, Value};
    use tokio::net::TcpListener;

    use super::{
        BoundedEmbeddingCache, OllamaClient, OllamaConfig, DEFAULT_CACHE_CAPACITY,
        QUERY_INSTRUCTION,
    };

    const TEST_DIM: usize = 4;

    /// Deterministic per-text vector so callers can assert result ordering.
    fn mock_vector(text: &str) -> Vec<f32> {
        let seed = f32::from(
            text.bytes()
                .fold(0_u8, |acc, byte| acc.wrapping_mul(31).wrapping_add(byte)),
        );
        vec![seed, seed + 1.0, seed + 2.0, seed + 3.0]
    }

    #[derive(Clone, Default)]
    struct MockState {
        embed_calls: std::sync::Arc<AtomicUsize>,
    }

    async fn embed_handler(State(state): State<MockState>, Json(body): Json<Value>) -> Json<Value> {
        state.embed_calls.fetch_add(1, Ordering::SeqCst);
        let inputs = body["input"].as_array().cloned().unwrap_or_default();
        let embeddings = inputs
            .iter()
            .map(|value| mock_vector(value.as_str().unwrap_or_default()))
            .collect::<Vec<_>>();
        Json(json!({ "embeddings": embeddings }))
    }

    async fn spawn_mock() -> (String, MockState) {
        let state = MockState::default();
        let app = Router::new()
            .route("/api/embed", post(embed_handler))
            .with_state(state.clone());
        let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind mock");
        let addr = listener.local_addr().expect("mock addr");
        tokio::spawn(async move {
            axum::serve(listener, app).await.expect("serve mock");
        });
        (format!("http://{addr}"), state)
    }

    fn test_client(
        base_url: String,
        cache_embeddings: bool,
        cache_capacity: usize,
    ) -> OllamaClient {
        OllamaClient::new(OllamaConfig {
            base_url,
            dim: TEST_DIM,
            batch_size: 2,
            cache_embeddings,
            cache_capacity,
            ..OllamaConfig::default()
        })
        .expect("client")
    }

    #[tokio::test]
    async fn bounded_cache_evicts_oldest_entries_beyond_capacity() {
        let cache = BoundedEmbeddingCache::new(3);
        for index in 0..10_u8 {
            let key = format!("key-{index}");
            cache
                .insert_many(&[key], &[vec![f32::from(index); TEST_DIM]])
                .await;
            assert!(cache.entry_count().await <= 3, "cache exceeded capacity");
        }

        assert_eq!(cache.entry_count().await, 3);
        let keys = (0..10_u8).map(|i| format!("key-{i}")).collect::<Vec<_>>();
        let found = cache.get_many(&keys).await;
        // Only the three most recent insertions survive; the rest were evicted.
        assert!(found[..7].iter().all(Option::is_none));
        assert_eq!(found[7], Some(vec![7.0; TEST_DIM]));
        assert_eq!(found[9], Some(vec![9.0; TEST_DIM]));

        cache.clear().await;
        assert_eq!(cache.entry_count().await, 0);
    }

    #[tokio::test]
    async fn bounded_cache_repeat_insert_does_not_double_count() {
        let cache = BoundedEmbeddingCache::new(2);
        let key = "same".to_owned();
        for _ in 0..5 {
            cache
                .insert_many(std::slice::from_ref(&key), &[vec![1.0; TEST_DIM]])
                .await;
        }
        assert_eq!(cache.entry_count().await, 1);

        // A repeat write must not have consumed eviction slots for other keys.
        cache
            .insert_many(&["other".to_owned()], &[vec![2.0; TEST_DIM]])
            .await;
        let found = cache.get_many(&[key, "other".to_owned()]).await;
        assert!(found.iter().all(Option::is_some));
    }

    #[tokio::test]
    async fn bounded_cache_with_zero_capacity_stores_nothing() {
        let cache = BoundedEmbeddingCache::new(0);
        assert!(!cache.is_enabled());
        cache
            .insert_many(&["key".to_owned()], &[vec![1.0; TEST_DIM]])
            .await;
        assert_eq!(cache.entry_count().await, 0);
        assert_eq!(cache.get_many(&["key".to_owned()]).await, vec![None]);
    }

    #[tokio::test]
    async fn embed_documents_leaves_process_cache_empty() {
        let (base_url, state) = spawn_mock().await;
        let client = test_client(base_url, true, DEFAULT_CACHE_CAPACITY);

        let docs = (0..5_u8)
            .map(|index| format!("doc-{index}"))
            .collect::<Vec<_>>();
        let vectors = client.embed_documents(&docs).await.expect("embeds");

        assert_eq!(vectors.len(), docs.len());
        assert_eq!(client.cache_len().await, 0);

        // A second identical run also caches nothing (SQLite owns durability).
        let repeat = client.embed_documents(&docs).await.expect("embeds again");
        assert_eq!(repeat, vectors);
        assert_eq!(client.cache_len().await, 0);
        assert_eq!(state.embed_calls.load(Ordering::SeqCst), 6);
    }

    #[tokio::test]
    async fn embed_query_caches_and_repeat_is_served_from_cache() {
        let (base_url, state) = spawn_mock().await;
        let client = test_client(base_url, true, DEFAULT_CACHE_CAPACITY);

        let first = client.embed_query("find the parser").await.expect("query");
        assert_eq!(client.cache_len().await, 1);
        assert_eq!(state.embed_calls.load(Ordering::SeqCst), 1);
        assert_eq!(
            first,
            mock_vector(&format!("{QUERY_INSTRUCTION}find the parser"))
        );

        let second = client.embed_query("find the parser").await.expect("query");
        assert_eq!(second, first);
        assert_eq!(client.cache_len().await, 1);
        assert_eq!(
            state.embed_calls.load(Ordering::SeqCst),
            1,
            "repeat query must not hit Ollama"
        );

        client.clear_cache().await;
        assert_eq!(client.cache_len().await, 0);
        client.embed_query("find the parser").await.expect("query");
        assert_eq!(state.embed_calls.load(Ordering::SeqCst), 2);
    }

    #[tokio::test]
    async fn query_cache_stops_growing_at_configured_capacity() {
        let (base_url, _state) = spawn_mock().await;
        let client = test_client(base_url, true, 2);

        for index in 0..8_u8 {
            client
                .embed_query(&format!("query-{index}"))
                .await
                .expect("query");
            assert!(client.cache_len().await <= 2);
        }
        assert_eq!(client.cache_len().await, 2);
    }

    #[tokio::test]
    async fn cache_embeddings_false_disables_the_cache_entirely() {
        let (base_url, state) = spawn_mock().await;
        let client = test_client(base_url, false, DEFAULT_CACHE_CAPACITY);

        client.embed_query("same question").await.expect("query");
        client.embed_query("same question").await.expect("query");

        assert_eq!(client.cache_len().await, 0);
        assert_eq!(state.embed_calls.load(Ordering::SeqCst), 2);
    }

    /// `cache_capacity: 0` and `cache_embeddings: false` are documented as
    /// equivalent; assert it observably rather than trusting the comment.
    #[tokio::test]
    async fn cache_capacity_zero_is_equivalent_to_cache_embeddings_false() {
        let (flag_url, flag_state) = spawn_mock().await;
        let disabled_by_flag = test_client(flag_url, false, DEFAULT_CACHE_CAPACITY);
        let (capacity_url, capacity_state) = spawn_mock().await;
        let disabled_by_capacity = test_client(capacity_url, true, 0);

        let mut results = Vec::new();
        for client in [&disabled_by_flag, &disabled_by_capacity] {
            let first = client.embed_query("same question").await.expect("query");
            let second = client.embed_query("same question").await.expect("query");
            assert_eq!(first, second);
            let prefixed = client
                .embed_prefixed(&["already prefixed".to_owned()])
                .await
                .expect("prefixed");
            // Clearing a disabled cache stays a no-op rather than a panic.
            client.clear_cache().await;
            assert_eq!(client.cache_len().await, 0);
            results.push((first, prefixed));
        }

        assert_eq!(results[0], results[1], "vectors must not differ");
        assert_eq!(
            flag_state.embed_calls.load(Ordering::SeqCst),
            capacity_state.embed_calls.load(Ordering::SeqCst),
            "both disabled forms must issue the same HTTP calls"
        );
        assert_eq!(flag_state.embed_calls.load(Ordering::SeqCst), 3);
    }

    #[tokio::test]
    async fn embed_prefixed_preserves_input_order_across_batches_and_cache_hits() {
        let (base_url, _state) = spawn_mock().await;
        let client = test_client(base_url, true, DEFAULT_CACHE_CAPACITY);

        let warm = vec!["text-1".to_owned(), "text-4".to_owned()];
        client.embed_prefixed(&warm).await.expect("warm cache");

        let texts = (0..6_u8)
            .map(|index| format!("text-{index}"))
            .collect::<Vec<_>>();
        let vectors = client.embed_prefixed(&texts).await.expect("embeds");

        assert_eq!(vectors.len(), texts.len());
        for (text, vector) in texts.iter().zip(vectors.iter()) {
            assert_eq!(vector, &mock_vector(text), "output order must match input");
        }
        assert_eq!(client.cache_len().await, texts.len());
    }
}
