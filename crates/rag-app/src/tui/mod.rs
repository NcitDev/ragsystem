//! `rag tui` — the stack dashboard (Rust port of the Python Textual app).
//!
//! Six screens (Dashboard, Search, Ask, Index, Logs, Help) rendered from a
//! [`data::Snapshot`]; widgets do no I/O themselves. Fast daemon polls every
//! 3s, the expensive external probes (Docker CLI, Ollama tags, LSP scan)
//! every 12s — same cadence as the web dashboard.

mod data;
mod ui;

use std::{
    io,
    time::{Duration, Instant},
};

use crossterm::{
    event::{self, Event, KeyCode, KeyEvent, KeyModifiers},
    execute,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
};
use rag_config::{RagPaths, Settings};
use ratatui::{backend::CrosstermBackend, Terminal};
use serde_json::{json, Value};
use tokio::sync::mpsc;

use crate::client::ApiClient;
use data::Snapshot;

const FAST_POLL: Duration = Duration::from_secs(3);
const SLOW_POLL: Duration = Duration::from_secs(12);

/// `rag tui --snapshot`: emit one full stack snapshot as JSON and exit.
pub async fn snapshot(client: &ApiClient) -> Value {
    let paths = RagPaths::from_env().ok();
    let settings = load_settings_or_default(paths.as_ref());
    let snap = data::collect(
        client,
        paths.as_ref(),
        &settings,
        false,
        &Snapshot::default(),
    )
    .await;
    json!({
        "daemon_up": snap.daemon_up,
        "daemon": snap.daemon,
        "ollama": snap.ollama,
        "docker": snap.docker,
        "qdrant": snap.qdrant,
        "repos": snap.repos.iter().map(|r| json!({
            "name": r.name, "path": r.path, "collection": r.collection,
            "points": r.points, "files": r.files, "last_indexed": r.last_indexed,
            "status": r.status, "kind": r.kind,
        })).collect::<Vec<_>>(),
        "repos_source": snap.repos_source,
        "lsp": snap.lsp,
        "stats": snap.stats,
        "queries": snap.queries,
        "jobs": snap.jobs,
    })
}

fn load_settings_or_default(paths: Option<&RagPaths>) -> Settings {
    paths
        .and_then(|paths| rag_config::load_settings(paths).ok())
        .unwrap_or_default()
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ScreenId {
    Home,
    Search,
    Ask,
    Index,
    Logs,
    Help,
}

impl ScreenId {
    pub fn title(self) -> &'static str {
        match self {
            Self::Home => "Dashboard",
            Self::Search => "Search",
            Self::Ask => "Ask",
            Self::Index => "Index",
            Self::Logs => "Logs",
            Self::Help => "Help",
        }
    }
}

/// Which text input currently swallows keystrokes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Focus {
    None,
    Query,
    Repo,
}

#[derive(Debug, Default)]
pub struct SearchState {
    pub query: String,
    pub repo: String,
    pub results: Vec<Value>,
    pub selected: usize,
    pub plan: String,
    pub running: bool,
}

#[derive(Debug, Default)]
pub struct AskState {
    pub question: String,
    pub repo: String,
    pub answer: String,
    pub citations: Vec<String>,
    pub meta: String,
    pub running: bool,
}

#[derive(Debug, Default)]
pub struct IndexScreenState {
    pub path: String,
    pub full: bool,
    pub status_line: String,
    pub running: bool,
}

enum Msg {
    Snap(Box<Snapshot>),
    SearchDone(Result<Value, String>),
    AskDone(Result<Value, String>),
    IndexDone(Result<Value, String>),
    Note(String),
}

pub struct App {
    pub screen: ScreenId,
    pub focus: Focus,
    pub snap: Snapshot,
    pub search: SearchState,
    pub ask: AskState,
    pub index: IndexScreenState,
    pub note: Option<(String, Instant)>,
    pub settings: Settings,
    pub base_url: String,
    /// Repo names, used to prefill the search/ask repo inputs once.
    repo_prefilled: bool,
}

