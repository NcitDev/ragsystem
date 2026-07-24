//! Rendering for the stack-dashboard TUI. Pure functions of [`App`] state —
//! no I/O here. Layout and palette mirror the Python Textual dashboard and
//! the embedded web dashboard.

use rag_server::stack::{humanize_ago, ServiceHealth, OK};
use ratatui::{
    layout::{Alignment, Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{
        Block, Borders, Cell, Clear, List, ListItem, ListState, Paragraph, Row, Table, Wrap,
    },
    Frame,
};
use serde_json::Value;

use super::{data::group_thousands, App, Focus, ScreenId};

// Palette (single dark theme, matches the web dashboard).
pub const C_BG: Color = Color::Rgb(0x0a, 0x0e, 0x14);
pub const C_PANEL: Color = Color::Rgb(0x10, 0x16, 0x1d);
pub const C_BAR: Color = Color::Rgb(0x12, 0x16, 0x1e);
pub const C_BORDER: Color = Color::Rgb(0x1a, 0x1f, 0x2a);
pub const C_TEXT: Color = Color::Rgb(0xc8, 0xd6, 0xe5);
pub const C_DIM: Color = Color::Rgb(0x5a, 0x6a, 0x7a);
pub const C_ACCENT: Color = Color::Rgb(0x5e, 0xe6, 0xd0);
pub const C_VIOLET: Color = Color::Rgb(0xb0, 0x84, 0xeb);
pub const C_BLUE: Color = Color::Rgb(0x7f, 0xb6, 0xf0);
pub const C_GREEN: Color = Color::Rgb(0x7f, 0xd1, 0x8b);
pub const C_YELLOW: Color = Color::Rgb(0xe0, 0xb4, 0x66);
pub const C_RED: Color = Color::Rgb(0xe5, 0x68, 0x7a);

fn state_color(state: &str) -> Color {
    match state {
        "ok" => C_GREEN,
        "warn" => C_YELLOW,
        "down" => C_RED,
        _ => C_DIM,
    }
}

fn state_dot(state: &str) -> Span<'static> {
    let glyph = if state == "off" { "○" } else { "●" };
    Span::styled(glyph.to_owned(), Style::default().fg(state_color(state)))
}

fn dim(text: impl Into<String>) -> Span<'static> {
    Span::styled(text.into(), Style::default().fg(C_DIM))
}

fn text(text: impl Into<String>) -> Span<'static> {
    Span::styled(text.into(), Style::default().fg(C_TEXT))
}

fn accent(text: impl Into<String>) -> Span<'static> {
    Span::styled(text.into(), Style::default().fg(C_ACCENT))
}

fn panel(title: Option<Line<'static>>) -> Block<'static> {
    let block = Block::default()
        .borders(Borders::ALL)
        .border_style(Style::default().fg(C_BORDER))
        .style(Style::default().bg(C_PANEL));
    match title {
        Some(title) => block.title(title),
        None => block,
    }
}

pub fn draw(frame: &mut Frame, app: &App) {
    let area = frame.area();
    frame.render_widget(Block::default().style(Style::default().bg(C_BG)), area);

    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(1),
            Constraint::Min(4),
            Constraint::Length(1),
        ])
        .split(area);
    draw_header(frame, app, rows[0]);
    draw_footer(frame, app, rows[2]);

    let body = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Length(20), Constraint::Min(10)])
        .split(rows[1]);
    draw_sidebar(frame, app, body[0]);

    match app.screen {
        ScreenId::Home => draw_home(frame, app, body[1]),
        ScreenId::Search => draw_search(frame, app, body[1]),
        ScreenId::Ask => draw_ask(frame, app, body[1]),
        ScreenId::Index => draw_index(frame, app, body[1]),
        ScreenId::Logs => draw_logs(frame, app, body[1]),
        ScreenId::Help => draw_help(frame, app, body[1]),
    }
}

