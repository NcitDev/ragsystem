//! Axum HTTP surface for the Rust daemon.

mod indexing;
mod qdrant_boot;
mod retrieval;

use std::{
    collections::{HashMap, VecDeque},
    sync::{Arc, Mutex},
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

pub use retrieval::RetrievalBackend;

use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        Path, Request, State,
    },
    middleware::{self, Next},
    response::{Html, IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use http::{header, HeaderMap, HeaderValue, StatusCode};
use rag_config::{RagPaths, ServerConfig};
use rag_contracts::{ErrorResponse, HealthResponse};
use rag_storage::{CodeChunk, RagDatabase, RepoInfo, RepoRegistry};
use serde_json::{json, Value};
use thiserror::Error;
use tokio::net::TcpListener;
use tokio::sync::{OwnedSemaphorePermit, Semaphore};

/// Python parity (`server.MAX_QUERY_LENGTH`): longer queries are rejected
/// with a FastAPI-style 422, not silently accepted.
const MAX_QUERY_LENGTH: usize = 2_000;
const DEFAULT_RATE_LIMIT_PER_MINUTE: u32 = 120;
const MAX_EVENTS: usize = 1_000;
const REQUEST_ID_HEADER: &str = "x-request-id";

#[derive(Clone)]
struct RequestId(String);

/// Mutable process state shared by middleware and route handlers.
#[derive(Clone)]
pub struct ServerState {
    started_at: Instant,
    token: Option<Arc<str>>,
    events: Arc<Mutex<VecDeque<Value>>>,
    rate_limit: u32,
    rate_windows: Arc<Mutex<HashMap<String, (Instant, u32)>>>,
    contract_fixtures: bool,
    rag_paths: Option<RagPaths>,
    retrieval: Option<Arc<RetrievalBackend>>,
    in_flight: Arc<Semaphore>,
}

impl Default for ServerState {
    fn default() -> Self {
        Self::new(std::env::var("RAG_TOKEN").ok())
    }
}

impl ServerState {
    /// Create daemon state. `None` disables auth for embedded/tests callers.
    #[must_use]
    pub fn new(token: Option<String>) -> Self {
        Self {
            started_at: Instant::now(),
            token: token.map(Arc::from),
            events: Arc::new(Mutex::new(VecDeque::with_capacity(MAX_EVENTS))),
            rate_limit: DEFAULT_RATE_LIMIT_PER_MINUTE,
            rate_windows: Arc::new(Mutex::new(HashMap::new())),
            contract_fixtures: false,
            rag_paths: RagPaths::from_env().ok(),
            retrieval: None,
            in_flight: Arc::new(Semaphore::new(32)),
        }
    }

    /// Attach the live dense-retrieval backend (Ollama + Qdrant clients).
    #[must_use]
    pub fn with_retrieval(mut self, backend: Arc<RetrievalBackend>) -> Self {
        self.retrieval = Some(backend);
        self
    }

    /// Override the per-token fixed-window limit, primarily for contract tests.
    #[must_use]
    pub fn with_rate_limit(mut self, requests_per_minute: u32) -> Self {
        self.rate_limit = requests_per_minute.max(1);
        self
    }

    /// Override the protected-request concurrency budget.
    #[must_use]
    pub fn with_max_in_flight(mut self, maximum: usize) -> Self {
        self.in_flight = Arc::new(Semaphore::new(maximum.max(1)));
        self
    }

    /// Enable captured responses for black-box contract tests only.
    #[must_use]
    pub fn with_contract_fixtures(mut self) -> Self {
        self.contract_fixtures = true;
        self
    }

    /// Use an explicit copied RAG home for live-backend compatibility tests.
    #[must_use]
    pub fn with_rag_home(mut self, home: impl Into<std::path::PathBuf>) -> Self {
        self.rag_paths = Some(RagPaths::from_home(home));
        self
    }

    fn push_event(&self, event: Value) {
        let mut events = self.events.lock().expect("event lock poisoned");
        if events.len() == MAX_EVENTS {
            events.pop_front();
        }
        events.push_back(event);
    }

    fn recent_events(&self) -> Vec<Value> {
        self.events
            .lock()
            .expect("event lock poisoned")
            .iter()
            .cloned()
            .collect()
    }
}

/// Build the complete R6 HTTP surface with auth disabled.
pub fn router() -> Router {
    router_with_state(ServerState::new(None).with_contract_fixtures())
}

/// Build the complete HTTP surface using explicit process state.
pub fn router_with_state(state: ServerState) -> Router {
    let protected = Router::new()
        .route("/status", get(status))
        .route("/queries/recent", get(generic_get))
        .route("/queries/stats", get(generic_get))
        .route("/collections", get(generic_get))
        .route("/plugins", get(generic_get))
        .route("/events/recent", get(events_recent))
        .route("/events/ws", get(events_ws))
        .route("/health/detail", get(generic_get))
        .route("/stack", get(generic_get))
        .route("/overview/tui", get(generic_get))
        .route("/files/recent", get(generic_get))
        .route("/index/progress/{job_id}", get(index_progress))
        .route("/index/jobs", get(generic_get))
        .route("/overview", get(generic_get))
        .route("/repos", get(generic_get))
        .route("/diagnose", get(generic_get))
        .route("/stack/qdrant/start", post(generic_post))
        .route("/index/start", post(generic_post))
        .route("/index/backfill-code-index", post(generic_post))
        .route("/search", post(generic_post))
        .route("/docs-search", post(generic_post))
        .route("/resolve", post(generic_post))
        .route("/vocab/build", post(generic_post))
        .route("/smart-search", post(generic_post))
        .route("/call-tree", post(generic_post))
        .route("/graph/files", post(generic_post))
        .route("/graph/node", post(generic_post))
        .route("/graph/callers", post(generic_post))
        .route("/graph/callees", post(generic_post))
        .route("/graph/impact", post(generic_post))
        .route("/graph/affected", post(generic_post))
        .route("/project-understand", post(generic_post))
        .route("/context-pack", post(generic_post))
        .route("/enumerate", post(generic_post))
        .route("/ask", post(generic_post))
        .route("/index", post(generic_post))
        .route("/index/docs", post(generic_post))
        .route("/admin/reload", post(generic_post))
        .route("/admin/export", post(generic_post))
        .route("/admin/import", post(generic_post))
        .route("/admin/verify", post(generic_post))
        .route("/admin/repair", post(generic_post))
        .route("/diff", post(generic_post))
        .route_layer(middleware::from_fn_with_state(
            state.clone(),
            authenticate_and_limit,
        ))
        .route_layer(middleware::from_fn_with_state(state.clone(), shed_overload));

    Router::new()
        .route("/", get(dashboard))
        .route("/health", get(health))
        .route("/live", get(liveness))
        .route("/ready", get(readiness))
        .route("/.well-known/rag-capabilities", get(capabilities))
        .route("/openapi.json", get(openapi))
        .merge(protected)
        .layer(middleware::from_fn(csrf_guard))
        .layer(middleware::from_fn_with_state(
            state.clone(),
            record_request,
        ))
        .layer(middleware::from_fn(trusted_host))
        .layer(middleware::from_fn(request_id))
        .with_state(state)
}

async fn request_id(mut request: Request, next: Next) -> Response {
    let presented = request
        .headers()
        .get(REQUEST_ID_HEADER)
        .and_then(|value| value.to_str().ok())
        .map(str::trim)
        .filter(|value| {
            !value.is_empty()
                && value.len() <= 128
                && value.bytes().all(|byte| byte.is_ascii_graphic())
        });
    let id = presented
        .map(str::to_owned)
        .unwrap_or_else(|| uuid::Uuid::new_v4().to_string());
    request.extensions_mut().insert(RequestId(id.clone()));
    let mut response = next.run(request).await;
    if let Ok(value) = HeaderValue::from_str(&id) {
        response.headers_mut().insert(REQUEST_ID_HEADER, value);
    }
    response
}

fn try_acquire_request_slot(state: &ServerState) -> Option<OwnedSemaphorePermit> {
    Arc::clone(&state.in_flight).try_acquire_owned().ok()
}

async fn shed_overload(State(state): State<ServerState>, request: Request, next: Next) -> Response {
    let Some(_permit) = try_acquire_request_slot(&state) else {
        let mut response = api_error(
            StatusCode::SERVICE_UNAVAILABLE,
            "Server is at its concurrent request limit",
            "OVERLOADED",
        );
        response
            .headers_mut()
            .insert(header::RETRY_AFTER, HeaderValue::from_static("1"));
        return response;
    };
    next.run(request).await
}

/// Python parity (`csrf_guard_middleware`): a non-safe request that carries a
/// non-localhost Origin and no bearer header is a cross-site form submission —
/// block it before any handler runs.
async fn csrf_guard(request: Request, next: Next) -> Response {
    let method = request.method();
    if method != http::Method::GET
        && method != http::Method::HEAD
        && method != http::Method::OPTIONS
    {
        if let Some(origin) = request
            .headers()
            .get(header::ORIGIN)
            .and_then(|value| value.to_str().ok())
        {
            let low = origin.to_ascii_lowercase();
            let localhost_origin = low.starts_with("http://localhost:")
                || low.starts_with("http://127.0.0.1:")
                || low == "http://localhost"
                || low == "http://127.0.0.1";
            let has_bearer = request
                .headers()
                .get(header::AUTHORIZATION)
                .and_then(|value| value.to_str().ok())
                .is_some_and(|value| {
                    value
                        .trim_start()
                        .to_ascii_lowercase()
                        .starts_with("bearer ")
                });
            if !localhost_origin && !has_bearer {
                return (
                    StatusCode::FORBIDDEN,
                    Json(ErrorResponse {
                        error: "Forbidden origin".to_owned(),
                        code: "CSRF_BLOCKED".to_owned(),
                        detail: Some(origin.to_owned()),
                    }),
                )
                    .into_response();
            }
        }
    }
    next.run(request).await
}

/// Serve until the process receives a termination signal or the server fails.
pub async fn serve(config: &ServerConfig) -> Result<(), ServerError> {
    // Authentication and configuration are startup invariants. Resolve them
    // before binding so an unreadable home/token can never create a live,
    // unauthenticated daemon.
    let paths = RagPaths::from_env()?;
    let persisted_token = bootstrap_rag_home(&paths)?;
    let cwd = std::env::current_dir().unwrap_or_else(|_| std::path::PathBuf::from("."));
    rag_config::load_env_files(&paths, &cwd)?;
    let token = std::env::var("RAG_TOKEN")
        .ok()
        .map(|value| value.trim().to_owned())
        .filter(|value| !value.is_empty())
        .unwrap_or(persisted_token);
    let settings = rag_config::load_settings(&paths)?;
    let mut state = ServerState::new(Some(token))
        .with_max_in_flight(usize::from(settings.server.max_in_flight));
    // Client construction validates URLs, TLS policy, credentials, limits and
    // headers without probing the services. Invalid external-service config is
    // fatal; a temporarily offline valid service is represented by readiness.
    let backend =
        Arc::new(RetrievalBackend::from_settings(&settings).map_err(ServerError::Startup)?);
    let listener = TcpListener::bind((config.host.as_str(), config.port)).await?;

    // `embedded` hosts Qdrant as a managed child process; `server`
    // connects to whatever serves qdrant.url (e.g. `rag qdrant-up`).
    if settings.qdrant.mode == "embedded" {
        qdrant_boot::ensure_local_qdrant(&paths, &settings.qdrant.url)
            .await
            .map_err(ServerError::Startup)?;
    }
    eprintln!("dense retrieval backend configured (Ollama + Qdrant)");
    // Warm the embedding model in the background so the first real query is
    // not the one that pays the model-load latency.
    let warm = Arc::clone(&backend);
    tokio::spawn(async move { warm.warm_up().await });
    state = state.with_retrieval(backend);
    let mut fields = serde_json::Map::new();
    fields.insert("host".to_owned(), json!(config.host));
    fields.insert("port".to_owned(), json!(config.port));
    log_daemon_event(Some(&paths), "info", "daemon_started", fields);

    let served = axum::serve(listener, router_with_state(state))
        .with_graceful_shutdown(shutdown_signal())
        .await;
    qdrant_boot::stop_managed().await;
    log_daemon_event(
        Some(&paths),
        "info",
        "daemon_stopped",
        serde_json::Map::new(),
    );
    served?;
    Ok(())
}

/// Fresh-machine bootstrap (Python `ensure_rag_home` parity): create the RAG
/// home, a `secrets.token_urlsafe(32)`-style bearer token, and a default
/// `config.toml` so a bare binary is fully self-sufficient.
fn bootstrap_rag_home(paths: &RagPaths) -> Result<String, rag_config::ConfigError> {
    let token_existed = paths.token_path.exists();
    let token = rag_config::get_or_create_token(paths)?;
    if !token_existed {
        eprintln!("created auth token at {}", paths.token_path.display());
    }
    if !paths.config_path.exists() {
        std::fs::write(&paths.config_path, rag_config::PYTHON_DEFAULT_TOML).map_err(|source| {
            rag_config::ConfigError::Io {
                context: "write default config",
                source,
            }
        })?;
        eprintln!("created default config at {}", paths.config_path.display());
    }
    Ok(token)
}

async fn shutdown_signal() {
    let ctrl_c = async {
        if let Err(error) = tokio::signal::ctrl_c().await {
            eprintln!("Ctrl+C signal handler failed; shutting down safely: {error}");
        }
    };
    #[cfg(unix)]
    let terminate = async {
        match tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()) {
            Ok(mut signal) => {
                signal.recv().await;
            }
            Err(error) => {
                eprintln!("SIGTERM handler failed; shutting down safely: {error}");
            }
        }
    };
    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();
    tokio::select! { _ = ctrl_c => {}, _ = terminate => {} }
}