impl App {
    fn new(settings: Settings, base_url: String) -> Self {
        Self {
            screen: ScreenId::Home,
            focus: Focus::None,
            snap: Snapshot::default(),
            search: SearchState::default(),
            ask: AskState::default(),
            index: IndexScreenState::default(),
            note: None,
            settings,
            base_url,
            repo_prefilled: false,
        }
    }

    pub fn note_text(&self) -> Option<&str> {
        match &self.note {
            Some((text, at)) if at.elapsed() < Duration::from_secs(5) => Some(text),
            _ => None,
        }
    }

    fn set_note(&mut self, text: impl Into<String>) {
        self.note = Some((text.into(), Instant::now()));
    }

    fn apply_snapshot(&mut self, snap: Snapshot) {
        // Prefill the repo filters with the first project once, like the web.
        if !self.repo_prefilled {
            if let Some(first) = snap.repos.iter().find(|r| r.kind == "repo") {
                self.repo_prefilled = true;
                if self.search.repo.is_empty() {
                    self.search.repo = first.name.clone();
                }
                if self.ask.repo.is_empty() {
                    self.ask.repo = first.name.clone();
                }
            }
        }
        self.snap = snap;
    }
}

pub async fn run(client: &ApiClient) -> anyhow::Result<()> {
    let paths = RagPaths::from_env().ok();
    let settings = load_settings_or_default(paths.as_ref());

    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;
    let result = run_loop(&mut terminal, client, paths, settings).await;
    disable_raw_mode()?;
    execute!(terminal.backend_mut(), LeaveAlternateScreen)?;
    terminal.show_cursor()?;
    result
}

async fn run_loop(
    terminal: &mut Terminal<CrosstermBackend<io::Stdout>>,
    client: &ApiClient,
    paths: Option<RagPaths>,
    settings: Settings,
) -> anyhow::Result<()> {
    let (tx, mut rx) = mpsc::unbounded_channel::<Msg>();
    let mut app = App::new(settings.clone(), client.base_url().to_owned());

    let mut last_fast = Instant::now() - FAST_POLL;
    let mut last_slow = Instant::now() - SLOW_POLL;
    let mut poll_in_flight = false;

    loop {
        // Drain background results.
        while let Ok(msg) = rx.try_recv() {
            match msg {
                Msg::Snap(snap) => {
                    app.apply_snapshot(*snap);
                    poll_in_flight = false;
                }
                Msg::SearchDone(result) => {
                    app.search.running = false;
                    match result {
                        Ok(value) => {
                            app.search.results = value
                                .get("results")
                                .and_then(Value::as_array)
                                .cloned()
                                .unwrap_or_default();
                            app.search.selected = 0;
                            app.search.plan = render_plan(&value);
                            if app.search.results.is_empty() {
                                app.set_note("search: no results");
                            }
                        }
                        Err(error) => app.set_note(format!("search failed: {error}")),
                    }
                }
                Msg::AskDone(result) => {
                    app.ask.running = false;
                    match result {
                        Ok(value) => {
                            app.ask.answer = value
                                .get("answer")
                                .and_then(Value::as_str)
                                .unwrap_or("")
                                .to_owned();
                            app.ask.citations = value
                                .get("citations")
                                .and_then(Value::as_array)
                                .map(|items| items.iter().map(render_citation).collect())
                                .unwrap_or_default();
                            app.ask.meta = render_ask_meta(&value);
                        }
                        Err(error) => app.set_note(format!("ask failed: {error}")),
                    }
                }
                Msg::IndexDone(result) => {
                    app.index.running = false;
                    match result {
                        Ok(value) => {
                            app.index.status_line = render_index_result(&value);
                        }
                        Err(error) => {
                            app.index.status_line = format!("index failed: {error}");
                        }
                    }
                }
                Msg::Note(text) => app.set_note(text),
            }
        }

        // Schedule snapshot polls (one in flight at a time).
        if !poll_in_flight {
            let slow_due = last_slow.elapsed() >= SLOW_POLL;
            let fast_due = last_fast.elapsed() >= FAST_POLL;
            if slow_due || fast_due {
                poll_in_flight = true;
                last_fast = Instant::now();
                if slow_due {
                    last_slow = Instant::now();
                }
                let tx = tx.clone();
                let client = client.clone();
                let paths = paths.clone();
                let settings = settings.clone();
                let previous = app.snap.clone();
                tokio::spawn(async move {
                    let snap =
                        data::collect(&client, paths.as_ref(), &settings, !slow_due, &previous)
                            .await;
                    let _ = tx.send(Msg::Snap(Box::new(snap)));
                });
            }
        }

        terminal.draw(|frame| ui::draw(frame, &app))?;

        // Blocking poll with a short timeout keeps redraws at ~10fps.
        if event::poll(Duration::from_millis(100))? {
            if let Event::Key(key) = event::read()? {
                if handle_key(&mut app, key, client, &tx, &mut last_slow, &mut last_fast) {
                    return Ok(());
                }
            }
        }
    }
}

