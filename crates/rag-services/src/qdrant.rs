//! Qdrant server-mode HTTP client.

use std::{collections::BTreeMap, path::PathBuf, time::Duration};

use serde::{Deserialize, Serialize};

use crate::{read_or_status, retry_async, trim_base_url, RetryPolicy, ServiceError};

const SERVICE: &str = "qdrant";

/// Rust compatibility strategy for Python's user-facing embedded mode.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EmbeddedQdrantMode {
    /// Storage directory passed to the managed Qdrant server.
    pub storage_path: PathBuf,
    /// Loopback URL for the managed server.
    pub url: String,
}

impl EmbeddedQdrantMode {
    /// Validate the managed-server compatibility contract.
    ///
    /// This deliberately does not read Python qdrant-client local-mode files.
    pub fn new(storage_path: PathBuf, url: impl Into<String>) -> Result<Self, ServiceError> {
        let url = trim_base_url(&url.into(), "qdrant.embedded.url")?;
        Ok(Self { storage_path, url })
    }
}

/// Qdrant client configuration.
#[derive(Debug, Clone)]
pub struct QdrantConfig {
    /// Qdrant server base URL, for example `http://127.0.0.1:6333`.
    pub base_url: String,
    /// Per-request timeout.
    pub request_timeout: Duration,
    /// Retry settings for mutating/search operations.
    pub retry: RetryPolicy,
}

impl Default for QdrantConfig {
    fn default() -> Self {
        Self {
            base_url: "http://127.0.0.1:6333".to_owned(),
            request_timeout: Duration::from_secs(30),
            retry: RetryPolicy::default(),
        }
    }
}

/// Distance metric for dense vectors.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Distance {
    /// Cosine distance.
    #[serde(rename = "Cosine")]
    Cosine,
    /// Euclidean distance.
    #[serde(rename = "Euclid")]
    Euclid,
    /// Dot-product distance.
    #[serde(rename = "Dot")]
    Dot,
}

/// Payload schema type for Qdrant indexes.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum PayloadSchemaType {
    /// Keyword payload index.
    #[serde(rename = "keyword")]
    Keyword,
    /// Integer payload index.
    #[serde(rename = "integer")]
    Integer,
}

/// Vector collection parameters.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CollectionVectorConfig {
    /// Named vector size.
    pub size: usize,
    /// Distance metric.
    pub distance: Distance,
}

/// Client-side representation of supported Qdrant payload values.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum PayloadValue {
    /// String.
    String(String),
    /// Boolean.
    Bool(bool),
    /// Signed integer.
    Integer(i64),
    /// Floating point.
    Float(f64),
    /// List of scalar payload values.
    List(Vec<PayloadValue>),
    /// Arbitrary JSON object.
    Object(BTreeMap<String, PayloadValue>),
    /// Null.
    Null,
}

impl From<&str> for PayloadValue {
    fn from(value: &str) -> Self {
        Self::String(value.to_owned())
    }
}

impl From<String> for PayloadValue {
    fn from(value: String) -> Self {
        Self::String(value)
    }
}

impl From<bool> for PayloadValue {
    fn from(value: bool) -> Self {
        Self::Bool(value)
    }
}

impl From<i64> for PayloadValue {
    fn from(value: i64) -> Self {
        Self::Integer(value)
    }
}

impl From<f64> for PayloadValue {
    fn from(value: f64) -> Self {
        Self::Float(value)
    }
}

/// Supported filter expression matching Python's current field filters.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct QdrantFilter {
    /// Required conditions.
    pub must: Vec<FieldCondition>,
}

impl QdrantFilter {
    /// Empty filter.
    #[must_use]
    pub fn empty() -> Self {
        Self { must: Vec::new() }
    }