fn draw_header(frame: &mut Frame, app: &App, area: Rect) {
    let clock = chrono::Local::now().format("%H:%M").to_string();
    let mut spans = vec![
        Span::styled(
            " RAG ",
            Style::default()
                .fg(Color::Black)
                .bg(C_ACCENT)
                .add_modifier(Modifier::BOLD),
        ),
        Span::styled(
            " SYSTEM",
            Style::default().fg(C_TEXT).add_modifier(Modifier::BOLD),
        ),
        dim("  ·  "),
        text(app.screen.title()),
        Span::raw("   "),
        state_dot(&app.snap.daemon.state),
        dim(" daemon  "),
        state_dot(&app.snap.ollama.state),
        dim(" ollama  "),
        state_dot(&app.snap.docker.state),
        dim(" docker  "),
        state_dot(&app.snap.qdrant.state),
        dim(" qdrant  "),
        state_dot(&app.snap.ast_index.state),
        dim(" ast-index"),
    ];
    if let Some(note) = app.note_text() {
        spans.push(Span::raw("   "));
        spans.push(Span::styled(note.to_owned(), Style::default().fg(C_YELLOW)));
    }
    let bar = Paragraph::new(Line::from(spans)).style(Style::default().bg(C_BAR));
    frame.render_widget(bar, area);

    // Right-aligned clock over the same bar.
    let clock_area = Rect {
        x: area.right().saturating_sub(7),
        y: area.y,
        width: 7.min(area.width),
        height: 1,
    };
    frame.render_widget(
        Paragraph::new(Line::from(dim(format!("{clock} "))))
            .alignment(Alignment::Right)
            .style(Style::default().bg(C_BAR)),
        clock_area,
    );
}

fn draw_footer(frame: &mut Frame, app: &App, area: Rect) {
    let mut spans = Vec::new();
    if app.focus == Focus::None {
        for (key, label) in [
            ("h", "dashboard"),
            ("s", "search"),
            ("a", "ask"),
            ("i", "index"),
            ("l", "logs"),
            ("?", "help"),
        ] {
            spans.push(accent(format!(" {key}")));
            spans.push(dim(format!(" {label} ")));
        }
        spans.push(dim(" │ "));
        for (key, label) in [
            ("D", "start daemon"),
            ("U", "start qdrant"),
            ("W", "web"),
            ("r", "refresh"),
            ("q", "quit"),
        ] {
            spans.push(accent(format!(" {key}")));
            spans.push(dim(format!(" {label} ")));
        }
    } else {
        spans.push(accent(" enter"));
        spans.push(dim(" run  "));
        spans.push(accent("tab"));
        spans.push(dim(" next field  "));
        spans.push(accent("esc"));
        spans.push(dim(" leave input"));
    }
    frame.render_widget(
        Paragraph::new(Line::from(spans)).style(Style::default().bg(C_BAR)),
        area,
    );
}

fn draw_sidebar(frame: &mut Frame, app: &App, area: Rect) {
    let mut lines = vec![
        Line::from(dim("")),
        Line::from(Span::styled(
            "  SCREENS",
            Style::default().fg(C_DIM).add_modifier(Modifier::BOLD),
        )),
        Line::from(""),
    ];
    for (id, hot) in [
        (ScreenId::Home, "h"),
        (ScreenId::Search, "s"),
        (ScreenId::Ask, "a"),
        (ScreenId::Index, "i"),
        (ScreenId::Logs, "l"),
        (ScreenId::Help, "?"),
    ] {
        let label = format!("{:<11}", id.title());
        if id == app.screen {
            lines.push(Line::from(vec![
                Span::styled(
                    format!(" ▌ {label}"),
                    Style::default()
                        .fg(C_ACCENT)
                        .bg(Color::Rgb(0x14, 0x1b, 0x23)),
                ),
                dim(hot),
            ]));
        } else {
            lines.push(Line::from(vec![text(format!("   {label}")), dim(hot)]));
        }
    }
    lines.push(Line::from(""));
    lines.push(Line::from(Span::styled(
        "  ACTIONS",
        Style::default().fg(C_DIM).add_modifier(Modifier::BOLD),
    )));
    lines.push(Line::from(""));
    for (label, hot) in [
        ("Start daemon", "D"),
        ("Start qdrant", "U"),
        ("Web dash    ", "W"),
        ("Refresh     ", "r"),
        ("Quit        ", "q"),
    ] {
        lines.push(Line::from(vec![text(format!("   {label}")), dim(hot)]));
    }
    let block = Block::default()
        .borders(Borders::RIGHT)
        .border_style(Style::default().fg(C_BORDER))
        .style(Style::default().bg(C_PANEL));
    frame.render_widget(Paragraph::new(lines).block(block), area);
}

