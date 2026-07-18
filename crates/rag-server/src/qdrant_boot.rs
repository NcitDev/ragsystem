//! Managed local Qdrant for `qdrant.mode = "embedded"`: the daemon hosts a
//! pinned Qdrant server binary as a child process (no Docker), resolving the
//! R2 decision gate's "managed server" option end to end. `mode = "server"`
//! never enters this module — the daemon just connects to `qdrant.url`
//! (typically the `rag qdrant-up` Docker container).

use std::io::{Read as _, Write as _};
use std::net::IpAddr;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, OnceLock};
use std::time::Duration;

use rag_config::RagPaths;
use sha2::{Digest as _, Sha256};
use uuid::Uuid;

const QDRANT_VERSION: &str = "v1.18.2";
const READY_TIMEOUT: Duration = Duration::from_secs(30);
const MAX_ARCHIVE_BYTES: usize = 64 * 1024 * 1024;
const MAX_BINARY_BYTES: u64 = 128 * 1024 * 1024;

/// Keeps the child handle alive for the daemon's lifetime; `kill_on_drop`
/// stops Qdrant when the runtime shuts down.
static MANAGED_QDRANT: OnceLock<Mutex<Option<tokio::process::Child>>> = OnceLock::new();

/// Ensure a local Qdrant serves the configured port: reuse a live instance,
/// otherwise locate (or download) the pinned binary and spawn it against
/// `~/.rag/qdrant_server`.
pub async fn ensure_local_qdrant(paths: &RagPaths, url: &str) -> Result<(), String> {
    let port = embedded_port(url)?;
    let ready_url = format!("http://127.0.0.1:{port}/readyz");
    if probe(&ready_url).await {
        if managed_child_is_running()? {
            return Ok(());
        }
        return Err(format!(
            "embedded qdrant refused to adopt the unknown process already serving port {port}; \
             stop it or set qdrant.mode = \"server\" explicitly"
        ));
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
    // cannot stop the child — `stop_managed` runs on graceful shutdown and on
    // readiness failure. An ungraceful daemon kill can still orphan Qdrant;
    // the next start refuses to adopt that unverified port occupant.
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
        if !managed_child_is_running()? {
            stop_managed().await;
            return Err(format!(
                "embedded qdrant exited before becoming ready (see {}/qdrant.log)",
                log_dir.display()
            ));
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
    stop_managed().await;
    Err(format!(
        "embedded qdrant did not become ready on port {port} within {READY_TIMEOUT:?} \
         (see {}/qdrant.log)",
        log_dir.display()
    ))
}

/// Stop the managed child on graceful daemon shutdown.
pub async fn stop_managed() {
    if let Some(lock) = MANAGED_QDRANT.get() {
        let child = lock.lock().ok().and_then(|mut guard| guard.take());
        if let Some(mut child) = child {
            let _ = tokio::time::timeout(Duration::from_secs(5), child.kill()).await;
        }
    }
}

fn managed_child_is_running() -> Result<bool, String> {
    let Some(lock) = MANAGED_QDRANT.get() else {
        return Ok(false);
    };
    let mut guard = lock
        .lock()
        .map_err(|_| "managed qdrant lock poisoned".to_owned())?;
    match guard.as_mut() {
        Some(child) => child
            .try_wait()
            .map(|status| status.is_none())
            .map_err(|error| format!("failed to inspect managed qdrant: {error}")),
        None => Ok(false),
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
    match std::fs::symlink_metadata(&managed) {
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_file() => {
            return Err(format!(
                "managed qdrant path is not a regular file: {}",
                managed.display()
            ));
        }
        Ok(_) if managed_binary_matches_sidecar(&managed)? => return Ok(managed),
        Ok(_) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => return Err(error.to_string()),
    }
    let artifact = release_artifact()?;
    let url = format!(
        "https://github.com/qdrant/qdrant/releases/download/{QDRANT_VERSION}/qdrant-{}.tar.gz",
        artifact.target
    );
    eprintln!("embedded qdrant: downloading {url}");
    let mut response = reqwest::Client::new()
        .get(&url)
        .timeout(Duration::from_secs(600))
        .send()
        .await
        .and_then(reqwest::Response::error_for_status)
        .map_err(|error| format!("qdrant download failed: {error}"))?;
    if response
        .content_length()
        .is_some_and(|length| length > MAX_ARCHIVE_BYTES as u64)
    {
        return Err(format!(
            "qdrant archive exceeds the {MAX_ARCHIVE_BYTES}-byte download limit"
        ));
    }
    let mut bytes = Vec::new();
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|error| format!("qdrant download failed: {error}"))?
    {
        if bytes.len().saturating_add(chunk.len()) > MAX_ARCHIVE_BYTES {
            return Err(format!(
                "qdrant archive exceeds the {MAX_ARCHIVE_BYTES}-byte download limit"
            ));
        }
        bytes.extend_from_slice(&chunk);
    }
    let actual_archive_sha256 = format!("{:x}", Sha256::digest(&bytes));
    if actual_archive_sha256 != artifact.sha256 {
        return Err(format!(
            "qdrant archive checksum mismatch for {}: expected {}, received {}",
            artifact.target, artifact.sha256, actual_archive_sha256
        ));
    }

    let bin_dir = paths.home.join("bin");
    std::fs::create_dir_all(&bin_dir).map_err(|error| error.to_string())?;
    let destination = managed.clone();
    let temporary = bin_dir.join(format!(".qdrant-{}.tmp", Uuid::new_v4()));
    tokio::task::spawn_blocking(move || -> Result<(), String> {
        install_verified_archive(&bytes, &temporary, &destination)
    })
    .await
    .map_err(|error| error.to_string())??;
    Ok(managed)
}

fn install_verified_archive(
    bytes: &[u8],
    temporary: &Path,
    destination: &Path,
) -> Result<(), String> {
    let result = (|| {
        let decoder = flate2::read::GzDecoder::new(std::io::Cursor::new(bytes));
        let mut archive = tar::Archive::new(decoder);
        for entry in archive.entries().map_err(|error| error.to_string())? {
            let entry = entry.map_err(|error| error.to_string())?;
            let path = entry.path().map_err(|error| error.to_string())?;
            if path.file_name().and_then(|name| name.to_str()) != Some("qdrant") {
                continue;
            }
            if !entry.header().entry_type().is_file() {
                return Err("qdrant release entry is not a regular file".to_owned());
            }
            let declared_size = entry.header().size().map_err(|error| error.to_string())?;
            if declared_size > MAX_BINARY_BYTES {
                return Err(format!(
                    "qdrant binary exceeds the {MAX_BINARY_BYTES}-byte extraction limit"
                ));
            }
            let mut output = std::fs::OpenOptions::new()
                .create_new(true)
                .write(true)
                .open(temporary)
                .map_err(|error| error.to_string())?;
            let copied = std::io::copy(
                &mut entry.take(MAX_BINARY_BYTES.saturating_add(1)),
                &mut output,
            )
            .map_err(|error| error.to_string())?;
            if copied != declared_size || copied > MAX_BINARY_BYTES {
                return Err("qdrant binary size did not match its archive entry".to_owned());
            }
            output.flush().map_err(|error| error.to_string())?;
            output.sync_all().map_err(|error| error.to_string())?;
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                std::fs::set_permissions(temporary, std::fs::Permissions::from_mode(0o755))
                    .map_err(|error| error.to_string())?;
            }
            let binary_sha256 = sha256_file(temporary)?;
            std::fs::rename(temporary, destination).map_err(|error| error.to_string())?;
            write_sidecar_atomic(destination, &binary_sha256)?;
            if let Some(parent) = destination.parent() {
                std::fs::File::open(parent)
                    .and_then(|directory| directory.sync_all())
                    .map_err(|error| error.to_string())?;
            }
            return Ok(());
        }
        Err("qdrant binary not found in release archive".to_owned())
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(temporary);
    }
    result
}

fn write_sidecar_atomic(binary: &Path, digest: &str) -> Result<(), String> {
    let sidecar = sidecar_path(binary);
    let temporary = sidecar.with_extension(format!("sha256.{}.tmp", Uuid::new_v4()));
    let result = (|| {
        let mut file = std::fs::OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&temporary)
            .map_err(|error| error.to_string())?;
        file.write_all(format!("{digest}\n").as_bytes())
            .map_err(|error| error.to_string())?;
        file.sync_all().map_err(|error| error.to_string())?;
        drop(file);
        std::fs::rename(&temporary, &sidecar).map_err(|error| error.to_string())
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&temporary);
    }
    result
}

fn managed_binary_matches_sidecar(binary: &Path) -> Result<bool, String> {
    let sidecar = sidecar_path(binary);
    let metadata = match std::fs::symlink_metadata(&sidecar) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(false),
        Err(error) => return Err(error.to_string()),
    };
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err("managed qdrant checksum sidecar is not a regular file".to_owned());
    }
    let expected = match std::fs::read_to_string(&sidecar) {
        Ok(value) => value.trim().to_owned(),
        Err(error) => return Err(error.to_string()),
    };
    Ok(expected.len() == 64 && sha256_file(binary)? == expected)
}

