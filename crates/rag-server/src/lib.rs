//! Axum HTTP surface for the Rust daemon.

mod indexing;
mod qdrant_boot;
mod retrieval;
pub mod stack;

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
use http::{header, HeaderMap, StatusCode};
use rag_config::{RagPaths, ServerConfig};
use rag_contracts::{ErrorResponse, HealthResponse};
use rag_storage::{CodeChunk, RagDatabase, RepoInfo, RepoRegistry};
use serde_json::{json, Value};
use thiserror::Error;
use tokio::net::TcpListener;

/// Python parity (`server.MAX_QUERY_LENGTH`): longer queries are rejected
/// with a FastAPI-style 422, not silently accepted.
const MAX_QUERY_LENGTH: usize = 2_000;
const DEFAULT_RATE_LIMIT_PER_MINUTE: u32 = 120;
const MAX_EVENTS: usize = 1_000;
/// `retrieval_mode` marker for responses produced by the live dense pipeline
/// (Ollama embeddings + Qdrant). Clients use it to tell a full-quality answer
/// apart from the degraded one below, which shares the same JSON shape.
pub(crate) const DENSE_RETRIEVAL_MODE: &str = "dense";
/// `retrieval_mode` marker for responses produced by the SQLite keyword
/// fallback, which runs whenever the dense backend is not configured.
pub(crate) const LEXICAL_RETRIEVAL_MODE: &str = "lexical_fallback";
/// Fixed rate-limit window; entries older than this carry no information.
const RATE_LIMIT_WINDOW: Duration = Duration::from_secs(60);
/// Only sweep expired rate-limit windows once the map is larger than a
/// single-token daemon will ever make it.
const RATE_WINDOW_SWEEP_THRESHOLD: usize = 64;
/// Hard ceiling on live rate-limit windows, so a flood of distinct credentials
/// cannot grow the map without bound inside one window.
const RATE_WINDOW_MAX_ENTRIES: usize = 10_000;

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
    /// Ephemeral credential handed to the browser dashboard.
    ///
    /// `GET /` is necessarily unauthenticated — a browser has no way to
    /// present a bearer token for its first request — so whatever it embeds is
    /// readable by any local process that can reach the loopback port. It used
    /// to embed the durable `~/.rag/token`, which made a page fetch equivalent
    /// to reading that 0600 file: the credential kept working after a restart
    /// and authenticated the CLI and every other client too.
    ///
    /// This token is generated per process start and never persisted, so the
    /// same fetch now yields something that dies with the daemon. It is not a
    /// boundary against a local attacker who can simply keep using it while
    /// the daemon runs; it bounds the blast radius rather than removing it.
    /// Hosts where that is not good enough should set `server.dashboard = false`.
    dashboard_token: Arc<str>,
    /// Whether `GET /` serves the dashboard at all.
    dashboard_enabled: bool,
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
            dashboard_token: Arc::from(generate_token()),
            dashboard_enabled: true,
        }
    }

    /// Disable `GET /` entirely (config `server.dashboard = false`). Intended
    /// for multi-user hosts, where handing any working credential to every
    /// local account is not acceptable.
    #[must_use]
    pub fn with_dashboard(mut self, enabled: bool) -> Self {
        self.dashboard_enabled = enabled;
        self
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

    /// Take the event ring lock, recovering from poisoning.
    ///
    /// `record_request` runs this on *every* request, so `.expect()` here would
    /// let a single panic anywhere under the lock turn the whole daemon into a
    /// permanent 500 machine — the opposite of the degrade-never-500 contract.
    /// The guarded value is an append-only ring of independent JSON events: a
    /// panic mid-`push_back` can at worst leave one event missing or malformed,
    /// never a state the later reads cannot handle. Losing an event beats
    /// wedging the process.
    fn events_guard(&self) -> std::sync::MutexGuard<'_, VecDeque<Value>> {
        self.events
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    fn push_event(&self, event: Value) {
        let mut events = self.events_guard();
        if events.len() == MAX_EVENTS {
            events.pop_front();
        }
        events.push_back(event);
    }

    fn recent_events(&self) -> Vec<Value> {
        self.events_guard().iter().cloned().collect()
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
        ));

    Router::new()
        .route("/", get(dashboard))
        .route("/health", get(health))
        .route("/openapi.json", get(openapi))
        .merge(protected)
        .layer(middleware::from_fn(csrf_guard))
        .layer(middleware::from_fn_with_state(
            state.clone(),
            record_request,
        ))
        .layer(middleware::from_fn(trusted_host))
        .with_state(state)
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
    let listener = TcpListener::bind((config.host.as_str(), config.port)).await?;
    let paths = RagPaths::from_env().ok();
    if let Some(paths) = paths.as_ref() {
        bootstrap_rag_home(paths);
        // Python parity: dotenv (`~/.rag/.env`, project `.env`) at startup.
        let cwd = std::env::current_dir().unwrap_or_else(|_| std::path::PathBuf::from("."));
        let _ = rag_config::load_env_files(paths, &cwd);
    }

    // Python parity: RAG_TOKEN env wins, then the persisted ~/.rag/token.
    let token = std::env::var("RAG_TOKEN").ok().or_else(|| {
        paths.as_ref().and_then(|paths| {
            std::fs::read_to_string(&paths.token_path)
                .ok()
                .map(|raw| raw.trim().to_owned())
                .filter(|token| !token.is_empty())
        })
    });

    let mut state = ServerState::new(token);
    let settings = paths
        .as_ref()
        .ok_or_else(|| "RAG home is unavailable".to_owned())
        .and_then(|paths| rag_config::load_settings(paths).map_err(|error| error.to_string()));
    match settings {
        Ok(settings) => {
            state = state.with_dashboard(settings.server.dashboard);
            if !settings.server.dashboard {
                eprintln!("browser dashboard disabled (server.dashboard = false)");
            }
            // `embedded` hosts Qdrant as a managed child process; `server`
            // connects to whatever serves qdrant.url (e.g. `rag qdrant-up`).
            if settings.qdrant.mode == "embedded" {
                if let Some(paths) = paths.as_ref() {
                    if let Err(error) =
                        qdrant_boot::ensure_local_qdrant(paths, &settings.qdrant.url).await
                    {
                        eprintln!("embedded qdrant unavailable: {error}");
                    }
                }
            }
            match RetrievalBackend::from_settings(&settings) {
                Ok(backend) => {
                    eprintln!("dense retrieval backend configured (Ollama + Qdrant)");
                    let backend = Arc::new(backend);
                    // Warm the embedding model in the background so the first
                    // real query isn't the one that pays the ~6s VRAM load.
                    let warm = Arc::clone(&backend);
                    tokio::spawn(async move { warm.warm_up().await });
                    state = state.with_retrieval(backend);
                }
                Err(error) => {
                    eprintln!(
                        "dense retrieval backend unavailable, staying on SQLite paths: {error}"
                    );
                    let mut fields = serde_json::Map::new();
                    fields.insert("error".to_owned(), json!(error));
                    log_daemon_event(paths.as_ref(), "error", "backend_unavailable", fields);
                }
            }
        }
        Err(error) => {
            eprintln!("settings unavailable, staying on SQLite paths: {error}");
            let mut fields = serde_json::Map::new();
            fields.insert("error".to_owned(), json!(error));
            log_daemon_event(paths.as_ref(), "error", "settings_unavailable", fields);
        }
    }
    let mut fields = serde_json::Map::new();
    fields.insert("host".to_owned(), json!(config.host));
    fields.insert("port".to_owned(), json!(config.port));
    log_daemon_event(paths.as_ref(), "info", "daemon_started", fields);

    let served = axum::serve(listener, router_with_state(state))
        .with_graceful_shutdown(shutdown_signal())
        .await;
    qdrant_boot::stop_managed();
    log_daemon_event(
        paths.as_ref(),
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
fn bootstrap_rag_home(paths: &RagPaths) {
    let _ = std::fs::create_dir_all(&paths.home);
    if !paths.token_path.exists() {
        let token = generate_token();
        if std::fs::write(&paths.token_path, &token).is_ok() {
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                let _ = std::fs::set_permissions(
                    &paths.token_path,
                    std::fs::Permissions::from_mode(0o600),
                );
            }
            eprintln!("created auth token at {}", paths.token_path.display());
        }
    }
    if !paths.config_path.exists()
        && std::fs::write(&paths.config_path, rag_config::PYTHON_DEFAULT_TOML).is_ok()
    {
        eprintln!("created default config at {}", paths.config_path.display());
    }
}