    /// Build a Python-compatible filter from field values.
    #[must_use]
    pub fn from_payload_filters(filters: BTreeMap<String, PayloadValue>) -> Self {
        let mut must = Vec::new();
        for (key, value) in filters {
            match value {
                PayloadValue::Integer(value) => {
                    must.push(FieldCondition::range_gte(key, value as f64))
                }
                PayloadValue::Float(value) => must.push(FieldCondition::range_gte(key, value)),
                PayloadValue::List(values) if values.is_empty() => {}
                PayloadValue::List(mut values) if values.len() == 1 => {
                    must.push(FieldCondition::match_value(key, values.remove(0)));
                }
                PayloadValue::List(values) => must.push(FieldCondition::match_any(key, values)),
                value => must.push(FieldCondition::match_value(key, value)),
            }
        }
        Self { must }
    }
}

/// Qdrant field condition.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct FieldCondition {
    /// Payload key.
    pub key: String,
    /// Exact match or any-of match.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub r#match: Option<MatchCondition>,
    /// Range match.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub range: Option<RangeCondition>,
}

impl FieldCondition {
    /// Exact payload match.
    #[must_use]
    pub fn match_value(key: String, value: PayloadValue) -> Self {
        Self {
            key,
            r#match: Some(MatchCondition::Value { value }),
            range: None,
        }
    }

    /// Match any value.
    #[must_use]
    pub fn match_any(key: String, values: Vec<PayloadValue>) -> Self {
        Self {
            key,
            r#match: Some(MatchCondition::Any { any: values }),
            range: None,
        }
    }

    /// Numeric greater-than-or-equal range.
    #[must_use]
    pub fn range_gte(key: String, gte: f64) -> Self {
        Self {
            key,
            r#match: None,
            range: Some(RangeCondition { gte }),
        }
    }
}

/// Qdrant match condition.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(untagged)]
pub enum MatchCondition {
    /// Exact value.
    Value { value: PayloadValue },
    /// Any of values.
    Any { any: Vec<PayloadValue> },
}

/// Qdrant range condition.
#[derive(Debug, Clone, Copy, PartialEq, Serialize)]
pub struct RangeCondition {
    /// Greater than or equal.
    pub gte: f64,
}

/// Point upsert request.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Point {
    /// Qdrant point id.
    pub id: String,
    /// Named vector map, usually containing `dense`.
    pub vector: BTreeMap<String, Vec<f32>>,
    /// Point payload.
    pub payload: BTreeMap<String, PayloadValue>,
}

/// Search result point.
#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct ScoredPoint {
    /// Point id.
    pub id: serde_json::Value,
    /// Point score.
    #[serde(default)]
    pub score: f32,
    /// Payload.
    #[serde(default)]
    pub payload: BTreeMap<String, PayloadValue>,
}

/// Scroll result page.
#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct ScrollPage {
    /// Returned points.
    #[serde(default)]
    pub points: Vec<Record>,
    /// Qdrant next page offset.
    #[serde(default)]
    pub next_page_offset: Option<serde_json::Value>,
}

/// Scroll record.
#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct Record {
    /// Point id.
    pub id: serde_json::Value,
    /// Payload.
    #[serde(default)]
    pub payload: BTreeMap<String, PayloadValue>,
}

/// Collection metadata.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CollectionMetadata {
    /// Collection name.
    pub name: String,
    /// Qdrant status or `not_found`.
    pub status: String,
    /// Point count.
    pub points_count: u64,
    /// Vector count.
    pub vectors_count: u64,
}

#[derive(Debug, Serialize)]
struct CreateCollectionRequest {
    vectors: BTreeMap<String, VectorParams>,
}

#[derive(Debug, Serialize)]
struct VectorParams {
    size: usize,
    distance: Distance,
}

#[derive(Debug, Serialize)]
struct CreatePayloadIndexRequest {
    field_name: String,
    field_schema: PayloadSchemaType,
}

#[derive(Debug, Serialize)]
struct UpsertRequest<'a> {
    points: &'a [Point],
}

#[derive(Debug, Serialize)]
struct SearchRequest<'a> {
    vector: NamedVector<'a>,
    limit: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    filter: Option<&'a QdrantFilter>,
    with_payload: bool,
}

#[derive(Debug, Serialize)]
struct NamedVector<'a> {
    name: &'a str,
    vector: &'a [f32],
}