fn sidecar_path(binary: &Path) -> PathBuf {
    binary.with_extension("sha256")
}

fn sha256_file(path: &Path) -> Result<String, String> {
    let mut file = std::fs::File::open(path).map_err(|error| error.to_string())?;
    let mut digest = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let read = file.read(&mut buffer).map_err(|error| error.to_string())?;
        if read == 0 {
            break;
        }
        digest.update(&buffer[..read]);
    }
    Ok(format!("{:x}", digest.finalize()))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct ReleaseArtifact {
    target: &'static str,
    sha256: &'static str,
}

fn release_artifact() -> Result<ReleaseArtifact, String> {
    match (std::env::consts::ARCH, std::env::consts::OS) {
        ("x86_64", "linux") => Ok(ReleaseArtifact {
            target: "x86_64-unknown-linux-gnu",
            sha256: "cd619c61d8d32dd176af88cf498714ecb765b7df9021d691862478d6ac35392c",
        }),
        ("aarch64", "linux") => Ok(ReleaseArtifact {
            target: "aarch64-unknown-linux-musl",
            sha256: "2ead5bb8206289b67c930f0eb29123228ddb43c2344551a0947cbc9046f92c6c",
        }),
        ("x86_64", "macos") => Ok(ReleaseArtifact {
            target: "x86_64-apple-darwin",
            sha256: "d395eb3d96c2196bbb8c611b800842928fb8b4997924b585bf42ce0ceb90fa1f",
        }),
        ("aarch64", "macos") => Ok(ReleaseArtifact {
            target: "aarch64-apple-darwin",
            sha256: "859f487e316ae1bda3b5d7c1e129a0a7344424d992503c188979ca6ac1b47253",
        }),
        (arch, os) => Err(format!("unsupported embedded Qdrant target: {arch}-{os}")),
    }
}

