use std::{
    io,
    time::{Duration, Instant},
};

use crossterm::{
    event::{self, Event, KeyCode},
    execute,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
};
use ratatui::{
    backend::CrosstermBackend,
    layout::{Constraint, Direction, Layout},
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{Block, Borders, Paragraph, Wrap},
    Terminal,
};
use serde_json::{json, Value};

use crate::client::ApiClient;

pub async fn snapshot(client: &ApiClient) -> Value {
    let daemon = client.get("/health").await;
    let http = reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build();
    let (ollama, qdrant) = if let Ok(http) = http {
        tokio::join!(
            probe(&http, "http://127.0.0.1:11434/api/tags"),
            probe(&http, "http://127.0.0.1:6333/healthz")
        )
    } else {
        ("unknown".to_owned(), "unknown".to_owned())
    };
    let docker = tokio::process::Command::new("docker")
        .arg("info")
        .kill_on_drop(true)
        .output()
        .await
        .map(|output| {
            if output.status.success() {
                "ok"
            } else {
                "unavailable"
            }
        })
        .unwrap_or("unavailable");
    json!({
        "daemon": daemon.unwrap_or_else(|error| json!({"status": "unavailable", "detail": error.to_string()})),
        "ollama": ollama,
        "qdrant": qdrant,
        "docker": docker,
    })
}

async fn probe(client: &reqwest::Client, url: &str) -> String {
    match client.get(url).send().await {
        Ok(response) if response.status().is_success() => "ok".to_owned(),
        Ok(response) => format!("http_{}", response.status().as_u16()),
        Err(_) => "unavailable".to_owned(),
    }
}

pub async fn run(client: &ApiClient) -> anyhow::Result<()> {
    let state = snapshot(client).await;
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;
    let result = run_loop(&mut terminal, client, state).await;
    disable_raw_mode()?;
    execute!(terminal.backend_mut(), LeaveAlternateScreen)?;
    terminal.show_cursor()?;
    result
}

async fn run_loop(
    terminal: &mut Terminal<CrosstermBackend<io::Stdout>>,
    client: &ApiClient,
    mut state: Value,
) -> anyhow::Result<()> {
    let mut refreshed_at = Instant::now();
    loop {
        terminal.draw(|frame| {
            let rows = Layout::default()
                .direction(Direction::Vertical)
                .constraints([
                    Constraint::Length(3),
                    Constraint::Min(4),
                    Constraint::Length(3),
                ])
                .split(frame.area());
            let title = Paragraph::new(Line::from(vec![
                Span::styled(
                    " RAG ",
                    Style::default()
                        .fg(Color::Black)
                        .bg(Color::Cyan)
                        .add_modifier(Modifier::BOLD),
                ),
                Span::raw(" Rust stack supervisor"),
            ]))
            .block(Block::default().borders(Borders::ALL));
            frame.render_widget(title, rows[0]);
            let body = serde_json::to_string_pretty(&state).unwrap_or_else(|_| "{}".to_owned());
            frame.render_widget(
                Paragraph::new(body)
                    .block(Block::default().title("Services").borders(Borders::ALL))
                    .wrap(Wrap { trim: false }),
                rows[1],
            );
            frame.render_widget(
                Paragraph::new("q quit  |  daemon is supervised independently of this TUI")
                    .block(Block::default().borders(Borders::ALL)),
                rows[2],
            );
        })?;
        if event::poll(Duration::from_millis(250))?
            && matches!(event::read()?, Event::Key(key) if key.code == KeyCode::Char('q'))
        {
            return Ok(());
        }
        if refreshed_at.elapsed() >= Duration::from_secs(2) {
            state = snapshot(client).await;
            refreshed_at = Instant::now();
        }
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    #[test]
    fn dashboard_state_is_serializable_without_a_tty() {
        let state = json!({"daemon": "running", "qdrant": "ok"});
        assert!(serde_json::to_string_pretty(&state)
            .unwrap()
            .contains("daemon"));
    }
}
