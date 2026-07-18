//! Managed local Qdrant for `qdrant.mode = "embedded"`: the daemon hosts a
//! pinned Qdrant server binary as a child process (no Docker), resolving the
//! R2 decision gate's "managed server" option end to end. `mode = "server"`
//! never enters this module — the daemon just connects to `qdrant.url`
//! (typically the `rag qdrant-up` Docker container).

use std::path::PathBuf;
use std::sync::{Mutex, OnceLock};
use std::time::Duration;

use rag_config::RagPaths;

const QDRANT_VERSION: &str = "v1.18.2";
const READY_TIMEOUT: Duration = Duration::from_secs(30);

/// Keeps the child handle alive for the daemon's lifetime; `kill_on_drop`
/// stops Qdrant when the runtime shuts down.
static MANAGED_QDRANT: OnceLock<Mutex<Option<tokio::process::Child>>> = OnceLock::new();

/// Ensure a local Qdrant serves the configured port: reuse a live instance,
/// otherwise locate (or download) the pinned binary and spawn it against
/// `~/.rag/qdrant_server`.
pub async fn ensure_local_qdrant(paths: &RagPaths, url: &str) -> Result<(), String> {
    let port = parse_port(url).unwrap_or(6333);
    let ready_url = format!("http://127.0.0.1:{port}/readyz");
    if probe(&ready_url).await {
        eprintln!("embedded qdrant: port {port} already serving; reusing that instance");
        return Ok(());
    }

    let binary = locate_or_download_binary(paths).await?;
    let storage = paths.home.join("qdrant_server");
    std::fs::create_dir_all(&storage).map_err(|error| error.to_string())?;
    let log_dir = paths.home.join("logs");
    let _ = std::fs::create_dir_all(&log_dir);
    let log = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_dir.join("qdrant.log"))
        .map_err(|error| error.to_string())?;

    let mut command = tokio::process::Command::new(&binary);
    command
        .env("QDRANT__STORAGE__STORAGE_PATH", &storage)
        .env("QDRANT__SERVICE__HOST", "127.0.0.1")
        .env("QDRANT__SERVICE__HTTP_PORT", port.to_string())
        .env(
            "QDRANT__SERVICE__GRPC_PORT",
            port.saturating_add(1).to_string(),
        )
        .env("QDRANT__TELEMETRY_DISABLED", "true")
        .stdout(std::process::Stdio::from(
            log.try_clone().map_err(|error| error.to_string())?,
        ))
        .stderr(std::process::Stdio::from(log))
        .kill_on_drop(true);
    // The handle lives in a static (never dropped), so `kill_on_drop` alone
    // cannot stop the child — `stop_managed` runs on graceful shutdown. If the
    // daemon is killed outright the child survives; the next start's readiness
    // probe adopts it instead of spawning a second instance.
    let child = command
        .spawn()
        .map_err(|error| format!("failed to spawn {}: {error}", binary.display()))?;
    MANAGED_QDRANT
        .get_or_init(|| Mutex::new(None))
        .lock()
        .map_err(|_| "managed qdrant lock poisoned".to_owned())?
        .replace(child);

    let deadline = std::time::Instant::now() + READY_TIMEOUT;
    while std::time::Instant::now() < deadline {
        if probe(&ready_url).await {
            eprintln!(
                "embedded qdrant {QDRANT_VERSION} serving on 127.0.0.1:{port} (storage {})",
                storage.display()
            );
            return Ok(());
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
    Err(format!(
        "embedded qdrant did not become ready on port {port} within {READY_TIMEOUT:?} \
         (see {}/qdrant.log)",
        log_dir.display()
    ))
}

/// Stop the managed child on graceful daemon shutdown.
pub fn stop_managed() {
    if let Some(lock) = MANAGED_QDRANT.get() {
        if let Ok(mut guard) = lock.lock() {
            if let Some(mut child) = guard.take() {
                let _ = child.start_kill();
            }
        }
    }
}

async fn probe(ready_url: &str) -> bool {
    reqwest::Client::new()
        .get(ready_url)
        .timeout(Duration::from_secs(2))
        .send()
        .await
        .map(|response| response.status().is_success())
        .unwrap_or(false)
}

async fn locate_or_download_binary(paths: &RagPaths) -> Result<PathBuf, String> {
    let managed = paths.home.join("bin").join("qdrant");
    if managed.is_file() {
        return Ok(managed);
    }
    // A system-installed qdrant also satisfies embedded mode.
    if let Ok(output) = std::process::Command::new("qdrant")
        .arg("--version")
        .output()
    {
        if output.status.success() {
            return Ok(PathBuf::from("qdrant"));
        }
    }

    let target = release_target()?;
    let url = format!(
        "https://github.com/qdrant/qdrant/releases/download/{QDRANT_VERSION}/qdrant-{target}.tar.gz"
    );
    eprintln!("embedded qdrant: downloading {url}");
    let bytes = reqwest::Client::new()
        .get(&url)
        .timeout(Duration::from_secs(600))
        .send()
        .await
        .and_then(reqwest::Response::error_for_status)
        .map_err(|error| format!("qdrant download failed: {error}"))?
        .bytes()
        .await
        .map_err(|error| format!("qdrant download failed: {error}"))?;

    let bin_dir = paths.home.join("bin");
    std::fs::create_dir_all(&bin_dir).map_err(|error| error.to_string())?;
    let destination = managed.clone();
    tokio::task::spawn_blocking(move || -> Result<(), String> {
        let decoder = flate2::read::GzDecoder::new(std::io::Cursor::new(bytes));
        let mut archive = tar::Archive::new(decoder);
        for entry in archive.entries().map_err(|error| error.to_string())? {
            let mut entry = entry.map_err(|error| error.to_string())?;
            let path = entry.path().map_err(|error| error.to_string())?;
            if path.file_name().and_then(|name| name.to_str()) == Some("qdrant") {
                entry
                    .unpack(&destination)
                    .map_err(|error| error.to_string())?;
                #[cfg(unix)]
                {
                    use std::os::unix::fs::PermissionsExt;
                    let _ = std::fs::set_permissions(
                        &destination,
                        std::fs::Permissions::from_mode(0o755),
                    );
                }
                return Ok(());
            }
        }
        Err("qdrant binary not found in release archive".to_owned())
    })
    .await
    .map_err(|error| error.to_string())??;
    Ok(managed)
}

fn release_target() -> Result<String, String> {
    let arch = match std::env::consts::ARCH {
        "x86_64" => "x86_64",
        "aarch64" => "aarch64",
        other => {
            return Err(format!(
                "unsupported architecture for embedded qdrant: {other}"
            ))
        }
    };
    let platform = match std::env::consts::OS {
        "linux" => "unknown-linux-gnu",
        "macos" => "apple-darwin",
        other => return Err(format!("unsupported OS for embedded qdrant: {other}")),
    };
    Ok(format!("{arch}-{platform}"))
}

pub(crate) fn parse_port(url: &str) -> Option<u16> {
    url.trim_end_matches('/')
        .rsplit(':')
        .next()
        .and_then(|value| value.parse::<u16>().ok())
}

#[cfg(test)]
mod tests {
    use super::{parse_port, release_target};

    #[test]
    fn port_parsing_handles_common_urls() {
        assert_eq!(parse_port("http://127.0.0.1:6333"), Some(6333));
        assert_eq!(parse_port("http://127.0.0.1:6335/"), Some(6335));
        assert_eq!(parse_port("http://localhost"), None);
    }

    #[test]
    fn release_target_resolves_on_supported_hosts() {
        let target = release_target().expect("supported test host");
        assert!(target.contains('-'));
    }
}
