//! Contract tests for the `/index` write path (`rag-server/src/indexing.rs`).
//!
//! `mod indexing` is private, so every case drives the real HTTP surface
//! (`POST /index`) against in-process Ollama and Qdrant mocks. The Qdrant mock
//! keeps an actual point store and honours delete-by-filter, so the CLAUDE.md
//! "Indexing invariants" are asserted against *stored state* (which points
//! survived, which collection ops ran, what `state.json` kept) rather than
//! against request shapes alone — a wipe of the wrong chunks is exactly the
//! class of bug these tests exist to catch.

use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};

use axum::body::{to_bytes, Body};
use axum::extract::{Path as UrlPath, State};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post, put};
use axum::{Json, Router};
use http::{header, Request, StatusCode};
use rag_config::{EmbeddingSettings, LlmSettings, QdrantSettings, RagPaths, Settings};
use rag_server::{router_with_state, RetrievalBackend, ServerState};
use rag_storage::RepoRegistry;
use serde_json::{json, Value};
use tower::ServiceExt;

/// Small enough to keep mock payloads readable; the real value is 2560.
const EMBED_DIM: u16 = 4;
const COLLECTION: &str = "repo_fixture";

const PY_ALPHA: &str = r#"
def alpha(value):
    """Alpha."""
    return value + 1


def beta(value):
    return value * 2
"#;

/// Same symbols as [`PY_ALPHA`], shifted down by a header block so every chunk
/// gets new `start:end` lines — and therefore a new `chunk_id`.
const PY_ALPHA_SHIFTED: &str = r#"
# shifted
# shifted
# shifted


def alpha(value):
    """Alpha, revised."""
    return value + 2


def beta(value):
    return value * 3
"#;

const RS_LIB: &str = r"
pub fn gamma(value: i32) -> i32 {
    value + 1
}

pub struct Delta {
    pub count: i32,
}
";

// ---------------------------------------------------------------------------
// Qdrant mock: a real (in-memory) point store, not just a call recorder.
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
struct Op {
    kind: &'static str,
    collection: String,
    detail: Value,
}

#[derive(Default)]
struct QdrantStore {
    /// collection -> point id -> payload
    collections: BTreeMap<String, BTreeMap<String, Value>>,
    ops: Vec<Op>,
    /// Upserts whose serialized body contains this needle fail with a
    /// non-retryable 400, simulating one bad batch.
    upsert_failure: Option<String>,
}

#[derive(Clone, Default)]
struct MockQdrant {
    inner: Arc<Mutex<QdrantStore>>,
}

impl MockQdrant {
    fn store(&self) -> MutexGuard<'_, QdrantStore> {
        self.inner.lock().expect("qdrant mock lock")
    }

    fn set_upsert_failure(&self, needle: Option<&str>) {
        self.store().upsert_failure = needle.map(str::to_owned);
    }

    fn has_collection(&self, collection: &str) -> bool {
        self.store().collections.contains_key(collection)
    }

    fn payloads(&self, collection: &str) -> Vec<Value> {
        self.store()
            .collections
            .get(collection)
            .map(|points| points.values().cloned().collect())
            .unwrap_or_default()
    }

    fn ids(&self, collection: &str) -> BTreeSet<String> {
        self.store()
            .collections
            .get(collection)
            .map(|points| points.keys().cloned().collect())
            .unwrap_or_default()
    }

    fn ids_for_file(&self, collection: &str, file_path: &str) -> BTreeSet<String> {
        self.store()
            .collections
            .get(collection)
            .map(|points| {
                points
                    .iter()
                    .filter(|(_, payload)| payload["file_path"] == json!(file_path))
                    .map(|(id, _)| id.clone())
                    .collect()
            })
            .unwrap_or_default()
    }

    fn stored_files(&self, collection: &str) -> BTreeSet<String> {
        self.payloads(collection)
            .iter()
            .filter_map(|payload| payload["file_path"].as_str().map(str::to_owned))
            .collect()
    }

    fn op_count(&self) -> usize {
        self.store().ops.len()
    }

    fn ops_since(&self, mark: usize) -> Vec<Op> {
        self.store().ops[mark..].to_vec()
    }

    /// Every `file_path` an exact-match delete filter has ever targeted.
    fn deleted_files(&self) -> Vec<String> {
        self.store()
            .ops
            .iter()
            .filter(|op| op.kind == "delete")
            .filter_map(|op| {
                op.detail["filter"]["must"][0]["match"]["value"]
                    .as_str()
                    .filter(|_| op.detail["filter"]["must"][0]["key"] == json!("file_path"))
                    .map(str::to_owned)
            })
            .collect()
    }
}

