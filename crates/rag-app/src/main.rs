mod client;
mod migration;
mod service;
mod tui;

use std::{fs, path::PathBuf, process::Command as ProcessCommand};

use anyhow::{bail, Context};
use clap::{Args, CommandFactory as _, Parser, Subcommand, ValueEnum};
use client::ApiClient;
use rag_config::{RagPaths, ServerConfig, DEFAULT_HOST, DEFAULT_PORT};
use reqwest::Method;
use serde_json::{json, Value};

#[derive(Debug, Parser)]
#[command(name = "rag-rs", version, about = "Standalone Rust RAG system")]
struct Cli {
    #[arg(
        long,
        env = "RAG_BASE_URL",
        default_value = "http://127.0.0.1:7890",
        global = true
    )]
    base_url: String,
    #[arg(long, env = "RAG_TOKEN", global = true, hide_env_values = true)]
    token: Option<String>,
    #[command(subcommand)]
    command: Option<Command>,
}

#[derive(Debug, Subcommand)]
enum Command {
    Init {
        #[arg(default_value = ".")]
        path: PathBuf,
    },
    Start {
        #[arg(long, default_value = DEFAULT_HOST)]
        host: String,
        #[arg(long, default_value_t = DEFAULT_PORT)]
        port: u16,
        #[arg(long)]
        watch: bool,
        #[arg(long)]
        tui: bool,
    },
    QdrantUp,
    QdrantDown,
    QdrantStatus,
    BenchmarkEmbeddings {
        #[arg(long, default_value_t = 16)]
        batch_size: usize,
    },
    Tui {
        #[arg(long)]
        snapshot: bool,
    },
    Web {
        #[arg(long)]
        print_url: bool,
    },
    Search(QueryArgs),
    SmartSearch(QuestionArgs),
    ContextPack(QueryArgs),
    RepoAgent(QueryArgs),
    Resolve(SymbolArgs),
    CallTree(SymbolArgs),
    Files(QueryArgs),
    Node(SymbolArgs),
    Callers(SymbolArgs),
    Callees(SymbolArgs),
    Impact(SymbolArgs),
    Affected {
        #[arg(long)]
        repo: String,
        #[arg(long, default_value = "HEAD")]
        since: String,
        #[arg(long)]
        files: Vec<String>,
    },
    Understand(QueryArgs),
    BackfillCodeIndex {
        #[arg(long)]
        repo: Option<String>,
        #[arg(long)]
        collection: Option<String>,
    },
    Ask(QuestionArgs),
    List {
        #[arg(long)]
        filters: Option<String>,
        #[arg(long, default_value_t = 500)]
        limit: usize,
    },
    Index {
        #[arg(default_value = ".")]
        path: PathBuf,
        #[arg(long)]
        full: bool,
        #[arg(long)]
        lang: Vec<String>,
        #[arg(long)]
        name: Option<String>,
    },
    IndexDocs {
        path: PathBuf,
        #[arg(long)]
        full: bool,
        #[arg(long)]
        collection: Option<String>,
    },
    GenerateEventCatalog {
        path: PathBuf,
        #[arg(long)]
        repo_name: Option<String>,
    },
    Status,
    Config {
        #[arg(long)]
        reload: bool,
    },
    Repos,
    Export {
        output: PathBuf,
        #[arg(long)]
        collection: Option<String>,
    },
    Import {
        input: PathBuf,
        #[arg(long)]
        collection: Option<String>,
    },
    Diff {
        query: String,
        #[arg(long, default_value = "HEAD")]
        since: String,
        #[arg(long)]
        path: Option<String>,
    },
    Overview,
    InstallClaude,
    Plugins,
    Collections {
        #[command(subcommand)]
        command: CollectionsCommand,
    },
    Verify {
        #[arg(default_value = ".")]
        path: PathBuf,
    },
    Repair {
        #[arg(default_value = ".")]
        path: PathBuf,
    },
    Diagnose,
    Service {
        #[command(subcommand)]
        command: ServiceCommand,
    },
    Migration {
        #[command(subcommand)]
        command: MigrationCommand,
    },
    Raw {
        method: HttpMethod,
        path: String,
        #[arg(long)]
        body: Option<String>,
    },
}