#[derive(Debug, Serialize)]
struct ScrollRequest<'a> {
    limit: usize,
    with_payload: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    filter: Option<&'a QdrantFilter>,
    #[serde(skip_serializing_if = "Option::is_none")]
    offset: Option<&'a serde_json::Value>,
}

#[derive(Debug, Serialize)]
struct RetrieveRequest<'a> {
    ids: &'a [String],
    with_payload: bool,
}

#[derive(Debug, Serialize)]
struct CountRequest<'a> {
    #[serde(skip_serializing_if = "Option::is_none")]
    filter: Option<&'a QdrantFilter>,
    exact: bool,
}

/// REST `points/delete` body: the filter selector is top-level
/// (`{"filter": …}`), unlike the gRPC `PointsSelector` wrapper.
#[derive(Debug, Serialize)]
struct DeleteRequest<'a> {
    filter: &'a QdrantFilter,
}

#[derive(Debug, Deserialize)]
struct QdrantEnvelope<T> {
    result: T,
}

#[derive(Debug, Deserialize)]
struct CollectionsResult {
    #[serde(default)]
    collections: Vec<CollectionDescription>,
}

#[derive(Debug, Deserialize)]
struct CollectionDescription {
    name: String,
}

#[derive(Debug, Deserialize)]
struct CollectionInfoResult {
    #[serde(default)]
    status: Option<String>,
    #[serde(default)]
    points_count: Option<u64>,
    #[serde(default)]
    vectors_count: Option<u64>,
}

#[derive(Debug, Deserialize)]
struct CountResult {
    count: u64,
}

/// Bounded Qdrant HTTP client.
#[derive(Clone)]
pub struct QdrantClient {
    config: QdrantConfig,
    client: reqwest::Client,
}

impl QdrantClient {
    /// Create a Qdrant server-mode client.
    pub fn new(mut config: QdrantConfig) -> Result<Self, ServiceError> {
        config.base_url = trim_base_url(&config.base_url, "qdrant.base_url")?;
        let client = reqwest::Client::builder()
            .timeout(config.request_timeout)
            .build()
            .map_err(|source| ServiceError::Transport {
                service: SERVICE,
                source,
            })?;
        Ok(Self { config, client })
    }

    /// Lightweight health check.
    pub async fn health(&self) -> bool {
        self.collections().await.is_ok()
    }

    /// List collection names.
    pub async fn collections(&self) -> Result<Vec<String>, ServiceError> {
        let response = self
            .client
            .get(format!("{}/collections", self.config.base_url))
            .send()
            .await
            .map_err(|source| ServiceError::Transport {
                service: SERVICE,
                source,
            })?;
        let envelope: QdrantEnvelope<CollectionsResult> = read_or_status(SERVICE, response).await?;
        Ok(envelope
            .result
            .collections
            .into_iter()
            .map(|collection| collection.name)
            .collect())
    }

    /// Create a named dense-vector collection.
    pub async fn create_collection(
        &self,
        collection: &str,
        dense: CollectionVectorConfig,
    ) -> Result<(), ServiceError> {
        self.validate_collection(collection)?;
        let mut vectors = BTreeMap::new();
        vectors.insert(
            "dense".to_owned(),
            VectorParams {
                size: dense.size,
                distance: dense.distance,
            },
        );
        let body = CreateCollectionRequest { vectors };
        retry_async(SERVICE, &self.config.retry, || async {
            let response = self
                .client
                .put(format!("{}/collections/{collection}", self.config.base_url))
                .json(&body)
                .send()
                .await
                .map_err(|source| ServiceError::Transport {
                    service: SERVICE,
                    source,
                })?;
            read_or_status::<serde_json::Value>(SERVICE, response)
                .await
                .map(|_| ())
        })
        .await
    }

    /// Create one payload index.
    pub async fn create_payload_index(
        &self,
        collection: &str,
        field_name: &str,
        field_schema: PayloadSchemaType,
    ) -> Result<(), ServiceError> {
        self.validate_collection(collection)?;
        let body = CreatePayloadIndexRequest {
            field_name: field_name.to_owned(),
            field_schema,
        };
        retry_async(SERVICE, &self.config.retry, || async {
            let response = self
                .client
                .put(format!(
                    "{}/collections/{collection}/index",
                    self.config.base_url
                ))
                .json(&body)
                .send()
                .await
                .map_err(|source| ServiceError::Transport {
                    service: SERVICE,
                    source,
                })?;
            read_or_status::<serde_json::Value>(SERVICE, response)
                .await
                .map(|_| ())
        })
        .await
    }