/// Qdrant `must` filter evaluation: exact match and match-any, the two forms
/// `indexing.rs` builds.
fn filter_matches(payload: &Value, filter: &Value) -> bool {
    let Some(must) = filter["must"].as_array() else {
        return true;
    };
    must.iter().all(|condition| {
        let key = condition["key"].as_str().unwrap_or_default();
        let actual = payload.get(key);
        if let Some(expected) = condition["match"].get("value") {
            return actual == Some(expected);
        }
        if let Some(any) = condition["match"]["any"].as_array() {
            return actual.is_some_and(|value| any.contains(value));
        }
        false
    })
}

async fn qdrant_list_collections(State(mock): State<MockQdrant>) -> Json<Value> {
    let names: Vec<Value> = mock
        .store()
        .collections
        .keys()
        .map(|name| json!({ "name": name }))
        .collect();
    Json(json!({ "result": { "collections": names } }))
}

async fn qdrant_create_collection(
    State(mock): State<MockQdrant>,
    UrlPath(collection): UrlPath<String>,
    Json(body): Json<Value>,
) -> Json<Value> {
    let mut store = mock.store();
    store.collections.entry(collection.clone()).or_default();
    store.ops.push(Op {
        kind: "create",
        collection,
        detail: body,
    });
    Json(json!({ "result": true }))
}

async fn qdrant_drop_collection(
    State(mock): State<MockQdrant>,
    UrlPath(collection): UrlPath<String>,
) -> Json<Value> {
    let mut store = mock.store();
    store.collections.remove(&collection);
    store.ops.push(Op {
        kind: "drop",
        collection,
        detail: Value::Null,
    });
    Json(json!({ "result": true }))
}

async fn qdrant_payload_index(
    State(mock): State<MockQdrant>,
    UrlPath(collection): UrlPath<String>,
    Json(body): Json<Value>,
) -> Json<Value> {
    mock.store().ops.push(Op {
        kind: "payload_index",
        collection,
        detail: body,
    });
    Json(json!({ "result": true }))
}

async fn qdrant_upsert(
    State(mock): State<MockQdrant>,
    UrlPath(collection): UrlPath<String>,
    Json(body): Json<Value>,
) -> Response {
    let mut store = mock.store();
    if let Some(needle) = store.upsert_failure.clone() {
        if body.to_string().contains(&needle) {
            store.ops.push(Op {
                kind: "upsert_rejected",
                collection,
                detail: json!(needle),
            });
            // 400 is a client error: `retry_async` does not retry it, so the
            // failing batch fails once and the run moves on.
            return (
                StatusCode::BAD_REQUEST,
                Json(json!({"status": {"error": "wrong input: vector dimension mismatch"}})),
            )
                .into_response();
        }
    }
    let points = body["points"].as_array().cloned().unwrap_or_default();
    let mut ids = Vec::new();
    let mut files = BTreeSet::new();
    {
        let Some(stored) = store.collections.get_mut(&collection) else {
            return (
                StatusCode::NOT_FOUND,
                Json(json!({"status": {"error": "collection not found"}})),
            )
                .into_response();
        };
        for point in points {
            let id = point["id"].as_str().unwrap_or_default().to_owned();
            if let Some(file) = point["payload"]["file_path"].as_str() {
                files.insert(file.to_owned());
            }
            stored.insert(id.clone(), point["payload"].clone());
            ids.push(id);
        }
    }
    store.ops.push(Op {
        kind: "upsert",
        collection,
        detail: json!({"ids": ids, "file_paths": files}),
    });
    Json(json!({ "result": { "status": "acknowledged" } })).into_response()
}

async fn qdrant_points_action(
    State(mock): State<MockQdrant>,
    UrlPath((collection, action)): UrlPath<(String, String)>,
    Json(body): Json<Value>,
) -> Json<Value> {
    let mut store = mock.store();
    match action.as_str() {
        "count" => {
            let count = store.collections.get(&collection).map_or(0, BTreeMap::len);
            Json(json!({ "result": { "count": count } }))
        }
        "delete" => {
            let filter = body["filter"].clone();
            let mut removed: Vec<String> = Vec::new();
            if let Some(points) = store.collections.get_mut(&collection) {
                points.retain(|id, payload| {
                    let doomed = filter_matches(payload, &filter);
                    if doomed {
                        removed.push(id.clone());
                    }
                    !doomed
                });
            }
            store.ops.push(Op {
                kind: "delete",
                collection,
                detail: json!({"filter": filter, "removed": removed}),
            });
            Json(json!({ "result": { "status": "acknowledged" } }))
        }
        "scroll" => {
            let points: Vec<Value> = store
                .collections
                .get(&collection)
                .map(|points| {
                    points
                        .iter()
                        .map(|(id, payload)| json!({"id": id, "payload": payload}))
                        .collect()
                })
                .unwrap_or_default();
            Json(json!({ "result": { "points": points, "next_page_offset": null } }))
        }
        _ => Json(json!({ "result": [] })),
    }
}

