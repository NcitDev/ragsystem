//! Stack health probes — the Rust port of Python's `rag.tui.monitor.StackMonitor`.
//!
//! Shared by the daemon's `/stack` route and the `rag tui` dashboard so both
//! frontends render identical service cards. Each check is independently
//! timeboxed and failure-isolated: the dashboard must stay informative when
//! parts of the stack are down, which is precisely when it is needed most.

use std::{
    path::Path,
    sync::OnceLock,
    time::{Duration, Instant},
};

use rag_config::{load_settings, RagPaths, Settings};
use rag_index::detect_lsp_servers;
pub use rag_index::LspServerStatus;
use rag_storage::{IndexState, RepoRegistry};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

/// Service states, mirrored from the Python TUI.
pub const OK: &str = "ok";
pub const WARN: &str = "warn";
pub const DOWN: &str = "down";
pub const OFF: &str = "off";

pub const QDRANT_CONTAINER: &str = "rag-qdrant";

/// The external `ast-index` CLI backs every symbol-exact route (`/resolve`,
/// `/graph/*`, `/call-tree`, `/context-pack`, the structural stage of
/// `/smart-search`). Its absence is otherwise silent — those routes return
/// empty results, not errors — so the dashboards get a card for it.
pub const AST_INDEX_INSTALL_HINT: &str =
    "npm install -g @ast-index/cli · then: cd <repo> && ast-index rebuild";
/// Probing spawns a subprocess and the web dashboard polls `/stack` every 12s;
/// an install/uninstall does not need to show up within a single poll.
const AST_INDEX_TTL: Duration = Duration::from_secs(300);
const AST_INDEX_TIMEOUT: Duration = Duration::from_secs(5);

/// One service card on the dashboard (Python `ServiceHealth` asdict shape).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServiceHealth {
    pub name: String,
    pub state: String,
    pub headline: String,
    pub lines: Vec<String>,
    pub hint: String,
}

impl ServiceHealth {
    #[must_use]
    pub fn new(name: &str) -> Self {
        Self {
            name: name.to_owned(),
            state: DOWN.to_owned(),
            headline: String::new(),
            lines: Vec::new(),
            hint: String::new(),
        }
    }
}

/// The external probes: everything that must work when the daemon is down.
#[derive(Debug, Clone, Serialize)]
pub struct ExternalChecks {
    pub ts: f64,
    pub ollama: ServiceHealth,
    pub docker: ServiceHealth,
    pub qdrant: ServiceHealth,
    pub ast_index: ServiceHealth,
    pub lsp: Vec<LspServerStatus>,
    pub service: Value,
}

fn epoch_now() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

fn probe_client() -> Option<reqwest::Client> {
    reqwest::Client::builder()
        .timeout(Duration::from_secs(3))
        .connect_timeout(Duration::from_secs(2))
        .build()
        .ok()
}

/// Run every non-daemon probe concurrently. Never fails.
pub async fn external_checks(settings: &Settings) -> ExternalChecks {
    let http = probe_client();
    let (ollama, docker, qdrant, ast_index) = match http {
        Some(http) => tokio::join!(
            check_ollama(&http, settings),
            check_docker(&settings.qdrant.mode),
            check_qdrant(&http, settings),
            check_ast_index(),
        ),
        None => (
            ServiceHealth::new("OLLAMA"),
            ServiceHealth::new("DOCKER"),
            ServiceHealth::new("QDRANT"),
            check_ast_index().await,
        ),
    };
    ExternalChecks {
        ts: epoch_now(),
        ollama,
        docker,
        qdrant,
        ast_index,
        lsp: detect_lsp_servers(None),
        // launchd info is macOS-only in the Python TUI; empty elsewhere.
        service: json!({}),
    }
}