// --- Home ----------------------------------------------------------------------

fn draw_home(frame: &mut Frame, app: &App, area: Rect) {
    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(9),
            Constraint::Min(5),
            Constraint::Length(9),
        ])
        .split(inset(area));

    let cards = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Ratio(1, 5),
            Constraint::Ratio(1, 5),
            Constraint::Ratio(1, 5),
            Constraint::Ratio(1, 5),
            Constraint::Ratio(1, 5),
        ])
        .split(rows[0]);
    draw_card(frame, &app.snap.daemon, cards[0]);
    draw_card(frame, &app.snap.ollama, cards[1]);
    draw_card(frame, &app.snap.docker, cards[2]);
    draw_card(frame, &app.snap.qdrant, cards[3]);
    draw_card(frame, &app.snap.ast_index, cards[4]);

    draw_repos(frame, app, rows[1]);

    let bottom = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Ratio(3, 5), Constraint::Ratio(2, 5)])
        .split(rows[2]);
    draw_activity(frame, app, bottom[0]);
    draw_lsp(frame, app, bottom[1]);
}

fn inset(area: Rect) -> Rect {
    Rect {
        x: area.x + 1,
        y: area.y,
        width: area.width.saturating_sub(2),
        height: area.height,
    }
}

fn draw_card(frame: &mut Frame, svc: &ServiceHealth, area: Rect) {
    let title = Line::from(Span::styled(
        format!(" {} ", svc.name),
        Style::default().fg(C_DIM).add_modifier(Modifier::BOLD),
    ));
    let mut lines = vec![Line::from(vec![
        state_dot(&svc.state),
        Span::raw(" "),
        Span::styled(
            if svc.headline.is_empty() {
                svc.state.clone()
            } else {
                svc.headline.clone()
            },
            Style::default().fg(state_color(&svc.state)),
        ),
    ])];
    for line in svc.lines.iter().take(4) {
        lines.push(Line::from(text(line.clone())));
    }
    if !svc.hint.is_empty() && svc.state != OK {
        lines.push(Line::from(Span::styled(
            format!("→ {}", svc.hint),
            Style::default().fg(C_YELLOW),
        )));
    }
    frame.render_widget(
        Paragraph::new(lines)
            .wrap(Wrap { trim: false })
            .block(panel(Some(title))),
        area,
    );
}

