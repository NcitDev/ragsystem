use std::{
    collections::{BTreeMap, BTreeSet},
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
    Ok(short_sha256(&bytes))
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
        if entry.file_type().is_some_and(|ty| ty.is_dir()) {
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