fn embedded_port(url: &str) -> Result<u16, String> {
    let parsed = reqwest::Url::parse(url)
        .map_err(|error| format!("invalid embedded qdrant URL: {error}"))?;
    let loopback = match parsed.host_str() {
        Some("localhost") => true,
        Some(host) => host
            .parse::<IpAddr>()
            .map(|address| address.is_loopback())
            .unwrap_or(false),
        None => false,
    };
    if parsed.scheme() != "http"
        || !loopback
        || !parsed.username().is_empty()
        || parsed.password().is_some()
        || parsed.query().is_some()
        || parsed.fragment().is_some()
    {
        return Err(
            "embedded qdrant URL must be a credential-free http:// loopback URL without a query or fragment"
                .to_owned(),
        );
    }
    let port = parsed.port().unwrap_or(6333);
    if port == u16::MAX {
        return Err(
            "embedded qdrant HTTP port must leave the following port available for gRPC".to_owned(),
        );
    }
    Ok(port)
}

#[cfg(test)]
fn parse_port(url: &str) -> Option<u16> {
    reqwest::Url::parse(url).ok()?.port()
}

#[cfg(test)]
mod tests {
    use std::io::Cursor;

    use super::{
        embedded_port, install_verified_archive, managed_binary_matches_sidecar, parse_port,
        release_artifact,
    };