fn qdrant_router(mock: MockQdrant) -> Router {
    Router::new()
        .route("/collections", get(qdrant_list_collections))
        .route(
            "/collections/{collection}",
            put(qdrant_create_collection).delete(qdrant_drop_collection),
        )
        .route("/collections/{collection}/index", put(qdrant_payload_index))
        .route("/collections/{collection}/points", put(qdrant_upsert))
        .route(
            "/collections/{collection}/points/{action}",
            post(qdrant_points_action),
        )
        .with_state(mock)
}

// ---------------------------------------------------------------------------
// Ollama mock, with an optional gate that parks the first embedding call so a
// concurrent request can be issued while an index run is provably in flight.
// ---------------------------------------------------------------------------

struct Gate {
    entered: tokio::sync::mpsc::UnboundedSender<()>,
    release: tokio::sync::Notify,
    tripped: AtomicBool,
}

fn new_gate() -> (Arc<Gate>, tokio::sync::mpsc::UnboundedReceiver<()>) {
    let (entered, receiver) = tokio::sync::mpsc::unbounded_channel();
    (
        Arc::new(Gate {
            entered,
            release: tokio::sync::Notify::new(),
            tripped: AtomicBool::new(false),
        }),
        receiver,
    )
}

#[derive(Clone)]
struct MockOllama {
    embed_calls: Arc<AtomicUsize>,
    gate: Option<Arc<Gate>>,
}

fn mock_vector(text: &str) -> Vec<f32> {
    let seed = f32::from(
        text.bytes()
            .fold(0_u8, |acc, byte| acc.wrapping_mul(31).wrapping_add(byte)),
    );
    (0..EMBED_DIM).map(|i| seed + f32::from(i)).collect()
}

async fn ollama_tags() -> Json<Value> {
    Json(json!({"models": [{"name": "mock-embed:latest"}]}))
}

async fn ollama_embed(State(mock): State<MockOllama>, Json(body): Json<Value>) -> Json<Value> {
    mock.embed_calls.fetch_add(1, Ordering::SeqCst);
    if let Some(gate) = &mock.gate {
        if !gate.tripped.swap(true, Ordering::SeqCst) {
            let _ = gate.entered.send(());
            gate.release.notified().await;
        }
    }
    let inputs = body["input"].as_array().cloned().unwrap_or_default();
    let embeddings: Vec<Value> = inputs
        .iter()
        .map(|value| json!(mock_vector(value.as_str().unwrap_or_default())))
        .collect();
    Json(json!({ "embeddings": embeddings }))
}

async fn spawn(router: Router) -> String {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind mock");
    let addr = listener.local_addr().expect("mock addr");
    tokio::spawn(async move {
        axum::serve(listener, router).await.expect("serve mock");
    });
    format!("http://{addr}")
}

// ---------------------------------------------------------------------------
// Harness
// ---------------------------------------------------------------------------

struct Harness {
    _root: tempfile::TempDir,
    home: PathBuf,
    repo: PathBuf,
    qdrant: MockQdrant,
    embed_calls: Arc<AtomicUsize>,
    app: Router,
}

impl Harness {
    async fn new() -> Self {
        Self::build(None).await
    }

    async fn build(gate: Option<Arc<Gate>>) -> Self {
        let root = tempfile::tempdir().expect("tempdir");
        let home = root.path().join("rag-home");
        let repo = root.path().join("repo");
        std::fs::create_dir_all(&home).expect("create rag home");
        std::fs::create_dir_all(&repo).expect("create repo");

        let qdrant = MockQdrant::default();
        let qdrant_url = spawn(qdrant_router(qdrant.clone())).await;
        let embed_calls = Arc::new(AtomicUsize::new(0));
        let ollama_url = spawn(
            Router::new()
                .route("/api/tags", get(ollama_tags))
                .route("/api/embed", post(ollama_embed))
                .with_state(MockOllama {
                    embed_calls: Arc::clone(&embed_calls),
                    gate,
                }),
        )
        .await;

        let settings = Settings {
            embeddings: EmbeddingSettings {
                model: "mock-embed".to_owned(),
                dim: EMBED_DIM,
                batch_size: 8,
                ..EmbeddingSettings::default()
            },
            qdrant: QdrantSettings {
                url: qdrant_url,
                code_collection: COLLECTION.to_owned(),
                ..QdrantSettings::default()
            },
            llm: LlmSettings {
                ollama_url,
                ..LlmSettings::default()
            },
            ..Settings::default()
        };
        let backend = RetrievalBackend::from_settings(&settings).expect("retrieval backend");
        let app = router_with_state(
            ServerState::new(None)
                .with_rag_home(&home)
                .with_retrieval(Arc::new(backend)),
        );

        Self {
            _root: root,
            home,
            repo,
            qdrant,
            embed_calls,
            app,
        }
    }