async fn health(State(state): State<ServerState>) -> Json<HealthResponse> {
    if state.contract_fixtures {
        return Json(HealthResponse::r0());
    }
    let Some(backend) = state.retrieval.as_ref() else {
        return Json(HealthResponse::r0());
    };
    let components =
        match tokio::time::timeout(Duration::from_secs(2), backend.component_health()).await {
            Ok(components) => components,
            Err(_) => return Json(HealthResponse::r0()),
        };
    let healthy = components.get("ollama").map(String::as_str) == Some("ok")
        && components.get("qdrant").map(String::as_str) == Some("ok");
    Json(HealthResponse {
        status: if healthy { "ok" } else { "degraded" }.to_owned(),
        components,
    })
}

async fn liveness() -> Json<Value> {
    Json(json!({"status": "ok"}))
}

async fn readiness(State(state): State<ServerState>) -> Response {
    if state.contract_fixtures {
        return (StatusCode::OK, Json(json!({"status": "ready"}))).into_response();
    }
    let Some(backend) = state.retrieval.as_ref() else {
        return (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(json!({"status": "not_ready", "reason": "backend_not_initialized"})),
        )
            .into_response();
    };
    match tokio::time::timeout(Duration::from_secs(2), backend.component_health()).await {
        Ok(components)
            if components.get("ollama").map(String::as_str) == Some("ok")
                && components.get("qdrant").map(String::as_str) == Some("ok") =>
        {
            (
                StatusCode::OK,
                Json(json!({"status": "ready", "components": components})),
            )
                .into_response()
        }
        Ok(components) => (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(json!({"status": "not_ready", "components": components})),
        )
            .into_response(),
        Err(_) => (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(json!({"status": "not_ready", "reason": "probe_timeout"})),
        )
            .into_response(),
    }
}