/// Returns `true` when the app should quit.
fn handle_key(
    app: &mut App,
    key: KeyEvent,
    client: &ApiClient,
    tx: &mpsc::UnboundedSender<Msg>,
    last_slow: &mut Instant,
    last_fast: &mut Instant,
) -> bool {
    if key.modifiers.contains(KeyModifiers::CONTROL) && key.code == KeyCode::Char('c') {
        return true;
    }

    if app.focus != Focus::None {
        handle_input_key(app, key, client, tx);
        return false;
    }

    match key.code {
        KeyCode::Char('q') => return true,
        KeyCode::Char('h') => switch_screen(app, ScreenId::Home),
        KeyCode::Char('s') => switch_screen(app, ScreenId::Search),
        KeyCode::Char('a') => switch_screen(app, ScreenId::Ask),
        KeyCode::Char('i') => switch_screen(app, ScreenId::Index),
        KeyCode::Char('l') => switch_screen(app, ScreenId::Logs),
        KeyCode::Char('?') => switch_screen(app, ScreenId::Help),
        KeyCode::Char('r') => {
            // Force both cadences on the next tick.
            *last_slow = Instant::now() - SLOW_POLL;
            *last_fast = Instant::now() - FAST_POLL;
            app.set_note("refreshing…");
        }
        KeyCode::Char('D') => {
            app.set_note(spawn_daemon());
        }
        KeyCode::Char('U') => {
            let tx = tx.clone();
            let client = client.clone();
            let daemon_up = app.snap.daemon_up;
            app.set_note("starting qdrant container…");
            tokio::spawn(async move {
                let message = if daemon_up {
                    match client.post("/stack/qdrant/start", json!({})).await {
                        Ok(value) => value
                            .get("message")
                            .and_then(Value::as_str)
                            .unwrap_or("done")
                            .to_owned(),
                        Err(error) => format!("start qdrant failed: {error}"),
                    }
                } else {
                    rag_server::stack::start_qdrant().await
                };
                let _ = tx.send(Msg::Note(message));
            });
        }
        KeyCode::Char('W') => {
            app.set_note(open_web(&app.base_url));
        }
        KeyCode::Char('f') if app.screen == ScreenId::Index => {
            app.index.full = !app.index.full;
        }
        KeyCode::Tab | KeyCode::Enter | KeyCode::Char('/') => {
            if screen_has_inputs(app.screen) {
                app.focus = Focus::Query;
            }
        }
        KeyCode::Up => move_selection(app, -1),
        KeyCode::Down => move_selection(app, 1),
        _ => {}
    }
    false
}