    fn paths(&self) -> RagPaths {
        RagPaths::from_home(&self.home)
    }

    fn write(&self, rel: &str, contents: &str) {
        let path = self.repo.join(rel);
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).expect("create parent");
        }
        std::fs::write(path, contents).expect("write repo file");
    }

    fn remove(&self, rel: &str) {
        std::fs::remove_file(self.repo.join(rel)).expect("remove repo file");
    }

    fn index_body(&self, extra: Value) -> Value {
        let mut body = json!({
            "repo_path": self.repo.to_string_lossy(),
            "collection": COLLECTION,
        });
        for (key, value) in extra.as_object().expect("object body") {
            body[key.as_str()] = value.clone();
        }
        body
    }

    async fn index(&self, extra: Value) -> (StatusCode, Value) {
        post_index(self.app.clone(), self.index_body(extra)).await
    }

    /// The run must succeed *and* report no partial errors.
    async fn index_ok(&self, extra: Value) -> Value {
        let (status, value) = self.index(extra).await;
        assert_eq!(status, StatusCode::OK, "index failed: {value}");
        assert_eq!(value["errors"], json!([]), "index reported errors: {value}");
        value
    }

    fn state(&self) -> rag_storage::IndexState {
        rag_storage::IndexState::load(&self.paths(), &self.repo).expect("state.json")
    }

    /// Distinct `file_path` values mirrored into the SQLite code index.
    fn sqlite_files(&self, collection: &str) -> BTreeSet<String> {
        rag_storage::RagDatabase::open(&self.paths())
            .expect("rag.db")
            .code_chunks(collection, 10_000)
            .expect("code chunks")
            .into_iter()
            .map(|chunk| chunk.file_path)
            .collect()
    }
}

async fn post_index(app: Router, body: Value) -> (StatusCode, Value) {
    post_endpoint(app, "/index", body).await
}

async fn post_endpoint(app: Router, uri: &str, body: Value) -> (StatusCode, Value) {
    let response = app
        .oneshot(
            Request::builder()
                .method("POST")
                .uri(uri)
                .header(header::HOST, "localhost:7891")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(body.to_string()))
                .expect("request"),
        )
        .await
        .expect("response");
    let status = response.status();
    let bytes = to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("body");
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or(Value::Null),
    )
}

/// `uuid5(NAMESPACE_DNS, chunk_id)` over the chunks the indexer would produce
/// for `contents`, recomputed independently of the write path.
fn expected_point_ids(paths: &RagPaths, rel_path: &str, contents: &str) -> BTreeSet<String> {
    let settings = rag_config::load_settings(paths).expect("settings");
    rag_index::chunk_code(
        contents,
        rel_path,
        rag_index::chunker::detect_language(rel_path),
        settings.index.max_chunk_chars as usize,
    )
    .iter()
    .map(|chunk| {
        uuid::Uuid::new_v5(&uuid::Uuid::NAMESPACE_DNS, chunk.chunk_id().as_bytes()).to_string()
    })
    .collect()
}

fn git(repo: &Path, args: &[&str]) -> String {
    let output = std::process::Command::new("git")
        .arg("-C")
        .arg(repo)
        .args(args)
        .output()
        .expect("run git");
    assert!(
        output.status.success(),
        "git {args:?} failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8_lossy(&output.stdout).trim().to_owned()
}

// ---------------------------------------------------------------------------
// CLI request-shape regressions.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn index_docs_embeds_into_qdrant_and_sqlite() {
    let harness = Harness::new().await;
    harness.write(
        "guide.md",
        "# Context packs\n\nOnly approved immutable revisions may enter a context pack.\n",
    );

    let (status, value) = post_endpoint(
        harness.app.clone(),
        "/index/docs",
        json!({
            "docs_path": harness.repo.to_string_lossy(),
            "collection": "doc_fixture",
            "full": true,
        }),
    )
    .await;

    assert_eq!(status, StatusCode::OK, "document index failed: {value}");
    assert_eq!(value["files_processed"], 1);
    assert!(value["chunks_indexed"].as_u64().unwrap_or(0) > 0);
    assert!(harness.qdrant.has_collection("doc_fixture"));
    assert_eq!(
        harness.qdrant.stored_files("doc_fixture"),
        BTreeSet::from(["guide.md".to_owned()])
    );
    assert!(harness.embed_calls.load(Ordering::SeqCst) > 0);
    assert_eq!(
        harness.sqlite_files("doc_fixture"),
        BTreeSet::from(["guide.md".to_owned()])
    );
}