async fn status(State(state): State<ServerState>) -> Json<Value> {
    if !state.contract_fixtures {
        let (status, provider, model) = match state.retrieval.as_ref() {
            Some(backend) => ("ok", "ollama", backend.embedder_model().to_owned()),
            None => ("degraded", "not_initialized", String::new()),
        };
        let collections = state
            .rag_paths
            .as_ref()
            .and_then(|paths| RepoRegistry::open(paths).ok())
            .and_then(|registry| registry.list_repos().ok())
            .map(|repos| {
                repos
                    .into_iter()
                    .map(|repo| json!(repo.collection))
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();
        return Json(json!({
            "status": status,
            "embedder_provider": provider,
            "embedder_model": model,
            "reranker_model": "disabled",
            "reranker_enabled": false,
            "collections": collections,
            "uptime_seconds": state.started_at.elapsed().as_secs_f64(),
            "files_indexed": 0,
            "embedder_warm_ms": null,
            "restart_count": 0,
            "gen_model": "",
            "gen_ctx_size": null,
        }));
    }
    let mut value: Value =
        serde_json::from_str(include_str!("../../../tests/contracts/status.json"))
            .expect("checked-in status fixture is valid JSON");
    value["uptime_seconds"] = json!(state.started_at.elapsed().as_secs_f64());
    Json(value)
}

async fn openapi() -> Json<Value> {
    Json(
        serde_json::from_str(include_str!("../../../tests/contracts/openapi.json"))
            .expect("checked-in OpenAPI fixture is valid JSON"),
    )
}

async fn capabilities() -> Json<Value> {
    Json(json!({
        "schema_version": "1.0",
        "service": "ragsystem",
        "version": env!("CARGO_PKG_VERSION"),
        "authentication": {"type": "http", "scheme": "bearer", "public_discovery": true},
        "capabilities": {
            "context_pack": {
                "endpoint": "/context-pack",
                "method": "POST",
                "budgets": ["max_slices", "max_source_tokens", "max_source_bytes"],
                "provenance": true,
                "content_digests": "sha256",
                "deterministic_order": true
            },
            "openapi": {"endpoint": "/openapi.json", "version": "3.1.0"},
            "health": {
                "liveness": "/live",
                "readiness": "/ready",
                "compatibility": "/health"
            }
        }
    }))
}

async fn dashboard(State(state): State<ServerState>) -> Response {
    // Python parity: the page is only served through this route so the
    // daemon token can be injected; same-origin fetch() then authenticates.
    // `no-store` keeps the token-bearing page out of browser/disk caches.
    let html = include_str!("../assets/index.html");
    let token = state.token.as_deref().unwrap_or("");
    (
        [(header::CACHE_CONTROL, "no-store")],
        Html(html.replace("__RAG_TOKEN__", token)),
    )
        .into_response()
}

async fn generic_get(State(state): State<ServerState>, request: Request) -> Response {
    let path = request.uri().path().to_owned();
    // Routes needing async Qdrant/Ollama access run through the backend.
    if !state.contract_fixtures {
        if let Some(backend) = state.retrieval.as_ref() {
            match path.as_str() {
                "/overview" => return Json(backend.overview_route().await).into_response(),
                "/health/detail" => {
                    return Json(backend.health_detail_route().await).into_response()
                }
                _ => {}
            }
        }
    }
    if let Some(value) = live_get_response(&path, state.rag_paths.as_ref()) {
        return Json(value).into_response();
    }
    Json(response_for(&path, None)).into_response()
}

async fn generic_post(State(state): State<ServerState>, request: Request) -> Response {
    let path = request.uri().path().to_owned();
    let body = match axum::body::to_bytes(request.into_body(), 2 * 1024 * 1024).await {
        Ok(bytes) if bytes.is_empty() => json!({}),
        Ok(bytes) => match serde_json::from_slice::<Value>(&bytes) {
            Ok(value) => value,
            Err(_) => return api_error(StatusCode::BAD_REQUEST, "Invalid JSON body", "HTTP_ERROR"),
        },
        Err(_) => {
            return api_error(
                StatusCode::PAYLOAD_TOO_LARGE,
                "Request body too large",
                "HTTP_ERROR",
            )
        }
    };
    if let Some(rejection) = validate_request_contract(&path, &body) {
        return rejection;
    }
    if !state.contract_fixtures {
        // Dense retrieval routes run through the async Ollama+Qdrant backend
        // when it is configured; other live routes stay on the SQLite path.
        if let (Some(backend), Some(paths)) = (state.retrieval.clone(), state.rag_paths.clone()) {
            let handled = match path.as_str() {
                "/search" => Some(backend.search_route(&paths, &body).await),
                "/smart-search" => Some(backend.smart_search_route(&paths, &body).await),
                "/ask" => Some(backend.ask_route(&paths, &body).await),
                "/index" => Some(indexing::index_route(&backend, &paths, &body).await),
                "/index/start" => Some(indexing::index_route(&backend, &paths, &body).await.map(
                    |result| {
                        json!({
                            "job_id": format!("completed-{}", uuid::Uuid::new_v4()),
                            "status": "completed",
                            "result": result,
                        })
                    },
                )),
                "/vocab/build" => Some(indexing::vocab_build_route(&backend, &paths, &body).await),
                "/diff" => Some(backend.diff_route(&paths, &body).await),
                "/admin/export" => Some(backend.admin_export_route(&paths, &body).await),
                "/admin/verify" => Some(backend.admin_verify_route(&paths, &body).await),
                _ => None,
            };
            if let Some(result) = handled {
                return match result {
                    Ok(value) => Json(value).into_response(),
                    Err(error) if error.starts_with("missing required field") => {
                        let field = error.rsplit(": ").next().unwrap_or("body");
                        validation_422(field, "field required", "value_error.missing")
                    }
                    Err(error) if error.starts_with("unknown repo") => {
                        api_error(StatusCode::NOT_FOUND, &error, "HTTP_ERROR")
                    }
                    Err(_) => api_error(
                        StatusCode::SERVICE_UNAVAILABLE,
                        "Live retrieval backend is unavailable",
                        "BACKEND_NOT_READY",
                    ),
                };
            }
        }
        if path == "/index/start" {
            return api_error(
                StatusCode::SERVICE_UNAVAILABLE,
                "Dense indexing requires the Ollama and Qdrant backend to be initialized",
                "BACKEND_NOT_READY",
            );
        }
        let live_path = path.clone();
        let live_body = body.clone();
        let rag_paths = state.rag_paths.clone();
        match tokio::task::spawn_blocking(move || {
            live_post_response(rag_paths.as_ref(), &live_path, &live_body)
        })
        .await
        {
            Ok(Ok(Some(value))) => return Json(value).into_response(),
            Ok(Ok(None)) => {}
            Ok(Err(_)) | Err(_) => {
                return api_error(
                    StatusCode::SERVICE_UNAVAILABLE,
                    "Live retrieval backend is unavailable",
                    "BACKEND_NOT_READY",
                );
            }
        }
        if requires_live_backend(&path) {
            return api_error(
                StatusCode::SERVICE_UNAVAILABLE,
                "Live retrieval backend is not initialized",
                "BACKEND_NOT_READY",
            );
        }
    }
    state.push_event(json!({
        "event": "request_completed",
        "path": path,
        "ts": unix_timestamp(),
    }));
    Json(response_for(&path, Some(&body))).into_response()
}

async fn events_recent(State(state): State<ServerState>) -> Json<Value> {
    Json(json!({"events": state.recent_events()}))
}

async fn events_ws(ws: WebSocketUpgrade, State(state): State<ServerState>) -> Response {
    ws.on_upgrade(move |socket| stream_events(socket, state))
}

async fn stream_events(mut socket: WebSocket, state: ServerState) {
    for event in state.recent_events() {
        if socket
            .send(Message::Text(event.to_string().into()))
            .await
            .is_err()
        {
            return;
        }
    }
    let _ = socket.send(Message::Close(None)).await;
}

async fn index_progress(Path(job_id): Path<String>) -> Json<Value> {
    Json(json!({
        "job_id": job_id,
        "status": "not_found",
        "files_processed": 0,
        "chunks_indexed": 0,
    }))
}

fn live_get_response(path: &str, paths: Option<&RagPaths>) -> Option<Value> {
    let paths = paths?;
    match path {
        "/repos" => RepoRegistry::open(paths)
            .and_then(|registry| registry.list_repos())
            .ok()
            .map(|repos| json!({"repos": repos})),
        "/collections" => RepoRegistry::open(paths)
            .and_then(|registry| registry.list_repos())
            .ok()
            .map(|repos| {
                json!({"collections": repos.into_iter().map(|repo| json!({
                    "name": repo.collection, "kind": "repository", "repo": repo.name,
                    "points_count": repo.chunks_count,
                })).collect::<Vec<_>>()})
            }),
        "/queries/recent" => RagDatabase::open(paths)
            .and_then(|database| database.recent_queries(50))
            .ok()
            .map(|queries| json!({"queries": queries})),
        "/queries/stats" => Some(live_queries_stats(paths)),
        _ => None,
    }
}

/// Python `/queries/stats`: p50/p95 latency, qpm (last 60s), avg results.
fn live_queries_stats(paths: &RagPaths) -> Value {
    let rows = RagDatabase::open(paths)
        .and_then(|database| database.recent_queries(100))
        .unwrap_or_default();
    if rows.is_empty() {
        return json!({"count": 0, "p50_ms": 0, "p95_ms": 0, "qpm": 0.0, "avg_results": 0.0});
    }
    let mut lats: Vec<f64> = rows.iter().filter_map(|row| row.latency_ms).collect();
    lats.sort_by(f64::total_cmp);
    let n = lats.len();
    let pct = |p: f64| -> f64 {
        if lats.is_empty() {
            return 0.0;
        }
        let idx = (((p / 100.0) * (n as f64 - 1.0)).round() as usize).min(n - 1);
        (lats[idx] * 10.0).round() / 10.0
    };
    // qpm: count of queries in the last 60s (timestamps are local ISO strings).
    let now = chrono::Local::now().naive_local();
    let recent_60 = rows
        .iter()
        .filter(|row| {
            chrono::NaiveDateTime::parse_from_str(&row.timestamp, "%Y-%m-%dT%H:%M:%S%.f")
                .ok()
                .map(|ts| (now - ts).num_seconds().abs() <= 60)
                .unwrap_or(false)
        })
        .count();
    let avg_results = rows
        .iter()
        .filter_map(|row| row.results_count)
        .map(|value| value as f64)
        .sum::<f64>()
        / rows.len() as f64;
    json!({
        "count": rows.len(),
        "p50_ms": pct(50.0),
        "p95_ms": pct(95.0),
        "qpm": recent_60 as f64,
        "avg_results": (avg_results * 100.0).round() / 100.0,
    })
}

fn live_post_response(
    paths: Option<&RagPaths>,
    path: &str,
    body: &Value,
) -> Result<Option<Value>, String> {
    let paths = paths.ok_or_else(|| "RAG home is unavailable".to_owned())?;
    match path {
        "/search" => live_search(paths, body).map(Some),
        "/docs-search" => live_docs_search(paths, body).map(Some),
        "/resolve" | "/graph/node" => live_resolve(paths, body, path == "/graph/node").map(Some),
        "/context-pack" => live_context_pack(paths, body).map(Some),
        "/call-tree" | "/graph/callers" => live_relation(paths, body, path).map(Some),
        "/graph/callees" => live_empty_relation(paths, body, "callees").map(Some),
        "/graph/files" => live_graph_files(paths, body).map(Some),
        "/graph/impact" => live_graph_impact(paths, body).map(Some),
        "/graph/affected" => live_graph_affected(paths, body).map(Some),
        "/project-understand" => live_project_understand(paths, body).map(Some),
        "/smart-search" => live_smart_search(paths, body).map(Some),
        "/enumerate" => live_enumerate(paths, body).map(Some),
        "/ask" => live_ask(paths, body).map(Some),
        "/index" => live_index(paths, body).map(Some),
        "/index/docs" => live_index_docs(paths, body).map(Some),
        "/index/start" => live_index_start(paths, body).map(Some),
        "/index/backfill-code-index" => Ok(Some(
            json!({"collection": body.get("collection").cloned().unwrap_or(json!("code_chunks")), "chunks_indexed": 0, "chunks_skipped": 0, "latency_ms": 0.0}),
        )),
        _ => Ok(None),
    }
}

fn live_search(paths: &RagPaths, body: &Value) -> Result<Value, String> {
    let started = Instant::now();
    let query = required_string(body, "query")?;
    let top_k = body
        .get("top_k")
        .and_then(Value::as_u64)
        .unwrap_or(20)
        .clamp(1, 100) as usize;
    let (repo, chunks) =
        load_repo_chunks(paths, body.get("repo").and_then(Value::as_str), 100_000)?;
    let terms = query_terms(query);
    let mut hits: Vec<_> = chunks
        .into_iter()
        .filter_map(|chunk| score_chunk(chunk, &terms))
        .collect();
    hits.sort_by(|(left_score, left), (right_score, right)| {
        right_score
            .total_cmp(left_score)
            .then_with(|| left.file_path.cmp(&right.file_path))
            .then_with(|| left.start_line.cmp(&right.start_line))
    });
    hits.truncate(top_k);
    let results: Vec<_> = hits
        .into_iter()
        .map(|(score, chunk)| chunk_json(&repo.name, &chunk, score))
        .collect();
    let plan = rag_agent::fallback_plan(query);
    Ok(json!({
        "query": query,
        "plan": plan,
        "total": results.len(),
        "results": results,
        "latency_ms": started.elapsed().as_secs_f64() * 1000.0,
    }))
}

fn live_docs_search(paths: &RagPaths, body: &Value) -> Result<Value, String> {
    let started = Instant::now();
    let query = required_string(body, "query")?;
    let top_k = body
        .get("top_k")
        .and_then(Value::as_u64)
        .unwrap_or(5)
        .clamp(1, 50) as usize;
    let chunks = RagDatabase::open(paths)
        .map_err(|error| error.to_string())?
        .code_chunks("doc_chunks", 100_000)
        .map_err(|error| error.to_string())?;
    let terms = query_terms(query);
    let mut hits: Vec<_> = chunks
        .into_iter()
        .filter_map(|chunk| score_chunk(chunk, &terms))
        .collect();
    hits.sort_by(|(left_score, left), (right_score, right)| {
        right_score
            .total_cmp(left_score)
            .then_with(|| left.file_path.cmp(&right.file_path))
    });
    hits.truncate(top_k);
    let results: Vec<_> = hits
        .into_iter()
        .map(|(score, chunk)| chunk_json("docs", &chunk, score))
        .collect();
    Ok(
        json!({"query": query, "total": results.len(), "results": results,
        "latency_ms": started.elapsed().as_secs_f64() * 1000.0}),
    )
}

fn live_resolve(paths: &RagPaths, body: &Value, graph_shape: bool) -> Result<Value, String> {
    let started = Instant::now();
    let repo_name = required_string(body, "repo")?;
    let repo = load_repo(paths, repo_name)?;
    let mut symbols = body
        .get("symbols")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_owned)
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    if symbols.is_empty() {
        if let Some(symbol) = body.get("symbol").and_then(Value::as_str) {
            symbols.push(symbol.to_owned());
        }
    }
    if symbols.is_empty() {
        symbols = query_terms(
            body.get("query")
                .and_then(Value::as_str)
                .unwrap_or_default(),
        );
    }
    let definitions_limit = body
        .get("definitions_limit")
        .or_else(|| body.get("limit"))
        .and_then(Value::as_u64)
        .unwrap_or(20) as usize;
    let usages_limit = body
        .get("usages_limit")
        .and_then(Value::as_u64)
        .unwrap_or(20) as usize;
    let mut resolved = rag_retrieval::ast_index::resolve_symbols(
        &repo.path,
        &symbols,
        definitions_limit,
        usages_limit,
    );
    add_repo_to_items(&mut resolved["definitions"], &repo.name);
    add_repo_to_items(&mut resolved["usages"], &repo.name);
    let definitions = resolved["definitions"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    let usages = resolved["usages"].as_array().cloned().unwrap_or_default();
    if graph_shape {
        let symbol = symbols.first().cloned().unwrap_or_default();
        Ok(
            json!({"repo": repo.name, "symbol": symbol, "definitions": definitions, "usages": usages,
            "total_definitions": definitions.len(), "total_usages": usages.len(), "provenance": "ast_index",
            "latency_ms": started.elapsed().as_secs_f64() * 1000.0}),
        )
    } else {
        Ok(
            json!({"repo": repo.name, "symbols": symbols, "definitions": definitions, "usages": usages,
            "total_definitions": definitions.len(), "total_usages": usages.len(),
            "latency_ms": started.elapsed().as_secs_f64() * 1000.0}),
        )
    }
}

fn live_context_pack(paths: &RagPaths, body: &Value) -> Result<Value, String> {
    let started = Instant::now();
    let repo_name = required_string(body, "repo")?;
    let query = required_string(body, "query")?;
    let repo = load_repo(paths, repo_name)?;
    let max_slices = body
        .get("max_slices")
        .and_then(Value::as_u64)
        .unwrap_or(8)
        .clamp(1, 50) as usize;
    let max_source_tokens = body
        .get("max_source_tokens")
        .and_then(Value::as_u64)
        .unwrap_or(6_000)
        .clamp(100, 100_000) as usize;
    let max_source_bytes = body
        .get("max_source_bytes")
        .and_then(Value::as_u64)
        .and_then(|value| usize::try_from(value).ok())
        .unwrap_or_else(|| max_source_tokens.saturating_mul(4))
        .clamp(64, 4 * 1024 * 1024);
    let use_ast_index = body
        .get("use_ast_index")
        .and_then(Value::as_bool)
        .unwrap_or(true);
    let include_semantic = body
        .get("include_semantic")
        .and_then(Value::as_bool)
        .unwrap_or(true);
    let candidate_limit = max_slices.saturating_mul(4).min(200);
    let mut candidates = if use_ast_index {
        rag_retrieval::ast_index::retrieve_context(&repo.path, query, candidate_limit, true)
    } else {
        Vec::new()
    };

    // The SQLite FTS mirror is a deterministic, locally available fallback
    // when ast-index is absent, and supplements AST candidates when present.
    let filters = body.get("filters").and_then(Value::as_object);
    let lexical_hits = RagDatabase::open(paths)
        .and_then(|database| {
            database.search_code_chunks(query, Some(&repo.collection), candidate_limit, filters)
        })
        .map_err(|error| error.to_string())?;
    for hit in lexical_hits {
        let mut candidate = chunk_json(&repo.name, &hit.chunk, hit.score);
        if let Some(object) = candidate.as_object_mut() {
            object.insert("start_line".to_owned(), json!(hit.chunk.start_line));
            object.insert("end_line".to_owned(), json!(hit.chunk.end_line));
            object.insert("why_included".to_owned(), json!("sqlite_fts"));
        }
        candidates.push(candidate);
    }

    let mut seen = std::collections::BTreeSet::new();
    candidates.retain(|candidate| {
        let key = format!(
            "{}:{}:{}:{}",
            candidate["file_path"].as_str().unwrap_or_default(),
            candidate["start_line"].as_u64().unwrap_or_default(),
            candidate["end_line"].as_u64().unwrap_or_default(),
            candidate["name"].as_str().unwrap_or_default()
        );
        seen.insert(key)
    });

    let candidate_count = candidates.len();
    let mut slices = Vec::new();
    let mut total_source_tokens = 0usize;
    let mut total_source_bytes = 0usize;
    let mut truncated = false;
    let mut included_sources = std::collections::BTreeSet::new();
    for mut candidate in candidates {
        if slices.len() >= max_slices
            || total_source_tokens >= max_source_tokens
            || total_source_bytes >= max_source_bytes
        {
            truncated = true;
            break;
        }
        let Some(object) = candidate.as_object_mut() else {
            continue;
        };
        let code = object
            .get("code")
            .and_then(Value::as_str)
            .unwrap_or_default();
        if code.is_empty() {
            continue;
        }
        let remaining_tokens = max_source_tokens.saturating_sub(total_source_tokens);
        let remaining_bytes = max_source_bytes.saturating_sub(total_source_bytes);
        let (packed_code, token_estimate, was_truncated) =
            trim_context_source(code, remaining_tokens, remaining_bytes);
        if packed_code.is_empty() {
            truncated = true;
            break;
        }
        truncated |= was_truncated;
        let source_bytes = packed_code.len();
        let start_line = object
            .get("start_line")
            .and_then(Value::as_u64)
            .or_else(|| {
                object
                    .get("lines")
                    .and_then(Value::as_str)
                    .and_then(|lines| lines.split('-').next())
                    .and_then(|line| line.parse().ok())
            })
            .unwrap_or(1);
        let line_count = packed_code.lines().count().max(1) as u64;
        let end_line = start_line.saturating_add(line_count.saturating_sub(1));
        let file_path = object
            .get("file_path")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned();
        let name = object
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned();
        let source = object
            .get("why_included")
            .and_then(Value::as_str)
            .filter(|value| value.starts_with("ast_index"))
            .map_or("sqlite_fts", |_| "ast_index");
        included_sources.insert(source);
        let citation = format!("{file_path}:{start_line}-{end_line} ({name})");
        use sha2::Digest as _;
        let digest = format!("{:x}", sha2::Sha256::digest(packed_code.as_bytes()));
        object.insert("repo".to_owned(), json!(repo.name));
        object.insert("code".to_owned(), json!(packed_code));
        object.insert(
            "lines".to_owned(),
            json!(format!("{start_line}-{end_line}")),
        );
        object.insert("start_line".to_owned(), json!(start_line));
        object.insert("end_line".to_owned(), json!(end_line));
        object.insert("citation".to_owned(), json!(citation));
        object.insert("token_estimate".to_owned(), json!(token_estimate));
        object.insert("source_bytes".to_owned(), json!(source_bytes));
        object.insert("content_sha256".to_owned(), json!(digest));
        object.insert("truncated".to_owned(), json!(was_truncated));
        object.insert(
            "provenance".to_owned(),
            json!({
                "source": source,
                "repository": repo.name,
                "collection": repo.collection,
                "citation": citation,
                "indexed_at": repo.last_indexed,
            }),
        );
        total_source_tokens += token_estimate;
        total_source_bytes += source_bytes;
        slices.push(candidate);
    }
    truncated |= slices.len() < candidate_count;
    Ok(json!({
        "query": query,
        "repo": repo.name,
        "total": slices.len(),
        "slices": slices,
        "total_source_tokens": total_source_tokens,
        "total_source_bytes": total_source_bytes,
        "truncated": truncated,
        "budget": {
            "max_slices": max_slices,
            "max_source_tokens": max_source_tokens,
            "max_source_bytes": max_source_bytes,
        },
        "retrieval": {
            "ast_index_requested": use_ast_index,
            "semantic_requested": include_semantic,
            "semantic_included": false,
            "sources_included": included_sources,
        },
        "freshness": {"indexed_at": repo.last_indexed},
        "latency_ms": started.elapsed().as_secs_f64() * 1000.0,
    }))
}

fn trim_context_source(
    code: &str,
    token_budget: usize,
    byte_budget: usize,
) -> (String, usize, bool) {
    let (token_trimmed, _) = rag_retrieval::trim_to_token_budget(code, token_budget);
    let mut output = token_trimmed;
    if output.len() > byte_budget {
        let boundary = output
            .char_indices()
            .map(|(index, _)| index)
            .take_while(|index| *index <= byte_budget)
            .last()
            .unwrap_or_default();
        output.truncate(boundary);
        if let Some(last_newline) = output.rfind('\n') {
            output.truncate(last_newline);
        }
        output = output.trim_end().to_owned();
    }
    let was_truncated = output.len() < code.len();
    let tokens = if output.is_empty() {
        0
    } else {
        rag_retrieval::estimate_tokens(&output)
    };
    (output, tokens, was_truncated)
}

fn live_relation(paths: &RagPaths, body: &Value, path: &str) -> Result<Value, String> {
    let started = Instant::now();
    let repo_name = required_string(body, "repo")?;
    let symbol = required_string(body, "symbol")?;
    let limit = body
        .get("limit")
        .and_then(Value::as_u64)
        .unwrap_or(50)
        .clamp(1, 200) as usize;
    let repo = load_repo(paths, repo_name)?;
    let mut nodes = if path == "/call-tree" {
        rag_retrieval::ast_index::call_tree(&repo.path, symbol, limit)
    } else {
        rag_retrieval::ast_index::callers(&repo.path, symbol, limit)
    };
    for node in &mut nodes {
        if let Some(object) = node.as_object_mut() {
            object.insert("repo".to_owned(), json!(repo.name));
        }
    }
    if path == "/call-tree" {
        Ok(
            json!({"repo": repo.name, "symbol": symbol, "total": nodes.len(), "nodes": nodes,
            "latency_ms": started.elapsed().as_secs_f64() * 1000.0}),
        )
    } else {
        Ok(
            json!({"repo": repo.name, "symbol": symbol, "relation": "callers", "total": nodes.len(),
            "nodes": nodes, "relation_source": "ast_index",
            "latency_ms": started.elapsed().as_secs_f64() * 1000.0}),
        )
    }
}

fn live_graph_files(paths: &RagPaths, body: &Value) -> Result<Value, String> {
    let started = Instant::now();
    let repo_name = required_string(body, "repo")?;
    let query = body
        .get("query")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_ascii_lowercase();
    let (repo, chunks) = load_repo_chunks(paths, Some(repo_name), 100_000)?;
    let mut files = std::collections::BTreeMap::<String, (usize, usize, Vec<String>, f64)>::new();
    for chunk in chunks {
        if !query.is_empty()
            && !chunk.file_path.to_ascii_lowercase().contains(&query)
            && !chunk.name.to_ascii_lowercase().contains(&query)
        {
            continue;
        }
        let entry = files.entry(chunk.file_path).or_default();
        entry.0 += 1;
        if !chunk.name.is_empty() && !entry.2.contains(&chunk.name) {
            entry.2.push(chunk.name);
        }
        entry.1 = entry.2.len();
        entry.3 = if query.is_empty() { 0.0 } else { 1.0 };
    }
    let files: Vec<_> = files
        .into_iter()
        .map(|(file_path, (chunk_count, symbol_count, symbols, score))| {
            json!({"file_path": file_path, "chunk_count": chunk_count, "symbol_count": symbol_count,
            "symbols": symbols, "updated_at": 0.0, "score": score})
        })
        .collect();
    Ok(
        json!({"repo": repo.name, "query": query, "total": files.len(), "files": files,
        "latency_ms": started.elapsed().as_secs_f64() * 1000.0}),
    )
}

/// Python `graph_tools.callees`: heuristic source scan — resolve the symbol's
/// body, regex out `name(` call sites, resolve each callee (AST then lexical).
fn live_empty_relation(paths: &RagPaths, body: &Value, relation: &str) -> Result<Value, String> {
    let started = Instant::now();
    let repo_name = required_string(body, "repo")?;
    let symbol = required_string(body, "symbol")?;
    let repo = load_repo(paths, repo_name)?;
    let limit = body.get("limit").and_then(Value::as_u64).unwrap_or(50) as usize;
    if relation != "callees" {
        return Ok(json!({
            "repo": repo.name, "symbol": symbol, "relation": relation, "nodes": [],
            "total": 0, "relation_source": "ast_index",
            "latency_ms": started.elapsed().as_secs_f64() * 1000.0,
        }));
    }

    const SKIP_CALLEES: [&str; 16] = [
        "if",
        "for",
        "while",
        "when",
        "switch",
        "return",
        "throw",
        "catch",
        "super",
        "this",
        "class",
        "interface",
        "object",
        "fun",
        "def",
        "function",
    ];
    let resolved =
        rag_retrieval::ast_index::resolve_symbols(&repo.path, &[symbol.to_owned()], 3, 0);
    let call_re = regex_lite_call();
    let mut names: Vec<String> = Vec::new();
    for definition in resolved["definitions"].as_array().into_iter().flatten() {
        let code = definition
            .get("code")
            .and_then(Value::as_str)
            .unwrap_or_default();
        for capture in call_re.captures_iter(code) {
            let name = capture.get(1).map(|m| m.as_str()).unwrap_or_default();
            if name == symbol || SKIP_CALLEES.contains(&name.to_ascii_lowercase().as_str()) {
                continue;
            }
            if !names.iter().any(|existing| existing == name) {
                names.push(name.to_owned());
            }
            if names.len() >= limit * 2 {
                break;
            }
        }
    }

    let mut nodes: Vec<Value> = Vec::new();
    let mut seen: std::collections::BTreeSet<(String, i64, String)> =
        std::collections::BTreeSet::new();
    let database = RagDatabase::open(paths).ok();
    for name in names {
        let mut candidates = rag_retrieval::ast_index::resolve_symbols(
            &repo.path,
            std::slice::from_ref(&name),
            2,
            0,
        )["definitions"]
            .as_array()
            .cloned()
            .unwrap_or_default();
        if candidates.is_empty() {
            if let Some(database) = &database {
                if let Ok(hits) =
                    database.search_code_chunks(&name, Some(&repo.collection), 2, None)
                {
                    candidates = hits
                        .into_iter()
                        .map(|hit| {
                            json!({
                                "file_path": hit.chunk.file_path, "name": hit.chunk.name,
                                "parent_name": hit.chunk.parent_name, "chunk_type": hit.chunk.chunk_type,
                                "language": hit.chunk.language,
                                "lines": format!("{}-{}", hit.chunk.start_line, hit.chunk.end_line),
                                "start_line": hit.chunk.start_line, "code": hit.chunk.code,
                                "score": hit.score,
                            })
                        })
                        .collect();
                }
            }
        }
        for candidate in candidates {
            let key = (
                candidate
                    .get("file_path")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_owned(),
                candidate
                    .get("start_line")
                    .and_then(Value::as_i64)
                    .or_else(|| {
                        candidate
                            .get("lines")
                            .and_then(Value::as_str)
                            .and_then(|lines| lines.split('-').next())
                            .and_then(|value| value.parse().ok())
                    })
                    .unwrap_or(0),
                candidate
                    .get("name")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_owned(),
            );
            if !seen.insert(key) {
                continue;
            }
            let mut node = candidate.clone();
            if let Some(object) = node.as_object_mut() {
                object.insert("callee_name".to_owned(), json!(name));
                object.insert("relation_source".to_owned(), json!("heuristic_source_scan"));
            }
            nodes.push(node);
            if nodes.len() >= limit {
                return Ok(json!({
                    "repo": repo.name, "symbol": symbol, "relation": relation, "nodes": nodes,
                    "total": nodes.len(), "relation_source": "heuristic_source_scan",
                    "latency_ms": started.elapsed().as_secs_f64() * 1000.0,
                }));
            }
        }
    }
    Ok(json!({
        "repo": repo.name, "symbol": symbol, "relation": relation, "nodes": nodes.clone(),
        "total": nodes.len(), "relation_source": "heuristic_source_scan",
        "latency_ms": started.elapsed().as_secs_f64() * 1000.0,
    }))
}

/// `\b([A-Za-z_][A-Za-z0-9_]*)\s*\(` — Python `graph_tools._CALL_RE`.
fn regex_lite_call() -> regex::Regex {
    static CELL: std::sync::OnceLock<regex::Regex> = std::sync::OnceLock::new();
    CELL.get_or_init(|| {
        regex::Regex::new(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(").expect("static regex")
    })
    .clone()
}

fn live_graph_impact(paths: &RagPaths, body: &Value) -> Result<Value, String> {
    let started = Instant::now();
    let repo_name = required_string(body, "repo")?;
    let symbol = required_string(body, "symbol")?;
    let repo = load_repo(paths, repo_name)?;
    let limit = body.get("limit").and_then(Value::as_u64).unwrap_or(50) as usize;
    let resolved = rag_retrieval::ast_index::resolve_symbols(
        &repo.path,
        &[symbol.to_owned()],
        limit.min(20),
        limit,
    );
    let callers = rag_retrieval::ast_index::callers(&repo.path, symbol, limit);
    let mut definitions = resolved["definitions"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    // Python `graph_tools.node` parity: when the AST scan yields no
    // definitions, exact/lexical index hits fill the definitions bucket —
    // these are the highest-signal files for the symbol.
    if definitions.is_empty() {
        if let Ok(database) = RagDatabase::open(paths) {
            if let Ok(hits) =
                database.search_code_chunks(symbol, Some(&repo.collection), limit.min(20), None)
            {
                definitions = hits
                    .into_iter()
                    .map(|hit| {
                        json!({
                            "file_path": hit.chunk.file_path,
                            "name": hit.chunk.name,
                            "parent_name": hit.chunk.parent_name,
                            "chunk_type": hit.chunk.chunk_type,
                            "language": hit.chunk.language,
                            "lines": format!("{}-{}", hit.chunk.start_line, hit.chunk.end_line),
                            "code": hit.chunk.code,
                            "score": hit.score,
                            "repo": repo.name,
                        })
                    })
                    .collect();
            }
        }
    }
    let usages = resolved["usages"].as_array().cloned().unwrap_or_default();
    let mut affected = std::collections::BTreeSet::new();
    for item in definitions
        .iter()
        .chain(usages.iter())
        .chain(callers.iter())
    {
        if let Some(path) = item.get("file_path").and_then(Value::as_str) {
            affected.insert(path.to_owned());
        }
    }
    // Python parity: tests are RELATED test files ranked against the impacted
    // set, not merely the test-looking members of it.
    let impacted: Vec<String> = affected.iter().cloned().collect();
    let tests: Vec<Value> = RagDatabase::open(paths)
        .and_then(|database| database.related_test_files(&repo.collection, &impacted, limit))
        .map(|items| {
            items
                .into_iter()
                .map(|item| serde_json::to_value(item).unwrap_or_default())
                .collect()
        })
        .unwrap_or_default();

    // Python `_impact_risks` + `_stale_risks`.
    let stale = stale_index_files(paths, &repo, &impacted);
    let mut risks: Vec<String> = Vec::new();
    if definitions.len() > 1 {
        risks.push(
            "Symbol has multiple definitions; disambiguate by file path before editing.".to_owned(),
        );
    }
    if !callers.is_empty() && tests.is_empty() {
        risks.push("Callers were found but no related tests were identified.".to_owned());
    }
    if definitions.is_empty() {
        risks.push(
            "No exact definition found; verify symbol spelling or index freshness.".to_owned(),
        );
    }
    risks.extend(stale_risk(&stale));

    Ok(json!({
        "repo": repo.name, "symbol": symbol, "definitions": definitions, "usages": usages,
        "callers": callers, "affected_files": affected, "tests": tests, "risks": risks,
        "metrics": {
            "definition_count": definitions.len(),
            "usage_count": usages.len(),
            "caller_count": callers.len(),
            "affected_file_count": affected.len(),
            "test_count": tests.len(),
            "stale_file_count": stale.len(),
            "whole_file_reads_avoided": true,
        },
        "latency_ms": started.elapsed().as_secs_f64() * 1000.0,
    }))
}

/// Python `_stale_index_files`: files whose on-disk mtime is newer than the
/// indexed `updated_at` (+2s slack) — the index may be stale for them.
fn stale_index_files(paths: &RagPaths, repo: &RepoInfo, files: &[String]) -> Vec<String> {
    if files.is_empty() {
        return Vec::new();
    }
    let Ok(database) = RagDatabase::open(paths) else {
        return Vec::new();
    };
    let Ok(indexed) = database.list_code_files(&repo.collection, 10_000) else {
        return Vec::new();
    };
    let updated: std::collections::HashMap<String, f64> = indexed
        .into_iter()
        .map(|item| (item.file_path, item.updated_at))
        .collect();
    let root = std::path::Path::new(&repo.path);
    let mut stale = Vec::new();
    for path in files {
        let Some(indexed_at) = updated.get(path) else {
            continue;
        };
        if let Ok(metadata) = std::fs::metadata(root.join(path)) {
            if let Ok(modified) = metadata.modified() {
                if let Ok(mtime) = modified.duration_since(std::time::UNIX_EPOCH) {
                    if mtime.as_secs_f64() > indexed_at + 2.0 {
                        stale.push(path.clone());
                    }
                }
            }
        }
    }
    stale
}

fn stale_risk(stale: &[String]) -> Vec<String> {
    if stale.is_empty() {
        return Vec::new();
    }
    let preview = stale.iter().take(5).cloned().collect::<Vec<_>>().join(", ");
    let suffix = if stale.len() > 5 { "..." } else { "" };
    vec![format!(
        "Index may be stale for changed files: {preview}{suffix}. Verify locally before editing."
    )]
}

/// Python `graph_tools._list_code_files`-backed `files()` are Python's; the
/// module grouping for `/graph/affected` (`_modules_for_files`).
fn modules_for_files(files: &[String]) -> Vec<Value> {
    let mut counts: std::collections::BTreeMap<String, usize> = std::collections::BTreeMap::new();
    for path in files {
        let parts: Vec<&str> = path.split('/').filter(|part| !part.is_empty()).collect();
        if parts.is_empty() {
            continue;
        }
        let take = parts.len().saturating_sub(1).clamp(1, 3);
        *counts.entry(parts[..take].join("/")).or_insert(0) += 1;
    }
    let mut modules: Vec<(String, usize)> = counts.into_iter().collect();
    modules.sort_by(|left, right| right.1.cmp(&left.1).then_with(|| left.0.cmp(&right.0)));
    modules
        .into_iter()
        .map(|(path, count)| json!({"path": path, "file_count": count}))
        .collect()
}

fn live_graph_affected(paths: &RagPaths, body: &Value) -> Result<Value, String> {
    let started = Instant::now();
    let repo_name = required_string(body, "repo")?;
    let limit = body.get("limit").and_then(Value::as_u64).unwrap_or(100) as usize;
    let repo = load_repo(paths, repo_name)?;
    // Python parity: explicit `files` win; otherwise `git diff --name-only <since>`.
    let mut changed_files: Vec<String> = body
        .get("files")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_owned)
                .collect()
        })
        .unwrap_or_default();
    if changed_files.is_empty() {
        let since = body.get("since").and_then(Value::as_str).unwrap_or("HEAD");
        changed_files = git_changed_files(&repo.path, since);
    }
    // affected = changed ∩ indexed (exact path membership).
    let indexed: std::collections::HashSet<String> = RagDatabase::open(paths)
        .and_then(|database| database.list_code_files(&repo.collection, 100_000))
        .map(|items| items.into_iter().map(|item| item.file_path).collect())
        .unwrap_or_default();
    let affected: Vec<String> = changed_files
        .iter()
        .filter(|path| indexed.contains(*path))
        .cloned()
        .collect();

    let test_anchor: Vec<String> = if affected.is_empty() {
        changed_files.clone()
    } else {
        affected.clone()
    };
    let tests: Vec<Value> = RagDatabase::open(paths)
        .and_then(|database| database.related_test_files(&repo.collection, &test_anchor, limit))
        .map(|items| {
            items
                .into_iter()
                .map(|item| serde_json::to_value(item).unwrap_or_default())
                .collect()
        })
        .unwrap_or_default();
    let module_anchor: Vec<String> = if affected.is_empty() {
        changed_files.clone()
    } else {
        affected.clone()
    };
    let modules = modules_for_files(&module_anchor);
    let stale = stale_index_files(paths, &repo, &affected);

    let mut risks: Vec<String> = Vec::new();
    if !changed_files.is_empty() && affected.is_empty() {
        risks.push(
            "Changed files were not found in the exact code index; index may be stale.".to_owned(),
        );
    }
    if !affected.is_empty() && tests.is_empty() {
        risks.push("No related tests identified for changed indexed files.".to_owned());
    }
    risks.extend(stale_risk(&stale));

    Ok(json!({
        "repo": repo.name, "changed_files": changed_files, "affected_files": affected,
        "tests": tests, "modules": modules, "risks": risks,
        "metrics": {
            "changed_file_count": changed_files.len(),
            "indexed_changed_file_count": affected.len(),
            "test_count": tests.len(),
            "stale_file_count": stale.len(),
        },
        "latency_ms": started.elapsed().as_secs_f64() * 1000.0,
    }))
}

/// Python `_git_changed_files`: `git diff --name-only <since>` (10s timeout).
fn git_changed_files(repo_path: &str, since: &str) -> Vec<String> {
    let output = std::process::Command::new("git")
        .args(["-C", repo_path, "diff", "--name-only", since])
        .output();
    match output {
        Ok(output) if output.status.success() => String::from_utf8_lossy(&output.stdout)
            .lines()
            .map(str::trim)
            .filter(|line| !line.is_empty())
            .map(str::to_owned)
            .collect(),
        _ => Vec::new(),
    }
}

fn live_project_understand(paths: &RagPaths, body: &Value) -> Result<Value, String> {
    let started = Instant::now();
    let query = required_string(body, "query")?;
    let repo = required_string(body, "repo")?;
    let files = live_graph_files(paths, &json!({"repo": repo, "query": query}))?;
    let context = live_context_pack(
        paths,
        &json!({"repo": repo, "query": query, "max_slices": body.get("max_slices").cloned().unwrap_or(json!(8))}),
    )?;
    let modules: Vec<_> = files["files"].as_array().into_iter().flatten().take(10).map(|item| json!({
        "name": item["file_path"], "path": item["file_path"], "summary": "indexed module", "score": item["score"],
    })).collect();
    Ok(
        json!({"repo": repo, "query": query, "modules": modules, "symbols": [],
        "slices": context["slices"], "total_source_tokens": context["total_source_tokens"],
        "latency_ms": started.elapsed().as_secs_f64() * 1000.0}),
    )
}

fn live_smart_search(paths: &RagPaths, body: &Value) -> Result<Value, String> {
    let started = Instant::now();
    let question = required_string(body, "question")?;
    let repo = body.get("repo").and_then(Value::as_str);
    let inferred = rag_agent::grounded_symbols(question, 8);
    let search = live_search(
        paths,
        &json!({"query": question, "repo": repo, "top_k": body.get("top_k").cloned().unwrap_or(json!(20))}),
    )?;
    let (definitions, usages) = if let Some(repo) = repo {
        let resolved = live_resolve(paths, &json!({"repo": repo, "symbols": inferred}), false)?;
        (resolved["definitions"].clone(), resolved["usages"].clone())
    } else {
        (json!([]), json!([]))
    };
    let candidates: Vec<_> = definitions
        .as_array()
        .into_iter()
        .flatten()
        .map(|item| {
            json!({
                "file_path": item["file_path"], "lines": item["lines"], "name": item["name"],
                "repo": item["repo"], "source": "definition", "summary": "",
            })
        })
        .collect();
    Ok(
        json!({"question": question, "inferred_symbols": inferred, "grounded_symbols": inferred,
        "definitions": definitions, "usages": usages, "semantic": search["results"], "related": [],
        "candidates": candidates, "candidates_total": candidates.len(), "repos_searched": repo.into_iter().collect::<Vec<_>>(),
        "vocab_anchors": [], "vocab_files": [], "symbol_inference_ms": 0.0,
        "latency_ms": started.elapsed().as_secs_f64() * 1000.0}),
    )
}

fn live_enumerate(paths: &RagPaths, body: &Value) -> Result<Value, String> {
    let limit = body
        .get("limit")
        .and_then(Value::as_u64)
        .unwrap_or(500)
        .clamp(1, 10_000) as u32;
    let filters = body.get("filters").cloned().unwrap_or(json!({}));
    let repo = body.get("repo").and_then(Value::as_str);
    let (_, chunks) = load_repo_chunks(paths, repo, limit.saturating_add(1))?;
    let fields = body
        .get("fields")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_else(|| {
            vec![
                json!("file_path"),
                json!("name"),
                json!("language"),
                json!("chunk_type"),
                json!("start_line"),
                json!("end_line"),
            ]
        });
    let mut results = Vec::new();
    for chunk in chunks {
        let value = serde_json::to_value(&chunk).map_err(|error| error.to_string())?;
        if filters.as_object().is_some_and(|expected| {
            expected
                .iter()
                .any(|(key, expected)| value.get(key) != Some(expected))
        }) {
            continue;
        }
        let mut selected = serde_json::Map::new();
        for field in &fields {
            if let Some(field) = field.as_str() {
                if let Some(value) = value.get(field) {
                    selected.insert(field.to_owned(), value.clone());
                }
            }
        }
        results.push(Value::Object(selected));
    }
    let truncated = results.len() > limit as usize;
    results.truncate(limit as usize);
    Ok(
        json!({"count": results.len(), "filters": filters, "results": results, "truncated": truncated}),
    )
}

fn live_index_start(paths: &RagPaths, body: &Value) -> Result<Value, String> {
    let result = live_index(paths, body)?;
    Ok(
        json!({"job_id": format!("completed-{:.0}", unix_timestamp() * 1000.0), "status": "completed", "result": result}),
    )
}

fn live_ask(paths: &RagPaths, body: &Value) -> Result<Value, String> {
    let started = Instant::now();
    let question = required_string(body, "question")?;
    let mut search_body = body.clone();
    search_body["query"] = json!(question);
    let search = live_search(paths, &search_body)?;
    let first = search["results"].as_array().and_then(|items| items.first());
    let Some(first) = first else {
        return Ok(
            json!({"question": question, "answer": "Insufficient indexed context to answer safely.",
            "citations": [], "model": "deterministic-fallback", "retrieval_ms": started.elapsed().as_secs_f64() * 1000.0,
            "generation_ms": 0.0, "latency_ms": started.elapsed().as_secs_f64() * 1000.0, "insufficient_context": true}),
        );
    };
    let citation = json!({"file_path": first["file_path"], "lines": first["lines"], "name": first["name"], "score": first["score"]});
    Ok(json!({"question": question,
        "answer": format!("The strongest indexed evidence is {} at {}.", first["name"].as_str().unwrap_or("the cited symbol"), first["citation"].as_str().unwrap_or("the cited location")),
        "citations": [citation], "model": "deterministic-fallback", "retrieval_ms": search["latency_ms"],
        "generation_ms": 0.0, "latency_ms": started.elapsed().as_secs_f64() * 1000.0, "insufficient_context": false}))
}

fn live_index(paths: &RagPaths, body: &Value) -> Result<Value, String> {
    let repo_path = std::path::PathBuf::from(required_string(body, "repo_path")?)
        .canonicalize()
        .map_err(|error| error.to_string())?;
    if !repo_path.is_dir() {
        return Err("repository path is not a directory".to_owned());
    }
    std::fs::create_dir_all(&paths.home).map_err(|error| error.to_string())?;
    let settings = rag_config::load_settings(paths)
        .map_err(|error| format!("configuration error: {error}"))?;
    let skip_dirs: Vec<_> = settings
        .index
        .skip_dirs
        .iter()
        .map(String::as_str)
        .collect();
    let files = rag_index::discover_files(&repo_path, None, &skip_dirs)
        .map_err(|error| error.to_string())?;
    let languages = body
        .get("languages")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_ascii_lowercase)
                .collect::<std::collections::BTreeSet<_>>()
        });
    let repo_name = body
        .get("repo_name")
        .and_then(Value::as_str)
        .filter(|name| !name.trim().is_empty())
        .map(str::to_owned)
        .or_else(|| {
            repo_path
                .file_name()
                .and_then(|name| name.to_str())
                .map(str::to_owned)
        })
        .ok_or_else(|| "repository name cannot be derived".to_owned())?;
    let collection = body
        .get("collection")
        .and_then(Value::as_str)
        .filter(|name| !name.trim().is_empty())
        .map(str::to_owned)
        .unwrap_or_else(|| format!("repo_{}", sanitize_name(&repo_name)));
    let full = body.get("full").and_then(Value::as_bool).unwrap_or(false);
    if full {
        let mut preflight_errors = Vec::new();
        for file in &files {
            let relative = file
                .strip_prefix(&repo_path)
                .unwrap_or(file)
                .to_string_lossy()
                .replace('\\', "/");
            let language = rag_index::chunker::detect_language(&relative).unwrap_or("unknown");
            if languages
                .as_ref()
                .is_some_and(|allowed| !allowed.contains(language))
            {
                continue;
            }
            if let Err(error) = rag_index::file_hash_bounded(file, settings.index.max_file_bytes) {
                preflight_errors.push(format!("{relative}: {error}"));
            }
        }
        if !preflight_errors.is_empty() {
            return Err(format!(
                "full lexical index aborted during file preflight: {}",
                preflight_errors.join("; ")
            ));
        }
    }
    let mut index = rag_index::LexicalIndex::open(paths.home.join("rag.db"))
        .map_err(|error| error.to_string())?;
    if full {
        match languages.as_ref() {
            Some(languages) if !languages.is_empty() => {
                for language in languages {
                    index
                        .delete_code_chunks_by_language(&collection, language)
                        .map_err(|error| error.to_string())?;
                }
            }
            _ => index
                .delete_code_chunks_by_collection(&collection)
                .map_err(|error| error.to_string())?,
        }
    }
    let mut files_processed = 0_usize;
    let mut files_skipped = 0_usize;
    let mut chunks_indexed = 0_usize;
    let mut errors = Vec::new();
    for file in files {
        let relative = file
            .strip_prefix(&repo_path)
            .unwrap_or(&file)
            .to_string_lossy()
            .replace('\\', "/");
        let language = rag_index::chunker::detect_language(&relative).unwrap_or("unknown");
        if languages
            .as_ref()
            .is_some_and(|allowed| !allowed.contains(language))
        {
            files_skipped += 1;
            continue;
        }
        let source = match rag_index::read_file_bounded(&file, settings.index.max_file_bytes) {
            Ok(bytes) => String::from_utf8_lossy(&bytes).into_owned(),
            Err(error) => {
                errors.push(format!("{relative}: {error}"));
                continue;
            }
        };
        let chunks = rag_index::chunk_code(
            &source,
            &relative,
            Some(language),
            settings.index.max_chunk_chars as usize,
        );
        let documents: Vec<_> = chunks
            .into_iter()
            .map(|chunk| rag_index::CodeDocument {
                chunk_id: chunk.chunk_id(),
                collection: collection.clone(),
                file_path: chunk.file_path,
                name: chunk.name,
                parent_name: chunk.parent_name,
                chunk_type: chunk.chunk_type.as_python_value().to_owned(),
                language: chunk.language,
                start_line: chunk.start_line,
                end_line: chunk.end_line,
                code: chunk.content,
            })
            .collect();
        chunks_indexed += index
            .replace_code_chunks_for_file(&collection, &relative, &documents)
            .map_err(|error| error.to_string())?;
        files_processed += 1;
    }
    let registry = RepoRegistry::open_writable(paths).map_err(|error| error.to_string())?;
    let previous_indexed_at = registry
        .get(&repo_name)
        .map_err(|error| error.to_string())?
        .and_then(|repo| repo.last_indexed);
    registry
        .upsert(&RepoInfo {
            name: repo_name,
            path: repo_path.to_string_lossy().to_string(),
            collection,
            last_indexed: if errors.is_empty() {
                Some(unix_timestamp().to_string())
            } else {
                previous_indexed_at
            },
            chunks_count: chunks_indexed as i64,
        })
        .map_err(|error| error.to_string())?;
    Ok(
        json!({"files_processed": files_processed, "chunks_indexed": chunks_indexed,
        "files_skipped": files_skipped, "files_deleted": 0, "errors": errors,
        "index_mode": "lexical_only", "dense_indexed": false}),
    )
}