async fn check_ollama(http: &reqwest::Client, settings: &Settings) -> ServiceHealth {
    let mut svc = ServiceHealth::new("OLLAMA");
    svc.hint = "run: ollama serve".to_owned();
    let base = settings.llm.ollama_url.trim_end_matches('/');
    let version = match get_json(http, &format!("{base}/api/version")).await {
        Some(value) => value
            .get("version")
            .and_then(Value::as_str)
            .unwrap_or("?")
            .to_owned(),
        None => {
            svc.state = DOWN.to_owned();
            svc.headline = "not running".to_owned();
            svc.lines = vec![base.to_owned()];
            return svc;
        }
    };

    svc.state = OK.to_owned();
    svc.headline = format!("running · v{version}");
    let models: Vec<String> = get_json(http, &format!("{base}/api/tags"))
        .await
        .and_then(|value| {
            value.get("models").and_then(Value::as_array).map(|items| {
                items
                    .iter()
                    .filter_map(|m| m.get("name").and_then(Value::as_str))
                    .map(str::to_owned)
                    .collect()
            })
        })
        .unwrap_or_default();

    let embed_model = settings
        .embeddings
        .model
        .rsplit('/')
        .next()
        .unwrap_or(&settings.embeddings.model)
        .to_lowercase();
    let agent_model = &settings.llm.agent_model;
    let has_embed = models
        .iter()
        .any(|m| m.to_lowercase().contains(&embed_model));
    let has_agent = models.iter().any(|m| m.contains(agent_model.as_str()));
    svc.lines = vec![format!("{} models installed", models.len())];
    svc.lines.push(format!(
        "embedder {}",
        if has_embed { "✓" } else { "✗ missing" }
    ));
    svc.lines.push(format!(
        "agent {agent_model} {}",
        if has_agent { "✓" } else { "✗ missing" }
    ));
    if !has_embed {
        svc.state = WARN.to_owned();
        svc.hint = format!(
            "ollama pull {} — or point [embeddings].model in ~/.rag/config.toml at an installed tag",
            settings.embeddings.model
        );
    } else {
        svc.hint = String::new();
    }

    if let Some(ps) = get_json(http, &format!("{base}/api/ps")).await {
        let loaded = ps
            .get("models")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        if loaded.is_empty() {
            svc.lines.push("loaded: none (cold)".to_owned());
        } else {
            for model in loaded.iter().take(3) {
                let vram = model
                    .get("size_vram")
                    .or_else(|| model.get("size"))
                    .and_then(Value::as_f64)
                    .map(humanize_bytes)
                    .unwrap_or_default();
                let name = model.get("name").and_then(Value::as_str).unwrap_or("?");
                svc.lines.push(format!("loaded: {name} {vram}"));
            }
        }
    }
    svc
}

async fn check_docker(qdrant_mode: &str) -> ServiceHealth {
    let mut svc = ServiceHealth::new("DOCKER");
    if which("docker").is_none() {
        svc.state = OFF.to_owned();
        svc.headline = "docker CLI not installed".to_owned();
        svc.hint = "install Docker Desktop (needed for Qdrant server mode)".to_owned();
        return svc;
    }
    let output = tokio::time::timeout(
        Duration::from_secs(5),
        tokio::process::Command::new("docker")
            .args([
                "ps",
                "-a",
                "--format",
                "{{.Names}}\t{{.State}}\t{{.Status}}",
            ])
            .kill_on_drop(true)
            .output(),
    )
    .await;
    let output = match output {
        Ok(Ok(output)) => output,
        _ => {
            svc.state = DOWN.to_owned();
            svc.headline = "docker not responding".to_owned();
            svc.hint = "start Docker Desktop".to_owned();
            return svc;
        }
    };
    if !output.status.success() {
        svc.state = DOWN.to_owned();
        svc.headline = "docker daemon not running".to_owned();
        let err = String::from_utf8_lossy(&output.stderr);
        if let Some(first) = err.trim().lines().next() {
            svc.lines = vec![first.chars().take(60).collect()];
        }
        svc.hint = "start Docker Desktop".to_owned();
        return svc;
    }

    svc.state = OK.to_owned();
    let mut running = 0usize;
    let mut container_line = String::new();
    let mut container_running = false;
    for line in String::from_utf8_lossy(&output.stdout).lines() {
        let parts: Vec<&str> = line.split('\t').collect();
        if parts.len() < 3 {
            continue;
        }
        let (name, state, status) = (parts[0], parts[1], parts[2]);
        if state == "running" {
            running += 1;
        }
        if name == QDRANT_CONTAINER {
            container_running = state == "running";
            container_line = format!("{QDRANT_CONTAINER}: {status}");
        }
    }
    svc.headline = format!(
        "running · {running} container{} up",
        if running == 1 { "" } else { "s" }
    );
    if !container_line.is_empty() {
        svc.lines = vec![container_line];
        if !container_running && qdrant_mode == "server" {
            svc.state = WARN.to_owned();
            svc.hint = "press U to start the Qdrant container".to_owned();
        }
    } else if qdrant_mode == "server" {
        svc.lines = vec![format!("{QDRANT_CONTAINER}: not created")];
        svc.state = WARN.to_owned();
        svc.hint = "press U (runs docker compose up for Qdrant)".to_owned();
    }
    svc
}

