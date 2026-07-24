//! Snapshot collection for the TUI — the client side of Python's
//! `StackMonitor`. Daemon data comes over HTTP; Ollama/Docker/Qdrant/LSP are
//! probed directly through `rag_server::stack` so the dashboard stays useful
//! when the daemon is down — which is precisely when it is needed most.

use rag_config::{RagPaths, Settings};
use rag_server::stack::{
    self, humanize_ago, humanize_seconds, LspServerStatus, ServiceHealth, DOWN, OK, WARN,
};
use serde_json::{json, Value};

use crate::client::ApiClient;

/// Everything the dashboard renders, gathered in one pass.
#[derive(Debug, Clone)]
pub struct Snapshot {
    pub daemon_up: bool,
    pub daemon: ServiceHealth,
    pub ollama: ServiceHealth,
    pub docker: ServiceHealth,
    pub qdrant: ServiceHealth,
    pub ast_index: ServiceHealth,
    pub repos: Vec<RepoRow>,
    pub repos_source: &'static str, // "daemon" | "local"
    pub lsp: Vec<LspServerStatus>,
    pub stats: Value,
    pub queries: Vec<Value>,
    pub events: Vec<Value>,
    pub jobs: Value,
}

impl Default for Snapshot {
    fn default() -> Self {
        Self {
            daemon_up: false,
            daemon: checking("DAEMON"),
            ollama: checking("OLLAMA"),
            docker: checking("DOCKER"),
            qdrant: checking("QDRANT"),
            ast_index: checking("AST-INDEX"),
            repos: Vec::new(),
            repos_source: "daemon",
            lsp: Vec::new(),
            stats: json!({}),
            queries: Vec::new(),
            events: Vec::new(),
            jobs: json!({}),
        }
    }
}

fn checking(name: &str) -> ServiceHealth {
    let mut svc = ServiceHealth::new(name);
    svc.headline = "checking…".to_owned();
    svc
}

/// One row of the PROJECT INDEXES table.
#[derive(Debug, Clone)]
pub struct RepoRow {
    pub name: String,
    pub path: String,
    pub collection: String,
    pub points: u64,
    pub files: usize,
    pub last_indexed: String,
    pub status: String,
    pub kind: String, // "repo" | "default"
}

/// Collect a full or fast snapshot. Never fails; `previous` supplies the
/// external-probe cards on the fast (daemon-only) cadence.
pub async fn collect(
    client: &ApiClient,
    paths: Option<&RagPaths>,
    settings: &Settings,
    fast_only: bool,
    previous: &Snapshot,
) -> Snapshot {
    let mut snap = Snapshot::default();

    let (daemon_pass, activity, external) = tokio::join!(
        check_daemon(client, paths),
        collect_activity(client),
        async {
            if fast_only {
                None
            } else {
                Some(stack::external_checks(settings).await)
            }
        },
    );

    let (daemon, daemon_up, status) = daemon_pass;
    snap.daemon = daemon;
    snap.daemon_up = daemon_up;
    (snap.stats, snap.queries, snap.events, snap.jobs) = activity;

    match external {
        Some(checks) => {
            snap.ollama = checks.ollama;
            snap.docker = checks.docker;
            snap.qdrant = checks.qdrant;
            snap.ast_index = checks.ast_index;
            snap.lsp = checks.lsp;
        }
        None => {
            snap.ollama = previous.ollama.clone();
            snap.docker = previous.docker.clone();
            snap.qdrant = previous.qdrant.clone();
            snap.ast_index = previous.ast_index.clone();
            snap.lsp = previous.lsp.clone();
        }
    }

    snap.repos = collect_repos(client, paths, daemon_up, status.as_ref()).await;
    snap.repos_source = if daemon_up { "daemon" } else { "local" };
    snap
}