fn draw_repos(frame: &mut Frame, app: &App, area: Rect) {
    let source = if app.snap.repos_source == "daemon" {
        "live from daemon"
    } else {
        "local registry (daemon down)"
    };
    let title = Line::from(vec![
        Span::styled(
            " PROJECT INDEXES ",
            Style::default().fg(C_DIM).add_modifier(Modifier::BOLD),
        ),
        dim(format!("· {source} ")),
    ]);

    if app.snap.repos.is_empty() {
        frame.render_widget(
            Paragraph::new(Line::from(dim(
                "no indexes yet — run: rag index /path/to/repo",
            )))
            .block(panel(Some(title))),
            area,
        );
        return;
    }

    let home = std::env::var("HOME").unwrap_or_default();
    let mut ordered: Vec<_> = app.snap.repos.iter().filter(|r| r.kind == "repo").collect();
    ordered.extend(app.snap.repos.iter().filter(|r| r.kind != "repo"));

    let rows: Vec<Row> = ordered
        .iter()
        .map(|r| {
            let missing = r.status == "not_found";
            let dot_color = if missing {
                C_RED
            } else if r.points > 0 {
                C_GREEN
            } else {
                C_DIM
            };
            let name_color = if r.kind == "repo" { C_BLUE } else { C_DIM };
            let path = if r.path.is_empty() {
                "—".to_owned()
            } else if !home.is_empty() {
                r.path.replace(&home, "~")
            } else {
                r.path.clone()
            };
            let points = if r.points > 0 {
                group_thousands(i64::try_from(r.points).unwrap_or(i64::MAX))
            } else if missing {
                "missing".to_owned()
            } else {
                "0".to_owned()
            };
            let files = if r.files > 0 {
                group_thousands(i64::try_from(r.files).unwrap_or(i64::MAX))
            } else {
                "—".to_owned()
            };
            Row::new(vec![
                Cell::from(Span::styled("●", Style::default().fg(dot_color))),
                Cell::from(Span::styled(
                    r.name.clone(),
                    Style::default().fg(name_color).add_modifier(Modifier::BOLD),
                )),
                Cell::from(dim(path)),
                Cell::from(Span::styled(
                    points,
                    Style::default().fg(if r.points > 0 { C_TEXT } else { C_DIM }),
                )),
                Cell::from(dim(files)),
                Cell::from(dim(if r.last_indexed.is_empty() {
                    "—".to_owned()
                } else {
                    r.last_indexed.clone()
                })),
                Cell::from(dim(r.collection.clone())),
            ])
        })
        .collect();

    let header = Row::new(
        [
            "",
            "PROJECT",
            "PATH",
            "CHUNKS",
            "FILES",
            "LAST INDEXED",
            "COLLECTION",
        ]
        .into_iter()
        .map(|h| Cell::from(Span::styled(h, Style::default().fg(C_DIM)))),
    );
    let table = Table::new(
        rows,
        [
            Constraint::Length(1),
            Constraint::Length(14),
            Constraint::Min(20),
            Constraint::Length(8),
            Constraint::Length(7),
            Constraint::Length(13),
            Constraint::Length(16),
        ],
    )
    .header(header)
    .column_spacing(2)
    .block(panel(Some(title)));
    frame.render_widget(table, area);
}

fn draw_activity(frame: &mut Frame, app: &App, area: Rect) {
    let stats = &app.snap.stats;
    let mut title_spans = vec![Span::styled(
        " ACTIVITY ",
        Style::default().fg(C_DIM).add_modifier(Modifier::BOLD),
    )];
    if app.snap.daemon_up {
        let count = stats.get("count").and_then(Value::as_i64).unwrap_or(0);
        let qpm = stats.get("qpm").and_then(Value::as_f64).unwrap_or(0.0);
        let p50 = stats.get("p50_ms").and_then(Value::as_f64).unwrap_or(0.0);
        let p95 = stats.get("p95_ms").and_then(Value::as_f64).unwrap_or(0.0);
        title_spans.push(dim(format!(
            "{count} recent · qpm {qpm:.0} · p50 {p50:.0}ms · p95 {p95:.0}ms "
        )));
    }
    let mut lines = Vec::new();
    if !app.snap.daemon_up {
        lines.push(Line::from(dim("daemon down — no query telemetry")));
        lines.push(Line::from(Span::styled(
            "→ press D to start the daemon",
            Style::default().fg(C_YELLOW),
        )));
    } else {
        // Running index jobs get top billing.
        if let Some(jobs) = app.snap.jobs.as_object() {
            for (job_id, job) in jobs.iter().rev().take(2) {
                let status = job.get("status").and_then(Value::as_str).unwrap_or("?");
                if status == "running" || status == "pending" {
                    let done = job
                        .get("files_processed")
                        .and_then(Value::as_i64)
                        .unwrap_or(0);
                    let total = job.get("total_files").and_then(Value::as_i64).unwrap_or(0);
                    lines.push(Line::from(vec![
                        Span::styled(
                            format!("⚙ index {}", &job_id[..job_id.len().min(8)]),
                            Style::default().fg(C_VIOLET),
                        ),
                        text(format!(" {status} {done}/{total} files")),
                    ]));
                }
            }
        }
        for q in app.snap.queries.iter().take(5) {
            let ts = humanize_ago(q.get("timestamp").and_then(Value::as_str));
            let query: String = q
                .get("query")
                .and_then(Value::as_str)
                .unwrap_or("")
                .chars()
                .take(46)
                .collect();
            let mut meta = Vec::new();
            if let Some(n) = q.get("results_count").and_then(Value::as_i64) {
                meta.push(format!("{n} hits"));
            }
            if let Some(lat) = q.get("latency_ms").and_then(Value::as_f64) {
                if lat > 0.0 {
                    meta.push(format!("{lat:.0}ms"));
                }
            }
            lines.push(Line::from(vec![
                dim(format!("{ts:>9}  ")),
                text(format!("{query:<46} ")),
                dim(meta.join(" · ")),
            ]));
        }
        if lines.is_empty() {
            lines.push(Line::from(dim(
                "no queries yet — try the Search screen (s)",
            )));
        }
    }
    frame.render_widget(
        Paragraph::new(lines).block(panel(Some(Line::from(title_spans)))),
        area,
    );
}