/// URL-safe base64 of 32 random bytes, matching Python `secrets.token_urlsafe(32)`.
fn generate_token() -> String {
    let mut bytes = Vec::with_capacity(32);
    bytes.extend_from_slice(uuid::Uuid::new_v4().as_bytes());
    bytes.extend_from_slice(uuid::Uuid::new_v4().as_bytes());
    const ALPHABET: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    let mut out = String::with_capacity(43);
    for chunk in bytes.chunks(3) {
        let buffer = [
            chunk[0],
            chunk.get(1).copied().unwrap_or(0),
            chunk.get(2).copied().unwrap_or(0),
        ];
        let value =
            (u32::from(buffer[0]) << 16) | (u32::from(buffer[1]) << 8) | u32::from(buffer[2]);
        let chars = [
            (value >> 18) & 0x3f,
            (value >> 12) & 0x3f,
            (value >> 6) & 0x3f,
            value & 0x3f,
        ];
        let keep = match chunk.len() {
            1 => 2,
            2 => 3,
            _ => 4,
        };
        for encoded in chars.iter().take(keep) {
            out.push(ALPHABET[*encoded as usize] as char);
        }
    }
    out
}

async fn shutdown_signal() {
    let ctrl_c = async {
        tokio::signal::ctrl_c()
            .await
            .expect("failed to install Ctrl+C handler");
    };
    #[cfg(unix)]
    let terminate = async {
        tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
            .expect("failed to install SIGTERM handler")
            .recv()
            .await;
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
    let components = backend.component_health().await;
    let healthy = components.get("ollama").map(String::as_str) == Some("ok")
        && components.get("qdrant").map(String::as_str) == Some("ok");
    Json(HealthResponse {
        status: if healthy { "ok" } else { "degraded" }.to_owned(),
        components,
    })
}

async fn status(State(state): State<ServerState>) -> Json<Value> {
    if !state.contract_fixtures {
        let (status, provider, model) = match state.retrieval.as_ref() {
            Some(backend) => ("ok", "ollama", backend.embedder_model().to_owned()),
            None => ("degraded", "not_initialized", String::new()),
        };
        let collections = status_collections(&state).await;
        let files_indexed = match state.rag_paths.clone() {
            Some(paths) => tokio::task::spawn_blocking(move || {
                RepoRegistry::open(&paths)
                    .and_then(|registry| registry.list_repos())
                    .map(|repos| {
                        repos
                            .iter()
                            .map(|repo| stack::repo_state_files(&paths, &repo.path))
                            .sum::<usize>()
                    })
                    .unwrap_or(0)
            })
            .await
            .unwrap_or(0),
            None => 0,
        };
        return Json(json!({
            "status": status,
            "embedder_provider": provider,
            "embedder_model": model,
            "reranker_model": "disabled",
            "reranker_enabled": false,
            "collections": collections,
            "uptime_seconds": state.started_at.elapsed().as_secs_f64(),
            "files_indexed": files_indexed,
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

/// Python parity: `/status.collections` carries per-collection objects
/// (`{name, kind, repo, path, points_count, status}`) — the dashboards'
/// project tables render straight from this list. Default collections come
/// first, then registered repos; point counts are live from Qdrant when the
/// backend is up and fall back to the registry's recorded chunk counts.
async fn status_collections(state: &ServerState) -> Vec<Value> {
    let mut out = Vec::new();
    let Some(paths) = state.rag_paths.as_ref() else {
        return out;
    };
    let settings = rag_config::load_settings(paths).ok();
    if let (Some(backend), Some(settings)) = (state.retrieval.as_ref(), settings.as_ref()) {
        for name in [
            &settings.qdrant.code_collection,
            &settings.qdrant.docs_collection,
        ] {
            let (points, status) = match backend.qdrant.collection_metadata(name).await {
                Ok(meta) => (meta.points_count, meta.status),
                Err(_) => (0, "not_found".to_owned()),
            };
            out.push(json!({
                "name": name, "kind": "default",
                "points_count": points, "status": status,
            }));
        }
    }
    let repos = RepoRegistry::open(paths)
        .and_then(|registry| registry.list_repos())
        .unwrap_or_default();
    for repo in repos {
        let (points, status) = match state.retrieval.as_ref() {
            Some(backend) => match backend.qdrant.collection_metadata(&repo.collection).await {
                Ok(meta) => (meta.points_count, meta.status),
                Err(_) => (u64::try_from(repo.chunks_count).unwrap_or(0), String::new()),
            },
            None => (u64::try_from(repo.chunks_count).unwrap_or(0), String::new()),
        };
        out.push(json!({
            "name": repo.collection, "repo": repo.name, "path": repo.path,
            "kind": "repo", "points_count": points, "status": status,
        }));
    }
    out
}

async fn openapi() -> Json<Value> {
    Json(
        serde_json::from_str(include_str!("../../../tests/contracts/openapi.json"))
            .expect("checked-in OpenAPI fixture is valid JSON"),
    )
}

async fn dashboard(State(state): State<ServerState>) -> Response {
    if !state.dashboard_enabled {
        return api_error(
            StatusCode::NOT_FOUND,
            "Dashboard is disabled (server.dashboard = false)",
            "DASHBOARD_DISABLED",
        );
    }
    // The page is only served through this route so a credential can be
    // injected; same-origin fetch() then authenticates with it. `no-store`
    // keeps the credential-bearing page out of browser and disk caches.
    //
    // Deliberately the ephemeral `dashboard_token`, never the durable
    // `~/.rag/token`: this response is unauthenticated by necessity, so
    // whatever it carries is readable by any local process. See the field
    // docs on `ServerState::dashboard_token`.
    let html = include_str!("../assets/index.html");
    (
        [(header::CACHE_CONTROL, "no-store")],
        Html(html.replace("__RAG_TOKEN__", &state.dashboard_token)),
    )
        .into_response()
}

async fn generic_get(State(state): State<ServerState>, request: Request) -> Response {
    let path = request.uri().path().to_owned();
    // Routes needing async Qdrant/Ollama access run through the backend.
    if !state.contract_fixtures {
        // Stack health probes only need paths, not the retrieval backend —
        // the web dashboard's service cards must work even when Qdrant is down.
        if path == "/stack" {
            if let Some(paths) = state.rag_paths.as_ref() {
                return Json(stack::stack_status_json(paths).await).into_response();
            }
        }
        if path == "/diagnose" {
            if let Some(paths) = state.rag_paths.as_ref() {
                return Json(diagnose_json(paths).await).into_response();
            }
        }
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
        // Same action as the TUI's U key; needs Docker, not the backend.
        if path == "/stack/qdrant/start" {
            return Json(json!({"message": stack::start_qdrant().await})).into_response();
        }
        // Dense retrieval routes run through the async Ollama+Qdrant backend
        // when it is configured; other live routes stay on the SQLite path.
        if let (Some(backend), Some(paths)) = (state.retrieval.clone(), state.rag_paths.clone()) {
            let handled = match path.as_str() {
                "/search" => Some(backend.search_route(&paths, &body).await),
                "/smart-search" => Some(backend.smart_search_route(&paths, &body).await),
                "/ask" => Some(backend.ask_route(&paths, &body).await),
                "/index" => Some(indexing::index_route(&backend, &paths, &body).await),
                "/index/docs" => Some(indexing::index_docs_route(&backend, &paths, &body).await),
                "/vocab/build" => Some(indexing::vocab_build_route(&backend, &paths, &body).await),
                "/diff" => Some(backend.diff_route(&paths, &body).await),
                "/admin/export" => Some(backend.admin_export_route(&paths, &body).await),
                "/admin/verify" => Some(backend.admin_verify_route(&paths, &body).await),
                _ => None,
            };
            if let Some(result) = handled {
                return match result {
                    Ok(value) => Json(value).into_response(),
                    Err(error) => route_error_response(&error),
                };
            }
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
            Ok(Err(error)) => return route_error_response(&error),
            // A JoinError is a panic in the blocking worker: a real failure of
            // this daemon, never something the caller asked for.
            Err(_) => {
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

/// `/diagnose`: the CLI-facing health summary.
///
/// This route used to return a hard-coded `{"status":"degraded","checks":[]}`
/// on every call — so `rag diagnose` always claimed the stack was degraded and
/// never named a reason, and the README told users to run it to check whether
/// `ast-index` was installed. `/stack` already performs the real probes for
/// the dashboards; this projects them into a flat, scriptable check list.
async fn diagnose_json(paths: &RagPaths) -> Value {
    let stack = stack::stack_status_json(paths).await;
    let mut checks = Vec::new();
    let mut degraded = false;

    for key in ["ollama", "qdrant", "docker", "ast_index"] {
        let Some(card) = stack.get(key) else { continue };
        let state = card
            .get("state")
            .and_then(Value::as_str)
            .unwrap_or("unknown");
        // `warn`/`error` both mean "a human should look at this"; docker is
        // informational because `qdrant.mode = "embedded"` needs no Docker.
        if key != "docker" && state != "ok" {
            degraded = true;
        }
        checks.push(json!({
            "name": key,
            "state": state,
            "detail": card.get("headline").cloned().unwrap_or(json!("")),
            "hint": card.get("hint").cloned().unwrap_or(json!("")),
        }));
    }

    // Config sanity: the class of misconfiguration that presents as a service
    // outage. An embeddings.model that is not an Ollama tag makes the daemon
    // report `ollama: unavailable` while Ollama is perfectly healthy.
    if let Ok(settings) = rag_config::load_settings(paths) {
        let model = settings.embeddings.model.clone();
        let looks_like_hf_path = model.contains('/');
        if looks_like_hf_path {
            degraded = true;
        }
        checks.push(json!({
            "name": "config.embeddings.model",
            "state": if looks_like_hf_path { "warn" } else { "ok" },
            "detail": model.clone(),
            "hint": if looks_like_hf_path {
                format!("{model:?} looks like a HuggingFace repo path, not an Ollama tag. \
                         Ollama is matched against the tags `ollama list` prints, so this \
                         never matches and the daemon reports `ollama: unavailable` even \
                         when Ollama is healthy.")
            } else {
                String::new()
            },
        }));
    }

    json!({
        "status": if degraded { "degraded" } else { "ok" },
        "checks": checks,
    })
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
                    "name": repo.collection, "kind": "repo", "repo": repo.name,
                    "path": repo.path, "points_count": repo.chunks_count,
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
        "retrieval_mode": LEXICAL_RETRIEVAL_MODE,
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
    // Both bounded: unclamped they reached `ast_index::resolve_symbols`, whose
    // over-fetch panicked for values above 200 (the panic surfaced as a 503,
    // not a 4xx, because spawn_blocking's JoinError reads as a backend outage).
    let definitions_limit = body
        .get("definitions_limit")
        .or_else(|| body.get("limit"))
        .and_then(Value::as_u64)
        .unwrap_or(20)
        .clamp(0, 200) as usize;
    let usages_limit = body
        .get("usages_limit")
        .and_then(Value::as_u64)
        .unwrap_or(20)
        .clamp(0, 200) as usize;
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
    let mut slices =
        rag_retrieval::ast_index::retrieve_context(&repo.path, query, max_slices, true);
    for slice in &mut slices {
        if let Some(object) = slice.as_object_mut() {
            object.insert("repo".to_owned(), json!(repo.name));
            let tokens = object
                .get("code")
                .and_then(Value::as_str)
                .map(rag_retrieval::estimate_tokens)
                .unwrap_or(0);
            object.insert("token_estimate".to_owned(), json!(tokens));
        }
    }
    let total_source_tokens: usize = slices
        .iter()
        .filter_map(|slice| slice.get("token_estimate").and_then(Value::as_u64))
        .map(|value| value as usize)
        .sum();
    Ok(
        json!({"query": query, "repo": repo.name, "total": slices.len(), "slices": slices,
        "total_source_tokens": total_source_tokens,
        "latency_ms": started.elapsed().as_secs_f64() * 1000.0}),
    )
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
        "retrieval_mode": LEXICAL_RETRIEVAL_MODE,
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
            "generation_ms": 0.0, "latency_ms": started.elapsed().as_secs_f64() * 1000.0, "insufficient_context": true,
            "retrieval_mode": LEXICAL_RETRIEVAL_MODE}),
        );
    };
    let citation = json!({"file_path": first["file_path"], "lines": first["lines"], "name": first["name"], "score": first["score"]});
    Ok(json!({"question": question,
        "answer": format!("The strongest indexed evidence is {} at {}.", first["name"].as_str().unwrap_or("the cited symbol"), first["citation"].as_str().unwrap_or("the cited location")),
        "citations": [citation], "model": "deterministic-fallback", "retrieval_ms": search["latency_ms"],
        "generation_ms": 0.0, "latency_ms": started.elapsed().as_secs_f64() * 1000.0, "insufficient_context": false,
        "retrieval_mode": LEXICAL_RETRIEVAL_MODE}))
}

fn live_index(paths: &RagPaths, body: &Value) -> Result<Value, String> {
    let repo_path =
        indexing::canonical_directory("repo_path", required_string(body, "repo_path")?)?;
    std::fs::create_dir_all(&paths.home).map_err(|error| error.to_string())?;
    let settings = rag_config::load_settings(paths).unwrap_or_default();
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
    let mut index = rag_index::LexicalIndex::open(paths.home.join("rag.db"))
        .map_err(|error| error.to_string())?;
    if full {
        index
            .delete_code_chunks_by_collection(&collection)
            .map_err(|error| error.to_string())?;
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
        let source = match std::fs::read_to_string(&file) {
            Ok(source) => source,
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
            .upsert_code_chunks(&documents)
            .map_err(|error| error.to_string())?;
        files_processed += 1;
    }
    let registry = RepoRegistry::open_writable(paths).map_err(|error| error.to_string())?;
    registry
        .upsert(&RepoInfo {
            name: repo_name,
            path: repo_path.to_string_lossy().to_string(),
            collection,
            last_indexed: Some(unix_timestamp().to_string()),
            chunks_count: chunks_indexed as i64,
        })
        .map_err(|error| error.to_string())?;
    Ok(
        json!({"files_processed": files_processed, "chunks_indexed": chunks_indexed,
        "files_skipped": files_skipped, "files_deleted": 0, "errors": errors}),
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

/// SQLite-only compatibility path for tests and deliberately unconfigured
/// servers. Configured production servers dispatch `/index/docs` through
/// `indexing::index_docs_route` before reaching this fallback.
fn live_index_docs(paths: &RagPaths, body: &Value) -> Result<Value, String> {
    let docs_path = indexing::canonical_path("docs_path", required_string(body, "docs_path")?)?;
    std::fs::create_dir_all(&paths.home).map_err(|error| error.to_string())?;
    let collection = body
        .get("collection")
        .and_then(Value::as_str)
        .filter(|name| !name.trim().is_empty())
        .unwrap_or("doc_chunks")
        .to_owned();
    let full = body.get("full").and_then(Value::as_bool).unwrap_or(false);
    let mut index = rag_index::LexicalIndex::open(paths.home.join("rag.db"))
        .map_err(|error| error.to_string())?;
    if full {
        index
            .delete_code_chunks_by_collection(&collection)
            .map_err(|error| error.to_string())?;
    }
    let files = discover_docs(&docs_path)?;
    let mut files_processed = 0_usize;
    let mut chunks_indexed = 0_usize;
    let mut errors = Vec::new();
    for file in files {
        let relative = if docs_path.is_file() {
            file.file_name()
                .and_then(|name| name.to_str())
                .unwrap_or_default()
                .to_owned()
        } else {
            file.strip_prefix(&docs_path)
                .unwrap_or(&file)
                .to_string_lossy()
                .replace('\\', "/")
        };
        let source = match std::fs::read_to_string(&file) {
            Ok(source) => source,
            Err(error) => {
                errors.push(format!("{relative}: {error}"));
                continue;
            }
        };
        let chunks = rag_index::chunk_code(&source, &relative, Some("markdown"), 8_000);
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
            .upsert_code_chunks(&documents)
            .map_err(|error| error.to_string())?;
        files_processed += 1;
    }
    Ok(json!({
        "files_processed": files_processed,
        "chunks_indexed": chunks_indexed,
        "files_skipped": 0,
        "files_deleted": 0,
        "errors": errors,
    }))
}

fn discover_docs(root: &std::path::Path) -> Result<Vec<std::path::PathBuf>, String> {
    let mut pending = vec![root.to_path_buf()];
    let mut files = Vec::new();
    while let Some(path) = pending.pop() {
        if path.is_file() {
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
        for entry in std::fs::read_dir(&path).map_err(|error| error.to_string())? {
            let entry = entry.map_err(|error| error.to_string())?;
            if entry.file_name().to_string_lossy().starts_with('.') {
                continue;
            }
            pending.push(entry.path());
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
            json!({"message": "managed Qdrant is not configured"})
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

/// Map a route error onto an HTTP response.
///
/// The default is `503 BACKEND_NOT_READY`, and it stays reserved for what it
/// says: the daemon could not reach Qdrant/Ollama/SQLite. Client mistakes are
/// classified explicitly first, because a caller error dressed as an outage
/// sends an operator to restart healthy services instead of fixing the
/// request. Two mechanisms feed the classification: [`indexing::RouteRejection`],
/// which is typed at the point of failure and decoded here, and the documented
/// error prefixes of the helpers that predate it.
fn route_error_response(error: &str) -> Response {
    match indexing::RouteRejection::decode(error) {
        // Well-formed request, busy repository: 409, and the message says which
        // repository — the caller can just retry.
        Some(indexing::RouteRejection::Conflict(message)) => {
            api_error(StatusCode::CONFLICT, &message, "HTTP_ERROR")
        }
        Some(indexing::RouteRejection::PathNotFound { field, message }) => {
            validation_422(&field, &message, "value_error.path.not_exists")
        }
        Some(indexing::RouteRejection::PathNotDirectory { field, message }) => {
            validation_422(&field, &message, "value_error.path.not_a_directory")
        }
        None if error.starts_with("missing required field") => {
            let field = error.rsplit(": ").next().unwrap_or("body");
            validation_422(field, "field required", "value_error.missing")
        }
        None if error.starts_with("unknown repo") => {
            api_error(StatusCode::NOT_FOUND, error, "HTTP_ERROR")
        }
        // A destination outside `~/.rag/exports` is a bad request, not a
        // backend outage — keep it off the 5xx path.
        None if error.starts_with("invalid output path") => {
            api_error(StatusCode::BAD_REQUEST, error, "HTTP_ERROR")
        }
        None => api_error(
            StatusCode::SERVICE_UNAVAILABLE,
            "Live retrieval backend is unavailable",
            "BACKEND_NOT_READY",
        ),
    }
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
        let has_repo = body
            .get("repo")
            .and_then(Value::as_str)
            .is_some_and(|value| !value.trim().is_empty());
        let has_repos = body
            .get("repos")
            .and_then(Value::as_array)
            .is_some_and(|values| !values.is_empty());
        if !has_repo && !has_repos {
            return Some(validation_422(
                "repo",
                "Provide repo or repos",
                "value_error",
            ));
        }
        // `repos` is accepted by this contract but the Rust pipeline only ever
        // reads `repo`, so a multi-repo request used to return 200 having
        // silently searched the DEFAULT collection instead of the named ones.
        // A wrong answer that looks right is worse than a refusal; say so
        // until cross-repo smart-search is actually ported.
        if !has_repo {
            let count = body
                .get("repos")
                .and_then(Value::as_array)
                .map_or(0, Vec::len);
            if count > 1 {
                return Some(validation_422(
                    "repos",
                    "Multi-repo smart-search is not supported yet; pass a single repo",
                    "value_error",
                ));
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
        // Either the durable daemon token or this process's dashboard token
        // authenticates. Both comparisons run so the answer does not leak
        // which credential was presented via timing.
        let matches_daemon =
            bearer.is_some_and(|actual| constant_time_eq(actual.as_bytes(), expected.as_bytes()));
        let matches_dashboard = state.dashboard_enabled
            && bearer.is_some_and(|actual| {
                constant_time_eq(actual.as_bytes(), state.dashboard_token.as_bytes())
            });
        if !(matches_daemon || matches_dashboard) {
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
    // Same reasoning as `events_guard`: this runs on every authenticated
    // request, so refusing to proceed on a poisoned lock would convert one
    // panic into a permanently 500-ing daemon. The map holds nothing but
    // independent fixed-window counters, so resuming costs at most one caller
    // an extra window.
    let mut windows = state
        .rate_windows
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    // The map is only ever added to, so distinct bearer credentials (rotated
    // tokens, or attacker-chosen values when auth is disabled) would grow it
    // forever. Expired windows carry no information, so drop them on insert.
    // Guarded by a threshold: the common single-token daemon never scans.
    if windows.len() >= RATE_WINDOW_SWEEP_THRESHOLD && !windows.contains_key(key) {
        windows.retain(|_, (started, _)| now.duration_since(*started) < RATE_LIMIT_WINDOW);
        // Even with every window still live, a flood of distinct credentials
        // must not be able to grow the map without bound. Dropping the counters
        // only grants those callers a fresh window — per-key limits already do
        // not constrain a caller who varies the key.
        if windows.len() >= RATE_WINDOW_MAX_ENTRIES {
            windows.clear();
        }
    }
    let entry = windows.entry(key.to_owned()).or_insert((now, 0));
    if now.duration_since(entry.0) >= RATE_LIMIT_WINDOW {
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
}

#[cfg(test)]
mod tests {
    use axum::body::{to_bytes, Body};
    use http::{header, Request, StatusCode};
    use rag_contracts::{ErrorResponse, HealthResponse};
    use serde_json::{json, Value};
    use tower::ServiceExt;

    use std::sync::Arc;
    use std::time::{Duration, Instant};

    use super::retrieval::resolve_export_path;
    use super::{consume_rate_limit, parse_bearer, router, router_with_state, ServerState};

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

    /// A panic while holding the event-ring mutex must not turn every later
    /// request into a 500 — the middleware runs on all of them.
    #[tokio::test]
    async fn poisoned_event_lock_still_serves_requests() {
        let state = ServerState::new(None).with_contract_fixtures();
        let poisoner = state.clone();
        let previous_hook = std::panic::take_hook();
        std::panic::set_hook(Box::new(|_| {}));
        let poisoned = std::thread::spawn(move || {
            let _guard = poisoner.events.lock().unwrap();
            panic!("deliberate poison");
        })
        .join();
        std::panic::set_hook(previous_hook);
        assert!(poisoned.is_err());
        assert!(
            state.events.lock().is_err(),
            "event mutex should now be poisoned"
        );

        let health = router_with_state(state.clone())
            .oneshot(request("GET", "/health").body(Body::empty()).unwrap())
            .await
            .unwrap();
        assert_eq!(health.status(), StatusCode::OK);

        let events = router_with_state(state)
            .oneshot(
                request("GET", "/events/recent")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(events.status(), StatusCode::OK);
        let value: Value =
            serde_json::from_slice(&to_bytes(events.into_body(), usize::MAX).await.unwrap())
                .unwrap();
        assert!(value["events"].is_array());
    }

    #[test]
    fn rate_limit_windows_are_evicted_and_bounded() {
        let state = ServerState::new(None);
        let stale = Instant::now()
            .checked_sub(Duration::from_secs(120))
            .expect("monotonic clock is younger than the rate-limit window");
        {
            let mut windows = state.rate_windows.lock().unwrap();
            for index in 0..5_000 {
                windows.insert(format!("expired-{index}"), (stale, 1));
            }
        }
        // Expired windows carry no information and must not survive new keys.
        assert!(consume_rate_limit(&state, "fresh-0"));
        {
            let windows = state.rate_windows.lock().unwrap();
            assert!(
                !windows.keys().any(|key| key.starts_with("expired-")),
                "expired rate-limit windows were never reclaimed"
            );
        }
        // Live windows from a flood of distinct credentials stay bounded too.
        for index in 0..(super::RATE_WINDOW_MAX_ENTRIES + 2_000) {
            consume_rate_limit(&state, &format!("flood-{index}"));
        }
        let len = state.rate_windows.lock().unwrap().len();
        assert!(
            len <= super::RATE_WINDOW_MAX_ENTRIES,
            "rate-limit map grew to {len} entries"
        );
    }

    /// Degraded (SQLite keyword) answers must be distinguishable from dense
    /// ones: they share the JSON shape but not the quality.
    #[tokio::test]
    async fn search_responses_declare_their_retrieval_mode() {
        let temp = tempfile::tempdir().unwrap();
        let repo = temp.path().join("repo");
        std::fs::create_dir_all(&repo).unwrap();
        std::fs::write(
            repo.join("auth.rs"),
            "pub fn verify_bearer(token: &str) -> bool { !token.is_empty() }",
        )
        .unwrap();
        let app =
            router_with_state(ServerState::new(None).with_rag_home(temp.path().join("rag-home")));
        let indexed = app
            .clone()
            .oneshot(
                request("POST", "/index")
                    .header(header::CONTENT_TYPE, "application/json")
                    .body(Body::from(format!(
                        r#"{{"repo_path":{},"repo_name":"sample","collection":"repo_sample","full":true}}"#,
                        serde_json::to_string(&repo).unwrap()
                    )))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(indexed.status(), StatusCode::OK);

        let search = app
            .oneshot(
                request("POST", "/search")
                    .header(header::CONTENT_TYPE, "application/json")
                    .body(Body::from(
                        r#"{"query":"verify bearer","repo":"sample","top_k":5}"#,
                    ))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(search.status(), StatusCode::OK);
        let value: Value =
            serde_json::from_slice(&to_bytes(search.into_body(), usize::MAX).await.unwrap())
                .unwrap();
        assert_eq!(value["retrieval_mode"], super::LEXICAL_RETRIEVAL_MODE);
    }

    #[test]
    fn export_paths_are_confined_to_the_exports_directory() {
        let temp = tempfile::tempdir().unwrap();
        let paths = super::RagPaths::from_home(temp.path());
        let root = temp.path().join("exports");

        let accepted = resolve_export_path(&paths, "dump.jsonl").unwrap();
        assert_eq!(accepted, root.canonicalize().unwrap().join("dump.jsonl"));
        let nested = resolve_export_path(&paths, "snapshots/dump.jsonl").unwrap();
        assert!(nested.starts_with(root.canonicalize().unwrap()));
        // An absolute path is only honored inside the root.
        assert!(resolve_export_path(&paths, accepted.to_str().unwrap()).is_ok());

        for traversal in [
            "../escaped.jsonl",
            "../../etc/cron.d/payload",
            "nested/../../escaped.jsonl",
            "/etc/cron.d/payload",
            "",
            ".",
        ] {
            let error = resolve_export_path(&paths, traversal)
                .expect_err("traversal accepted: {traversal}");
            assert!(
                error.starts_with("invalid output path"),
                "unexpected error for {traversal}: {error}"
            );
        }
        assert!(!temp.path().join("escaped.jsonl").exists());
    }

    #[cfg(unix)]
    #[test]
    fn export_paths_reject_symlinked_escapes() {
        let temp = tempfile::tempdir().unwrap();
        let paths = super::RagPaths::from_home(temp.path());
        let outside = temp.path().join("outside");
        std::fs::create_dir_all(&outside).unwrap();
        let root = temp.path().join("exports");
        std::fs::create_dir_all(&root).unwrap();
        std::os::unix::fs::symlink(&outside, root.join("link")).unwrap();
        std::os::unix::fs::symlink(outside.join("target.jsonl"), root.join("file.jsonl")).unwrap();

        assert!(resolve_export_path(&paths, "link/dump.jsonl").is_err());
        assert!(resolve_export_path(&paths, "file.jsonl").is_err());
        assert!(!outside.join("dump.jsonl").exists());
    }

    /// Pull the credential the dashboard page embeds (`const TOKEN = "..."`).
    fn embedded_dashboard_token(body: &str) -> String {
        let marker = "const TOKEN = \"";
        let start = body.find(marker).expect("dashboard embeds a token") + marker.len();
        body[start..]
            .split('"')
            .next()
            .expect("token literal")
            .to_owned()
    }

    async fn dashboard_body(app: axum::Router) -> String {
        let response = app
            .oneshot(request("GET", "/").body(Body::empty()).unwrap())
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        String::from_utf8(
            to_bytes(response.into_body(), usize::MAX)
                .await
                .unwrap()
                .to_vec(),
        )
        .unwrap()
    }

    /// `GET /` is unauthenticated by necessity, so whatever it embeds is
    /// readable by any local process. It must never be the durable
    /// `~/.rag/token`, which outlives the process and authenticates the CLI.
    #[tokio::test]
    async fn dashboard_never_serves_the_durable_daemon_token() {
        let daemon_token = "durable-secret-from-rag-home";
        let state = ServerState::new(Some(daemon_token.to_owned()));
        let body = dashboard_body(router_with_state(state)).await;

        assert!(
            !body.contains(daemon_token),
            "durable daemon token leaked into the unauthenticated dashboard page"
        );
        let embedded = embedded_dashboard_token(&body);
        assert!(!embedded.is_empty() && embedded != daemon_token);
    }

    /// Two independent daemons must not share a dashboard credential — it is
    /// generated per process and never persisted.
    #[tokio::test]
    async fn dashboard_tokens_are_per_process() {
        let first = embedded_dashboard_token(
            &dashboard_body(router_with_state(ServerState::new(None))).await,
        );
        let second = embedded_dashboard_token(
            &dashboard_body(router_with_state(ServerState::new(None))).await,
        );
        assert_ne!(first, second);
    }

    /// The embedded credential has to actually work, or the dashboard is
    /// broken; the daemon token has to keep working, or the CLI is.
    #[tokio::test]
    async fn both_credentials_authenticate_and_others_do_not() {
        let state = ServerState::new(Some("daemon-token".to_owned())).with_contract_fixtures();
        let app = router_with_state(state);
        let embedded = embedded_dashboard_token(&dashboard_body(app.clone()).await);

        for (credential, expected) in [
            (embedded.as_str(), StatusCode::OK),
            ("daemon-token", StatusCode::OK),
            ("neither-of-them", StatusCode::UNAUTHORIZED),
        ] {
            let response = app
                .clone()
                .oneshot(
                    request("GET", "/status")
                        .header(header::AUTHORIZATION, format!("Bearer {credential}"))
                        .body(Body::empty())
                        .unwrap(),
                )
                .await
                .unwrap();
            assert_eq!(response.status(), expected, "credential {credential:?}");
        }
    }

    /// `server.dashboard = false`: no page, and the credential it would have
    /// carried stops authenticating too — otherwise disabling the page would
    /// leave a live credential behind.
    #[tokio::test]
    async fn disabling_the_dashboard_serves_no_page_and_no_credential() {
        let state = ServerState::new(Some("daemon-token".to_owned()))
            .with_contract_fixtures()
            .with_dashboard(false);
        let leaked = state.dashboard_token.to_string();
        let app = router_with_state(state);

        let page = app
            .clone()
            .oneshot(request("GET", "/").body(Body::empty()).unwrap())
            .await
            .unwrap();
        assert_eq!(page.status(), StatusCode::NOT_FOUND);

        let response = app
            .oneshot(
                request("GET", "/status")
                    .header(header::AUTHORIZATION, format!("Bearer {leaked}"))
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    }

    // -----------------------------------------------------------------------
    // Route error mapping: a client mistake must never be reported as an
    // outage, and an outage must never be reported as anything else.
    // -----------------------------------------------------------------------

    /// A backend wired to a port nothing listens on. Enough to take the dense
    /// `/index` write path (`indexing::index_route`), and guaranteed to fail
    /// the instant that path touches Qdrant.
    fn unreachable_backend() -> super::RetrievalBackend {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").expect("reserve a port");
        let address = listener.local_addr().expect("reserved address");
        // Releasing it leaves the port closed, so every connection is refused
        // immediately instead of hanging on a firewall-black-holed address.
        drop(listener);
        let settings = rag_config::Settings {
            qdrant: rag_config::QdrantSettings {
                url: format!("http://{address}"),
                ..rag_config::QdrantSettings::default()
            },
            ..rag_config::Settings::default()
        };
        super::RetrievalBackend::from_settings(&settings).expect("backend clients")
    }

    async fn post_json(app: axum::Router, uri: &str, body: &Value) -> (StatusCode, Value) {
        let response = app
            .oneshot(
                request("POST", uri)
                    .header(header::CONTENT_TYPE, "application/json")
                    .body(Body::from(body.to_string()))
                    .unwrap(),
            )
            .await
            .unwrap();
        let status = response.status();
        let bytes = to_bytes(response.into_body(), usize::MAX).await.unwrap();
        (
            status,
            serde_json::from_slice(&bytes).unwrap_or(Value::Null),
        )
    }

    /// A second `/index` for a repository that is already being indexed is a
    /// conflict, not an outage: the daemon is healthy and the request is
    /// well-formed, the repository is merely busy. It used to answer
    /// `503 BACKEND_NOT_READY` and throw the real message away, which sends an
    /// operator to restart Qdrant over a request that just needs a retry.
    #[tokio::test]
    async fn concurrent_index_for_the_same_repo_is_a_409_conflict() {
        let temp = tempfile::tempdir().unwrap();
        let repo = temp.path().join("repo");
        std::fs::create_dir_all(&repo).unwrap();
        let repo = repo.canonicalize().unwrap();

        // Hold the per-repo guard exactly as an in-flight run does. The write
        // path takes it before it talks to Qdrant, so the rejected request is
        // answered without ever reaching the (deliberately dead) backend —
        // deterministic, and no sleep anywhere.
        let _in_flight =
            super::indexing::IndexRunGuard::acquire(&repo).expect("first run takes the guard");

        let app = router_with_state(
            ServerState::new(None)
                .with_rag_home(temp.path().join("rag-home"))
                .with_retrieval(Arc::new(unreachable_backend())),
        );
        let (status, value) = post_json(
            app,
            "/index",
            &json!({"repo_path": repo, "collection": "repo_busy"}),
        )
        .await;

        assert_eq!(status, StatusCode::CONFLICT, "unexpected body: {value}");
        let message = value["error"].as_str().expect("error envelope");
        assert!(
            message.contains("another index run is already in progress"),
            "the conflict was not named: {message}"
        );
        assert!(
            !message.contains("backend"),
            "a busy repository was reported as a backend problem: {message}"
        );
        // Envelope shape is unchanged — only the status and the message are.
        assert_eq!(value["code"], "HTTP_ERROR");
        assert!(value["detail"].is_null());
    }

    /// A `repo_path` the caller made up is a 4xx on both write paths (dense and
    /// the SQLite fallback), in the same FastAPI shape the rest of the request
    /// contract uses. It used to be `503 BACKEND_NOT_READY` on both.
    #[tokio::test]
    async fn bad_repo_path_is_a_422_not_a_backend_outage() {
        let temp = tempfile::tempdir().unwrap();
        let home = temp.path().join("rag-home");
        let missing = temp.path().join("no-such-repo");
        let a_file = temp.path().join("a-file.txt");
        std::fs::write(&a_file, "not a repository").unwrap();

        for (path, expected_type) in [
            (&missing, "value_error.path.not_exists"),
            (&a_file, "value_error.path.not_a_directory"),
        ] {
            let states = [
                // No retrieval backend: the SQLite `live_index` path.
                (
                    "sqlite fallback",
                    ServerState::new(None).with_rag_home(&home),
                ),
                (
                    "dense backend",
                    ServerState::new(None)
                        .with_rag_home(&home)
                        .with_retrieval(Arc::new(unreachable_backend())),
                ),
            ];
            for (label, state) in states {
                let (status, value) = post_json(
                    router_with_state(state),
                    "/index",
                    &json!({"repo_path": path, "collection": "repo_missing"}),
                )
                .await;
                assert_eq!(
                    status,
                    StatusCode::UNPROCESSABLE_ENTITY,
                    "{label} answered {status} for {}: {value}",
                    path.display()
                );
                assert_eq!(value["detail"][0]["loc"], json!(["body", "repo_path"]));
                assert_eq!(value["detail"][0]["type"], expected_type, "{label}");
                assert!(
                    value["detail"][0]["msg"].is_string(),
                    "{label} lost the FastAPI msg"
                );
            }
        }
    }

    /// The regression guard for the two cases above: narrowing the mapping must
    /// not let a genuine outage through as a client error. Everything about
    /// this request is valid — the path exists, nothing holds the run guard —
    /// and the only thing wrong is that Qdrant cannot be reached.
    #[tokio::test]
    async fn unreachable_backend_still_returns_503_backend_not_ready() {
        let temp = tempfile::tempdir().unwrap();
        let repo = temp.path().join("repo");
        std::fs::create_dir_all(&repo).unwrap();
        std::fs::write(repo.join("app.py"), "def alpha(value):\n    return value\n").unwrap();

        let app = router_with_state(
            ServerState::new(None)
                .with_rag_home(temp.path().join("rag-home"))
                .with_retrieval(Arc::new(unreachable_backend())),
        );
        let (status, value) = post_json(
            app,
            "/index",
            &json!({"repo_path": repo, "collection": "repo_offline"}),
        )
        .await;

        assert_eq!(
            status,
            StatusCode::SERVICE_UNAVAILABLE,
            "a real outage stopped being a 503: {value}"
        );
        assert_eq!(value["code"], "BACKEND_NOT_READY");
        assert_eq!(value["error"], "Live retrieval backend is unavailable");
    }

    /// The rejection wire format is the contract between the write paths and
    /// the HTTP mapping. Field names never contain `": "`, messages do, so the
    /// split has to be on the first separator only — and an error nobody
    /// tagged must stay unclassified (i.e. a 503).
    #[test]
    fn route_rejections_round_trip_and_leave_untagged_errors_alone() {
        use super::indexing::RouteRejection;

        for rejection in [
            RouteRejection::Conflict("another index run is already in progress for /a: b".into()),
            RouteRejection::PathNotFound {
                field: "repo_path".into(),
                message: "file or directory at path \"/a: b\" does not exist".into(),
            },
            RouteRejection::PathNotDirectory {
                field: "docs_path".into(),
                message: "path \"/a: b\" does not point to a directory".into(),
            },
        ] {
            let encoded = rejection.encode();
            assert_eq!(
                RouteRejection::decode(&encoded),
                Some(rejection),
                "{encoded}"
            );
        }
        for untagged in [
            "qdrant returned HTTP 500: internal error",
            "unknown repo: sample",
            "",
        ] {
            assert_eq!(RouteRejection::decode(untagged), None, "{untagged}");
        }
    }
}