fn sanitize_name(name: &str) -> String {
    name.chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() {
                character.to_ascii_lowercase()
            } else {
                '_'
            }
        })
        .collect::<String>()
        .trim_matches('_')
        .to_owned()
}

fn live_index_docs(paths: &RagPaths, body: &Value) -> Result<Value, String> {
    let docs_path = std::path::PathBuf::from(required_string(body, "docs_path")?)
        .canonicalize()
        .map_err(|error| error.to_string())?;
    std::fs::create_dir_all(&paths.home).map_err(|error| error.to_string())?;
    let collection = body
        .get("collection")
        .and_then(Value::as_str)
        .filter(|name| !name.trim().is_empty())
        .unwrap_or("doc_chunks")
        .to_owned();
    let full = body.get("full").and_then(Value::as_bool).unwrap_or(false);
    let settings = rag_config::load_settings(paths)
        .map_err(|error| format!("configuration error: {error}"))?;
    let files = discover_docs(&docs_path)?;
    let mut sources = Vec::with_capacity(files.len());
    let mut errors = Vec::new();
    for file in files {
        let relative = file
            .strip_prefix(&docs_path)
            .unwrap_or(&file)
            .to_string_lossy()
            .replace('\\', "/");
        let source = match rag_index::read_file_bounded(&file, settings.index.max_file_bytes) {
            Ok(bytes) => String::from_utf8_lossy(&bytes).into_owned(),
            Err(error) => {
                errors.push(format!("{relative}: {error}"));
                continue;
            }
        };
        sources.push((relative, source));
    }
    if full && !errors.is_empty() {
        return Err(format!(
            "full docs index aborted during file preflight: {}",
            errors.join("; ")
        ));
    }
    let mut index = rag_index::LexicalIndex::open(paths.home.join("rag.db"))
        .map_err(|error| error.to_string())?;
    if full {
        index
            .delete_code_chunks_by_collection(&collection)
            .map_err(|error| error.to_string())?;
    }
    let mut files_processed = 0_usize;
    let mut chunks_indexed = 0_usize;
    for (relative, source) in sources {
        let chunks = rag_index::chunk_code(
            &source,
            &relative,
            Some("markdown"),
            settings.index.max_chunk_chars as usize,
        );
        let documents: Vec<_> = chunks
            .into_iter()
            .map(|chunk| rag_index::CodeDocument {
                chunk_id: chunk.chunk_id(),
                collection: collection.clone(),
                file_path: chunk.file_path,
                name: chunk.name,
                parent_name: chunk.parent_name,
                chunk_type: "document".to_owned(),
                language: "markdown".to_owned(),
                start_line: chunk.start_line,
                end_line: chunk.end_line,
                code: chunk.content,
            })
            .collect();
        chunks_indexed += index
            .replace_code_chunks_for_file(&collection, &relative, &documents)
            .map_err(|error| error.to_string())?;
        files_processed += 1;
    }
    Ok(
        json!({"files_processed": files_processed, "chunks_indexed": chunks_indexed,
        "files_skipped": 0, "files_deleted": 0, "errors": errors}),
    )
}