fn draw_lsp(frame: &mut Frame, app: &App, area: Rect) {
    let title = Line::from(Span::styled(
        " LSP / SERVICE ",
        Style::default().fg(C_DIM).add_modifier(Modifier::BOLD),
    ));
    let mut lines = Vec::new();
    if app.snap.lsp.is_empty() {
        lines.push(Line::from(dim("no LSP servers detected")));
    } else {
        let found: Vec<_> = app.snap.lsp.iter().filter(|s| s.found).collect();
        let missing: Vec<_> = app.snap.lsp.iter().filter(|s| !s.found).collect();
        let mut spans = vec![text(format!("{} LSP found: ", found.len()))];
        for s in &found {
            spans.push(Span::styled(
                format!("{} ", s.language),
                Style::default().fg(C_GREEN),
            ));
        }
        lines.push(Line::from(spans));
        if !missing.is_empty() {
            let names = missing
                .iter()
                .map(|s| s.language.as_str())
                .collect::<Vec<_>>()
                .join(" ");
            lines.push(Line::from(dim(format!("missing: {names}"))));
        }
    }
    frame.render_widget(
        Paragraph::new(lines)
            .wrap(Wrap { trim: false })
            .block(panel(Some(title))),
        area,
    );
}

// --- Search --------------------------------------------------------------------

fn draw_search(frame: &mut Frame, app: &App, area: Rect) {
    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(3),
            Constraint::Min(4),
            Constraint::Length(1),
        ])
        .split(inset(area));

    draw_query_row(
        frame,
        rows[0],
        &app.search.query,
        "search the index — Enter to run",
        &app.search.repo,
        app.focus,
        app.screen == ScreenId::Search,
    );

    let mid = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Ratio(2, 5), Constraint::Ratio(3, 5)])
        .split(rows[1]);

    let items: Vec<ListItem> = app
        .search
        .results
        .iter()
        .enumerate()
        .map(|(i, r)| {
            let lang = r.get("language").and_then(Value::as_str).unwrap_or("?");
            let file = r.get("file_path").and_then(Value::as_str).unwrap_or("?");
            let lines_range = r.get("lines").and_then(Value::as_str).unwrap_or("?");
            let name = r.get("name").and_then(Value::as_str).unwrap_or("");
            let score = r.get("score").and_then(Value::as_f64).unwrap_or(0.0);
            ListItem::new(vec![
                Line::from(vec![
                    dim(format!("{:>2}. ", i + 1)),
                    Span::styled(format!("{lang} "), Style::default().fg(C_BLUE)),
                    text(format!("{file}:{lines_range}")),
                ]),
                Line::from(dim(format!("     {name}  score={score:.3}"))),
            ])
        })
        .collect();
    let empty = items.is_empty();
    let results_title = if app.search.running {
        " RESULTS · searching… "
    } else {
        " RESULTS "
    };
    let list = List::new(items)
        .block(panel(Some(Line::from(Span::styled(
            results_title,
            Style::default().fg(C_DIM).add_modifier(Modifier::BOLD),
        )))))
        .highlight_style(
            Style::default()
                .bg(Color::Rgb(0x14, 0x1b, 0x23))
                .fg(C_ACCENT),
        );
    let mut list_state = ListState::default();
    if !empty {
        list_state.select(Some(app.search.selected));
    }
    frame.render_stateful_widget(list, mid[0], &mut list_state);

    let detail: Vec<Line> = app
        .search
        .results
        .get(app.search.selected)
        .and_then(|r| r.get("code").and_then(Value::as_str))
        .map(|code| {
            code.lines()
                .map(|l| Line::from(text(l.to_owned())))
                .collect()
        })
        .unwrap_or_else(|| {
            vec![Line::from(dim(
                "select a result — code preview appears here",
            ))]
        });
    frame.render_widget(
        Paragraph::new(detail).block(panel(Some(Line::from(Span::styled(
            " CODE ",
            Style::default().fg(C_DIM).add_modifier(Modifier::BOLD),
        ))))),
        mid[1],
    );

    let plan = if app.search.plan.is_empty() {
        "plan appears here after the first query".to_owned()
    } else {
        app.search.plan.clone()
    };
    frame.render_widget(Paragraph::new(Line::from(dim(plan))), rows[2]);
}