#[tokio::test]
async fn empty_language_list_indexes_all_supported_files() {
    let harness = Harness::new().await;
    harness.write("app.py", PY_ALPHA);
    harness.write("lib.rs", RS_LIB);

    let indexed = harness.index_ok(json!({"languages": []})).await;
    assert_eq!(indexed["files_processed"], 2);
    assert_eq!(
        harness.qdrant.stored_files(COLLECTION),
        BTreeSet::from(["app.py".to_owned(), "lib.rs".to_owned()])
    );
}

#[tokio::test]
async fn repo_name_registers_the_indexed_repository() {
    let harness = Harness::new().await;
    harness.write("app.py", PY_ALPHA);

    harness.index_ok(json!({"repo_name": "fixture"})).await;
    let registered = RepoRegistry::open(&harness.paths())
        .expect("registry")
        .get("fixture")
        .expect("get repo")
        .expect("registered repo");
    assert_eq!(registered.collection, COLLECTION);
    assert_eq!(
        registered.path,
        harness
            .repo
            .canonicalize()
            .expect("canonical repo")
            .to_string_lossy()
    );
    assert!(registered.chunks_count > 0);
}

// ---------------------------------------------------------------------------
// Invariant 1: a language-filtered run must not touch other languages.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn language_filtered_run_preserves_other_languages_everywhere() {
    let harness = Harness::new().await;
    harness.write("app.py", PY_ALPHA);
    harness.write("lib.rs", RS_LIB);

    harness.index_ok(json!({})).await;
    let rust_ids = harness.qdrant.ids_for_file(COLLECTION, "lib.rs");
    assert!(!rust_ids.is_empty(), "rust file produced no chunks");
    let rust_hash = harness.state().file_hashes["lib.rs"].clone();

    // Only python is in scope; `lib.rs` is absent from the fresh scan and must
    // NOT therefore be classified as deleted.
    harness.write("app.py", PY_ALPHA_SHIFTED);
    let second = harness.index_ok(json!({"languages": ["python"]})).await;

    assert_eq!(second["files_processed"], 1, "only app.py was in scope");
    assert_eq!(
        second["files_deleted"], 0,
        "an out-of-scope file was treated as deleted"
    );
    assert_eq!(
        harness.qdrant.ids_for_file(COLLECTION, "lib.rs"),
        rust_ids,
        "rust chunks were disturbed by a python-only run"
    );
    assert!(
        !harness
            .qdrant
            .deleted_files()
            .contains(&"lib.rs".to_owned()),
        "a delete filter targeted the out-of-scope file"
    );
    assert!(
        harness.sqlite_files(COLLECTION).contains("lib.rs"),
        "rust chunks vanished from the SQLite code index"
    );
    // The out-of-scope hash must survive into the new state.json, otherwise the
    // next full run re-indexes (and the run after that re-deletes) every rust
    // file for no reason.
    assert_eq!(
        harness.state().file_hashes.get("lib.rs"),
        Some(&rust_hash),
        "state.json dropped the out-of-scope file hash"
    );
}