/// `/health` + `/status` → the DAEMON card (Python `_check_daemon`).
async fn check_daemon(
    client: &ApiClient,
    paths: Option<&RagPaths>,
) -> (ServiceHealth, bool, Option<Value>) {
    let mut svc = ServiceHealth::new("DAEMON");
    svc.hint = "press D to start · or: rag start".to_owned();
    let base = client.base_url().to_owned();

    let Ok(health) = client.get("/health").await else {
        svc.state = DOWN.to_owned();
        svc.headline = "not running".to_owned();
        svc.lines = vec![base];
        if let Some(paths) = paths {
            let crash = last_daemon_error(paths);
            if !crash.is_empty() {
                svc.lines.push(crash);
            }
        }
        return (svc, false, None);
    };

    let degraded = health.get("status").and_then(Value::as_str) != Some("ok");
    svc.state = if degraded { WARN } else { OK }.to_owned();
    svc.lines = vec![base];

    let status = client.get("/status").await.ok();
    match &status {
        Some(status) => {
            let up = humanize_seconds(
                status
                    .get("uptime_seconds")
                    .and_then(Value::as_f64)
                    .unwrap_or(0.0),
            );
            svc.headline = format!("running · up {up}");
            let restarts = status
                .get("restart_count")
                .and_then(Value::as_i64)
                .unwrap_or(0);
            svc.lines.push(match restarts {
                0 => "no restarts".to_owned(),
                1 => "1 restart".to_owned(),
                n => format!("{n} restarts"),
            });
            let files = status
                .get("files_indexed")
                .and_then(Value::as_i64)
                .unwrap_or(0);
            if files > 0 {
                svc.lines
                    .push(format!("{} files indexed", group_thousands(files)));
            }
        }
        None => {
            svc.headline = if degraded {
                "degraded".to_owned()
            } else {
                "running (auth failed on /status)".to_owned()
            };
        }
    }

    let components = health
        .get("components")
        .cloned()
        .unwrap_or_else(|| json!({}));
    let mut bits = Vec::new();
    for comp in ["qdrant", "embedder", "ollama"] {
        let val = components
            .get(comp)
            .and_then(Value::as_str)
            .unwrap_or("?")
            .to_owned();
        if comp == "qdrant" && val != "ok" {
            svc.state = WARN.to_owned();
            svc.hint = "qdrant component failing — press U to start Qdrant".to_owned();
        }
        bits.push(format!("{comp}:{val}"));
    }
    svc.lines.push(bits.join("  "));
    if svc.state == OK {
        svc.hint = String::new();
    }
    (svc, true, status)
}

/// Query stats, recent queries, events and index jobs in one daemon pass.
async fn collect_activity(client: &ApiClient) -> (Value, Vec<Value>, Vec<Value>, Value) {
    let (stats, recent, events, jobs) = tokio::join!(
        client.get("/queries/stats?window=100"),
        client.get("/queries/recent?limit=100"),
        client.get("/events/recent?limit=300"),
        client.get("/index/jobs"),
    );
    (
        stats.unwrap_or_else(|_| json!({})),
        recent
            .ok()
            .and_then(|v| v.get("queries").and_then(Value::as_array).cloned())
            .unwrap_or_default(),
        events
            .ok()
            .and_then(|v| v.get("events").and_then(Value::as_array).cloned())
            .unwrap_or_default(),
        jobs.ok()
            .and_then(|v| v.get("jobs").cloned())
            .unwrap_or_else(|| json!({})),
    )
}

/// Project indexes: `/status.collections` when the daemon is up, the local
/// registry otherwise (Python `_collect_repos`).
async fn collect_repos(
    client: &ApiClient,
    paths: Option<&RagPaths>,
    daemon_up: bool,
    status: Option<&Value>,
) -> Vec<RepoRow> {
    let mut collections: Vec<Value> = status
        .and_then(|s| s.get("collections").and_then(Value::as_array).cloned())
        .unwrap_or_default()
        .into_iter()
        .filter(Value::is_object)
        .collect();
    if collections.is_empty() && daemon_up {
        collections = client
            .get("/collections")
            .await
            .ok()
            .and_then(|v| v.get("collections").and_then(Value::as_array).cloned())
            .unwrap_or_default();
    }

    if !collections.is_empty() {
        let mut rows = Vec::new();
        for c in &collections {
            let path = c
                .get("path")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_owned();
            let files = match (paths, path.is_empty()) {
                (Some(paths), false) => stack::repo_state_files(paths, &path),
                _ => 0,
            };
            rows.push(RepoRow {
                name: c
                    .get("repo")
                    .or_else(|| c.get("name"))
                    .and_then(Value::as_str)
                    .unwrap_or("?")
                    .to_owned(),
                path,
                collection: c
                    .get("name")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_owned(),
                points: c.get("points_count").and_then(Value::as_u64).unwrap_or(0),
                files,
                last_indexed: local_last_indexed(paths, c.get("repo").and_then(Value::as_str)),
                status: c
                    .get("status")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_owned(),
                kind: c
                    .get("kind")
                    .and_then(Value::as_str)
                    .unwrap_or("repo")
                    .to_owned(),
            });
        }
        return rows;
    }

    // Daemon down (or gave nothing): read the local registry read-only.
    let Some(paths) = paths else {
        return Vec::new();
    };
    let paths = paths.clone();
    tokio::task::spawn_blocking(move || {
        rag_storage::RepoRegistry::open(&paths)
            .and_then(|registry| registry.list_repos())
            .map(|repos| {
                repos
                    .into_iter()
                    .map(|r| RepoRow {
                        files: stack::repo_state_files(&paths, &r.path),
                        last_indexed: humanize_ago(r.last_indexed.as_deref()),
                        name: r.name,
                        path: r.path,
                        collection: r.collection,
                        points: u64::try_from(r.chunks_count).unwrap_or(0),
                        status: String::new(),
                        kind: "repo".to_owned(),
                    })
                    .collect()
            })
            .unwrap_or_default()
    })
    .await
    .unwrap_or_default()
}