#[derive(Debug, Args)]
struct QueryArgs {
    query: Option<String>,
    #[arg(long)]
    repo: Option<String>,
    #[arg(long, default_value_t = 20)]
    top_k: usize,
}

#[derive(Debug, Args)]
struct QuestionArgs {
    question: String,
    #[arg(long)]
    repo: Option<String>,
    #[arg(long, default_value_t = 8)]
    top_k: usize,
}

#[derive(Debug, Args)]
struct SymbolArgs {
    symbol: String,
    #[arg(long)]
    repo: String,
    #[arg(long, default_value_t = 50)]
    limit: usize,
}

#[derive(Debug, Subcommand)]
enum CollectionsCommand {
    List,
    Delete { name: String },
}

#[derive(Debug, Subcommand)]
enum ServiceCommand {
    Install {
        #[arg(long)]
        dry_run: bool,
    },
    Uninstall {
        #[arg(long)]
        dry_run: bool,
    },
    Status,
}

#[derive(Debug, Subcommand)]
enum MigrationCommand {
    Shadow {
        #[arg(long, default_value = "http://127.0.0.1:7890")]
        python_url: String,
        #[arg(long, default_value = "http://127.0.0.1:7891")]
        rust_url: String,
        #[arg(long)]
        cases: Option<PathBuf>,
        #[arg(long)]
        output: PathBuf,
    },
    PrepareCutover {
        #[arg(long)]
        rag_home: PathBuf,
        #[arg(long)]
        backup: PathBuf,
        #[arg(long)]
        rust_binary: PathBuf,
        #[arg(long)]
        shadow_report: PathBuf,
    },
    Activate {
        #[arg(long)]
        manifest: PathBuf,
        #[arg(long)]
        acknowledge_data_risk: bool,
    },
    Rollback {
        #[arg(long)]
        manifest: PathBuf,
        #[arg(long)]
        acknowledge_data_risk: bool,
    },
    ReleaseManifest {
        binary: PathBuf,
        #[arg(long)]
        output: PathBuf,
    },
}

#[derive(Debug, Clone, Copy, ValueEnum)]
enum HttpMethod {
    Get,
    Post,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Python parity: `~/.rag/.env` and the nearest project `.env` load at
    // startup (no override) so provider API keys are available everywhere.
    if let Ok(paths) = RagPaths::from_env() {
        let cwd = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
        let _ = rag_config::load_env_files(&paths, &cwd);
    }
    let cli = Cli::parse();
    let token = cli.token.or_else(read_token);
    let client = ApiClient::new(cli.base_url.clone(), token.clone())?;
    let Some(command) = cli.command else {
        Cli::command().print_help()?;
        println!();
        return Ok(());
    };
    execute(command, client, token, cli.base_url).await
}