// --- Ask -----------------------------------------------------------------------

fn draw_ask(frame: &mut Frame, app: &App, area: Rect) {
    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(3),
            Constraint::Min(4),
            Constraint::Length(1),
        ])
        .split(inset(area));

    draw_query_row(
        frame,
        rows[0],
        &app.ask.question,
        "ask a grounded question about the indexed code — Enter to run",
        &app.ask.repo,
        app.focus,
        app.screen == ScreenId::Ask,
    );

    let mid = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Ratio(3, 5), Constraint::Ratio(2, 5)])
        .split(rows[1]);

    let answer_title = if app.ask.running {
        " ANSWER · thinking… "
    } else {
        " ANSWER "
    };
    let answer: Vec<Line> = if app.ask.answer.is_empty() {
        vec![Line::from(dim("the grounded answer appears here"))]
    } else {
        app.ask
            .answer
            .lines()
            .map(|l| Line::from(text(l.to_owned())))
            .collect()
    };
    frame.render_widget(
        Paragraph::new(answer)
            .wrap(Wrap { trim: false })
            .block(panel(Some(Line::from(Span::styled(
                answer_title,
                Style::default().fg(C_DIM).add_modifier(Modifier::BOLD),
            ))))),
        mid[0],
    );

    let citations: Vec<ListItem> = app
        .ask
        .citations
        .iter()
        .enumerate()
        .map(|(i, c)| {
            ListItem::new(Line::from(vec![
                dim(format!("{:>2}. ", i + 1)),
                text(c.clone()),
            ]))
        })
        .collect();
    frame.render_widget(
        List::new(citations).block(panel(Some(Line::from(Span::styled(
            " CITATIONS ",
            Style::default().fg(C_DIM).add_modifier(Modifier::BOLD),
        ))))),
        mid[1],
    );

    frame.render_widget(
        Paragraph::new(Line::from(dim(app.ask.meta.clone()))),
        rows[2],
    );
}

// --- Index ---------------------------------------------------------------------