    /// Return metadata for a collection, or `not_found` metadata on 404.
    pub async fn collection_metadata(
        &self,
        collection: &str,
    ) -> Result<CollectionMetadata, ServiceError> {
        self.validate_collection(collection)?;
        let response = self
            .client
            .get(format!("{}/collections/{collection}", self.config.base_url))
            .send()
            .await
            .map_err(|source| ServiceError::Transport {
                service: SERVICE,
                source,
            })?;
        if response.status() == http::StatusCode::NOT_FOUND {
            return Ok(CollectionMetadata {
                name: collection.to_owned(),
                status: "not_found".to_owned(),
                points_count: 0,
                vectors_count: 0,
            });
        }
        let envelope: QdrantEnvelope<CollectionInfoResult> =
            read_or_status(SERVICE, response).await?;
        let points_count = envelope.result.points_count.unwrap_or_default();
        Ok(CollectionMetadata {
            name: collection.to_owned(),
            status: envelope
                .result
                .status
                .unwrap_or_else(|| "unknown".to_owned()),
            points_count,
            vectors_count: envelope.result.vectors_count.unwrap_or(points_count),
        })
    }

    /// Upsert points into a collection.
    pub async fn upsert(&self, collection: &str, points: &[Point]) -> Result<(), ServiceError> {
        self.validate_collection(collection)?;
        if points.is_empty() {
            return Ok(());
        }
        let body = UpsertRequest { points };
        retry_async(SERVICE, &self.config.retry, || async {
            let response = self
                .client
                .put(format!(
                    "{}/collections/{collection}/points?wait=true",
                    self.config.base_url
                ))
                .json(&body)
                .send()
                .await
                .map_err(|source| ServiceError::Transport {
                    service: SERVICE,
                    source,
                })?;
            read_or_status::<serde_json::Value>(SERVICE, response)
                .await
                .map(|_| ())
        })
        .await
    }

    /// Dense vector search using Qdrant's named-vector HTTP shape.
    pub async fn search(
        &self,
        collection: &str,
        dense: &[f32],
        top_k: usize,
        filter: Option<&QdrantFilter>,
    ) -> Result<Vec<ScoredPoint>, ServiceError> {
        self.validate_collection(collection)?;
        if dense.is_empty() {
            return Err(ServiceError::InvalidRequest(
                "search vector must not be empty".to_owned(),
            ));
        }
        if top_k == 0 {
            return Ok(Vec::new());
        }
        let body = SearchRequest {
            vector: NamedVector {
                name: "dense",
                vector: dense,
            },
            limit: top_k,
            filter,
            with_payload: true,
        };
        retry_async(SERVICE, &self.config.retry, || async {
            let response = self
                .client
                .post(format!(
                    "{}/collections/{collection}/points/search",
                    self.config.base_url
                ))
                .json(&body)
                .send()
                .await
                .map_err(|source| ServiceError::Transport {
                    service: SERVICE,
                    source,
                })?;
            let envelope: QdrantEnvelope<Vec<ScoredPoint>> =
                read_or_status(SERVICE, response).await?;
            Ok(envelope.result)
        })
        .await
    }

    /// Scroll points with optional filter and page offset.
    pub async fn scroll(
        &self,
        collection: &str,
        limit: usize,
        filter: Option<&QdrantFilter>,
        offset: Option<&serde_json::Value>,
    ) -> Result<ScrollPage, ServiceError> {
        self.validate_collection(collection)?;
        let body = ScrollRequest {
            limit,
            with_payload: true,
            filter,
            offset,
        };
        retry_async(SERVICE, &self.config.retry, || async {
            let response = self
                .client
                .post(format!(
                    "{}/collections/{collection}/points/scroll",
                    self.config.base_url
                ))
                .json(&body)
                .send()
                .await
                .map_err(|source| ServiceError::Transport {
                    service: SERVICE,
                    source,
                })?;
            let envelope: QdrantEnvelope<ScrollPage> = read_or_status(SERVICE, response).await?;
            Ok(envelope.result)
        })
        .await
    }

