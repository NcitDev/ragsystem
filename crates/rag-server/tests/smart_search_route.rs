//! Route-level coverage for `POST /smart-search`, the dense smart-search
//! pipeline in `rag-server/src/retrieval.rs`.
//!
//! Everything the pipeline reaches for is neutralised so the assertions pin
//! *route* behavior rather than the environment:
//!
//! * Ollama and Qdrant are in-process `axum` mocks, so every dense hit the
//!   route sees is one this file wrote.
//! * `retrieval_agent.provider` is deliberately neither `agy` nor `codex`, so
//!   `infer_symbols` returns empty and symbol inference degrades to the
//!   deterministic `rag_agent::grounded_symbols` path — the one most callers
//!   actually hit.
//! * The registered repo points at a path that does not exist, so the
//!   `ast-index` CLI bridge short-circuits (`resolve_symbols` / `related_files`
//!   both bail on a missing root) and the tests are identical on a machine with
//!   and without that CLI installed. The one test that needs the structural
//!   stage builds a real repo and is gated on `ast_index::is_available()`.

use std::collections::BTreeMap;
use std::net::SocketAddr;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use axum::body::{to_bytes, Body};
use axum::extract::{Path as AxumPath, State};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post, put};
use axum::{Json, Router};
use http::{header, Request, StatusCode};
use rag_config::{
    EmbeddingSettings, LlmSettings, QdrantSettings, RagPaths, RetrievalAgentSettings, Settings,
};
use rag_server::{RetrievalBackend, ServerState};
use rag_storage::{RepoInfo, RepoRegistry};
use serde_json::{json, Value};
use tokio::net::TcpListener;
use tower::ServiceExt;

/// Small embedding width so the mock can return literal vectors; the Ollama
/// client rejects any width other than `embeddings.dim`. Keep in step with the
/// vector `ollama_embed` returns.
const EMBED_DIM: u16 = 4;

// ---------------------------------------------------------------------------
// Mock external services
// ---------------------------------------------------------------------------

#[derive(Clone, Default)]
struct MockOllama {
    /// A non-5xx failure: retries would only slow the test down, and the route
    /// contract is the same for every embedding failure.
    fail: Arc<AtomicBool>,
}

#[derive(Clone, Default)]
struct MockQdrant {
    /// Collection name -> scored points returned by `points/search`.
    hits: Arc<Mutex<BTreeMap<String, Vec<Value>>>>,
    /// When set, every `points/*` call answers 404 (the shape a request against
    /// a collection that was never created takes).
    fail: Arc<AtomicBool>,
}