async fn execute(
    command: Command,
    client: ApiClient,
    token: Option<String>,
    base_url: String,
) -> anyhow::Result<()> {
    match command {
        Command::Start { host, port, watch, tui: with_tui } => {
            if watch { eprintln!("watch mode is managed by the index job API"); }
            let config = ServerConfig::new(host, port).context("invalid server configuration")?;
            eprintln!("rag-rs listening on http://{}:{}", display_host(&config.host), config.port);
            if with_tui { eprintln!("launch `rag-rs tui` in a separate process; daemon lifetime is independent"); }
            rag_server::serve(&config).await?;
        }
        Command::Init { path } => {
            let path = path.canonicalize().context("repository path does not exist")?;
            emit(client.post_with_timeout("/index", json!({"repo_path": path}), 600).await?)?;
        }
        Command::QdrantUp => qdrant_docker_up()?,
        Command::QdrantDown => qdrant_docker_down()?,
        Command::QdrantStatus => emit(qdrant_docker_status().await?)?,
        Command::BenchmarkEmbeddings { batch_size } => emit(json!({"batch_size": batch_size, "detail": client.get("/health/detail").await?}))?,
        Command::Tui { snapshot } => {
            if snapshot { emit(tui::snapshot(&client).await)?; } else { tui::run(&client).await?; }
        }
        Command::Web { print_url } => open_web(&base_url, print_url)?,
        Command::Search(args) => emit(client.post("/search", query_body(args)).await?)?,
        Command::SmartSearch(args) => emit(client.post_with_timeout("/smart-search", question_body(args), 300).await?)?,
        Command::ContextPack(args) => emit(client.post("/context-pack", query_body(args)).await?)?,
        Command::RepoAgent(args) | Command::Understand(args) => emit(client.post_with_timeout("/project-understand", query_body(args), 180).await?)?,
        Command::Resolve(args) => emit(client.post("/resolve", json!({"repo": args.repo, "symbols": [args.symbol], "limit": args.limit})).await?)?,
        Command::Node(args) => emit(client.post("/graph/node", symbol_body(args)).await?)?,
        Command::CallTree(args) => emit(client.post("/call-tree", symbol_body(args)).await?)?,
        Command::Files(args) => emit(client.post("/graph/files", query_body(args)).await?)?,
        Command::Callers(args) => emit(client.post("/graph/callers", symbol_body(args)).await?)?,
        Command::Callees(args) => emit(client.post("/graph/callees", symbol_body(args)).await?)?,
        Command::Impact(args) => emit(client.post("/graph/impact", symbol_body(args)).await?)?,
        Command::Affected { repo, since, files } => emit(client.post("/graph/affected", json!({"repo": repo, "since": since, "files": files})).await?)?,
        Command::BackfillCodeIndex { repo, collection } => emit(client.post_with_timeout("/index/backfill-code-index", json!({"repo": repo, "collection": collection}), 600).await?)?,
        Command::Ask(args) => emit(client.post_with_timeout("/ask", question_body(args), 300).await?)?,
        Command::List { filters, limit } => emit(client.post("/enumerate", json!({"filters": parse_json_object(filters.as_deref())?, "limit": limit})).await?)?,
        Command::Index { path, full, lang, name } => {
            let path = path.canonicalize().context("repository path does not exist")?;
            let collection = name.as_deref().map(repo_collection);
            emit(client.post_with_timeout("/index", json!({"repo_path": path, "full": full, "languages": lang, "repo_name": name, "collection": collection}), 600).await?)?;
        }
        Command::IndexDocs { path, full, collection } => {
            let path = path.canonicalize().context("docs path does not exist")?;
            emit(client.post_with_timeout("/index/docs", json!({"docs_path": path, "full": full, "collection": collection}), 600).await?)?;
        }
        Command::GenerateEventCatalog { path, repo_name } => emit(client.post("/index/docs", json!({"docs_path": path, "doc_types": ["event_catalog"], "collection": repo_name})).await?)?,
        Command::Status => emit(client.get("/status").await?)?,
        Command::Config { reload } => {
            if reload { emit(client.post("/admin/reload", json!({"force": true})).await?)?; }
            else { println!("{}", RagPaths::from_env()?.config_path.display()); }
        }
        Command::Repos => emit(client.get("/repos").await?)?,
        Command::Export { output, collection } => {
            // The daemon streams the records back and we write them here, so the
            // user's path is honored even when the daemon is remote. Previously
            // this sent no `output` at all, which the route required -> every
            // `rag export` died on a 422 before reaching the export logic.
            let value = client.post("/admin/export", json!({"collection": collection})).await?;
            let records = value.get("records").and_then(Value::as_array).cloned().unwrap_or_default();
            let jsonl = records.iter().map(|r| r.to_string()).collect::<Vec<_>>().join("\n");
            fs::write(&output, jsonl)?;
            emit(json!({"output": output, "exported": value.get("exported").cloned().unwrap_or(json!(0))}))?;
        }
        Command::Import { input, collection } => {
            let records: Value = serde_json::from_slice(&fs::read(&input)?).context("import must be JSON")?;
            emit(client.post("/admin/import", json!({"collection": collection, "records": records})).await?)?;
        }
        Command::Diff { query, since, path } => emit(client.post("/diff", json!({"query": query, "since": since, "path": path})).await?)?,
        Command::Overview => emit(client.get("/overview").await?)?,
        Command::InstallClaude => emit(json!({"installed": false, "detail": "Claude command installation remains an explicit local integration"}))?,
        Command::Plugins => emit(client.get("/plugins").await?)?,
        Command::Collections { command: CollectionsCommand::List } => emit(client.get("/collections").await?)?,
        Command::Collections { command: CollectionsCommand::Delete { name } } => emit(client.post("/admin/repair", json!({"drop_collection": name})).await?)?,
        Command::Verify { path } => emit(client.post("/admin/verify", json!({"repo_path": path})).await?)?,
        Command::Repair { path } => emit(client.post("/admin/repair", json!({"repo_path": path})).await?)?,
        Command::Diagnose => emit(client.get("/diagnose").await?)?,
        Command::Service { command } => execute_service(command)?,
        Command::Migration { command } => execute_migration(command, token).await?,
        Command::Raw { method, path, body } => {
            let method = match method { HttpMethod::Get => Method::GET, HttpMethod::Post => Method::POST };
            let body = body.map(|raw| serde_json::from_str(&raw)).transpose()?;
            emit(client.request(method, &path, body).await?)?;
        }
    }
    Ok(())
}