fn draw_index(frame: &mut Frame, app: &App, area: Rect) {
    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(3),
            Constraint::Length(3),
            Constraint::Min(4),
        ])
        .split(inset(area));

    let cols = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Min(20), Constraint::Length(12)])
        .split(rows[0]);
    draw_input(
        frame,
        cols[0],
        &app.index.path,
        "/absolute/path/to/repo   (Enter to index)",
        app.screen == ScreenId::Index && app.focus != Focus::None,
    );
    let full_label = if app.index.full {
        "[x] full"
    } else {
        "[ ] full"
    };
    frame.render_widget(
        Paragraph::new(Line::from(vec![text(full_label), dim(" f")])).block(panel(None)),
        cols[1],
    );

    let status = if app.index.status_line.is_empty() {
        "idle — daemon runs the job, progress shows here".to_owned()
    } else {
        app.index.status_line.clone()
    };
    frame.render_widget(
        Paragraph::new(Line::from(dim(status))).block(panel(None)),
        rows[1],
    );

    let mut lines = vec![Line::from(Span::styled(
        "JOBS",
        Style::default().fg(C_DIM).add_modifier(Modifier::BOLD),
    ))];
    match app.snap.jobs.as_object() {
        Some(jobs) if !jobs.is_empty() => {
            for (job_id, job) in jobs.iter().rev().take(20) {
                let status = job.get("status").and_then(Value::as_str).unwrap_or("?");
                let color = match status {
                    "completed" => C_GREEN,
                    "failed" => C_RED,
                    "running" => C_VIOLET,
                    _ => C_DIM,
                };
                lines.push(Line::from(vec![
                    dim(format!("{} ", &job_id[..job_id.len().min(8)])),
                    Span::styled(format!("{status:<10} "), Style::default().fg(color)),
                    text(format!(
                        "{}/{} files · {} chunks ",
                        job.get("files_processed")
                            .and_then(Value::as_i64)
                            .unwrap_or(0),
                        job.get("total_files").and_then(Value::as_i64).unwrap_or(0),
                        job.get("chunks_indexed")
                            .and_then(Value::as_i64)
                            .unwrap_or(0),
                    )),
                    dim(job
                        .get("repo_path")
                        .and_then(Value::as_str)
                        .unwrap_or("")
                        .to_owned()),
                ]));
            }
        }
        _ => lines.push(Line::from(dim("no index jobs this daemon session"))),
    }
    frame.render_widget(Paragraph::new(lines).block(panel(None)), rows[2]);
}

// --- Logs ----------------------------------------------------------------------

fn draw_logs(frame: &mut Frame, app: &App, area: Rect) {
    let area = inset(area);
    let capacity = area.height.saturating_sub(2) as usize;
    let events = &app.snap.events;
    let start = events.len().saturating_sub(capacity);
    let lines: Vec<Line> = events[start..]
        .iter()
        .map(|ev| {
            let ts = ev
                .get("ts")
                .and_then(Value::as_f64)
                .map(|ts| {
                    chrono::DateTime::from_timestamp(ts as i64, 0)
                        .map(|dt| {
                            dt.with_timezone(&chrono::Local)
                                .format("%H:%M:%S")
                                .to_string()
                        })
                        .unwrap_or_default()
                })
                .unwrap_or_default();
            let name = ev.get("event").and_then(Value::as_str).unwrap_or("?");
            let payload: Vec<String> = ev
                .as_object()
                .map(|map| {
                    map.iter()
                        .filter(|(k, _)| k.as_str() != "ts" && k.as_str() != "event")
                        .map(|(k, v)| format!("{k}={v}"))
                        .collect()
                })
                .unwrap_or_default();
            Line::from(vec![
                dim(format!("{ts} ")),
                Span::styled(
                    format!("{name} "),
                    Style::default().fg(C_ACCENT).add_modifier(Modifier::BOLD),
                ),
                text(payload.join(" ")),
            ])
        })
        .collect();
    let title = Line::from(Span::styled(
        " DAEMON EVENTS ",
        Style::default().fg(C_DIM).add_modifier(Modifier::BOLD),
    ));
    let body = if lines.is_empty() {
        vec![Line::from(dim("no daemon events yet"))]
    } else {
        lines
    };
    frame.render_widget(Paragraph::new(body).block(panel(Some(title))), area);
}

// --- Help ----------------------------------------------------------------------

