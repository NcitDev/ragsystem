use std::{
    collections::BTreeMap,
    net::SocketAddr,
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    },
    time::Duration,
};

use axum::{
    extract::{Path, State},
    response::IntoResponse,
    routing::{get, post, put},
    Json, Router,
};
use http::StatusCode;
use rag_services::{
    ollama::{OllamaClient, OllamaConfig},
    qdrant::{
        CollectionVectorConfig, Distance, EmbeddedQdrantMode, PayloadSchemaType, PayloadValue,
        Point, QdrantClient, QdrantConfig, QdrantFilter,
    },
    RetryPolicy, ServiceError,
};
use serde_json::{json, Value};
use tokio::{net::TcpListener, sync::Mutex};

#[derive(Clone, Default)]
struct MockState {
    calls: Arc<Mutex<Vec<(String, Value)>>>,
    embed_calls: Arc<AtomicUsize>,
    fail_embeds: Arc<AtomicUsize>,
}

fn fast_retry() -> RetryPolicy {
    RetryPolicy {
        max_attempts: 3,
        budget: Duration::from_secs(2),
        initial_backoff: Duration::from_millis(1),
        max_backoff: Duration::from_millis(2),
    }
}

async fn spawn(router: Router) -> String {
    let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind mock");
    let addr: SocketAddr = listener.local_addr().expect("mock addr");
    tokio::spawn(async move {
        axum::serve(listener, router).await.expect("mock server");
    });
    format!("http://{addr}")
}

async fn tags() -> impl IntoResponse {
    Json(json!({
        "models": [
            {"name": "qwen3-embedding-4b:latest", "size": 42, "digest": "abc123"},
            {"name": "llama3.2:latest"}
        ]
    }))
}

async fn embed(State(state): State<MockState>, Json(body): Json<Value>) -> impl IntoResponse {
    state.embed_calls.fetch_add(1, Ordering::SeqCst);
    state
        .calls
        .lock()
        .await
        .push(("ollama_embed".to_owned(), body.clone()));

    let remaining_failures = state.fail_embeds.load(Ordering::SeqCst);
    if remaining_failures > 0 {
        state.fail_embeds.fetch_sub(1, Ordering::SeqCst);
        return (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"error": "temporary"})),
        );
    }

    let inputs = body["input"].as_array().expect("input array");
    let embeddings = inputs
        .iter()
        .enumerate()
        .map(|(idx, _)| json!([idx as f32, idx as f32 + 0.5]))
        .collect::<Vec<_>>();
    (StatusCode::OK, Json(json!({ "embeddings": embeddings })))
}

#[tokio::test]
async fn ollama_verifies_model_batches_embeddings_retries_and_caches() {
    let state = MockState::default();
    state.fail_embeds.store(1, Ordering::SeqCst);
    let base_url = spawn(
        Router::new()
            .route("/api/tags", get(tags))
            .route("/api/embed", post(embed))
            .with_state(state.clone()),
    )
    .await;
    let client = OllamaClient::new(OllamaConfig {
        base_url,
        model: "Qwen/Qwen3-Embedding-4B".to_owned(),
        dim: 2,
        batch_size: 2,
        retry: fast_retry(),
        ..OllamaConfig::default()
    })
    .expect("client");

    assert!(client.health().await);
    client.verify_model().await.expect("model present");

    let docs = vec!["alpha".to_owned(), "beta".to_owned(), "gamma".to_owned()];
    let vectors = client.embed_documents(&docs).await.expect("embeds");
    assert_eq!(vectors.len(), 3);
    assert_eq!(state.embed_calls.load(Ordering::SeqCst), 3);

    let cached = client.embed_documents(&docs).await.expect("cached embeds");
    assert_eq!(cached, vectors);
    assert_eq!(client.cache_len().await, 3);
    assert_eq!(state.embed_calls.load(Ordering::SeqCst), 3);

    let calls = state.calls.lock().await;
    let first_body = &calls[0].1;
    assert_eq!(first_body["model"], "Qwen/Qwen3-Embedding-4B");
    assert_eq!(first_body["keep_alive"], "30m");
    assert!(first_body["input"][0]
        .as_str()
        .expect("input string")
        .starts_with("Instruct: Retrieve code that is semantically similar"));
}

#[tokio::test]
async fn ollama_model_verification_reports_missing_model() {
    let base_url = spawn(Router::new().route("/api/tags", get(tags))).await;
    let client = OllamaClient::new(OllamaConfig {
        base_url,
        model: "missing-model".to_owned(),
        dim: 2,
        retry: fast_retry(),
        ..OllamaConfig::default()
    })
    .expect("client");

    let err = client.verify_model().await.expect_err("missing model");
    assert!(matches!(err, ServiceError::ModelUnavailable { .. }));
}

async fn qdrant_collections() -> impl IntoResponse {
    Json(json!({"result": {"collections": [{"name": "code_chunks"}]}}))
}

async fn qdrant_collection_info(Path(collection): Path<String>) -> impl IntoResponse {
    if collection == "missing" {
        return (
            StatusCode::NOT_FOUND,
            Json(json!({"status": {"error": "missing"}})),
        );
    }
    (
        StatusCode::OK,
        Json(json!({"result": {
            "status": "green",
            "points_count": 7,
            "vectors_count": 7
        }})),
    )
}