fn discover_docs(root: &std::path::Path) -> Result<Vec<std::path::PathBuf>, String> {
    let mut pending = vec![root.to_path_buf()];
    let mut files = Vec::new();
    while let Some(path) = pending.pop() {
        let metadata = std::fs::symlink_metadata(&path).map_err(|error| error.to_string())?;
        if metadata.file_type().is_symlink() {
            continue;
        }
        if metadata.is_file() {
            let supported = path
                .extension()
                .and_then(|extension| extension.to_str())
                .is_some_and(|extension| {
                    matches!(
                        extension.to_ascii_lowercase().as_str(),
                        "md" | "mdx" | "txt" | "rst"
                    )
                });
            if supported {
                files.push(path);
            }
            continue;
        }
        if !metadata.is_dir() {
            continue;
        }
        for entry in std::fs::read_dir(&path).map_err(|error| error.to_string())? {
            let entry = entry.map_err(|error| error.to_string())?;
            if entry.file_name().to_string_lossy().starts_with('.') {
                continue;
            }
            if !entry
                .file_type()
                .map_err(|error| error.to_string())?
                .is_symlink()
            {
                pending.push(entry.path());
            }
        }
    }
    files.sort();
    Ok(files)
}

fn load_repo(paths: &RagPaths, name: &str) -> Result<RepoInfo, String> {
    RepoRegistry::open(paths)
        .map_err(|error| error.to_string())?
        .get(name)
        .map_err(|error| error.to_string())?
        .ok_or_else(|| format!("repository not found: {name}"))
}