fn draw_help(frame: &mut Frame, app: &App, area: Rect) {
    let cols = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Ratio(1, 2), Constraint::Ratio(1, 2)])
        .split(inset(area));

    let key_lines: Vec<Line> = vec![
        Line::from(Span::styled(
            "Keys",
            Style::default().fg(C_TEXT).add_modifier(Modifier::BOLD),
        )),
        Line::from(""),
        help_key("h", "Dashboard — stack health + project indexes"),
        help_key("s", "Search the index"),
        help_key("a", "Ask (grounded RAG answer)"),
        help_key("i", "Index a repository"),
        help_key("l", "Daemon event log"),
        help_key("?", "This help"),
        Line::from(""),
        help_key("D", "Start the daemon (background)"),
        help_key("U", "Start the Qdrant docker container"),
        help_key("W", "Open the web dashboard"),
        help_key("r", "Refresh all checks now"),
        help_key("q", "Quit  ·  esc leaves an input field"),
    ];
    frame.render_widget(Paragraph::new(key_lines).block(panel(None)), cols[0]);

    let s = &app.settings;
    let gen = if s.llm.gen_model.is_empty() {
        s.llm.agent_model.clone()
    } else {
        s.llm.gen_model.clone()
    };
    let config_lines: Vec<Line> = vec![
        Line::from(Span::styled(
            "Active config",
            Style::default().fg(C_TEXT).add_modifier(Modifier::BOLD),
        )),
        Line::from(""),
        help_kv("embedder", &s.embeddings.model),
        help_kv("agent", &s.llm.agent_model),
        help_kv("gen", &gen),
        help_kv(
            "planner",
            &format!(
                "{} ({})",
                s.retrieval_agent.provider, s.retrieval_agent.model
            ),
        ),
        help_kv("ollama", &s.llm.ollama_url),
        help_kv("qdrant", &format!("{} · {}", s.qdrant.mode, s.qdrant.url)),
        help_kv("daemon", &app.base_url),
        Line::from(""),
        Line::from(Span::styled(
            "CLI equivalents",
            Style::default().fg(C_TEXT).add_modifier(Modifier::BOLD),
        )),
        Line::from(""),
        help_key("rag start", "run the daemon"),
        help_key("rag qdrant-up", "start Qdrant (docker compose)"),
        help_key("rag index PATH", "index a repository"),
        help_key("rag search \"q\"", "search from the shell"),
        help_key("rag web", "browser dashboard"),
    ];
    frame.render_widget(Paragraph::new(config_lines).block(panel(None)), cols[1]);
}

fn help_key(key: &str, description: &str) -> Line<'static> {
    Line::from(vec![
        accent(format!("  {key:<16}")),
        text(description.to_owned()),
    ])
}

fn help_kv(key: &str, value: &str) -> Line<'static> {
    Line::from(vec![accent(format!("  {key:<9}")), text(value.to_owned())])
}

// --- shared input widgets --------------------------------------------------------

#[allow(clippy::too_many_arguments)]
fn draw_query_row(
    frame: &mut Frame,
    area: Rect,
    query: &str,
    placeholder: &str,
    repo: &str,
    focus: Focus,
    on_screen: bool,
) {
    let cols = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Min(20), Constraint::Length(26)])
        .split(area);
    draw_input(
        frame,
        cols[0],
        query,
        placeholder,
        on_screen && focus == Focus::Query,
    );
    draw_input(
        frame,
        cols[1],
        repo,
        "repo (optional)",
        on_screen && focus == Focus::Repo,
    );
}

fn draw_input(frame: &mut Frame, area: Rect, value: &str, placeholder: &str, focused: bool) {
    let border = if focused { C_ACCENT } else { C_BORDER };
    let block = Block::default()
        .borders(Borders::ALL)
        .border_style(Style::default().fg(border))
        .style(Style::default().bg(C_PANEL));
    let mut spans = Vec::new();
    if value.is_empty() {
        spans.push(dim(placeholder.to_owned()));
    } else {
        // Keep the tail visible when the value is wider than the input.
        let visible = area.width.saturating_sub(3) as usize;
        let chars: Vec<char> = value.chars().collect();
        let start = chars.len().saturating_sub(visible);
        spans.push(text(chars[start..].iter().collect::<String>()));
    }
    if focused {
        spans.push(Span::styled("▏", Style::default().fg(C_ACCENT)));
    }
    frame.render_widget(Clear, area);
    frame.render_widget(Paragraph::new(Line::from(spans)).block(block), area);
}