async fn check_qdrant(http: &reqwest::Client, settings: &Settings) -> ServiceHealth {
    let mut svc = ServiceHealth::new("QDRANT");
    if settings.qdrant.mode != "server" {
        svc.state = OK.to_owned();
        svc.headline = "embedded mode".to_owned();
        svc.lines = vec![settings.qdrant.path.clone()];
        return svc;
    }
    let base = settings.qdrant.url.trim_end_matches('/');
    let version = match get_json(http, &format!("{base}/")).await {
        Some(value) => value
            .get("version")
            .and_then(Value::as_str)
            .unwrap_or("?")
            .to_owned(),
        None => {
            svc.state = DOWN.to_owned();
            svc.headline = "not reachable".to_owned();
            svc.lines = vec![base.to_owned()];
            svc.hint = "press U to start · or: rag qdrant-up".to_owned();
            return svc;
        }
    };
    svc.state = OK.to_owned();
    svc.headline = format!("running · v{version}");
    svc.lines = vec![base.to_owned()];
    if let Some(cols) = get_json(http, &format!("{base}/collections")).await {
        let count = cols
            .get("result")
            .and_then(|r| r.get("collections"))
            .and_then(Value::as_array)
            .map_or(0, Vec::len);
        svc.lines.push(format!("{count} collections"));
    }
    svc
}

/// Cached `(checked_at, available)` — the probe shells out, so it is rate
/// limited to one subprocess per [`AST_INDEX_TTL`] across every poller.
static AST_INDEX_PROBE: OnceLock<tokio::sync::Mutex<Option<(Instant, bool)>>> = OnceLock::new();

/// `Some(available)`, or `None` when the probe timed out with nothing cached.
async fn ast_index_available() -> Option<bool> {
    let cache = AST_INDEX_PROBE.get_or_init(|| tokio::sync::Mutex::new(None));
    let mut cached = cache.lock().await;
    if let Some((checked_at, available)) = *cached {
        if checked_at.elapsed() < AST_INDEX_TTL {
            return Some(available);
        }
    }
    // `is_available()` spawns `ast-index --version` with the blocking std API.
    let probe = tokio::time::timeout(
        AST_INDEX_TIMEOUT,
        tokio::task::spawn_blocking(rag_retrieval::ast_index::is_available),
    )
    .await;
    match probe {
        Ok(Ok(available)) => {
            *cached = Some((Instant::now(), available));
            Some(available)
        }
        // A hung or panicking probe keeps the last answer rather than lying.
        _ => cached.map(|(_, available)| available),
    }
}

async fn check_ast_index() -> ServiceHealth {
    let mut svc = ServiceHealth::new("AST-INDEX");
    match ast_index_available().await {
        Some(true) => {
            svc.state = OK.to_owned();
            svc.headline = "installed".to_owned();
            svc.lines = vec![
                which("ast-index")
                    .map_or_else(|| "on PATH".to_owned(), |path| path.display().to_string()),
                "symbol navigation enabled".to_owned(),
            ];
        }
        Some(false) => {
            svc.state = WARN.to_owned();
            svc.headline = "not installed".to_owned();
            svc.lines = vec![
                "resolve · callers · callees · impact return empty".to_owned(),
                "smart-search loses its structural stage".to_owned(),
            ];
            svc.hint = AST_INDEX_INSTALL_HINT.to_owned();
        }
        None => {
            svc.state = WARN.to_owned();
            svc.headline = "probe timed out".to_owned();
            svc.lines = vec!["ast-index --version did not answer".to_owned()];
            svc.hint = AST_INDEX_INSTALL_HINT.to_owned();
        }
    }
    svc
}