fn load_repo_chunks(
    paths: &RagPaths,
    name: Option<&str>,
    limit: u32,
) -> Result<(RepoInfo, Vec<CodeChunk>), String> {
    let repo = if let Some(name) = name {
        load_repo(paths, name)?
    } else {
        RepoInfo {
            name: "default".to_owned(),
            path: String::new(),
            collection: "code_chunks".to_owned(),
            last_indexed: None,
            chunks_count: 0,
        }
    };
    let chunks = RagDatabase::open(paths)
        .map_err(|error| error.to_string())?
        .code_chunks(&repo.collection, limit)
        .map_err(|error| error.to_string())?;
    Ok((repo, chunks))
}

fn required_string<'a>(body: &'a Value, key: &str) -> Result<&'a str, String> {
    body.get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| format!("missing required field: {key}"))
}

fn query_terms(query: &str) -> Vec<String> {
    query
        .split(|character: char| !character.is_alphanumeric() && character != '_')
        .filter(|term| term.len() >= 2)
        .map(str::to_ascii_lowercase)
        .collect()
}

fn score_chunk(chunk: CodeChunk, terms: &[String]) -> Option<(f64, CodeChunk)> {
    if terms.is_empty() {
        return None;
    }
    let name = chunk.name.to_ascii_lowercase();
    let haystack = format!(
        "{}\n{}\n{}",
        name,
        chunk.file_path.to_ascii_lowercase(),
        chunk.code.to_ascii_lowercase()
    );
    let matches = terms
        .iter()
        .filter(|term| haystack.contains(term.as_str()))
        .count();
    if matches == 0 {
        return None;
    }
    let exact_bonus = terms.iter().any(|term| term == &name) as u8 as f64;
    Some((matches as f64 / terms.len() as f64 + exact_bonus, chunk))
}

fn chunk_json(repo: &str, chunk: &CodeChunk, score: f64) -> Value {
    json!({"file_path": chunk.file_path, "name": chunk.name, "parent_name": chunk.parent_name,
        "chunk_type": chunk.chunk_type, "language": chunk.language, "lines": format!("{}-{}", chunk.start_line, chunk.end_line),
        "code": chunk.code, "score": score, "repo": repo, "matched_queries": [0],
        "citation": format!("{}:{}-{} ({})", chunk.file_path, chunk.start_line, chunk.end_line, chunk.name)})
}

fn add_repo_to_items(value: &mut Value, repo: &str) {
    if let Some(items) = value.as_array_mut() {
        for item in items {
            if let Some(object) = item.as_object_mut() {
                object.insert("repo".to_owned(), json!(repo));
            }
        }
    }
}

fn response_for(path: &str, body: Option<&Value>) -> Value {
    match path {
        "/search" => fixture_with_field("search.json", "query", body, "query"),
        "/resolve" => fixture("resolve.json"),
        "/context-pack" => fixture_with_field("context-pack.json", "query", body, "query"),
        "/smart-search" => fixture_with_field("smart-search.json", "question", body, "question"),
        "/ask" => json!({
            "question": body.and_then(|v| v.get("question")).cloned().unwrap_or(json!("")),
            "answer": "Insufficient indexed context to answer safely.",
            "citations": [], "model": "deterministic-fallback", "retrieval_ms": 0.0,
            "generation_ms": 0.0, "latency_ms": 0.0, "insufficient_context": true,
        }),
        "/collections" => json!([]),
        // Python response shapes (objects, not bare arrays).
        "/plugins" => json!({"plugins": []}),
        "/files/recent" => json!({"files": []}),
        "/index/jobs" => json!({"jobs": {}}),
        "/queries/recent" => json!({"queries": []}),
        "/queries/stats" => {
            json!({"count": 0, "p50_ms": 0, "p95_ms": 0, "qpm": 0.0, "avg_results": 0.0})
        }
        "/events/recent" => json!({"events": []}),
        "/health/detail" => json!({
            "status": "degraded", "components": HealthResponse::r0().components,
            "checks": [],
        }),
        "/stack" | "/overview/tui" => json!({
            "daemon": "running", "ollama": "unavailable", "qdrant": "unavailable",
        }),
        "/overview" => json!({"languages": {}, "patterns": {}, "complexity": {}}),
        "/repos" => json!({"repos": []}),
        "/diagnose" => json!({"status": "degraded", "checks": []}),
        "/stack/qdrant/start" => {
            json!({"started": false, "detail": "managed Qdrant is not configured"})
        }
        "/index/start" => json!({"job_id": "", "status": "queued"}),
        "/index/backfill-code-index" => {
            json!({"collection": "", "chunks_indexed": 0, "chunks_skipped": 0, "latency_ms": 0.0})
        }
        "/docs-search" => {
            json!({"query": body_field(body, "query"), "results": [], "total": 0, "latency_ms": 0.0})
        }
        "/vocab/build" => {
            json!({"repo": body_field(body, "repo"), "terms": 0, "files": 0, "latency_ms": 0.0})
        }
        "/call-tree" => {
            json!({"repo": body_field(body, "repo"), "symbol": body_field(body, "symbol"), "nodes": [], "total": 0, "latency_ms": 0.0})
        }
        "/graph/files" => {
            json!({"repo": body_field(body, "repo"), "query": body_field(body, "query"), "files": [], "total": 0, "latency_ms": 0.0})
        }
        "/graph/node" => {
            json!({"repo": body_field(body, "repo"), "symbol": body_field(body, "symbol"), "definitions": [], "usages": [], "total_definitions": 0, "total_usages": 0, "provenance": "ast_index", "latency_ms": 0.0})
        }
        "/graph/callers" | "/graph/callees" => {
            json!({"repo": body_field(body, "repo"), "symbol": body_field(body, "symbol"), "relation": path.rsplit('/').next().unwrap_or_default(), "nodes": [], "total": 0, "relation_source": "ast_index", "latency_ms": 0.0})
        }
        "/graph/impact" => {
            json!({"repo": body_field(body, "repo"), "symbol": body_field(body, "symbol"), "definitions": [], "usages": [], "callers": [], "affected_files": [], "tests": [], "risks": [], "metrics": {}, "latency_ms": 0.0})
        }
        "/graph/affected" => {
            json!({"repo": body_field(body, "repo"), "changed_files": body.and_then(|v| v.get("files")).cloned().unwrap_or(json!([])), "affected_files": [], "tests": [], "modules": [], "risks": [], "metrics": {}, "latency_ms": 0.0})
        }
        "/project-understand" => {
            json!({"repo": body_field(body, "repo"), "query": body_field(body, "query"), "modules": [], "symbols": [], "slices": [], "total_source_tokens": 0, "latency_ms": 0.0})
        }
        "/enumerate" => {
            json!({"count": 0, "filters": body.and_then(|v| v.get("filters")).cloned().unwrap_or(json!({})), "results": [], "truncated": false})
        }
        "/index" | "/index/docs" => {
            json!({"files_processed": 0, "chunks_indexed": 0, "files_skipped": 0, "files_deleted": 0, "errors": []})
        }
        "/admin/reload" => {
            json!({"reloaded": true, "embedder_reinitialized": false, "reranker_reinitialized": false, "detail": "configuration reloaded"})
        }
        "/admin/export" => json!({"exported": 0, "records": []}),
        "/admin/import" => json!({"imported": 0, "errors": []}),
        "/admin/verify" => json!({"ok": true, "orphans": 0, "duplicates": 0, "errors": []}),
        "/admin/repair" => json!({"removed_orphans": 0, "removed_duplicates": 0, "errors": []}),
        "/diff" => {
            json!({"query": body_field(body, "query"), "results": [], "total": 0, "latency_ms": 0.0})
        }
        _ => json!({}),
    }
}