// ---------------------------------------------------------------------------
// Invariant 2: `--full` semantics.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn full_run_with_language_filter_clears_only_that_language() {
    let harness = Harness::new().await;
    harness.write("app.py", PY_ALPHA);
    harness.write("stale.py", PY_ALPHA);
    harness.write("lib.rs", RS_LIB);
    harness.index_ok(json!({})).await;
    let rust_ids = harness.qdrant.ids_for_file(COLLECTION, "lib.rs");

    // `--full` empties the prior hashes, so `stale.py` is NOT in `diff.deleted`:
    // only the language-scoped reset can remove its chunks.
    harness.remove("stale.py");
    let mark = harness.qdrant.op_count();
    let full = harness
        .index_ok(json!({"full": true, "languages": ["python"]}))
        .await;
    assert_eq!(full["files_deleted"], 0, "diff must not report deletions");

    let ops = harness.qdrant.ops_since(mark);
    assert!(
        !ops.iter().any(|op| op.kind == "drop"),
        "a language-filtered full run must not drop the collection"
    );
    let language_reset = ops
        .iter()
        .find(|op| {
            op.kind == "delete" && op.detail["filter"]["must"][0]["key"] == json!("language")
        })
        .expect("language-scoped delete-by-filter");
    assert_eq!(
        language_reset.detail["filter"]["must"][0]["match"]["any"],
        json!(["python"])
    );

    assert!(
        harness
            .qdrant
            .ids_for_file(COLLECTION, "stale.py")
            .is_empty(),
        "stale python chunks survived the language-scoped reset"
    );
    assert_eq!(
        harness.qdrant.ids_for_file(COLLECTION, "lib.rs"),
        rust_ids,
        "the rust chunks were cleared by a python-only full run"
    );
    let sqlite = harness.sqlite_files(COLLECTION);
    assert!(
        !sqlite.contains("stale.py"),
        "SQLite kept stale python rows"
    );
    assert!(sqlite.contains("lib.rs"), "SQLite lost the rust rows");
    assert!(harness.qdrant.stored_files(COLLECTION).contains("app.py"));
}

#[tokio::test]
async fn full_run_without_language_filter_drops_the_whole_collection() {
    let harness = Harness::new().await;
    harness.write("app.py", PY_ALPHA);
    harness.write("lib.rs", RS_LIB);
    harness.index_ok(json!({})).await;

    // Same trick: with `full` the removed file is not part of the diff, so only
    // the collection drop + code-index reset can remove it.
    harness.remove("lib.rs");
    let mark = harness.qdrant.op_count();
    let full = harness.index_ok(json!({"full": true})).await;
    assert_eq!(full["files_deleted"], 0);

    let ops = harness.qdrant.ops_since(mark);
    let drop_at = ops
        .iter()
        .position(|op| op.kind == "drop" && op.collection == COLLECTION)
        .expect("collection drop");
    let create_at = ops
        .iter()
        .position(|op| op.kind == "create")
        .expect("collection recreate");
    assert!(
        drop_at < create_at,
        "collection must be recreated after drop"
    );
    assert!(
        harness.qdrant.has_collection(COLLECTION),
        "collection missing after a full run"
    );
    assert_eq!(
        harness.qdrant.stored_files(COLLECTION),
        BTreeSet::from(["app.py".to_owned()]),
        "a full run must leave exactly the on-disk files indexed"
    );
    assert_eq!(
        harness.sqlite_files(COLLECTION),
        BTreeSet::from(["app.py".to_owned()]),
        "the SQLite code index was not reset by the full run"
    );
}

// ---------------------------------------------------------------------------
// Invariant 3: changed files must not leave stale chunks.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn changed_file_deletes_its_old_chunks_before_reupserting() {
    let harness = Harness::new().await;
    harness.write("app.py", PY_ALPHA);
    harness.index_ok(json!({})).await;
    let before = harness.qdrant.ids_for_file(COLLECTION, "app.py");
    let after_expected = expected_point_ids(&harness.paths(), "app.py", PY_ALPHA_SHIFTED);
    assert!(!before.is_empty());
    assert!(
        before.is_disjoint(&after_expected),
        "fixture no longer moves chunk boundaries, so the test proves nothing"
    );

    harness.write("app.py", PY_ALPHA_SHIFTED);
    let mark = harness.qdrant.op_count();
    let second = harness.index_ok(json!({})).await;
    assert_eq!(second["files_processed"], 1);

    let ops = harness.qdrant.ops_since(mark);
    let delete_at = ops
        .iter()
        .position(|op| {
            op.kind == "delete" && op.detail["filter"]["must"][0]["match"]["value"] == "app.py"
        })
        .expect("stale delete for the changed file");
    let upsert_at = ops
        .iter()
        .position(|op| op.kind == "upsert")
        .expect("re-upsert of the changed file");
    assert!(
        delete_at < upsert_at,
        "stale chunks must be deleted before the new ones land"
    );

    let stored = harness.qdrant.ids_for_file(COLLECTION, "app.py");
    assert_eq!(
        stored, after_expected,
        "stored chunk ids are not the new ones"
    );
    assert!(
        stored.is_disjoint(&before),
        "stale chunks from the previous revision are still indexed"
    );
}

// ---------------------------------------------------------------------------
// Invariant 4: a failed batch only forfeits its own hashes.
// ---------------------------------------------------------------------------