async fn execute_migration(command: MigrationCommand, token: Option<String>) -> anyhow::Result<()> {
    match command {
        MigrationCommand::Shadow {
            python_url,
            rust_url,
            cases,
            output,
        } => {
            let cases = cases
                .as_deref()
                .map(migration::load_shadow_cases)
                .transpose()?
                .unwrap_or_else(migration::default_shadow_cases);
            let python = ApiClient::new(python_url, token.clone())?;
            let rust = ApiClient::new(rust_url, token)?;
            let report = migration::shadow_compare(&python, &rust, &cases).await?;
            fs::write(&output, serde_json::to_vec_pretty(&report)?)?;
            emit(serde_json::to_value(report)?)?;
        }
        MigrationCommand::PrepareCutover {
            rag_home,
            backup,
            rust_binary,
            shadow_report,
        } => emit(serde_json::to_value(migration::prepare_cutover(
            &rag_home,
            &backup,
            &rust_binary,
            &shadow_report,
        )?)?)?,
        MigrationCommand::Activate {
            manifest,
            acknowledge_data_risk,
        } => emit(serde_json::to_value(migration::activate_cutover(
            &manifest,
            acknowledge_data_risk,
        )?)?)?,
        MigrationCommand::Rollback {
            manifest,
            acknowledge_data_risk,
        } => emit(serde_json::to_value(migration::rollback(
            &manifest,
            acknowledge_data_risk,
        )?)?)?,
        MigrationCommand::ReleaseManifest { binary, output } => {
            let bytes = fs::read(&binary)?;
            use sha2::Digest as _;
            let checksum = format!("{:x}", sha2::Sha256::digest(&bytes));
            let manifest = json!({"binary": binary, "bytes": bytes.len(), "sha256": checksum, "targets": ["aarch64-apple-darwin", "x86_64-apple-darwin", "x86_64-unknown-linux-gnu"]});
            fs::write(&output, serde_json::to_vec_pretty(&manifest)?)?;
            emit(manifest)?;
        }
    }
    Ok(())
}