impl MockQdrant {
    fn set(&self, collection: &str, points: Vec<Value>) {
        self.hits
            .lock()
            .expect("mock qdrant lock")
            .insert(collection.to_owned(), points);
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

async fn ollama_tags() -> impl IntoResponse {
    Json(json!({"models": [{"name": "mock-embed"}]}))
}

async fn ollama_embed(State(state): State<MockOllama>, Json(body): Json<Value>) -> Response {
    if state.fail.load(Ordering::SeqCst) {
        return (
            StatusCode::BAD_REQUEST,
            Json(json!({"error": "embedder unavailable"})),
        )
            .into_response();
    }
    let inputs = body["input"].as_array().cloned().unwrap_or_default();
    let embeddings: Vec<Value> = inputs.iter().map(|_| json!([0.1, 0.2, 0.3, 0.4])).collect();
    Json(json!({ "embeddings": embeddings })).into_response()
}

async fn qdrant_collections() -> impl IntoResponse {
    Json(json!({"result": {"collections": []}}))
}

async fn qdrant_ack() -> impl IntoResponse {
    Json(json!({"result": {"status": "acknowledged"}}))
}

async fn qdrant_points(
    State(state): State<MockQdrant>,
    AxumPath((collection, action)): AxumPath<(String, String)>,
    Json(_body): Json<Value>,
) -> Response {
    if state.fail.load(Ordering::SeqCst) {
        return (
            StatusCode::NOT_FOUND,
            Json(json!({"status": {"error": "collection not found"}})),
        )
            .into_response();
    }
    match action.as_str() {
        "search" => {
            let points = state
                .hits
                .lock()
                .expect("mock qdrant lock")
                .get(&collection)
                .cloned()
                .unwrap_or_default();
            Json(json!({ "result": points })).into_response()
        }
        "count" => Json(json!({"result": {"count": 0}})).into_response(),
        "scroll" => {
            Json(json!({"result": {"points": [], "next_page_offset": null}})).into_response()
        }
        _ => Json(json!({"result": {"status": "acknowledged"}})).into_response(),
    }
}

// ---------------------------------------------------------------------------
// Harness
// ---------------------------------------------------------------------------

struct Harness {
    /// Held for the lifetime of the test: dropping it deletes the RAG home.
    _home: tempfile::TempDir,
    home: std::path::PathBuf,
    qdrant: MockQdrant,
    ollama: MockOllama,
    app: Router,
    /// Qdrant collection the registered repo maps to.
    collection: String,
    /// `<collection>_vocab`, the concept-anchor collection.
    vocab_collection: String,
}

impl Harness {
    /// Register `repo_name` at `repo_path` and wire the dense backend at mocks.
    async fn build(repo_name: &str, repo_path: &std::path::Path) -> Self {
        let home = tempfile::tempdir().expect("tempdir");
        let paths = RagPaths::from_home(home.path());
        std::fs::create_dir_all(&paths.home).expect("create rag home");

        let collection = format!("repo_{repo_name}");
        RepoRegistry::open_writable(&paths)
            .expect("open registry")
            .upsert(&RepoInfo {
                name: repo_name.to_owned(),
                path: repo_path.to_string_lossy().into_owned(),
                collection: collection.clone(),
                last_indexed: None,
                chunks_count: 0,
            })
            .expect("register repo");

        let ollama = MockOllama::default();
        let ollama_url = spawn(
            Router::new()
                .route("/api/tags", get(ollama_tags))
                .route("/api/embed", post(ollama_embed))
                .with_state(ollama.clone()),
        )
        .await;

        let qdrant = MockQdrant::default();
        let qdrant_url = spawn(
            Router::new()
                .route("/collections", get(qdrant_collections))
                .route("/collections/{collection}", put(qdrant_ack))
                .route("/collections/{collection}/index", put(qdrant_ack))
                .route("/collections/{collection}/points", put(qdrant_ack))
                .route(
                    "/collections/{collection}/points/{action}",
                    post(qdrant_points),
                )
                .with_state(qdrant.clone()),
        )
        .await;

        let settings = Settings {
            embeddings: EmbeddingSettings {
                model: "mock-embed".to_owned(),
                dim: EMBED_DIM,
                batch_size: 8,
                ..EmbeddingSettings::default()
            },
            llm: LlmSettings {
                ollama_url,
                ..LlmSettings::default()
            },
            qdrant: QdrantSettings {
                url: qdrant_url,
                ..QdrantSettings::default()
            },
            // Anything but a CLI planner: `infer_symbols` returns empty without
            // ever shelling out, and the route falls back to the deterministic
            // `grounded_symbols` heuristic.
            retrieval_agent: RetrievalAgentSettings {
                provider: "gemini".to_owned(),
                model: "mock-planner".to_owned(),
                ..RetrievalAgentSettings::default()
            },
            ..Settings::default()
        };

        let backend = RetrievalBackend::from_settings(&settings).expect("build backend");
        let app = rag_server::router_with_state(
            ServerState::new(None)
                .with_rag_home(home.path())
                .with_retrieval(Arc::new(backend)),
        );

        Self {
            home: home.path().to_path_buf(),
            _home: home,
            qdrant,
            ollama,
            app,
            vocab_collection: format!("{collection}_vocab"),
            collection,
        }
    }

    /// The common case: a repo whose on-disk path does not exist, so the
    /// `ast-index` stages degrade to empty without spawning anything.
    async fn detached() -> Self {
        let scratch = tempfile::tempdir().expect("tempdir");
        let missing = scratch.path().join("never-created");
        // Dropping the temp dir removes the whole tree, so the registered repo
        // path is guaranteed not to exist for the life of the test.
        drop(scratch);
        Self::build("sample", &missing).await
    }

    fn set_semantic(&self, points: Vec<Value>) {
        self.qdrant.set(&self.collection, points);
    }

    fn set_vocab(&self, points: Vec<Value>) {
        self.qdrant.set(&self.vocab_collection, points);
    }

    async fn post(&self, body: &Value) -> (StatusCode, Value) {
        let response = self
            .app
            .clone()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/smart-search")
                    .header(header::HOST, "localhost:7891")
                    .header(header::CONTENT_TYPE, "application/json")
                    .body(Body::from(body.to_string()))
                    .expect("build request"),
            )
            .await
            .expect("route response");
        let status = response.status();
        let bytes = to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("read body");
        (status, serde_json::from_slice(&bytes).expect("json body"))
    }

    /// Post and assert a 200 — the never-500 contract holds on every path here.
    async fn ok(&self, body: &Value) -> Value {
        let (status, value) = self.post(body).await;
        assert_eq!(status, StatusCode::OK, "unexpected status for {body}");
        value
    }
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

fn code_point(id: &str, score: f64, file_path: &str, name: &str, code: &str) -> Value {
    json!({
        "id": id,
        "score": score,
        "payload": {
            "file_path": file_path,
            "name": name,
            "parent_name": "",
            "chunk_type": "class",
            "language": "kotlin",
            "start_line": 1,
            "end_line": 9,
            "content": code,
        },
    })
}

fn vocab_point(id: &str, score: f64, file_path: &str, name: &str, summary: &str) -> Value {
    json!({
        "id": id,
        "score": score,
        "payload": {
            "file_path": file_path,
            "name": name,
            "summary": summary,
            "content": summary,
        },
    })
}

fn strings(value: &Value, key: &str) -> Vec<String> {
    value
        .as_array()
        .into_iter()
        .flatten()
        .map(|item| {
            item.get(key)
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_owned()
        })
        .collect()
}

fn string_list(value: &Value) -> Vec<String> {
    value
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .map(str::to_owned)
        .collect()
}

// ---------------------------------------------------------------------------
// 1. Candidate pagination
// ---------------------------------------------------------------------------

/// `candidate_offset`/`candidate_limit` page the pool, and `candidates_total`
/// reports the size of the WHOLE pool so a client can drive pagination from the
/// first response. An offset past the end is an empty page, not an error.
#[tokio::test]
async fn candidate_pagination_slices_the_pool_and_always_reports_the_full_total() {
    let harness = Harness::detached().await;
    harness.set_vocab(vec![
        vocab_point("v0", 0.9, "vocab/a.kt", "AlphaVocab", "alpha"),
        vocab_point("v1", 0.8, "vocab/b.kt", "BetaVocab", "beta"),
        vocab_point("v2", 0.7, "vocab/c.kt", "GammaVocab", "gamma"),
    ]);
    harness.set_semantic(
        (0..6)
            .map(|index| {
                code_point(
                    &format!("s{index}"),
                    0.9 - f64::from(index) / 100.0,
                    &format!("code/s{index}.kt"),
                    &format!("Chunk{index}"),
                    "body",
                )
            })
            .collect(),
    );

    let pool: Vec<String> = ["vocab/a.kt", "vocab/b.kt", "vocab/c.kt"]
        .iter()
        .map(|path| (*path).to_owned())
        .chain((0..6).map(|index| format!("code/s{index}.kt")))
        .collect();
    assert_eq!(pool.len(), 9);

    // (paging fields, expected page)
    let cases: Vec<(Value, Vec<String>)> = vec![
        (json!({}), pool.clone()),
        (
            json!({"candidate_offset": 0, "candidate_limit": 4}),
            pool[..4].to_vec(),
        ),
        (
            json!({"candidate_offset": 3, "candidate_limit": 3}),
            pool[3..6].to_vec(),
        ),
        (
            json!({"candidate_offset": 7, "candidate_limit": 5}),
            pool[7..].to_vec(),
        ),
        (
            json!({"candidate_offset": 9, "candidate_limit": 5}),
            Vec::new(),
        ),
        (
            json!({"candidate_offset": 500, "candidate_limit": 5}),
            Vec::new(),
        ),
        (
            json!({"candidate_offset": 0, "candidate_limit": 0}),
            Vec::new(),
        ),
    ];

    for (paging, expected) in cases {
        let mut body = json!({"question": "how is caching wired", "repo": "sample"});
        for (key, value) in paging.as_object().expect("paging object") {
            body[key] = value.clone();
        }
        let response = harness.ok(&body).await;
        assert_eq!(
            strings(&response["candidates"], "file_path"),
            expected,
            "wrong page for {paging}"
        );
        assert_eq!(
            response["candidates_total"], 9,
            "candidates_total must be the pool size, not the page size ({paging})"
        );
        assert_eq!(response["retrieval_mode"], "dense");
    }
}

// ---------------------------------------------------------------------------
// 2. Candidate pool composition and dedup
// ---------------------------------------------------------------------------

/// The pool is path-deduped and ordered definitions -> vocab -> usages ->
/// related -> semantic. A file reachable from two sources appears once,
/// attributed to the FIRST source that produced it — here `vocab` over
/// `semantic`, keeping the vocab summary rather than the semantic name.
#[tokio::test]
async fn candidate_pool_dedupes_by_path_and_keeps_the_first_source() {
    let harness = Harness::detached().await;
    harness.set_vocab(vec![
        vocab_point(
            "v0",
            0.9,
            "src/shared.kt",
            "SharedVocab",
            "the shared module",
        ),
        vocab_point("v1", 0.8, "src/vocab_only.kt", "OnlyVocab", "vocab only"),
    ]);
    harness.set_semantic(vec![
        code_point("s0", 0.9, "src/shared.kt", "SharedSemantic", "shared body"),
        code_point("s1", 0.8, "src/code_only.kt", "OnlySemantic", "code body"),
    ]);

    let response = harness
        .ok(&json!({"question": "how is caching wired", "repo": "sample"}))
        .await;
    let candidates = &response["candidates"];

    assert_eq!(
        strings(candidates, "file_path"),
        ["src/shared.kt", "src/vocab_only.kt", "src/code_only.kt"],
        "vocab entries must precede semantic ones and paths must not repeat"
    );
    assert_eq!(
        strings(candidates, "source"),
        ["vocab", "vocab", "semantic"]
    );
    assert_eq!(
        candidates[0]["name"], "SharedVocab",
        "the duplicate path keeps the first source's metadata"
    );
    assert_eq!(candidates[0]["summary"], "the shared module");
    // The semantic section itself is unaffected by the pool dedup.
    assert_eq!(
        strings(&response["semantic"], "file_path"),
        ["src/shared.kt", "src/code_only.kt"]
    );
}

// ---------------------------------------------------------------------------
// 3. Lazy mode
// ---------------------------------------------------------------------------

/// `include_bodies=false` blanks `code` on definitions/usages/semantic. The
/// candidate pool is token-light links only, so it must come back byte-identical
/// either way — that is the whole point of the two-phase (links, then bodies)
/// client flow.
#[tokio::test]
async fn include_bodies_false_blanks_section_code_but_leaves_candidates_alone() {
    let harness = Harness::detached().await;
    harness.set_vocab(vec![vocab_point(
        "v0",
        0.9,
        "src/vocab.kt",
        "VocabName",
        "summary",
    )]);
    harness.set_semantic(vec![
        code_point("s0", 0.9, "src/a.kt", "Alpha", "fun alpha() = 1"),
        code_point("s1", 0.8, "src/b.kt", "Betaa", "fun beta() = 2"),
    ]);

    let question = json!({"question": "how is caching wired", "repo": "sample"});
    let with_bodies = harness.ok(&question).await;
    let mut lazy_body = question.clone();
    lazy_body["include_bodies"] = json!(false);
    let without_bodies = harness.ok(&lazy_body).await;

    assert_eq!(
        strings(&with_bodies["semantic"], "code"),
        ["fun alpha() = 1", "fun beta() = 2"]
    );
    assert_eq!(strings(&without_bodies["semantic"], "code"), ["", ""]);
    // Only `code` is dropped: the citation metadata a client pages on stays.
    assert_eq!(
        strings(&without_bodies["semantic"], "file_path"),
        ["src/a.kt", "src/b.kt"]
    );
    assert_eq!(
        with_bodies["candidates"], without_bodies["candidates"],
        "candidates carry no bodies and must not change"
    );
    assert_eq!(
        with_bodies["candidates_total"],
        without_bodies["candidates_total"]
    );
}

// ---------------------------------------------------------------------------
// 4/5. Section flags
// ---------------------------------------------------------------------------

/// Each `include_*` flag suppresses its own section — and, because the
/// candidate pool is built out of the sections, the matching candidates too.
#[tokio::test]
async fn section_flags_suppress_their_section_and_its_candidates() {
    let harness = Harness::detached().await;
    harness.set_vocab(vec![vocab_point(
        "v0",
        0.9,
        "src/vocab.kt",
        "VocabName",
        "summary",
    )]);
    harness.set_semantic(vec![code_point(
        "s0",
        0.9,
        "src/code.kt",
        "CodeName",
        "body",
    )]);

    // (flags, expected candidate sources, expected candidates_total)
    let cases: Vec<(Value, Vec<&str>, u64)> = vec![
        (json!({}), vec!["vocab", "semantic"], 2),
        (json!({"include_vocab": false}), vec!["semantic"], 1),
        (json!({"include_semantic": false}), vec!["vocab"], 1),
        (
            json!({"include_vocab": false, "include_semantic": false}),
            vec![],
            0,
        ),
        // `related` is empty here (no resolvable repo on disk), so the flag can
        // only be pinned as coherent; the real suppression is asserted in the
        // ast-index-gated test below.
        (
            json!({"include_related": false}),
            vec!["vocab", "semantic"],
            2,
        ),
    ];

    for (flags, expected_sources, expected_total) in cases {
        let mut body = json!({"question": "how is caching wired", "repo": "sample"});
        for (key, value) in flags.as_object().expect("flag object") {
            body[key] = value.clone();
        }
        let response = harness.ok(&body).await;
        assert_eq!(
            strings(&response["candidates"], "source"),
            expected_sources,
            "wrong candidate sources for {flags}"
        );
        assert_eq!(
            response["candidates_total"], expected_total,
            "wrong total for {flags}"
        );

        let vocab_on = flags.get("include_vocab") != Some(&json!(false));
        assert_eq!(
            response["vocab_files"]
                .as_array()
                .expect("vocab_files")
                .len(),
            usize::from(vocab_on),
            "include_vocab not honoured for {flags}"
        );
        assert_eq!(
            string_list(&response["vocab_anchors"]).len(),
            usize::from(vocab_on),
            "vocab anchors must follow include_vocab for {flags}"
        );

        let semantic_on = flags.get("include_semantic") != Some(&json!(false));
        assert_eq!(
            response["semantic"].as_array().expect("semantic").len(),
            usize::from(semantic_on),
            "include_semantic not honoured for {flags}"
        );
        assert_eq!(response["related"], json!([]));
    }
}

// ---------------------------------------------------------------------------
// 6. Grounding
// ---------------------------------------------------------------------------

/// Inferred symbols survive only if the SQLite mirror knows them; PascalCase
/// names (>= 4 chars, no dot) from the top-10 semantic hits are added on top —
/// and those are NOT checked against the index, which is the asymmetry that
/// makes the two lists diverge.
#[tokio::test]
async fn grounding_drops_unknown_inferred_symbols_and_adds_top_ten_pascal_case() {
    let harness = Harness::detached().await;
    seed_code_index(&harness.home, &harness.collection, "RealSymbol");

    // Ten hits fill the grounding window; the eleventh must be out of reach.
    let mut semantic = vec![
        code_point("h0", 0.99, "src/p.kt", "PascalName", "body"),
        code_point("h1", 0.98, "src/l.kt", "lowercase", "body"),
        code_point("h2", 0.97, "src/s.kt", "Abc", "body"),
        code_point("h3", 0.96, "src/d.kt", "Dotted.Name", "body"),
    ];
    for index in 4..10 {
        semantic.push(code_point(
            &format!("h{index}"),
            0.9 - f64::from(index) / 100.0,
            &format!("src/f{index}.kt"),
            "filler",
            "body",
        ));
    }
    semantic.push(code_point("h10", 0.1, "src/late.kt", "TooLateName", "body"));
    harness.set_semantic(semantic);

    let response = harness
        .ok(&json!({
            "question": "how does RealSymbol talk to GhostSymbol",
            "repo": "sample",
        }))
        .await;

    let inferred = string_list(&response["inferred_symbols"]);
    let grounded = string_list(&response["grounded_symbols"]);
    assert_eq!(
        inferred,
        ["RealSymbol", "GhostSymbol"],
        "the deterministic fallback must still infer both identifiers"
    );
    assert!(
        grounded.contains(&"RealSymbol".to_owned()),
        "an inferred symbol present in the index must survive: {grounded:?}"
    );
    assert!(
        !grounded.contains(&"GhostSymbol".to_owned()),
        "an inferred symbol absent from the index must be dropped: {grounded:?}"
    );
    assert!(
        grounded.contains(&"PascalName".to_owned()),
        "PascalCase names from the semantic head must be added: {grounded:?}"
    );
    for rejected in ["lowercase", "Abc", "Dotted.Name", "filler", "TooLateName"] {
        assert!(
            !grounded.contains(&rejected.to_owned()),
            "{rejected} must not be grounded: {grounded:?}"
        );
    }
    assert!(grounded.len() <= 8, "grounded is capped at 8: {grounded:?}");
}

/// Write one row into the SQLite code index the route's `symbol_exists` reads.
fn seed_code_index(home: &std::path::Path, collection: &str, name: &str) {
    let mut index = rag_index::LexicalIndex::open(home.join("rag.db")).expect("open lexical index");
    index
        .upsert_code_chunks(&[rag_index::CodeDocument {
            chunk_id: format!("seed:{name}"),
            collection: collection.to_owned(),
            file_path: "src/real.kt".to_owned(),
            name: name.to_owned(),
            parent_name: String::new(),
            chunk_type: "class".to_owned(),
            language: "kotlin".to_owned(),
            start_line: 1,
            end_line: 4,
            code: format!("class {name} {{}}"),
        }])
        .expect("seed code index");
}

// ---------------------------------------------------------------------------
// 7. Degradation
// ---------------------------------------------------------------------------

/// CLAUDE.md's never-500 contract: an outage in either external service still
/// produces a 200 with a coherent, empty-ish body. Nothing may be missing from
/// the envelope, because clients index into it unconditionally.
#[tokio::test]
async fn external_service_outages_degrade_to_an_empty_answer_not_an_error() {
    for service in ["qdrant", "ollama"] {
        let harness = Harness::detached().await;
        harness.set_vocab(vec![vocab_point(
            "v0",
            0.9,
            "src/vocab.kt",
            "VocabName",
            "summary",
        )]);
        harness.set_semantic(vec![code_point(
            "s0",
            0.9,
            "src/code.kt",
            "CodeName",
            "body",
        )]);
        match service {
            "qdrant" => harness.qdrant.fail.store(true, Ordering::SeqCst),
            _ => harness.ollama.fail.store(true, Ordering::SeqCst),
        }

        let response = harness
            .ok(&json!({"question": "what breaks if CodeName changes", "repo": "sample"}))
            .await;
        for section in [
            "definitions",
            "usages",
            "semantic",
            "related",
            "candidates",
            "vocab_anchors",
            "vocab_files",
        ] {
            assert_eq!(
                response[section],
                json!([]),
                "{section} must degrade to empty when {service} is down"
            );
        }
        assert_eq!(response["candidates_total"], 0);
        assert_eq!(response["question"], "what breaks if CodeName changes");
        assert_eq!(response["repos_searched"], json!(["sample"]));
        assert_eq!(response["retrieval_mode"], "dense");
        assert!(response["latency_ms"].is_number());
        assert!(response["symbol_inference_ms"].is_number());
        // Inference is deterministic and local, so it keeps working.
        assert_eq!(
            string_list(&response["inferred_symbols"]),
            ["CodeName"],
            "{service}: symbol inference must not depend on the services"
        );
    }
}

// ---------------------------------------------------------------------------
// 8. Envelope
// ---------------------------------------------------------------------------

/// The response envelope, including `retrieval_mode: "dense"` — the marker that
/// tells a client this came from the dense pipeline and not the SQLite
/// keyword fallback, which returns the same field names.
#[tokio::test]
async fn response_envelope_is_complete_and_marked_dense() {
    let harness = Harness::detached().await;
    harness.set_semantic(vec![code_point(
        "s0",
        0.9,
        "src/code.kt",
        "CodeName",
        "body",
    )]);

    let response = harness
        .ok(&json!({"question": "how is caching wired", "repo": "sample"}))
        .await;
    for key in [
        "question",
        "inferred_symbols",
        "grounded_symbols",
        "definitions",
        "usages",
        "semantic",
        "related",
        "candidates",
        "candidates_total",
        "repos_searched",
        "vocab_anchors",
        "vocab_files",
        "retrieval_mode",
        "symbol_inference_ms",
        "latency_ms",
    ] {
        assert!(response.get(key).is_some(), "missing {key} in the envelope");
    }
    assert_eq!(response["retrieval_mode"], "dense");

    // The contract 422 that guards this route (repo or repos required).
    let (status, error) = harness.post(&json!({"question": "no repo"})).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(error["detail"][0]["msg"], "Provide repo or repos");
}

// ---------------------------------------------------------------------------
// 9. Structural stage (requires the external `ast-index` CLI)
// ---------------------------------------------------------------------------

/// The stages that need the `ast-index` CLI: exact resolve (definitions), the
/// blast-radius usage bump, and structural expansion (related) — plus the pool
/// ordering across all five sources.
///
/// Skipped when `ast-index` is not installed; every other test in this file is
/// written so it does not care either way.
#[tokio::test]
async fn ast_index_stages_fill_definitions_usages_related_and_order_the_pool() {
    if !rag_retrieval::ast_index::is_available() {
        eprintln!("skipping: the ast-index CLI is not installed");
        return;
    }
    let repo = tempfile::tempdir().expect("repo tempdir");
    let root = repo.path().canonicalize().expect("canonical repo path");
    std::fs::create_dir_all(root.join("src")).expect("create src");
    std::fs::write(
        root.join("src/widget.kt"),
        "package demo\n\ninterface Widget { fun render(): String }\n\n\
         class WidgetFactory : Widget {\n    override fun render(): String = \"widget\"\n\
         \n    fun build(): String = render()\n}\n",
    )
    .expect("write widget.kt");
    std::fs::write(
        root.join("src/consumer.kt"),
        "package demo\n\nclass Consumer {\n    fun run(): String {\n\
         \n        val factory = WidgetFactory()\n        return factory.build()\n    }\n}\n",
    )
    .expect("write consumer.kt");
    let built = std::process::Command::new("ast-index")
        .arg("rebuild")
        .current_dir(&root)
        .output()
        .expect("run ast-index rebuild");
    assert!(
        built.status.success(),
        "ast-index rebuild failed: {built:?}"
    );

    let harness = Harness::build("kt", &root).await;
    harness.set_vocab(vec![vocab_point(
        "v0",
        0.9,
        "src/vocab.kt",
        "VocabName",
        "summary",
    )]);
    // The semantic hit is what grounds `WidgetFactory` (PascalCase from the
    // semantic head), so the resolve stage has something to look up.
    harness.set_semantic(vec![code_point(
        "s0",
        0.9,
        "src/other.kt",
        "WidgetFactory",
        "body",
    )]);

    // A plain question: no usages are requested, so the consumer file can only
    // reach the pool through the structural `related` stage.
    let plain = harness
        .ok(&json!({"question": "describe the WidgetFactory class", "repo": "kt"}))
        .await;
    assert_eq!(
        strings(&plain["definitions"], "file_path"),
        ["src/widget.kt"],
        "exact resolve must find the definition"
    );
    assert_eq!(
        plain["usages"],
        json!([]),
        "a plain question must not request usages"
    );
    assert_eq!(strings(&plain["related"], "file_path"), ["src/consumer.kt"]);
    assert_eq!(
        strings(&plain["candidates"], "source"),
        ["definition", "vocab", "related", "semantic"],
        "pool order is definitions -> vocab -> usages -> related -> semantic"
    );
    assert_eq!(
        strings(&plain["candidates"], "file_path"),
        [
            "src/widget.kt",
            "src/vocab.kt",
            "src/consumer.kt",
            "src/other.kt"
        ]
    );

    // The same repo, a blast-radius phrasing: `usages_limit` auto-bumps to 100
    // and the consumer file now arrives as a usage instead of a related link.
    let blast = harness
        .ok(&json!({"question": "what breaks if I rename WidgetFactory", "repo": "kt"}))
        .await;
    assert_eq!(
        strings(&blast["usages"], "file_path"),
        ["src/consumer.kt"],
        "a blast-radius phrase must auto-request usages"
    );
    assert_eq!(
        strings(&blast["candidates"], "source"),
        ["definition", "vocab", "usage", "semantic"],
        "usages outrank related for the same path"
    );

    // include_related genuinely suppresses the structural stage.
    let no_related = harness
        .ok(&json!({
            "question": "describe the WidgetFactory class",
            "repo": "kt",
            "include_related": false,
        }))
        .await;
    assert_eq!(no_related["related"], json!([]));
    assert_eq!(
        strings(&no_related["candidates"], "source"),
        ["definition", "vocab", "semantic"]
    );

    // Lazy mode strips definition bodies too, not just semantic ones.
    let lazy = harness
        .ok(&json!({
            "question": "what breaks if I rename WidgetFactory",
            "repo": "kt",
            "include_bodies": false,
        }))
        .await;
    assert_eq!(strings(&lazy["definitions"], "code"), [""]);
    assert_eq!(strings(&lazy["usages"], "code"), [""]);
}