/// `FILES_PER_FLUSH` is 16, so 17 files means two batches: the second holds
/// only `f16.py` and is the one the mock rejects.
#[tokio::test]
async fn failed_batch_forfeits_only_its_own_hashes_and_the_run_continues() {
    let harness = Harness::new().await;
    for index in 0..17 {
        harness.write(
            &format!("f{index:02}.py"),
            &format!("def symbol_{index}(value):\n    return value + {index}\n"),
        );
    }
    harness.qdrant.set_upsert_failure(Some("f16.py"));

    let (status, first) = harness.index(json!({})).await;
    assert_eq!(
        status,
        StatusCode::OK,
        "a batch failure must not fail the run"
    );
    assert_eq!(
        first["files_processed"], 16,
        "healthy batch must still land"
    );
    let errors = first["errors"].as_array().expect("errors array");
    assert_eq!(errors.len(), 1, "unexpected errors: {errors:?}");
    assert!(
        errors[0]
            .as_str()
            .expect("error string")
            .starts_with("flush failed (1 files)"),
        "unexpected error text: {}",
        errors[0]
    );

    let hashes = harness.state().file_hashes;
    assert_eq!(hashes.len(), 16, "state.json must not promote failed files");
    assert!(
        !hashes.contains_key("f16.py"),
        "the failed file's hash was promoted, so it will never reprocess"
    );
    assert!(hashes.contains_key("f15.py"));
    assert!(harness.qdrant.ids_for_file(COLLECTION, "f16.py").is_empty());

    // Next run: exactly the forfeited file is reprocessed.
    harness.qdrant.set_upsert_failure(None);
    let second = harness.index_ok(json!({})).await;
    assert_eq!(second["files_processed"], 1);
    assert_eq!(second["files_skipped"], 16);
    assert!(!harness.qdrant.ids_for_file(COLLECTION, "f16.py").is_empty());
    assert_eq!(harness.state().file_hashes.len(), 17);
}

// ---------------------------------------------------------------------------
// Invariant 5: deleted files drop out of Qdrant and SQLite.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn deleted_file_drops_its_chunks_from_qdrant_and_the_code_index() {
    let harness = Harness::new().await;
    harness.write("app.py", PY_ALPHA);
    harness.write("gone.py", PY_ALPHA);
    harness.index_ok(json!({})).await;
    assert!(harness.sqlite_files(COLLECTION).contains("gone.py"));

    harness.remove("gone.py");
    let mark = harness.qdrant.op_count();
    let second = harness.index_ok(json!({})).await;

    assert_eq!(second["files_deleted"], 1);
    assert!(
        harness
            .qdrant
            .ops_since(mark)
            .iter()
            .any(|op| op.kind == "delete"
                && op.detail["filter"]["must"][0]["match"]["value"] == "gone.py"),
        "no delete-by-file_path was issued for the removed file"
    );
    assert!(harness
        .qdrant
        .ids_for_file(COLLECTION, "gone.py")
        .is_empty());
    assert!(!harness.sqlite_files(COLLECTION).contains("gone.py"));
    assert!(!harness.state().file_hashes.contains_key("gone.py"));
    // The surviving file is untouched.
    assert!(!harness.qdrant.ids_for_file(COLLECTION, "app.py").is_empty());
}

// ---------------------------------------------------------------------------
// Invariant 6: deterministic chunk ids / idempotent upserts.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn point_ids_are_uuid5_of_chunk_ids_and_reindexing_is_idempotent() {
    let harness = Harness::new().await;
    harness.write("app.py", PY_ALPHA);
    let expected = expected_point_ids(&harness.paths(), "app.py", PY_ALPHA);
    assert!(!expected.is_empty());

    let first = harness.index_ok(json!({})).await;
    assert_eq!(
        harness.qdrant.ids(COLLECTION),
        expected,
        "point ids are not uuid5(NAMESPACE_DNS, chunk_id)"
    );
    let chunks_indexed = first["chunks_indexed"].as_u64().expect("chunks_indexed");
    assert_eq!(chunks_indexed as usize, expected.len());

    // Unchanged content: nothing is re-processed and nothing is written.
    let embed_calls = harness.embed_calls.load(Ordering::SeqCst);
    let mark = harness.qdrant.op_count();
    let second = harness.index_ok(json!({})).await;
    assert_eq!(second["files_processed"], 0);
    assert_eq!(second["files_skipped"], 1);
    assert_eq!(second["chunks_indexed"], 0);
    assert!(
        !harness
            .qdrant
            .ops_since(mark)
            .iter()
            .any(|op| op.kind == "upsert" || op.kind == "delete"),
        "an unchanged repository must not write to Qdrant"
    );
    assert_eq!(harness.embed_calls.load(Ordering::SeqCst), embed_calls);

    // A forced re-run reproduces exactly the same ids (idempotent upsert).
    let third = harness.index_ok(json!({"full": true})).await;
    assert_eq!(third["files_processed"], 1);
    assert_eq!(harness.qdrant.ids(COLLECTION), expected);
}