async fn qdrant_record(
    State(state): State<MockState>,
    Path((collection, action)): Path<(String, String)>,
    Json(body): Json<Value>,
) -> impl IntoResponse {
    state
        .calls
        .lock()
        .await
        .push((format!("{collection}:{action}"), body));
    match action.as_str() {
        "search" => {
            Json(json!({"result": [{"id": "p1", "score": 0.91, "payload": {"file_path": "a.py"}}]}))
        }
        "scroll" => Json(
            json!({"result": {"points": [{"id": "p1", "payload": {"name": "A"}}], "next_page_offset": "next"}}),
        ),
        "count" => Json(json!({"result": {"count": 3}})),
        "delete" => Json(json!({"result": {"status": "acknowledged"}})),
        _ => Json(json!({"result": {"status": "acknowledged"}})),
    }
}

async fn qdrant_create_or_upsert(
    State(state): State<MockState>,
    Path(collection): Path<String>,
    Json(body): Json<Value>,
) -> impl IntoResponse {
    state
        .calls
        .lock()
        .await
        .push((format!("{collection}:put"), body));
    Json(json!({"result": {"status": "acknowledged"}}))
}

async fn qdrant_index(
    State(state): State<MockState>,
    Path(collection): Path<String>,
    Json(body): Json<Value>,
) -> impl IntoResponse {
    state
        .calls
        .lock()
        .await
        .push((format!("{collection}:index"), body));
    Json(json!({"result": {"status": "acknowledged"}}))
}

async fn qdrant_drop(Path(_collection): Path<String>) -> impl IntoResponse {
    Json(json!({"result": true}))
}

fn qdrant_router(state: MockState) -> Router {
    Router::new()
        .route("/collections", get(qdrant_collections))
        .route(
            "/collections/{collection}",
            get(qdrant_collection_info)
                .put(qdrant_create_or_upsert)
                .delete(qdrant_drop),
        )
        .route("/collections/{collection}/index", put(qdrant_index))
        .route(
            "/collections/{collection}/points",
            put(qdrant_create_or_upsert),
        )
        .route(
            "/collections/{collection}/points/{action}",
            post(qdrant_record),
        )
        .with_state(state)
}

#[tokio::test]
async fn qdrant_client_covers_collection_search_scroll_upsert_delete_count_and_metadata() {
    let state = MockState::default();
    let base_url = spawn(qdrant_router(state.clone())).await;
    let client = QdrantClient::new(QdrantConfig {
        base_url,
        retry: fast_retry(),
        ..QdrantConfig::default()
    })
    .expect("client");

    assert!(client.health().await);
    assert_eq!(
        client.collections().await.expect("collections"),
        ["code_chunks"]
    );
    client
        .create_collection(
            "code_chunks",
            CollectionVectorConfig {
                size: 2560,
                distance: Distance::Cosine,
            },
        )
        .await
        .expect("create");
    client
        .create_payload_index("code_chunks", "language", PayloadSchemaType::Keyword)
        .await
        .expect("index");

    let mut vectors = BTreeMap::new();
    vectors.insert("dense".to_owned(), vec![0.1, 0.2]);
    let mut payload = BTreeMap::new();
    payload.insert("content".to_owned(), PayloadValue::from("fn main() {}"));
    let points = [Point {
        id: "00000000-0000-0000-0000-000000000001".to_owned(),
        vector: vectors,
        payload,
    }];
    client.upsert("code_chunks", &points).await.expect("upsert");

    let filter = QdrantFilter::from_payload_filters(BTreeMap::from([
        (
            "language".to_owned(),
            PayloadValue::List(vec![
                PayloadValue::from("rust"),
                PayloadValue::from("python"),
            ]),
        ),
        ("line_count".to_owned(), PayloadValue::Integer(10)),
    ]));
    let search = client
        .search("code_chunks", &[0.1, 0.2], 5, Some(&filter))
        .await
        .expect("search");
    assert_eq!(search[0].score, 0.91);
    let scroll = client
        .scroll("code_chunks", 10, Some(&filter), None)
        .await
        .expect("scroll");
    assert_eq!(scroll.next_page_offset, Some(json!("next")));
    assert_eq!(client.count("code_chunks", Some(&filter)).await.unwrap(), 3);
    client
        .delete_by_filter("code_chunks", &filter)
        .await
        .expect("delete");
    let metadata = client
        .collection_metadata("code_chunks")
        .await
        .expect("metadata");
    assert_eq!(metadata.status, "green");
    assert_eq!(metadata.points_count, 7);
    let missing = client
        .collection_metadata("missing")
        .await
        .expect("missing metadata");
    assert_eq!(missing.status, "not_found");
    client
        .drop_collection("code_chunks")
        .await
        .expect("drop collection");

    let calls = state.calls.lock().await;
    let search_body = calls
        .iter()
        .find(|(name, _)| name == "code_chunks:search")
        .map(|(_, body)| body)
        .expect("search call");
    assert_eq!(search_body["vector"]["name"], "dense");
    assert_eq!(search_body["filter"]["must"][0]["match"]["any"][0], "rust");
    assert_eq!(search_body["filter"]["must"][1]["range"]["gte"], 10.0);
}

#[test]
fn embedded_mode_contract_is_managed_local_server_not_python_local_files() {
    let mode = EmbeddedQdrantMode::new(
        "/tmp/rag-qdrant".into(),
        "http://127.0.0.1:6333/".to_owned(),
    )
    .expect("embedded mode");
    assert_eq!(mode.url, "http://127.0.0.1:6333");
    assert!(mode.storage_path.ends_with("rag-qdrant"));
}
