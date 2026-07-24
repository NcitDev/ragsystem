//! Bounded Ollama embedding client.

use std::{collections::HashMap, sync::Arc, time::Duration};

use serde::{Deserialize, Serialize};
use tokio::sync::RwLock;

use crate::{read_or_status, retry_async, trim_base_url, RetryPolicy, ServiceError};

const SERVICE: &str = "ollama";
const DOCUMENT_INSTRUCTION: &str = "Instruct: Retrieve code that is semantically similar\nQuery: ";
const QUERY_INSTRUCTION: &str =
    "Instruct: Given a code search query, retrieve relevant code snippets\nQuery: ";

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
    pub cache_embeddings: bool,
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

/// Bounded Ollama HTTP client.
#[derive(Clone)]
pub struct OllamaClient {
    config: OllamaConfig,
    client: reqwest::Client,
    cache: Arc<RwLock<HashMap<String, Vec<f32>>>>,
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
        Ok(Self {
            config,
            client,
            cache: Arc::new(RwLock::new(HashMap::new())),
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
    pub async fn embed_documents(&self, texts: &[String]) -> Result<Vec<Vec<f32>>, ServiceError> {
        let prefixed = texts
            .iter()
            .map(|text| format!("{DOCUMENT_INSTRUCTION}{text}"))
            .collect::<Vec<_>>();
        self.embed_prefixed(&prefixed).await
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
    /// and cache callers that own prefixing.
    pub async fn embed_prefixed(&self, texts: &[String]) -> Result<Vec<Vec<f32>>, ServiceError> {
        if texts.is_empty() {
            return Ok(Vec::new());
        }

        let mut output = vec![None; texts.len()];
        let mut missing_positions = Vec::new();
        let mut missing_texts = Vec::new();

        if self.config.cache_embeddings {
            let cache = self.cache.read().await;
            for (idx, text) in texts.iter().enumerate() {
                if let Some(value) = cache.get(text) {
                    output[idx] = Some(value.clone());
                } else {
                    missing_positions.push(idx);
                    missing_texts.push(text.clone());
                }
            }
        } else {
            missing_positions.extend(0..texts.len());
            missing_texts.extend(texts.iter().cloned());
        }

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

            if self.config.cache_embeddings {
                let mut cache = self.cache.write().await;
                for (text, vector) in missing_texts.iter().zip(embedded.iter()) {
                    cache.insert(text.clone(), vector.clone());
                }
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

    /// Number of cached embedding vectors.
    pub async fn cache_len(&self) -> usize {
        self.cache.read().await.len()
    }

    /// Clear the in-memory embedding cache.
    pub async fn clear_cache(&self) {
        self.cache.write().await.clear();
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