fn handle_input_key(
    app: &mut App,
    key: KeyEvent,
    client: &ApiClient,
    tx: &mpsc::UnboundedSender<Msg>,
) {
    match key.code {
        KeyCode::Esc => app.focus = Focus::None,
        KeyCode::Tab => {
            app.focus = match (app.screen, app.focus) {
                (ScreenId::Index, _) => Focus::Query,
                (_, Focus::Query) => Focus::Repo,
                _ => Focus::Query,
            };
        }
        KeyCode::Enter => submit(app, client, tx),
        KeyCode::Backspace => {
            focused_input(app).pop();
        }
        KeyCode::Char(c) if !key.modifiers.contains(KeyModifiers::CONTROL) => {
            focused_input(app).push(c);
        }
        _ => {}
    }
}

fn focused_input(app: &mut App) -> &mut String {
    match (app.screen, app.focus) {
        (ScreenId::Search, Focus::Repo) => &mut app.search.repo,
        (ScreenId::Search, _) => &mut app.search.query,
        (ScreenId::Ask, Focus::Repo) => &mut app.ask.repo,
        (ScreenId::Ask, _) => &mut app.ask.question,
        (ScreenId::Index, _) => &mut app.index.path,
        // Focus is only set on screens with inputs; default to search.
        _ => &mut app.search.query,
    }
}

fn screen_has_inputs(screen: ScreenId) -> bool {
    matches!(screen, ScreenId::Search | ScreenId::Ask | ScreenId::Index)
}

fn switch_screen(app: &mut App, screen: ScreenId) {
    app.screen = screen;
    // Entering an interactive screen focuses its main input, like the web.
    app.focus = if screen_has_inputs(screen) {
        Focus::Query
    } else {
        Focus::None
    };
}

fn move_selection(app: &mut App, delta: i64) {
    if app.screen == ScreenId::Search && !app.search.results.is_empty() {
        let len = app.search.results.len() as i64;
        let next = (app.search.selected as i64 + delta).clamp(0, len - 1);
        app.search.selected = next as usize;
    }
}

fn submit(app: &mut App, client: &ApiClient, tx: &mpsc::UnboundedSender<Msg>) {
    match app.screen {
        ScreenId::Search => {
            let query = app.search.query.trim().to_owned();
            if query.is_empty() || app.search.running {
                return;
            }
            app.search.running = true;
            app.focus = Focus::None;
            let mut body = json!({"query": query, "top_k": 10});
            let repo = app.search.repo.trim();
            if !repo.is_empty() {
                body["repo"] = json!(repo);
            }
            let client = client.clone();
            let tx = tx.clone();
            tokio::spawn(async move {
                let result = client
                    .post_with_timeout("/search", body, 60)
                    .await
                    .map_err(|e| e.to_string());
                let _ = tx.send(Msg::SearchDone(result));
            });
        }
        ScreenId::Ask => {
            let question = app.ask.question.trim().to_owned();
            if question.is_empty() || app.ask.running {
                return;
            }
            app.ask.running = true;
            app.ask.answer = String::new();
            app.ask.citations = Vec::new();
            app.ask.meta = "thinking…".to_owned();
            app.focus = Focus::None;
            let mut body = json!({"question": question});
            let repo = app.ask.repo.trim();
            if !repo.is_empty() {
                body["repo"] = json!(repo);
            }
            let client = client.clone();
            let tx = tx.clone();
            tokio::spawn(async move {
                let result = client
                    .post_with_timeout("/ask", body, 300)
                    .await
                    .map_err(|e| e.to_string());
                let _ = tx.send(Msg::AskDone(result));
            });
        }
        ScreenId::Index => {
            let path = app.index.path.trim().to_owned();
            if path.is_empty() || app.index.running {
                return;
            }
            app.index.running = true;
            app.index.status_line = format!("indexing {path}…");
            app.focus = Focus::None;
            let body = json!({"repo_path": path, "full": app.index.full});
            let client = client.clone();
            let tx = tx.clone();
            tokio::spawn(async move {
                let result = client
                    .post_with_timeout("/index", body, 600)
                    .await
                    .map_err(|e| e.to_string());
                let _ = tx.send(Msg::IndexDone(result));
            });
        }
        _ => {}
    }
}