fn requires_live_backend(path: &str) -> bool {
    matches!(
        path,
        "/search"
            | "/docs-search"
            | "/resolve"
            | "/vocab/build"
            | "/smart-search"
            | "/call-tree"
            | "/graph/files"
            | "/graph/node"
            | "/graph/callers"
            | "/graph/callees"
            | "/graph/impact"
            | "/graph/affected"
            | "/project-understand"
            | "/context-pack"
            | "/enumerate"
            | "/ask"
            | "/index"
            | "/index/docs"
            | "/index/start"
            | "/index/backfill-code-index"
    )
}

fn fixture(name: &str) -> Value {
    let raw = match name {
        "search.json" => include_str!("../../../tests/contracts/search.json"),
        "resolve.json" => include_str!("../../../tests/contracts/resolve.json"),
        "context-pack.json" => include_str!("../../../tests/contracts/context-pack.json"),
        "smart-search.json" => include_str!("../../../tests/contracts/smart-search.json"),
        _ => "{}",
    };
    serde_json::from_str(raw).expect("checked-in contract fixture is valid JSON")
}

fn fixture_with_field(name: &str, output: &str, body: Option<&Value>, input: &str) -> Value {
    let mut value = fixture(name);
    if let Some(field) = body.and_then(|item| item.get(input)) {
        value[output] = field.clone();
    }
    value
}

fn body_field(body: Option<&Value>, field: &str) -> Value {
    body.and_then(|value| value.get(field))
        .cloned()
        .unwrap_or(json!(""))
}

/// FastAPI-style validation rejection: `{"detail": [{loc, msg, type}]}`.
fn validation_422(field: &str, msg: &str, error_type: &str) -> Response {
    (
        StatusCode::UNPROCESSABLE_ENTITY,
        Json(json!({
            "detail": [{"loc": ["body", field], "msg": msg, "type": error_type}]
        })),
    )
        .into_response()
}

/// Python request-model parity: pydantic bounds that FastAPI enforces with a
/// 422 before any handler runs. Rust previously clamped these silently.
fn validate_request_contract(path: &str, body: &Value) -> Option<Response> {
    if matches!(
        path,
        "/admin/import" | "/admin/reload" | "/admin/repair" | "/index/backfill-code-index"
    ) {
        let detail = match path {
            "/admin/import" => {
                "Import is disabled because the current export format omits vectors and is not a restorable backup"
            }
            "/admin/reload" => {
                "Live configuration reload is not implemented; restart the supervised daemon to apply validated settings"
            }
            "/admin/repair" => {
                "Automatic repair is not implemented safely; run verify and use an explicit reindex or snapshot restore"
            }
            _ => {
                "Qdrant-to-SQLite backfill is not implemented by the Rust server; run a full verified reindex"
            }
        };
        return Some(api_error(
            StatusCode::NOT_IMPLEMENTED,
            detail,
            "NOT_IMPLEMENTED",
        ));
    }
    for field in ["query", "question", "symbol"] {
        if let Some(text) = body.get(field).and_then(Value::as_str) {
            if text.chars().count() > MAX_QUERY_LENGTH {
                return Some(validation_422(
                    field,
                    &format!("ensure this value has at most {MAX_QUERY_LENGTH} characters"),
                    "value_error.any_str.max_length",
                ));
            }
        }
    }
    if let Some(top_k) = body.get("top_k").filter(|value| !value.is_null()) {
        let Some(value) = top_k.as_i64() else {
            return Some(validation_422(
                "top_k",
                "value is not a valid integer",
                "type_error.integer",
            ));
        };
        let ceiling: i64 = if path == "/ask" { 20 } else { 200 };
        if value < 1 {
            return Some(validation_422(
                "top_k",
                "ensure this value is greater than or equal to 1",
                "value_error.number.not_ge",
            ));
        }
        if value > ceiling {
            return Some(validation_422(
                "top_k",
                &format!("ensure this value is less than or equal to {ceiling}"),
                "value_error.number.not_le",
            ));
        }
    }
    if path == "/search" {
        if let Some(planner) = body.get("planner").and_then(Value::as_str) {
            if !matches!(planner, "auto" | "llm" | "fallback") {
                return Some(validation_422(
                    "planner",
                    "string does not match regex \"^(auto|llm|fallback)$\"",
                    "value_error.str.regex",
                ));
            }
        }
    }
    if path == "/smart-search" {
        if body.get("repos").is_some_and(|value| !value.is_null()) {
            return Some(validation_422(
                "repos",
                "multi-repository smart search is not implemented by the Rust server; send one repo per request",
                "value_error.unsupported",
            ));
        }
        let has_repo = body
            .get("repo")
            .and_then(Value::as_str)
            .is_some_and(|value| !value.trim().is_empty());
        if !has_repo {
            return Some(validation_422("repo", "Provide repo", "value_error"));
        }
    }
    if path == "/context-pack" {
        for field in ["repo", "query"] {
            if body
                .get(field)
                .and_then(Value::as_str)
                .is_none_or(|value| value.trim().is_empty())
            {
                return Some(validation_422(
                    field,
                    "field required",
                    "value_error.missing",
                ));
            }
        }
        for field in ["use_ast_index", "include_semantic"] {
            if body.get(field).is_some_and(|value| !value.is_boolean()) {
                return Some(validation_422(
                    field,
                    "value is not a valid boolean",
                    "type_error.bool",
                ));
            }
        }
        if body
            .get("filters")
            .is_some_and(|value| !value.is_null() && !value.is_object())
        {
            return Some(validation_422(
                "filters",
                "value is not a valid object",
                "type_error.dict",
            ));
        }
        if let Some(strategy) = body.get("strategy") {
            match strategy.as_str() {
                Some("lod_drill") => {}
                Some(_) => {
                    return Some(validation_422(
                        "strategy",
                        "only the deterministic lod_drill strategy is implemented",
                        "value_error.unsupported",
                    ))
                }
                None => {
                    return Some(validation_422(
                        "strategy",
                        "value is not a valid string",
                        "type_error.string",
                    ))
                }
            }
        }
        for (field, minimum, maximum) in [
            ("max_slices", 1, 50),
            ("max_source_tokens", 100, 100_000),
            ("max_source_bytes", 64, 4 * 1024 * 1024),
        ] {
            if let Some(raw) = body.get(field) {
                let Some(value) = raw.as_u64() else {
                    return Some(validation_422(
                        field,
                        "value is not a valid integer",
                        "type_error.integer",
                    ));
                };
                if value < minimum {
                    return Some(validation_422(
                        field,
                        &format!("ensure this value is greater than or equal to {minimum}"),
                        "value_error.number.not_ge",
                    ));
                }
                if value > maximum {
                    return Some(validation_422(
                        field,
                        &format!("ensure this value is less than or equal to {maximum}"),
                        "value_error.number.not_le",
                    ));
                }
            }
        }
    }
    None
}

#[allow(dead_code)]
fn contains_oversized_query(value: &Value) -> bool {
    ["query", "question", "symbol"]
        .iter()
        .filter_map(|key| value.get(key).and_then(Value::as_str))
        .any(|text| text.len() > MAX_QUERY_LENGTH)
}

async fn authenticate_and_limit(
    State(state): State<ServerState>,
    request: Request,
    next: Next,
) -> Response {
    let bearer = request
        .headers()
        .get(header::AUTHORIZATION)
        .and_then(|value| value.to_str().ok())
        .and_then(parse_bearer);
    if let Some(expected) = state.token.as_deref() {
        if bearer.is_none_or(|actual| !constant_time_eq(actual.as_bytes(), expected.as_bytes())) {
            return api_error(
                StatusCode::UNAUTHORIZED,
                "Invalid or missing token",
                "HTTP_ERROR",
            );
        }
    }
    if !consume_rate_limit(&state, bearer.unwrap_or("anonymous")) {
        return api_error(
            StatusCode::TOO_MANY_REQUESTS,
            "Rate limit exceeded",
            "RATE_LIMITED",
        );
    }
    next.run(request).await
}

fn consume_rate_limit(state: &ServerState, key: &str) -> bool {
    let now = Instant::now();
    let mut windows = state.rate_windows.lock().expect("rate limit lock poisoned");
    let entry = windows.entry(key.to_owned()).or_insert((now, 0));
    if now.duration_since(entry.0) >= Duration::from_secs(60) {
        *entry = (now, 0);
    }
    if entry.1 >= state.rate_limit {
        return false;
    }
    entry.1 += 1;
    true
}

async fn record_request(
    State(state): State<ServerState>,
    request: Request,
    next: Next,
) -> Response {
    let request_id = request
        .extensions()
        .get::<RequestId>()
        .map(|value| value.0.clone())
        .unwrap_or_default();
    let method = request.method().clone();
    let path = request.uri().path().to_owned();
    let started = Instant::now();
    let response = next.run(request).await;
    let status = response.status().as_u16();
    let latency_ms = started.elapsed().as_secs_f64() * 1000.0;
    state.push_event(json!({
        "event": "http_request",
        "method": method.as_str(),
        "path": path,
        "status": status,
        "latency_ms": latency_ms,
        "request_id": request_id,
        "ts": unix_timestamp(),
    }));
    // Python parity: requests also land in the durable structured log so the
    // TUI crash tail and post-mortems survive the process.
    let mut fields = serde_json::Map::new();
    fields.insert("method".to_owned(), json!(method.as_str()));
    fields.insert("path".to_owned(), json!(path));
    fields.insert("status".to_owned(), json!(status));
    fields.insert(
        "latency_ms".to_owned(),
        json!((latency_ms * 10.0).round() / 10.0),
    );
    fields.insert("request_id".to_owned(), json!(request_id));
    let level = if status >= 500 { "error" } else { "info" };
    log_daemon_event(state.rag_paths.as_ref(), level, "http_request", fields);
    response
}

/// Best-effort JSON line into `~/.rag/logs/daemon.jsonl` (Python
/// `logging_setup` parity: `event`/`level`/`timestamp` keys, ~10 MB rotation).
fn log_daemon_event(
    paths: Option<&RagPaths>,
    level: &str,
    event: &str,
    mut fields: serde_json::Map<String, Value>,
) {
    let Some(paths) = paths else { return };
    let log_dir = paths.home.join("logs");
    let log_path = log_dir.join("daemon.jsonl");
    fields.insert("event".to_owned(), json!(event));
    fields.insert("level".to_owned(), json!(level));
    fields.insert(
        "timestamp".to_owned(),
        json!(chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, true)),
    );
    let line = Value::Object(fields).to_string();
    let _ = std::fs::create_dir_all(&log_dir);
    if let Ok(metadata) = std::fs::metadata(&log_path) {
        if metadata.len() > 10 * 1024 * 1024 {
            let _ = std::fs::rename(&log_path, log_dir.join("daemon.jsonl.1"));
        }
    }
    if let Ok(mut file) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
    {
        use std::io::Write;
        let _ = writeln!(file, "{line}");
    }
}

async fn trusted_host(request: Request, next: Next) -> Response {
    if is_trusted_host(request.headers()) {
        next.run(request).await
    } else {
        api_error(
            StatusCode::FORBIDDEN,
            "Untrusted Host header",
            "HOST_BLOCKED",
        )
    }
}

fn api_error(status: StatusCode, error: &str, code: &str) -> Response {
    (
        status,
        Json(ErrorResponse {
            error: error.to_owned(),
            code: code.to_owned(),
            detail: None,
        }),
    )
        .into_response()
}

fn is_trusted_host(headers: &HeaderMap) -> bool {
    let Some(raw_host) = headers
        .get(header::HOST)
        .and_then(|value| value.to_str().ok())
    else {
        return false;
    };
    let Ok(authority) = raw_host.parse::<http::uri::Authority>() else {
        return false;
    };
    let raw_host = authority.host();
    let host = raw_host
        .strip_prefix('[')
        .and_then(|value| value.strip_suffix(']'))
        .unwrap_or(raw_host);
    host.eq_ignore_ascii_case("localhost")
        || host.eq_ignore_ascii_case("testserver")
        || host
            .parse::<std::net::IpAddr>()
            .is_ok_and(|address| address.is_loopback())
}

/// Extract a bearer credential using the Python server's whitespace and casing rules.
#[must_use]
pub fn parse_bearer(value: &str) -> Option<&str> {
    let value = value.trim();
    let split = value.find(char::is_whitespace)?;
    let (scheme, credential) = value.split_at(split);
    let credential = credential.trim();
    if scheme.eq_ignore_ascii_case("bearer") && !credential.is_empty() {
        Some(credential)
    } else {
        None
    }
}

fn constant_time_eq(left: &[u8], right: &[u8]) -> bool {
    if left.len() != right.len() {
        return false;
    }
    left.iter()
        .zip(right)
        .fold(0_u8, |diff, (a, b)| diff | (a ^ b))
        == 0
}

fn unix_timestamp() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}