// ---------------------------------------------------------------------------
// Invariant 7: the per-repo run lock.
// ---------------------------------------------------------------------------

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn concurrent_run_for_the_same_repo_is_rejected() {
    let (gate, mut entered) = new_gate();
    let harness = Harness::build(Some(Arc::clone(&gate))).await;
    harness.write("app.py", PY_ALPHA);

    // The first run parks inside the embedding call, i.e. holding the lock.
    let app = harness.app.clone();
    let body = harness.index_body(json!({}));
    let first = tokio::spawn(async move { post_index(app, body).await });
    entered.recv().await.expect("first run reached embedding");

    let (status, blocked) = harness.index(json!({})).await;
    // A busy repository is a conflict, not an outage: the daemon is healthy and
    // the request is well-formed, so it gets a 409 that names the conflict.
    assert_eq!(
        status,
        StatusCode::CONFLICT,
        "a concurrent run for the same repo must be rejected: {blocked}"
    );
    assert!(
        blocked["error"]
            .as_str()
            .expect("error envelope")
            .contains("another index run is already in progress"),
        "the conflict was not named: {blocked}"
    );
    assert!(
        harness.qdrant.ids(COLLECTION).is_empty(),
        "the rejected run must not have written anything"
    );

    gate.release.notify_one();
    let (status, completed) = first.await.expect("join first run");
    assert_eq!(status, StatusCode::OK, "gated run failed: {completed}");
    assert!(completed["chunks_indexed"].as_u64().expect("count") > 0);

    // The guard is released on completion, so the repo is indexable again.
    let after = harness.index_ok(json!({"full": true})).await;
    assert_eq!(after["files_processed"], 1);
}

// ---------------------------------------------------------------------------
// Invariant 8: `git_last_modified` payload stamping.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn git_tracked_files_carry_git_last_modified_and_untracked_ones_do_not() {
    let harness = Harness::new().await;
    harness.write("app.py", PY_ALPHA);
    git(&harness.repo, &["init", "-q"]);
    git(&harness.repo, &["add", "app.py"]);
    git(
        &harness.repo,
        &[
            "-c",
            "user.email=rag@example.com",
            "-c",
            "user.name=RAG Test",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-q",
            "-m",
            "initial",
        ],
    );
    let committed_at = git(&harness.repo, &["log", "-1", "--format=%aI"]);
    // Untracked: present on disk, absent from `git log`.
    harness.write("scratch.py", PY_ALPHA_SHIFTED);

    harness.index_ok(json!({})).await;

    for payload in harness.qdrant.payloads(COLLECTION) {
        let file = payload["file_path"].as_str().expect("file_path");
        match file {
            "app.py" => assert_eq!(
                payload["git_last_modified"],
                json!(committed_at),
                "tracked file lost its recency stamp"
            ),
            "scratch.py" => assert!(
                payload.get("git_last_modified").is_none(),
                "untracked file must not be dated"
            ),
            other => panic!("unexpected indexed file {other}"),
        }
    }
    assert!(
        harness.state().last_commit.len() >= 7,
        "HEAD was not recorded"
    );
}

#[tokio::test]
async fn indexing_outside_git_succeeds_without_recency_data() {
    let harness = Harness::new().await;
    harness.write("app.py", PY_ALPHA);

    let response = harness.index_ok(json!({})).await;
    assert!(response["chunks_indexed"].as_u64().expect("count") > 0);

    let payloads = harness.qdrant.payloads(COLLECTION);
    assert!(!payloads.is_empty());
    assert!(
        payloads
            .iter()
            .all(|payload| payload.get("git_last_modified").is_none()),
        "a non-git directory must not produce recency stamps"
    );
    assert_eq!(harness.state().last_commit, "");
}

// ---------------------------------------------------------------------------
// Request contract
// ---------------------------------------------------------------------------

#[tokio::test]
async fn missing_repo_path_is_a_422_not_a_backend_error() {
    let harness = Harness::new().await;
    let (status, value) = post_index(harness.app.clone(), json!({"collection": COLLECTION})).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(value["detail"][0]["loc"], json!(["body", "repo_path"]));
    assert_eq!(value["detail"][0]["type"], "value_error.missing");
}
