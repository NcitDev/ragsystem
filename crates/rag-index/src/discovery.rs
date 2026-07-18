use std::{
    collections::{BTreeMap, BTreeSet},
    io::Read as _,
    path::{Path, PathBuf},
};

use ignore::WalkBuilder;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use thiserror::Error;

use crate::chunker::supported_extensions;

#[derive(Debug, Error)]
pub enum DiscoveryError {
    #[error("io error at {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error("file at {path} is larger than the configured {max_bytes}-byte limit")]
    FileTooLarge { path: PathBuf, max_bytes: u64 },
    #[error("source path is not a regular file: {path}")]
    NotRegularFile { path: PathBuf },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct IndexState {
    pub last_commit: String,
    pub file_hashes: BTreeMap<String, String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct IndexDiff {
    pub added: Vec<String>,
    pub changed: Vec<String>,
    pub unchanged: Vec<String>,
    pub deleted: Vec<String>,
}

pub fn file_hash(path: impl AsRef<Path>) -> Result<String, DiscoveryError> {
    let path = path.as_ref();
    let bytes = std::fs::read(path).map_err(|source| DiscoveryError::Io {
        path: path.to_path_buf(),
        source,
    })?;
    Ok(source_hash(&bytes))
}

/// Read at most `max_bytes` from a regular source file.
///
/// The extra byte makes the limit enforceable even when a file grows between
/// discovery and processing, without ever buffering the whole oversized file.
pub fn read_file_bounded(
    path: impl AsRef<Path>,
    max_bytes: u64,
) -> Result<Vec<u8>, DiscoveryError> {
    let path = path.as_ref();
    let mut options = std::fs::OpenOptions::new();
    options.read(true);
    // Refuse a final-component symlink even if it replaces a discovered file
    // between the walk and this open. Parent-directory races require stronger
    // platform-specific openat semantics and remain a documented limitation.
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt as _;
        options.custom_flags(libc::O_NOFOLLOW);
    }
    #[cfg(not(unix))]
    {
        let metadata = std::fs::symlink_metadata(path).map_err(|source| DiscoveryError::Io {
            path: path.to_path_buf(),
            source,
        })?;
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            return Err(DiscoveryError::NotRegularFile {
                path: path.to_path_buf(),
            });
        }
    }
    let file = options.open(path).map_err(|source| DiscoveryError::Io {
        path: path.to_path_buf(),
        source,
    })?;
    if !file
        .metadata()
        .map_err(|source| DiscoveryError::Io {
            path: path.to_path_buf(),
            source,
        })?
        .is_file()
    {
        return Err(DiscoveryError::NotRegularFile {
            path: path.to_path_buf(),
        });
    }
    let mut bytes = Vec::new();
    file.take(max_bytes.saturating_add(1))
        .read_to_end(&mut bytes)
        .map_err(|source| DiscoveryError::Io {
            path: path.to_path_buf(),
            source,
        })?;
    if bytes.len() as u64 > max_bytes {
        return Err(DiscoveryError::FileTooLarge {
            path: path.to_path_buf(),
            max_bytes,
        });
    }
    Ok(bytes)
}

/// Hash a source file while enforcing the same byte budget as processing.
pub fn file_hash_bounded(path: impl AsRef<Path>, max_bytes: u64) -> Result<String, DiscoveryError> {
    read_file_bounded(path, max_bytes).map(|bytes| source_hash(&bytes))
}

/// Stable short SHA-256 used by persisted source-file index state.
#[must_use]
pub fn source_hash(bytes: &[u8]) -> String {
    short_sha256(bytes)
}

pub fn state_dir_for(rag_home: impl AsRef<Path>, repo_path: impl AsRef<Path>) -> PathBuf {
    let abs = repo_path
        .as_ref()
        .canonicalize()
        .unwrap_or_else(|_| repo_path.as_ref().to_path_buf());
    let digest = short_sha256(abs.to_string_lossy().as_bytes());
    rag_home.as_ref().join("repos").join(digest)
}

pub fn discover_files(
    repo_path: impl AsRef<Path>,
    extensions: Option<&[&str]>,
    skip_dirs: &[&str],
) -> Result<Vec<PathBuf>, DiscoveryError> {
    let repo = repo_path.as_ref();
    let allowed: BTreeSet<String> = extensions
        .map(|items| items.iter().map(|value| (*value).to_owned()).collect())
        .unwrap_or_else(|| supported_extensions().into_iter().collect());
    let skip: BTreeSet<&str> = skip_dirs.iter().copied().collect();
    let mut out = Vec::new();
    // Python parity: `os.walk` + skip_dirs + extension filter only. Git
    // ignore files are deliberately NOT consulted — Python indexes tracked
    // files under gitignored paths (e.g. .idea/fileTemplates), and the
    // skip_dirs setting is the single exclusion mechanism.
    for entry in WalkBuilder::new(repo)
        .hidden(false)
        .git_ignore(false)
        .git_global(false)
        .git_exclude(false)
        .ignore(false)
        .require_git(false)
        .parents(false)
        .build()
    {
        let entry = match entry {
            Ok(entry) => entry,
            Err(err) => {
                return Err(DiscoveryError::Io {
                    path: repo.to_path_buf(),
                    source: std::io::Error::other(err.to_string()),
                });
            }
        };
        let path = entry.path();
        // `os.walk` never treats a symlink-to-file as a regular file. Keeping
        // that property is also a security boundary: a repository symlink
        // must not make the indexer read secrets outside the repository root.
        if !entry.file_type().is_some_and(|ty| ty.is_file()) {
            continue;
        }
        if path
            .components()
            .any(|component| skip.contains(component.as_os_str().to_string_lossy().as_ref()))
        {
            continue;
        }
        let Some(ext) = path.extension().and_then(|value| value.to_str()) else {
            continue;
        };
        let dotted = format!(".{}", ext.to_ascii_lowercase());
        if allowed.contains(&dotted) {
            out.push(path.to_path_buf());
        }
    }
    out.sort();
    Ok(out)
}

pub fn diff_index_state(
    previous: &IndexState,
    current_hashes: &BTreeMap<String, String>,
) -> IndexDiff {
    let mut diff = IndexDiff::default();
    for (path, hash) in current_hashes {
        match previous.file_hashes.get(path) {
            None => diff.added.push(path.clone()),
            Some(old) if old != hash => diff.changed.push(path.clone()),
            Some(_) => diff.unchanged.push(path.clone()),
        }
    }
    for path in previous.file_hashes.keys() {
        if !current_hashes.contains_key(path) {
            diff.deleted.push(path.clone());
        }
    }
    diff
}

pub(crate) fn short_sha256(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    format!("{digest:x}")[..16].to_owned()
}