async fn get_json(http: &reqwest::Client, url: &str) -> Option<Value> {
    let response = http.get(url).send().await.ok()?;
    if !response.status().is_success() {
        return None;
    }
    response.json().await.ok()
}

/// Per-repo metadata the registry knows but `/status` does not carry:
/// indexed-file count from `state.json` and a humanized last-indexed stamp.
#[must_use]
pub fn repos_meta(paths: &RagPaths) -> Value {
    let mut out = serde_json::Map::new();
    let repos = RepoRegistry::open(paths)
        .and_then(|registry| registry.list_repos())
        .unwrap_or_default();
    for repo in repos {
        out.insert(
            repo.name.clone(),
            json!({
                "files": repo_state_files(paths, &repo.path),
                "last_indexed": humanize_ago(repo.last_indexed.as_deref()),
            }),
        );
    }
    Value::Object(out)
}

/// Count of indexed files from `~/.rag/repos/<sha>/state.json`.
#[must_use]
pub fn repo_state_files(paths: &RagPaths, repo_path: &str) -> usize {
    IndexState::load(paths, Path::new(repo_path))
        .map(|state| state.file_hashes.len())
        .unwrap_or(0)
}

/// The daemon's `/stack` response (Python parity: `asdict` of the snapshot's
/// external slice — the daemon card is built client-side from `/health`).
pub async fn stack_status_json(paths: &RagPaths) -> Value {
    let settings = load_settings(paths).unwrap_or_default();
    let checks = external_checks(&settings).await;
    let repos_meta = tokio::task::spawn_blocking({
        let paths = paths.clone();
        move || repos_meta(&paths)
    })
    .await
    .unwrap_or_else(|_| json!({}));
    json!({
        "ts": checks.ts,
        "ollama": checks.ollama,
        "docker": checks.docker,
        "qdrant": checks.qdrant,
        "ast_index": checks.ast_index,
        "lsp": checks.lsp,
        "service": checks.service,
        "repos_meta": repos_meta,
    })
}

/// Start the Qdrant container — the TUI's `U` key and `/stack/qdrant/start`.
pub async fn start_qdrant() -> String {
    if which("docker").is_none() {
        return "docker CLI not found — install Docker Desktop".to_owned();
    }
    let result = tokio::time::timeout(
        Duration::from_secs(20),
        tokio::process::Command::new("docker")
            .args(["start", QDRANT_CONTAINER])
            .kill_on_drop(true)
            .output(),
    )
    .await;
    match result {
        Ok(Ok(output)) if output.status.success() => format!("{QDRANT_CONTAINER} starting"),
        Ok(Ok(_)) => format!("container {QDRANT_CONTAINER} missing — run: rag qdrant-up"),
        Ok(Err(error)) => format!("docker start failed: {error}"),
        Err(_) => "docker start timed out".to_owned(),
    }
}

fn which(binary: &str) -> Option<std::path::PathBuf> {
    let path = std::env::var_os("PATH")?;
    std::env::split_paths(&path)
        .map(|dir| dir.join(binary))
        .find(|candidate| candidate.is_file())
}

// --- humanizers (Python `rag.tui.monitor` ports) --------------------------------

#[must_use]
pub fn humanize_seconds(seconds: f64) -> String {
    let seconds = seconds.max(0.0) as u64;
    let (days, rem) = (seconds / 86_400, seconds % 86_400);
    let (hours, rem) = (rem / 3_600, rem % 3_600);
    let minutes = rem / 60;
    if days > 0 {
        format!("{days}d {hours}h")
    } else if hours > 0 {
        format!("{hours}h {minutes}m")
    } else {
        format!("{minutes}m")
    }
}