    #[test]
    fn port_parsing_handles_common_urls() {
        assert_eq!(parse_port("http://127.0.0.1:6333"), Some(6333));
        assert_eq!(parse_port("http://127.0.0.1:6335/"), Some(6335));
        assert_eq!(parse_port("http://localhost"), None);
        assert_eq!(parse_port("http://[::1]:6336"), Some(6336));
        assert_eq!(embedded_port("http://localhost").unwrap(), 6333);
        assert!(embedded_port("http://qdrant.example.com:6333").is_err());
        assert!(embedded_port("http://user@127.0.0.1:6333").is_err());
        assert!(embedded_port("http://127.0.0.1:6333?key=value").is_err());
        assert!(embedded_port("http://127.0.0.1:65535").is_err());
    }

    #[test]
    fn release_artifact_resolves_with_an_official_sha256() {
        let artifact = release_artifact().expect("supported test host");
        assert!(artifact.target.contains('-'));
        assert_eq!(artifact.sha256.len(), 64);
    }

    #[test]
    fn archive_install_is_bounded_to_a_regular_qdrant_file_and_writes_integrity_state() {
        let payload = b"verified-qdrant-binary";
        let encoder = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
        let mut archive = tar::Builder::new(encoder);
        let mut header = tar::Header::new_gnu();
        header.set_size(payload.len() as u64);
        header.set_mode(0o755);
        header.set_cksum();
        archive
            .append_data(&mut header, "qdrant", Cursor::new(payload))
            .unwrap();
        let bytes = archive.into_inner().unwrap().finish().unwrap();

        let directory = tempfile::tempdir().unwrap();
        let temporary = directory.path().join("qdrant.tmp");
        let destination = directory.path().join("qdrant");
        install_verified_archive(&bytes, &temporary, &destination).unwrap();

        assert_eq!(std::fs::read(&destination).unwrap(), payload);
        assert!(managed_binary_matches_sidecar(&destination).unwrap());
        assert!(!temporary.exists());
    }

    #[test]
    fn archive_install_rejects_a_qdrant_symlink() {
        let encoder = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
        let mut archive = tar::Builder::new(encoder);
        let mut header = tar::Header::new_gnu();
        header.set_entry_type(tar::EntryType::Symlink);
        header.set_size(0);
        header.set_mode(0o755);
        header.set_link_name("/tmp/not-qdrant").unwrap();
        header.set_cksum();
        archive
            .append_data(&mut header, "qdrant", Cursor::new([]))
            .unwrap();
        let bytes = archive.into_inner().unwrap().finish().unwrap();

        let directory = tempfile::tempdir().unwrap();
        let temporary = directory.path().join("qdrant.tmp");
        let destination = directory.path().join("qdrant");
        let error = install_verified_archive(&bytes, &temporary, &destination).unwrap_err();
        assert!(error.contains("not a regular file"));
        assert!(!destination.exists());
        assert!(!temporary.exists());
    }

    #[cfg(unix)]
    #[test]
    fn managed_checksum_sidecar_must_not_be_a_symlink() {
        use std::os::unix::fs::symlink;

        let directory = tempfile::tempdir().unwrap();
        let binary = directory.path().join("qdrant");
        let outside = directory.path().join("outside");
        std::fs::write(&binary, b"binary").unwrap();
        std::fs::write(&outside, b"not-a-sidecar").unwrap();
        symlink(&outside, super::sidecar_path(&binary)).unwrap();

        let error = managed_binary_matches_sidecar(&binary).unwrap_err();

        assert!(error.contains("not a regular file"));
    }
}