fn local_last_indexed(paths: Option<&RagPaths>, repo: Option<&str>) -> String {
    let (Some(paths), Some(repo)) = (paths, repo) else {
        return String::new();
    };
    rag_storage::RepoRegistry::open(paths)
        .and_then(|registry| registry.list_repos())
        .ok()
        .and_then(|repos| {
            repos
                .into_iter()
                .find(|r| r.name == repo)
                .map(|r| humanize_ago(r.last_indexed.as_deref()))
        })
        .unwrap_or_default()
}

/// Last error event from `~/.rag/logs/daemon.jsonl` — why the daemon died.
/// Ignored when the log is older than a day (Python `_last_daemon_error`).
fn last_daemon_error(paths: &RagPaths) -> String {
    let log_path = paths.home.join("logs").join("daemon.jsonl");
    let Ok(meta) = std::fs::metadata(&log_path) else {
        return String::new();
    };
    let recent = meta
        .modified()
        .ok()
        .and_then(|m| m.elapsed().ok())
        .is_some_and(|age| age.as_secs() < 86_400);
    if !recent {
        return String::new();
    }
    let Ok(text) = std::fs::read_to_string(&log_path) else {
        return String::new();
    };
    let lines: Vec<&str> = text.lines().rev().take(200).collect();
    let errors: Vec<Value> = lines
        .iter()
        .filter_map(|line| serde_json::from_str::<Value>(line).ok())
        .filter(|entry| entry.get("level").and_then(Value::as_str) == Some("error"))
        .collect();
    let entry = errors
        .iter()
        .take(6)
        .find(|e| {
            e.get("error")
                .and_then(Value::as_str)
                .is_some_and(|s| !s.is_empty())
        })
        .or_else(|| errors.first());
    let Some(entry) = entry else {
        return String::new();
    };
    let msg = entry
        .get("error")
        .or_else(|| entry.get("event"))
        .and_then(Value::as_str)
        .unwrap_or("")
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ");
    if msg.is_empty() {
        return String::new();
    }
    let when = humanize_ago(entry.get("timestamp").and_then(Value::as_str));
    let suffix = if when.is_empty() {
        String::new()
    } else {
        format!(" ({when})")
    };
    let truncated: String = msg.chars().take(110).collect();
    format!("crash: {truncated}{suffix}")
}

/// `46121` → `46 121` (the dashboards use space-grouped thousands).
#[must_use]
pub fn group_thousands(n: i64) -> String {
    let raw = n.abs().to_string();
    let mut grouped = String::new();
    for (i, ch) in raw.chars().enumerate() {
        if i > 0 && (raw.len() - i) % 3 == 0 {
            grouped.push(' ');
        }
        grouped.push(ch);
    }
    if n < 0 {
        format!("-{grouped}")
    } else {
        grouped
    }
}

#[cfg(test)]
mod tests {
    use super::group_thousands;

    #[test]
    fn thousands_are_space_grouped() {
        assert_eq!(group_thousands(0), "0");
        assert_eq!(group_thousands(999), "999");
        assert_eq!(group_thousands(46_121), "46 121");
        assert_eq!(group_thousands(1_234_567), "1 234 567");
    }
}