    /// Fetch payloads for explicit point ids.
    ///
    /// Lexically-promoted search hits are built from the SQLite mirror, which
    /// stores only the structural columns (`file_path`, `name`, lines, …) and
    /// none of the enrichment the ranker scores on. Without a way to hydrate
    /// them, every FTS hit scored 0.0 on recency, patterns and quality while
    /// dense hits carried the full payload — systematically under-ranking
    /// exact-symbol evidence. Point ids are deterministic
    /// (`uuid5(NAMESPACE_DNS, chunk_id)`), so the caller can ask for exactly
    /// the ids it needs in one round trip.
    ///
    /// Missing ids are simply absent from the result; this is not an error.
    pub async fn retrieve(
        &self,
        collection: &str,
        ids: &[String],
    ) -> Result<Vec<Record>, ServiceError> {
        self.validate_collection(collection)?;
        if ids.is_empty() {
            return Ok(Vec::new());
        }
        let body = RetrieveRequest {
            ids,
            with_payload: true,
        };
        retry_async(SERVICE, &self.config.retry, || async {
            let response = self
                .client
                .post(format!(
                    "{}/collections/{collection}/points",
                    self.config.base_url
                ))
                .json(&body)
                .send()
                .await
                .map_err(|source| ServiceError::Transport {
                    service: SERVICE,
                    source,
                })?;
            let envelope: QdrantEnvelope<Vec<Record>> = read_or_status(SERVICE, response).await?;
            Ok(envelope.result)
        })
        .await
    }

    /// Count points in a collection with optional filter.
    pub async fn count(
        &self,
        collection: &str,
        filter: Option<&QdrantFilter>,
    ) -> Result<u64, ServiceError> {
        self.validate_collection(collection)?;
        let body = CountRequest {
            filter,
            exact: true,
        };
        let response = self
            .client
            .post(format!(
                "{}/collections/{collection}/points/count",
                self.config.base_url
            ))
            .json(&body)
            .send()
            .await
            .map_err(|source| ServiceError::Transport {
                service: SERVICE,
                source,
            })?;
        let envelope: QdrantEnvelope<CountResult> = read_or_status(SERVICE, response).await?;
        Ok(envelope.result.count)
    }

    /// Delete points matching a filter.
    pub async fn delete_by_filter(
        &self,
        collection: &str,
        filter: &QdrantFilter,
    ) -> Result<(), ServiceError> {
        self.validate_collection(collection)?;
        let body = DeleteRequest { filter };
        retry_async(SERVICE, &self.config.retry, || async {
            let response = self
                .client
                .post(format!(
                    "{}/collections/{collection}/points/delete?wait=true",
                    self.config.base_url
                ))
                .json(&body)
                .send()
                .await
                .map_err(|source| ServiceError::Transport {
                    service: SERVICE,
                    source,
                })?;
            read_or_status::<serde_json::Value>(SERVICE, response)
                .await
                .map(|_| ())
        })
        .await
    }

    /// Delete a collection. A missing collection is treated as already deleted.
    pub async fn drop_collection(&self, collection: &str) -> Result<(), ServiceError> {
        self.validate_collection(collection)?;
        let response = self
            .client
            .delete(format!("{}/collections/{collection}", self.config.base_url))
            .send()
            .await
            .map_err(|source| ServiceError::Transport {
                service: SERVICE,
                source,
            })?;
        if response.status() == http::StatusCode::NOT_FOUND {
            return Ok(());
        }
        read_or_status::<serde_json::Value>(SERVICE, response)
            .await
            .map(|_| ())
    }

    fn validate_collection(&self, collection: &str) -> Result<(), ServiceError> {
        if collection.trim().is_empty() || collection.contains('/') {
            return Err(ServiceError::InvalidRequest(
                "collection name must be non-empty and must not contain '/'".to_owned(),
            ));
        }
        Ok(())
    }
}