/// Server startup/runtime failures.
#[derive(Debug, Error)]
pub enum ServerError {
    /// Socket bind or HTTP serving failure.
    #[error("Rust daemon server error: {0}")]
    Io(#[from] std::io::Error),
    /// RAG home, token, dotenv, or settings initialization failed.
    #[error("Rust daemon configuration error: {0}")]
    Config(#[from] rag_config::ConfigError),
    /// A requested managed dependency could not be started safely.
    #[error("Rust daemon startup error: {0}")]
    Startup(String),
}

#[cfg(test)]
mod tests {
    use axum::body::{to_bytes, Body};
    use http::{header, Request, StatusCode};
    use rag_contracts::{ErrorResponse, HealthResponse};
    use serde_json::{json, Value};
    use tower::ServiceExt;

    use super::{
        bootstrap_rag_home, live_context_pack, parse_bearer, router, router_with_state,
        try_acquire_request_slot, ServerState, REQUEST_ID_HEADER,
    };

    fn request(method: &str, uri: &str) -> http::request::Builder {
        Request::builder()
            .method(method)
            .uri(uri)
            .header(header::HOST, "127.0.0.1:7891")
    }

    #[test]
    fn parses_bearer_like_python() {
        assert_eq!(parse_bearer("Bearer secret"), Some("secret"));
        assert_eq!(parse_bearer("bearer\t secret "), Some("secret"));
        assert_eq!(
            parse_bearer("BEARER a token with spaces"),
            Some("a token with spaces")
        );
        assert_eq!(parse_bearer("Basic secret"), None);
        assert_eq!(parse_bearer("Bearer"), None);
    }

    #[test]
    fn bootstrap_fails_when_the_rag_home_cannot_be_created() {
        let temp = tempfile::tempdir().unwrap();
        let home = temp.path().join("not-a-directory");
        std::fs::write(&home, "occupied").unwrap();

        let error = bootstrap_rag_home(&rag_config::RagPaths::from_home(home))
            .expect_err("startup must fail closed");
        assert!(error.to_string().contains("create RAG home"));
    }

    #[tokio::test]
    async fn health_is_public_and_matches_contract() {
        let response = router()
            .oneshot(request("GET", "/health").body(Body::empty()).unwrap())
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
        let health: HealthResponse = serde_json::from_slice(&body).unwrap();
        assert_eq!(health, HealthResponse::r0());
    }

    #[tokio::test]
    async fn capability_discovery_is_public_and_machine_readable() {
        let response = router()
            .oneshot(
                request("GET", "/.well-known/rag-capabilities")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let body: Value =
            serde_json::from_slice(&to_bytes(response.into_body(), usize::MAX).await.unwrap())
                .unwrap();
        assert_eq!(body["capabilities"]["context_pack"]["provenance"], true);
        assert_eq!(
            body["capabilities"]["context_pack"]["content_digests"],
            "sha256"
        );
    }

    #[tokio::test]
    async fn liveness_is_cheap_and_readiness_fails_without_backends() {
        let live = router_with_state(ServerState::new(None))
            .oneshot(request("GET", "/live").body(Body::empty()).unwrap())
            .await
            .unwrap();
        assert_eq!(live.status(), StatusCode::OK);

        let ready = router_with_state(ServerState::new(None))
            .oneshot(request("GET", "/ready").body(Body::empty()).unwrap())
            .await
            .unwrap();
        assert_eq!(ready.status(), StatusCode::SERVICE_UNAVAILABLE);
    }

    #[tokio::test]
    async fn request_ids_are_echoed_or_generated_on_every_response() {
        let echoed = router()
            .oneshot(
                request("GET", "/health")
                    .header(REQUEST_ID_HEADER, "agent-turn-42")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(echoed.headers()[REQUEST_ID_HEADER], "agent-turn-42");

        let generated = router()
            .oneshot(request("GET", "/health").body(Body::empty()).unwrap())
            .await
            .unwrap();
        let id = generated.headers()[REQUEST_ID_HEADER].to_str().unwrap();
        assert!(uuid::Uuid::parse_str(id).is_ok());
    }

    #[tokio::test]
    async fn smart_search_rejects_unsupported_multi_repo_instead_of_ignoring_it() {
        let response = router()
            .oneshot(
                request("POST", "/smart-search")
                    .header(header::CONTENT_TYPE, "application/json")
                    .body(Body::from(
                        json!({"question": "where is auth?", "repos": ["one", "two"]}).to_string(),
                    ))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
        let body: Value =
            serde_json::from_slice(&to_bytes(response.into_body(), usize::MAX).await.unwrap())
                .unwrap();
        assert_eq!(body["detail"][0]["loc"][1], "repos");
    }

    #[tokio::test]
    async fn import_is_rejected_instead_of_reporting_a_fake_success() {
        let response = router()
            .oneshot(
                request("POST", "/admin/import")
                    .header(header::CONTENT_TYPE, "application/json")
                    .body(Body::from(json!({"records": []}).to_string()))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::NOT_IMPLEMENTED);
        let error: ErrorResponse =
            serde_json::from_slice(&to_bytes(response.into_body(), usize::MAX).await.unwrap())
                .unwrap();
        assert_eq!(error.code, "NOT_IMPLEMENTED");
    }

    #[tokio::test]
    async fn unimplemented_mutations_fail_explicitly_instead_of_claiming_success() {
        for path in [
            "/admin/reload",
            "/admin/repair",
            "/index/backfill-code-index",
        ] {
            let response = router()
                .oneshot(
                    request("POST", path)
                        .header(header::CONTENT_TYPE, "application/json")
                        .body(Body::from("{}"))
                        .unwrap(),
                )
                .await
                .unwrap();
            assert_eq!(response.status(), StatusCode::NOT_IMPLEMENTED, "{path}");
        }
    }

    #[test]
    fn protected_request_concurrency_is_bounded() {
        let state = ServerState::new(None).with_max_in_flight(1);
        let first = try_acquire_request_slot(&state).expect("first permit");
        assert!(try_acquire_request_slot(&state).is_none());
        drop(first);
        assert!(try_acquire_request_slot(&state).is_some());
    }

    #[test]
    fn context_pack_enforces_byte_budget_with_provenance_deterministically() {
        use rag_index::{CodeDocument, LexicalIndex};
        use rag_storage::{RepoInfo, RepoRegistry};

        let temp = tempfile::tempdir().unwrap();
        let paths = rag_config::RagPaths::from_home(temp.path().join("rag-home"));
        std::fs::create_dir_all(&paths.home).unwrap();
        let repo_path = temp.path().join("repo");
        std::fs::create_dir(&repo_path).unwrap();
        RepoRegistry::open_writable(&paths)
            .unwrap()
            .upsert(&RepoInfo {
                name: "sample".to_owned(),
                path: repo_path.to_string_lossy().into_owned(),
                collection: "repo_sample".to_owned(),
                last_indexed: Some("2026-07-18T10:00:00Z".to_owned()),
                chunks_count: 2,
            })
            .unwrap();
        let mut index = LexicalIndex::open(paths.home.join("rag.db")).unwrap();
        index
            .upsert_code_chunks(&[
                CodeDocument {
                    chunk_id: "auth-a".to_owned(),
                    collection: "repo_sample".to_owned(),
                    file_path: "src/auth.rs".to_owned(),
                    name: "authenticate".to_owned(),
                    parent_name: String::new(),
                    chunk_type: "function".to_owned(),
                    language: "rust".to_owned(),
                    start_line: 10,
                    end_line: 20,
                    code: format!("fn authenticate() {{ {} }}", "verify_token(); ".repeat(40)),
                },
                CodeDocument {
                    chunk_id: "auth-b".to_owned(),
                    collection: "repo_sample".to_owned(),
                    file_path: "src/session.rs".to_owned(),
                    name: "session_authentication".to_owned(),
                    parent_name: String::new(),
                    chunk_type: "function".to_owned(),
                    language: "rust".to_owned(),
                    start_line: 1,
                    end_line: 4,
                    code: "fn session_authentication() { authenticate(); }".repeat(8),
                },
            ])
            .unwrap();

        let request = json!({
            "repo": "sample",
            "query": "authentication",
            "max_slices": 2,
            "max_source_tokens": 100,
            "max_source_bytes": 128,
            "use_ast_index": false,
        });
        let first = live_context_pack(&paths, &request).unwrap();
        let second = live_context_pack(&paths, &request).unwrap();

        assert!(first["total_source_bytes"].as_u64().unwrap() <= 128);
        assert!(first["total_source_tokens"].as_u64().unwrap() <= 100);
        assert_eq!(first["truncated"], true);
        assert_eq!(first["slices"], second["slices"]);
        assert_eq!(first["slices"][0]["provenance"]["source"], "sqlite_fts");
        assert_eq!(
            first["slices"][0]["content_sha256"].as_str().unwrap().len(),
            64
        );
    }

    #[tokio::test]
    async fn context_pack_rejects_non_integer_budgets() {
        let response = router()
            .oneshot(
                request("POST", "/context-pack")
                    .header(header::CONTENT_TYPE, "application/json")
                    .body(Body::from(
                        json!({
                            "repo": "sample",
                            "query": "auth",
                            "max_source_bytes": "unbounded"
                        })
                        .to_string(),
                    ))
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
    }

    #[tokio::test]
    async fn protected_routes_require_token_and_keep_contract_shape() {
        let app =
            router_with_state(ServerState::new(Some("secret".to_owned())).with_contract_fixtures());
        let denied = app
            .clone()
            .oneshot(request("GET", "/status").body(Body::empty()).unwrap())
            .await
            .unwrap();
        assert_eq!(denied.status(), StatusCode::UNAUTHORIZED);

        let allowed = app
            .oneshot(
                request("POST", "/search")
                    .header(header::AUTHORIZATION, "Bearer secret")
                    .header(header::CONTENT_TYPE, "application/json")
                    .body(Body::from(r#"{"query":"custom"}"#))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(allowed.status(), StatusCode::OK);
        let value: Value =
            serde_json::from_slice(&to_bytes(allowed.into_body(), usize::MAX).await.unwrap())
                .unwrap();
        assert_eq!(value["query"], "custom");
        assert!(value["results"].is_array());
    }

    #[tokio::test]
    async fn production_mode_never_returns_captured_results_as_live_data() {
        let response = router_with_state(ServerState::new(None))
            .oneshot(
                request("POST", "/search")
                    .header(header::CONTENT_TYPE, "application/json")
                    .body(Body::from(r#"{"query":"zzzz_no_contract_fixture_7f30de"}"#))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert!(matches!(
            response.status(),
            StatusCode::OK | StatusCode::SERVICE_UNAVAILABLE
        ));
        let status = response.status();
        let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
        let value: Value = serde_json::from_slice(&body).unwrap();
        if status == StatusCode::OK {
            assert_eq!(value["query"], "zzzz_no_contract_fixture_7f30de");
            assert_eq!(value["total"], 0);
            assert!(value["results"].as_array().unwrap().is_empty());
        } else {
            assert_eq!(value["code"], "BACKEND_NOT_READY");
        }
    }

    #[tokio::test]
    async fn code_indexing_without_dense_backend_is_explicitly_lexical_only() {
        let temp = tempfile::tempdir().unwrap();
        let repo = temp.path().join("repo");
        std::fs::create_dir(&repo).unwrap();
        std::fs::write(repo.join("lib.rs"), "fn indexed() {}\n").unwrap();
        let app =
            router_with_state(ServerState::new(None).with_rag_home(temp.path().join("rag-home")));

        let response = app
            .oneshot(
                request("POST", "/index")
                    .header(header::CONTENT_TYPE, "application/json")
                    .body(Body::from(
                        json!({"repo_path": repo.to_string_lossy()}).to_string(),
                    ))
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::OK);
        let body: Value =
            serde_json::from_slice(&to_bytes(response.into_body(), usize::MAX).await.unwrap())
                .unwrap();
        assert_eq!(body["index_mode"], "lexical_only");
        assert_eq!(body["dense_indexed"], false);
    }

    #[tokio::test]
    async fn rate_limit_and_host_errors_use_stable_envelopes() {
        let app = router_with_state(ServerState::new(Some("secret".to_owned())).with_rate_limit(1));
        let authorized = || {
            request("GET", "/status")
                .header(header::AUTHORIZATION, "Bearer secret")
                .body(Body::empty())
                .unwrap()
        };
        assert_eq!(
            app.clone().oneshot(authorized()).await.unwrap().status(),
            StatusCode::OK
        );
        assert_eq!(
            app.clone().oneshot(authorized()).await.unwrap().status(),
            StatusCode::TOO_MANY_REQUESTS
        );

        let blocked = app
            .oneshot(
                Request::builder()
                    .uri("/health")
                    .header(header::HOST, "evil.example.com")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        let body = to_bytes(blocked.into_body(), usize::MAX).await.unwrap();
        let error: ErrorResponse = serde_json::from_slice(&body).unwrap();
        assert_eq!(error.code, "HOST_BLOCKED");
    }

    #[tokio::test]
    async fn captured_openapi_paths_are_served() {
        let response = router()
            .oneshot(request("GET", "/openapi.json").body(Body::empty()).unwrap())
            .await
            .unwrap();
        let value: Value =
            serde_json::from_slice(&to_bytes(response.into_body(), usize::MAX).await.unwrap())
                .unwrap();
        for path in ["/health", "/search", "/resolve", "/context-pack", "/ask"] {
            assert!(value["paths"].get(path).is_some(), "missing {path}");
        }
    }
}