fn render_plan(value: &Value) -> String {
    let Some(plan) = value.get("plan").filter(|p| p.is_object()) else {
        return String::new();
    };
    let strategy = plan.get("strategy").and_then(Value::as_str).unwrap_or("?");
    let queries = plan
        .get("queries")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .collect::<Vec<_>>()
                .join(" · ")
        })
        .unwrap_or_default();
    format!("plan: {strategy} — {queries}")
}

fn render_citation(citation: &Value) -> String {
    match citation {
        Value::String(text) => text.clone(),
        Value::Object(map) => {
            let file = map
                .get("file_path")
                .or_else(|| map.get("citation"))
                .and_then(Value::as_str)
                .unwrap_or("?");
            match map.get("lines").and_then(Value::as_str) {
                Some(lines) => format!("{file}:{lines}"),
                None => file.to_owned(),
            }
        }
        other => other.to_string(),
    }
}

fn render_ask_meta(value: &Value) -> String {
    let model = value.get("model").and_then(Value::as_str).unwrap_or("?");
    let latency = value
        .get("latency_ms")
        .and_then(Value::as_f64)
        .unwrap_or(0.0);
    let insufficient = value
        .get("insufficient_context")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let mut meta = format!("model {model} · {latency:.0}ms");
    if insufficient {
        meta.push_str(" · insufficient context");
    }
    meta
}

fn render_index_result(value: &Value) -> String {
    if let Some(job_id) = value.get("job_id").and_then(Value::as_str) {
        return format!("job {job_id} queued — progress in the jobs panel");
    }
    let chunks = value
        .get("chunks_indexed")
        .and_then(Value::as_i64)
        .unwrap_or(0);
    let files = value
        .get("files_processed")
        .or_else(|| value.get("total_files"))
        .and_then(Value::as_i64)
        .unwrap_or(0);
    format!("done — {files} files · {chunks} chunks")
}

fn spawn_daemon() -> String {
    let Ok(exe) = std::env::current_exe() else {
        return "cannot resolve the rag binary path".to_owned();
    };
    match std::process::Command::new(exe)
        .arg("start")
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
    {
        Ok(_) => "daemon starting — watch the DAEMON card".to_owned(),
        Err(error) => format!("failed to spawn daemon: {error}"),
    }
}

fn open_web(base_url: &str) -> String {
    let opener = if cfg!(target_os = "macos") {
        "open"
    } else {
        "xdg-open"
    };
    match std::process::Command::new(opener)
        .arg(base_url)
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
    {
        Ok(_) => format!("opening {base_url}"),
        Err(error) => format!("browser opener failed: {error}"),
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::{render_citation, render_index_result, render_plan};

    #[test]
    fn plan_line_summarizes_strategy_and_queries() {
        let value = json!({"plan": {"strategy": "hybrid", "queries": ["a", "b"]}});
        assert_eq!(render_plan(&value), "plan: hybrid — a · b");
        assert_eq!(render_plan(&json!({})), "");
    }

    #[test]
    fn citations_render_strings_and_objects() {
        assert_eq!(render_citation(&json!("src/x.py:1-2")), "src/x.py:1-2");
        assert_eq!(
            render_citation(&json!({"file_path": "src/x.py", "lines": "1-2"})),
            "src/x.py:1-2"
        );
    }

    #[test]
    fn index_result_prefers_job_id() {
        assert!(render_index_result(&json!({"job_id": "abc"})).contains("abc"));
        assert!(render_index_result(&json!({"chunks_indexed": 5})).contains("5 chunks"));
    }
}