fn execute_service(command: ServiceCommand) -> anyhow::Result<()> {
    let platform = service::ServicePlatform::current()?;
    let home = user_home()?;
    match command {
        ServiceCommand::Install { dry_run: true } => println!(
            "{}",
            service::render(
                platform,
                &std::env::current_exe()?,
                DEFAULT_HOST,
                DEFAULT_PORT
            )
        ),
        ServiceCommand::Install { dry_run: false } => {
            let descriptor = service::install(
                platform,
                &home,
                &std::env::current_exe()?,
                DEFAULT_HOST,
                DEFAULT_PORT,
            )?;
            service::activate(platform, &descriptor)?;
            emit(json!({"installed": descriptor, "active": true}))?;
        }
        ServiceCommand::Uninstall { dry_run: true } => {
            emit(json!({"would_remove": service::descriptor_path(platform, &home)}))?
        }
        ServiceCommand::Uninstall { dry_run: false } => {
            let _ = service::deactivate(platform);
            emit(json!({"removed": service::uninstall(platform, &home)?}))?;
        }
        ServiceCommand::Status => emit(serde_json::to_value(service::status(platform, &home))?)?,
    }
    Ok(())
}

fn query_body(args: QueryArgs) -> Value {
    json!({"query": args.query.unwrap_or_default(), "repo": args.repo, "top_k": args.top_k})
}
fn question_body(args: QuestionArgs) -> Value {
    json!({"question": args.question, "repo": args.repo, "top_k": args.top_k})
}
fn symbol_body(args: SymbolArgs) -> Value {
    json!({"symbol": args.symbol, "repo": args.repo, "limit": args.limit})
}

fn parse_json_object(raw: Option<&str>) -> anyhow::Result<Value> {
    let value = raw
        .map(serde_json::from_str)
        .transpose()?
        .unwrap_or_else(|| json!({}));
    if !value.is_object() {
        bail!("filters must be a JSON object");
    }
    Ok(value)
}

fn emit(value: Value) -> anyhow::Result<()> {
    println!("{}", serde_json::to_string_pretty(&value)?);
    Ok(())
}

fn read_token() -> Option<String> {
    let path = RagPaths::from_env().ok()?.token_path;
    fs::read_to_string(path)
        .ok()
        .map(|value| value.trim().to_owned())
        .filter(|value| !value.is_empty())
}

/// Managed Qdrant container. Plain `docker run` (no compose file) so a
/// standalone `rag` binary can host Qdrant anywhere Docker is present.
/// Port comes from `qdrant.url` in config; storage is `~/.rag/qdrant_server`.
const QDRANT_CONTAINER: &str = "rag-qdrant";
const QDRANT_IMAGE: &str = "qdrant/qdrant:v1.18.2";

fn qdrant_settings() -> anyhow::Result<(u16, std::path::PathBuf)> {
    let paths = RagPaths::from_env().context("RAG home unavailable")?;
    let settings = rag_config::load_settings(&paths).unwrap_or_default();
    let port = settings
        .qdrant
        .url
        .rsplit(':')
        .next()
        .and_then(|value| value.trim_end_matches('/').parse::<u16>().ok())
        .unwrap_or(6333);
    Ok((port, paths.home.join("qdrant_server")))
}

fn docker_output(args: &[&str]) -> anyhow::Result<std::process::Output> {
    ProcessCommand::new("docker")
        .args(args)
        .output()
        .context("failed to execute docker — is Docker installed and running?")
}

fn qdrant_docker_up() -> anyhow::Result<()> {
    let (port, storage) = qdrant_settings()?;
    std::fs::create_dir_all(&storage)?;

    // Reuse an existing container (matching name) when present.
    let existing = docker_output(&[
        "ps",
        "-a",
        "--filter",
        &format!("name=^{QDRANT_CONTAINER}$"),
        "--format",
        "{{.Names}}",
    ])?;
    if String::from_utf8_lossy(&existing.stdout).trim() == QDRANT_CONTAINER {
        let started = docker_output(&["start", QDRANT_CONTAINER])?;
        if !started.status.success() {
            bail!(
                "docker start {QDRANT_CONTAINER} failed: {}",
                String::from_utf8_lossy(&started.stderr).trim()
            );
        }
        println!("{QDRANT_CONTAINER} started (existing container, port {port})");
        return Ok(());
    }

    let user = format!("{}:{}", unix_id("-u")?, unix_id("-g")?);
    let run = docker_output(&[
        "run",
        "-d",
        "--name",
        QDRANT_CONTAINER,
        "--restart",
        "unless-stopped",
        "--user",
        &user,
        "-p",
        &format!("127.0.0.1:{port}:6333"),
        "-p",
        &format!("127.0.0.1:{}:6334", port.saturating_add(1)),
        "-v",
        &format!("{}:/qdrant/storage", storage.display()),
        QDRANT_IMAGE,
    ])?;
    if !run.status.success() {
        bail!(
            "docker run failed: {}",
            String::from_utf8_lossy(&run.stderr).trim()
        );
    }
    println!(
        "{QDRANT_CONTAINER} running on 127.0.0.1:{port} (storage {})",
        storage.display()
    );
    Ok(())
}