/// `"2d ago"` from an ISO-8601 string; empty when unparseable.
#[must_use]
pub fn humanize_ago(iso: Option<&str>) -> String {
    let Some(iso) = iso.filter(|s| !s.is_empty()) else {
        return String::new();
    };
    let parsed = chrono::DateTime::parse_from_rfc3339(&iso.replace("Z", "+00:00"))
        .map(|dt| dt.timestamp() as f64)
        .or_else(|_| {
            chrono::NaiveDateTime::parse_from_str(iso, "%Y-%m-%dT%H:%M:%S%.f")
                .map(|dt| dt.and_utc().timestamp() as f64)
        });
    let Ok(then) = parsed else {
        return String::new();
    };
    let delta = epoch_now() - then;
    if delta < 90.0 {
        "just now".to_owned()
    } else if delta < 3_600.0 {
        format!("{}m ago", (delta / 60.0) as u64)
    } else if delta < 86_400.0 {
        format!("{}h ago", (delta / 3_600.0) as u64)
    } else {
        format!("{}d ago", (delta / 86_400.0) as u64)
    }
}

#[must_use]
pub fn humanize_bytes(n: f64) -> String {
    let mut size = n;
    for unit in ["B", "KB", "MB", "GB", "TB"] {
        if size < 1024.0 || unit == "TB" {
            return if unit == "B" || unit == "KB" {
                format!("{size:.0}{unit}")
            } else {
                format!("{size:.1}{unit}")
            };
        }
        size /= 1024.0;
    }
    String::new()
}

#[cfg(test)]
mod tests {
    use super::{
        ast_index_available, check_ast_index, humanize_ago, humanize_bytes, humanize_seconds,
        ServiceHealth, AST_INDEX_PROBE, OK, WARN,
    };

    #[test]
    fn humanize_seconds_matches_python() {
        assert_eq!(humanize_seconds(59.0), "0m");
        assert_eq!(humanize_seconds(3_660.0), "1h 1m");
        assert_eq!(humanize_seconds(90_000.0), "1d 1h");
    }

    #[test]
    fn humanize_bytes_matches_python() {
        assert_eq!(humanize_bytes(512.0), "512B");
        assert_eq!(humanize_bytes(2.5 * 1024.0 * 1024.0), "2.5MB");
    }

    #[test]
    fn humanize_ago_handles_bad_input() {
        assert_eq!(humanize_ago(None), "");
        assert_eq!(humanize_ago(Some("not-a-date")), "");
        assert_eq!(humanize_ago(Some("")), "");
    }

    #[test]
    fn service_health_serializes_python_shape() {
        let svc = ServiceHealth::new("OLLAMA");
        let value = serde_json::to_value(&svc).unwrap();
        for key in ["name", "state", "headline", "lines", "hint"] {
            assert!(value.get(key).is_some(), "missing key {key}");
        }
    }

    /// The card must render on both kinds of machine: with `ast-index` on PATH
    /// and without it. Missing must never be silent — it carries an install hint.
    #[tokio::test]
    async fn ast_index_card_is_a_dashboard_service_card() {
        let svc = check_ast_index().await;
        assert_eq!(svc.name, "AST-INDEX");
        assert!(matches!(svc.state.as_str(), OK | WARN), "{}", svc.state);
        assert!(!svc.headline.is_empty());
        assert!(!svc.lines.is_empty());
        if svc.state == WARN {
            assert!(svc.hint.contains("ast-index"), "{}", svc.hint);
        }
        let value = serde_json::to_value(&svc).unwrap();
        for key in ["name", "state", "headline", "lines", "hint"] {
            assert!(value.get(key).is_some(), "missing key {key}");
        }
    }

    /// `/stack` is polled every 12s by the web dashboard; the subprocess probe
    /// must be served from cache in between.
    #[tokio::test]
    async fn ast_index_probe_is_cached() {
        let first = ast_index_available().await;
        let second = ast_index_available().await;
        assert_eq!(first, second);
        if first.is_some() {
            let cache = AST_INDEX_PROBE.get().expect("probe cache initialised");
            assert!(cache.lock().await.is_some());
        }
    }
}