fn qdrant_docker_down() -> anyhow::Result<()> {
    let stopped = docker_output(&["stop", QDRANT_CONTAINER])?;
    if !stopped.status.success() {
        bail!(
            "docker stop failed: {}",
            String::from_utf8_lossy(&stopped.stderr).trim()
        );
    }
    println!("{QDRANT_CONTAINER} stopped");
    Ok(())
}

async fn qdrant_docker_status() -> anyhow::Result<serde_json::Value> {
    let (port, storage) = qdrant_settings()?;
    let container_state =
        docker_output(&["inspect", "--format", "{{.State.Status}}", QDRANT_CONTAINER])
            .map(|output| {
                if output.status.success() {
                    String::from_utf8_lossy(&output.stdout).trim().to_owned()
                } else {
                    "absent".to_owned()
                }
            })
            .unwrap_or_else(|_| "docker-unavailable".to_owned());
    let ready = reqwest::Client::new()
        .get(format!("http://127.0.0.1:{port}/readyz"))
        .timeout(std::time::Duration::from_secs(2))
        .send()
        .await
        .map(|response| response.status().is_success())
        .unwrap_or(false);
    Ok(json!({
        "container": QDRANT_CONTAINER,
        "image": QDRANT_IMAGE,
        "state": container_state,
        "port": port,
        "storage": storage.display().to_string(),
        "ready": ready,
    }))
}

fn unix_id(flag: &str) -> anyhow::Result<String> {
    let output = ProcessCommand::new("id").arg(flag).output()?;
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_owned())
}

fn open_web(base_url: &str, print_url: bool) -> anyhow::Result<()> {
    if print_url {
        println!("{base_url}/");
        return Ok(());
    }
    let (program, args): (&str, Vec<&str>) = if cfg!(target_os = "macos") {
        ("open", vec![base_url])
    } else {
        ("xdg-open", vec![base_url])
    };
    let status = ProcessCommand::new(program).args(args).status()?;
    if !status.success() {
        bail!("browser opener failed with {status}");
    }
    Ok(())
}

fn user_home() -> anyhow::Result<PathBuf> {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .context("HOME is not set")
}

fn display_host(host: &str) -> String {
    if host.contains(':') {
        format!("[{host}]")
    } else {
        host.to_owned()
    }
}

fn repo_collection(name: &str) -> String {
    let name: String = name
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() {
                character.to_ascii_lowercase()
            } else {
                '_'
            }
        })
        .collect();
    format!("repo_{}", name.trim_matches('_'))
}

#[cfg(test)]
mod tests {
    use clap::Parser;

    use super::{Cli, Command};

    #[test]
    fn production_command_surface_parses() {
        for command in [
            "search",
            "smart-search",
            "context-pack",
            "resolve",
            "index",
            "status",
            "tui",
            "diagnose",
        ] {
            let mut args = vec!["rag-rs", command];
            match command {
                "search" | "context-pack" => args.push("query"),
                "smart-search" => args.push("question"),
                "resolve" => args.extend(["Symbol", "--repo", "repo"]),
                _ => {}
            }
            assert!(
                Cli::try_parse_from(args).is_ok(),
                "failed to parse {command}"
            );
        }
        assert!(matches!(
            Cli::try_parse_from(["rag-rs", "status"]).unwrap().command,
            Some(Command::Status)
        ));
    }
}
