//! Live indexing write path: port of Python `core/indexer.py` for the Rust
//! daemon. Incremental by git-state + per-file hash, embeds through Ollama
//! with the shared `embed_cache.db`, upserts to Qdrant with deterministic
//! UUIDv5 point ids, and mirrors chunks into the SQLite code index.

use std::collections::{BTreeMap, BTreeSet};
use std::io::Write as _;
use std::path::{Path, PathBuf};

use fs2::FileExt as _;
use serde_json::{json, Map, Value};
use uuid::Uuid;

use rag_config::RagPaths;
use rag_index::chunker::detect_language;
use rag_index::enrich::enrich_chunk_metadata;
use rag_index::lexical::{CodeDocument, LexicalIndex};
use rag_index::{chunk_code, diff_index_state};
use rag_services::qdrant::{
    CollectionVectorConfig, Distance, FieldCondition, PayloadSchemaType, PayloadValue, Point,
    QdrantFilter,
};
use rag_storage::{EmbedCache, IndexState, RepoInfo, RepoRegistry};

use crate::retrieval::RetrievalBackend;

/// Authoritative filterable payload fields (Python `vectorstore.PAYLOAD_INDEXES`).
const PAYLOAD_INDEXES: [(&str, PayloadSchemaType); 44] = [
    ("file_path", PayloadSchemaType::Keyword),
    ("language", PayloadSchemaType::Keyword),
    ("chunk_type", PayloadSchemaType::Keyword),
    ("name", PayloadSchemaType::Keyword),
    ("parent_name", PayloadSchemaType::Keyword),
    ("doc_type", PayloadSchemaType::Keyword),
    ("patterns", PayloadSchemaType::Keyword),
    ("pattern_roles", PayloadSchemaType::Keyword),
    ("domains", PayloadSchemaType::Keyword),
    ("layers", PayloadSchemaType::Keyword),
    ("is_async", PayloadSchemaType::Keyword),
    ("is_suspend", PayloadSchemaType::Keyword),
    ("uses_coroutines", PayloadSchemaType::Keyword),
    ("uses_flow", PayloadSchemaType::Keyword),
    ("uses_async_java", PayloadSchemaType::Keyword),
    ("is_singleton", PayloadSchemaType::Keyword),
    ("is_singleton_pattern", PayloadSchemaType::Keyword),
    ("is_kotlin_object", PayloadSchemaType::Keyword),
    ("is_sealed", PayloadSchemaType::Keyword),
    ("is_data_class", PayloadSchemaType::Keyword),
    ("is_interface", PayloadSchemaType::Keyword),
    ("is_composable", PayloadSchemaType::Keyword),
    ("is_di_component", PayloadSchemaType::Keyword),
    ("is_enum", PayloadSchemaType::Keyword),
    ("is_public", PayloadSchemaType::Keyword),
    ("is_abstract", PayloadSchemaType::Keyword),
    ("has_docstring", PayloadSchemaType::Keyword),
    ("has_unit_test", PayloadSchemaType::Keyword),
    ("dead_code_candidate", PayloadSchemaType::Keyword),
    ("nesting_depth", PayloadSchemaType::Integer),
    ("parameter_count", PayloadSchemaType::Integer),
    ("line_count", PayloadSchemaType::Integer),
    ("complexity_cyclomatic", PayloadSchemaType::Integer),
    ("complexity_cognitive", PayloadSchemaType::Integer),
    ("fan_in", PayloadSchemaType::Integer),
    ("fan_out", PayloadSchemaType::Integer),
    ("external_deps", PayloadSchemaType::Keyword),
    ("inherits_from", PayloadSchemaType::Keyword),
    ("defines_fqn", PayloadSchemaType::Keyword),
    ("references_fqn", PayloadSchemaType::Keyword),
    ("decorator_tags", PayloadSchemaType::Keyword),
    ("concurrency_patterns", PayloadSchemaType::Keyword),
    ("module_path", PayloadSchemaType::Keyword),
    ("lod_level", PayloadSchemaType::Keyword),
];

/// Files flushed to Qdrant + SQLite per batch. Embedding batching happens
/// inside the Ollama client; this only bounds hash-promotion granularity.
const FILES_PER_FLUSH: usize = 16;
/// Maximum summary JSONL accepted by `/vocab/build`.
const MAX_VOCAB_JSONL_BYTES: u64 = 64 * 1024 * 1024;

/// In-process per-repo run lock (Python parity: non-blocking flock that fails
/// fast with "another index run holds the lock").
static ACTIVE_INDEX_RUNS: std::sync::OnceLock<
    std::sync::Mutex<std::collections::BTreeSet<PathBuf>>,
> = std::sync::OnceLock::new();

#[derive(Debug)]
struct IndexRunGuard {
    repo_path: PathBuf,
    lock_file: std::fs::File,
}

impl IndexRunGuard {
    fn acquire(paths: &RagPaths, repo_path: &Path) -> Result<Self, String> {
        let lock = ACTIVE_INDEX_RUNS.get_or_init(|| std::sync::Mutex::new(Default::default()));
        let mut active = lock
            .lock()
            .map_err(|_| "index run lock poisoned".to_owned())?;
        if !active.insert(repo_path.to_path_buf()) {
            return Err(format!(
                "another index run is already in progress for {}",
                repo_path.display()
            ));
        }
        let state_dir = rag_storage::state_dir_for(paths, repo_path);
        if let Err(error) = std::fs::create_dir_all(&state_dir) {
            active.remove(repo_path);
            return Err(format!("create index lock directory: {error}"));
        }
        let lock_path = state_dir.join("index.lock");
        let lock_file = match std::fs::OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(&lock_path)
        {
            Ok(file) => file,
            Err(error) => {
                active.remove(repo_path);
                return Err(format!("open index run lock: {error}"));
            }
        };
        if let Err(error) = lock_file.try_lock_exclusive() {
            active.remove(repo_path);
            return if error.kind() == std::io::ErrorKind::WouldBlock {
                Err(format!(
                    "another index run is already in progress for {}",
                    repo_path.display()
                ))
            } else {
                Err(format!("acquire index run lock: {error}"))
            };
        }
        Ok(Self {
            repo_path: repo_path.to_path_buf(),
            lock_file,
        })
    }
}

impl Drop for IndexRunGuard {
    fn drop(&mut self) {
        let _ = fs2::FileExt::unlock(&self.lock_file);
        if let Some(lock) = ACTIVE_INDEX_RUNS.get() {
            if let Ok(mut active) = lock.lock() {
                active.remove(&self.repo_path);
            }
        }
    }
}

struct FileChunks {
    rel_path: String,
    file_hash: String,
    documents: Vec<PendingDocument>,
}

struct PendingDocument {
    chunk_id: String,
    content: String,
    content_hash: String,
    payload: Map<String, Value>,
    code_document: CodeDocument,
}

fn requested_repo_name(body: &Value) -> Option<String> {
    ["repo_name", "name"].into_iter().find_map(|field| {
        body.get(field)
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|name| !name.is_empty())
            .map(str::to_owned)
    })
}

fn assemble_file_hashes(
    mut out_of_scope: BTreeMap<String, String>,
    diff: &rag_index::IndexDiff,
    previous: &BTreeMap<String, String>,
    retry_previous: &BTreeSet<String>,
    promoted: BTreeMap<String, String>,
) -> BTreeMap<String, String> {
    for rel in diff.unchanged.iter().chain(retry_previous) {
        if let Some(hash) = previous.get(rel) {
            out_of_scope.insert(rel.clone(), hash.clone());
        }
    }
    out_of_scope.extend(promoted);
    out_of_scope
}

fn indexed_at_after_run(
    previous: Option<String>,
    completed_without_errors: bool,
    completed_at: String,
) -> Option<String> {
    if completed_without_errors {
        Some(completed_at)
    } else {
        previous
    }
}

pub async fn index_route(
    backend: &RetrievalBackend,
    paths: &RagPaths,
    body: &Value,
) -> Result<Value, String> {
    let repo_path = PathBuf::from(crate::required_string(body, "repo_path")?)
        .canonicalize()
        .map_err(|error| error.to_string())?;
    if !repo_path.is_dir() {
        return Err("repository path is not a directory".to_owned());
    }
    let repo_name = requested_repo_name(body);
    let full = body.get("full").and_then(Value::as_bool).unwrap_or(false);
    let languages: Option<Vec<String>> =
        body.get("languages")
            .and_then(Value::as_array)
            .map(|items| {
                items
                    .iter()
                    .filter_map(Value::as_str)
                    .map(str::to_ascii_lowercase)
                    .collect()
            });

    let settings = rag_config::load_settings(paths)
        .map_err(|error| format!("configuration error: {error}"))?;
    // Python parity: an explicit `collection` in the request wins; otherwise
    // a named repo maps to `repo_{name}`, else the default code collection.
    let explicit_collection = body
        .get("collection")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_owned);
    let collection = explicit_collection
        .clone()
        .or_else(|| repo_name.as_ref().map(|name| format!("repo_{name}")))
        .unwrap_or_else(|| settings.qdrant.code_collection.clone());

    // Acquire the repository lock before the scan. Besides serializing writes,
    // this prevents a second daemon from completing an index between our scan
    // and state load and making a newly indexed file look deleted.
    let _run_guard = IndexRunGuard::acquire(paths, &repo_path)?;

    // Discover + hash on a blocking thread (walks the repo, reads files).
    let scan_repo = repo_path.clone();
    let skip_dirs = settings.index.skip_dirs.clone();
    let max_file_bytes = settings.index.max_file_bytes;
    let language_filter = languages.clone();
    let (mut current_hashes, test_files, skipped_hashes, scan_errors) =
        tokio::task::spawn_blocking(move || -> Result<_, String> {
            let skip: Vec<&str> = skip_dirs.iter().map(String::as_str).collect();
            let files = rag_index::discover_files(&scan_repo, None, &skip)
                .map_err(|error| error.to_string())?;
            let mut hashes = BTreeMap::new();
            let mut skipped_hashes = std::collections::BTreeSet::new();
            let mut scan_errors = Vec::new();
            // Python `_discover_test_files`: stems of test_*.py / *_test.py,
            // used for the has_unit_test quality signal.
            let mut test_files: std::collections::BTreeSet<String> =
                std::collections::BTreeSet::new();
            for file in files {
                let Ok(rel) = file.strip_prefix(&scan_repo) else {
                    continue;
                };
                let rel = rel.to_string_lossy().replace('\\', "/");
                if let Some(stem) = std::path::Path::new(&rel)
                    .file_stem()
                    .and_then(|value| value.to_str())
                {
                    if rel.ends_with(".py")
                        && (stem.starts_with("test_") || stem.ends_with("_test"))
                    {
                        test_files.insert(stem.to_owned());
                    }
                }
                if let Some(filter) = &language_filter {
                    match detect_language(&rel) {
                        Some(language) if filter.iter().any(|item| item == language) => {}
                        _ => continue,
                    }
                }
                match rag_index::file_hash_bounded(&file, max_file_bytes) {
                    Ok(hash) => {
                        hashes.insert(rel, hash);
                    }
                    Err(error) => {
                        scan_errors.push(format!("scan {rel}: {error}"));
                        skipped_hashes.insert(rel);
                    }
                }
            }
            Ok((hashes, test_files, skipped_hashes, scan_errors))
        })
        .await
        .map_err(|error| error.to_string())??;
    let test_files = std::sync::Arc::new(test_files);

    let mut state_warnings = Vec::new();
    let stored_state = match IndexState::load(paths, &repo_path) {
        Ok(state) => state,
        Err(error) if full && languages.as_ref().is_none_or(Vec::is_empty) => {
            // An unscoped full rebuild resets every indexed point and can
            // safely recover from corrupt local state. Scoped or incremental
            // runs cannot know which stale entries to preserve/delete.
            state_warnings.push(format!(
                "replacing unreadable index state during full rebuild: {error}"
            ));
            IndexState::default()
        }
        Err(error) => return Err(format!("load index state: {error}")),
    };
    // A transient read failure or size-limit violation must not be interpreted
    // as deletion. Preserve the last successfully indexed hash so stale data
    // is visible and the file is retried on the next run.
    for rel in &skipped_hashes {
        if let Some(hash) = stored_state.file_hashes.get(rel) {
            current_hashes.insert(rel.clone(), hash.clone());
        }
    }
    if full && !scan_errors.is_empty() {
        return Err(format!(
            "full index aborted during file preflight: {}",
            scan_errors.join("; ")
        ));
    }
    // Language-scoped runs must leave other languages untouched: their files
    // are absent from `current_hashes`, so diffing against the FULL prior
    // state would classify every out-of-scope file as deleted and wipe its
    // chunks (Python re-scopes `removed` to the requested extensions).
    let in_scope = |rel: &str| match &languages {
        Some(filter) if !filter.is_empty() => {
            matches!(detect_language(rel), Some(language) if filter.iter().any(|item| item == language))
        }
        _ => true,
    };
    let mut previous_scoped: BTreeMap<String, String> = BTreeMap::new();
    let mut previous_out_of_scope: BTreeMap<String, String> = BTreeMap::new();
    for (rel, hash) in &stored_state.file_hashes {
        if in_scope(rel) {
            previous_scoped.insert(rel.clone(), hash.clone());
        } else {
            previous_out_of_scope.insert(rel.clone(), hash.clone());
        }
    }
    // `--full` reprocesses everything in scope; out-of-scope hashes survive.
    let previous_hashes: BTreeMap<String, String> = if full {
        BTreeMap::new()
    } else {
        previous_scoped
    };
    let diff = diff_index_state(
        &rag_index::IndexState {
            last_commit: stored_state.last_commit.clone(),
            file_hashes: previous_hashes.clone(),
        },
        &current_hashes,
    );

    // Python `--full` parity: reset previously indexed data before re-adding.
    // With a language filter only that language's chunks are cleared.
    if full {
        // Invalidate the in-scope state *before* the first destructive write.
        // If either Qdrant or SQLite reset succeeds and the other fails, the
        // next incremental run must rebuild instead of trusting stale hashes.
        save_state(
            paths,
            &repo_path,
            &IndexState {
                last_commit: stored_state.last_commit.clone(),
                file_hashes: previous_out_of_scope.clone(),
            },
        )
        .map_err(|error| format!("invalidate state before full reset: {error}"))?;
        match &languages {
            Some(filter) if !filter.is_empty() => {
                let qdrant_filter = QdrantFilter {
                    must: vec![FieldCondition::match_any(
                        "language".to_owned(),
                        filter
                            .iter()
                            .map(|language| PayloadValue::String(language.clone()))
                            .collect(),
                    )],
                };
                backend
                    .qdrant
                    .delete_by_filter(&collection, &qdrant_filter)
                    .await
                    .map_err(|error| format!("qdrant full reset failed: {error}"))?;
                reset_code_index(paths, &collection, Some(filter.clone())).await?;
            }
            _ => {
                backend
                    .qdrant
                    .drop_collection(&collection)
                    .await
                    .map_err(|error| format!("qdrant full reset failed: {error}"))?;
                reset_code_index(paths, &collection, None).await?;
            }
        }
    }

    ensure_collection(backend, &collection).await?;

    let mut files_to_process: Vec<String> = diff.added.clone();
    files_to_process.extend(diff.changed.iter().cloned());
    files_to_process.sort();

    let mut errors: Vec<String> = scan_errors;
    errors.extend(state_warnings);
    let mut chunks_indexed = 0usize;
    let mut files_processed = 0usize;
    let mut promoted_hashes: BTreeMap<String, String> = BTreeMap::new();
    let mut retry_previous: BTreeSet<String> = BTreeSet::new();

    // Deleted files: drop their chunks from Qdrant and the code index.
    for removed in &diff.deleted {
        if let Err(error) = delete_file_chunks(backend, paths, &collection, removed).await {
            errors.push(format!("delete {removed}: {error}"));
            retry_previous.insert(removed.clone());
        }
    }

    for group in files_to_process.chunks(FILES_PER_FLUSH) {
        // Chunk + enrich the group on a blocking thread.
        let group_paths: Vec<(String, PathBuf)> = group
            .iter()
            .map(|rel| (rel.clone(), repo_path.join(rel)))
            .collect();
        let target_collection = collection.clone();
        let max_chars = settings.index.max_chunk_chars as usize;
        let group_max_file_bytes = settings.index.max_file_bytes;
        let group_test_files = std::sync::Arc::clone(&test_files);
        let chunked = tokio::task::spawn_blocking(move || -> Vec<_> {
            group_paths
                .into_iter()
                .map(|(rel, absolute)| {
                    let outcome = process_file(
                        &target_collection,
                        &rel,
                        &absolute,
                        max_chars,
                        group_max_file_bytes,
                        &group_test_files,
                    );
                    (rel, outcome)
                })
                .collect()
        })
        .await
        .map_err(|error| error.to_string())?;

        let mut group_files: Vec<FileChunks> = Vec::new();
        for (rel, outcome) in chunked {
            match outcome {
                Ok(file) => group_files.push(file),
                Err(error) => {
                    errors.push(error);
                    if previous_hashes.contains_key(&rel) {
                        retry_previous.insert(rel);
                    }
                }
            }
        }
        if group_files.is_empty() {
            continue;
        }

        // Changed files must not leave stale chunks behind.
        let mut ready_files = Vec::with_capacity(group_files.len());
        for file in group_files {
            if previous_hashes.contains_key(&file.rel_path) {
                if let Err(error) =
                    delete_file_chunks(backend, paths, &collection, &file.rel_path).await
                {
                    errors.push(format!("stale-delete {}: {error}", file.rel_path));
                    retry_previous.insert(file.rel_path.clone());
                    continue;
                }
            }
            ready_files.push(file);
        }
        if ready_files.is_empty() {
            continue;
        }

        match flush_group(backend, paths, &collection, &ready_files).await {
            Ok(count) => {
                chunks_indexed += count;
                files_processed += ready_files.len();
                for file in &ready_files {
                    promoted_hashes.insert(file.rel_path.clone(), file.file_hash.clone());
                }
            }
            Err(error) => {
                // Python parity: a failed flush drops that batch's hashes so
                // the files re-process next run; the run itself continues.
                errors.push(format!(
                    "flush failed ({} files): {error}",
                    ready_files.len()
                ));
            }
        }
    }

    // New state: unchanged files keep prior hashes; processed files use fresh
    // hashes only when their flush succeeded; deleted files drop out.
    // Out-of-scope languages keep their prior hashes untouched.
    let new_hashes = assemble_file_hashes(
        previous_out_of_scope,
        &diff,
        &previous_hashes,
        &retry_previous,
        promoted_hashes,
    );
    let state = IndexState {
        last_commit: git_head(&repo_path).await.unwrap_or_default(),
        file_hashes: new_hashes,
    };
    if let Err(error) = save_state(paths, &repo_path, &state) {
        errors.push(format!("state save failed: {error}"));
    }

    let total_points = match backend.qdrant.count(&collection, None).await {
        Ok(count) => Some(count),
        Err(error) => {
            errors.push(format!("collection count failed: {error}"));
            None
        }
    };
    if let Some(name) = &repo_name {
        let completed_without_errors = errors.is_empty();
        let registry_result = RepoRegistry::open_writable(paths).and_then(|registry| {
            let previous = registry.get(name)?;
            let previous_count = previous.as_ref().map_or(0, |repo| repo.chunks_count);
            let chunks_count = total_points
                .and_then(|count| i64::try_from(count).ok())
                .unwrap_or(previous_count.max(i64::try_from(chunks_indexed).unwrap_or(i64::MAX)));
            registry.upsert(&RepoInfo {
                name: name.clone(),
                path: repo_path.to_string_lossy().into_owned(),
                collection: collection.clone(),
                last_indexed: indexed_at_after_run(
                    previous.and_then(|repo| repo.last_indexed),
                    completed_without_errors,
                    chrono::Utc::now().to_rfc3339(),
                ),
                chunks_count,
            })
        });
        if let Err(error) = registry_result {
            errors.push(format!("registry update failed: {error}"));
        }
    } else if explicit_collection.is_some() && total_points.is_some() {
        let completed_without_errors = errors.is_empty();
        // Python parity: an explicit collection that belongs to a registered
        // repo refreshes that repo's stats.
        let updated = RepoRegistry::open_writable(paths).and_then(|registry| {
            if let Some(mut repo) = registry
                .list_repos()?
                .into_iter()
                .find(|repo| repo.collection == collection)
            {
                repo.chunks_count =
                    i64::try_from(total_points.unwrap_or_default()).unwrap_or(i64::MAX);
                repo.last_indexed = indexed_at_after_run(
                    repo.last_indexed,
                    completed_without_errors,
                    chrono::Utc::now().to_rfc3339(),
                );
                registry.upsert(&repo)?;
            }
            Ok(())
        });
        if let Err(error) = updated {
            errors.push(format!("registry stats update failed: {error}"));
        }
    }

    Ok(json!({
        "files_processed": files_processed,
        "chunks_indexed": chunks_indexed,
        "files_skipped": diff.unchanged.len(),
        "files_deleted": diff.deleted.len(),
        "errors": errors,
    }))
}

/// Python `/vocab/build` parity: embed per-file summaries from a JSONL into
/// the repo's `<collection>_vocab` collection. Idempotent via deterministic
/// chunk ids (`repo:vocab:rel-path`).
pub async fn vocab_build_route(
    backend: &RetrievalBackend,
    paths: &RagPaths,
    body: &Value,
) -> Result<Value, String> {
    let started = std::time::Instant::now();
    let repo = crate::required_string(body, "repo")?.to_owned();
    let jsonl_path = crate::required_string(body, "jsonl_path")?.to_owned();
    let jsonl_path = if let Some(rest) = jsonl_path.strip_prefix("~/") {
        std::env::var_os("HOME")
            .map(|home| PathBuf::from(home).join(rest))
            .unwrap_or_else(|| PathBuf::from(&jsonl_path))
    } else {
        PathBuf::from(&jsonl_path)
    };
    let read_path = jsonl_path.clone();
    let raw = tokio::task::spawn_blocking(move || {
        let bytes = rag_index::read_file_bounded(&read_path, MAX_VOCAB_JSONL_BYTES)
            .map_err(|error| format!("cannot read JSONL {}: {error}", read_path.display()))?;
        String::from_utf8(bytes)
            .map_err(|error| format!("JSONL {} is not UTF-8: {error}", read_path.display()))
    })
    .await
    .map_err(|error| format!("JSONL reader task failed: {error}"))??;

    // Later records win on duplicate paths; empty/ERROR summaries drop.
    let mut merged: BTreeMap<String, String> = BTreeMap::new();
    for line in raw.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let Ok(record) = serde_json::from_str::<Value>(line) else {
            continue;
        };
        let Some(file) = record.get("file").and_then(Value::as_str) else {
            continue;
        };
        let summary = record
            .get("summary")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .trim()
            .to_owned();
        if file.is_empty() || summary.is_empty() || summary.starts_with("ERROR") {
            continue;
        }
        merged.insert(file.to_owned(), summary);
    }
    if merged.is_empty() {
        return Err("No valid summaries in JSONL".to_owned());
    }

    let registry = RepoRegistry::open(paths).map_err(|error| error.to_string())?;
    let code_collection = registry
        .get(&repo)
        .map_err(|error| error.to_string())?
        .ok_or_else(|| format!("unknown repo: {repo}"))?
        .collection;
    let collection = format!("{code_collection}_vocab");
    ensure_collection(backend, &collection).await?;

    let records: Vec<(String, String)> = merged.into_iter().collect();
    let mut upserted = 0usize;
    for batch in records.chunks(64) {
        let texts: Vec<String> = batch.iter().map(|(_, summary)| summary.clone()).collect();
        let hashes: Vec<String> = batch
            .iter()
            .map(|(rel, summary)| {
                use sha2::{Digest, Sha256};
                let mut hasher = Sha256::new();
                hasher.update(format!("{rel}:{summary}").as_bytes());
                format!("{:x}", hasher.finalize())
            })
            .collect();
        let vectors = embed_with_cache(backend, paths, &texts, &hashes).await?;
        let mut points = Vec::with_capacity(batch.len());
        for (((rel, summary), content_hash), dense) in batch.iter().zip(hashes.iter()).zip(vectors)
        {
            if dense.len() != backend.embed_dim {
                return Err(format!(
                    "embedding dim {} != expected {} for vocab {rel}",
                    dense.len(),
                    backend.embed_dim
                ));
            }
            let path = Path::new(rel);
            let stem = path
                .file_stem()
                .and_then(|value| value.to_str())
                .unwrap_or_default();
            let extension = path
                .extension()
                .and_then(|value| value.to_str())
                .unwrap_or_default();
            let mut payload: BTreeMap<String, PayloadValue> = BTreeMap::new();
            payload.insert("content".to_owned(), PayloadValue::String(summary.clone()));
            payload.insert("file_path".to_owned(), PayloadValue::String(rel.clone()));
            payload.insert("name".to_owned(), PayloadValue::String(stem.to_owned()));
            payload.insert("summary".to_owned(), PayloadValue::String(summary.clone()));
            payload.insert("repo".to_owned(), PayloadValue::String(repo.clone()));
            payload.insert(
                "language".to_owned(),
                PayloadValue::String(extension.to_owned()),
            );
            payload.insert(
                "chunk_type".to_owned(),
                PayloadValue::String("vocab_summary".to_owned()),
            );
            payload.insert(
                "content_hash".to_owned(),
                PayloadValue::String(content_hash.clone()),
            );
            let mut vector = BTreeMap::new();
            vector.insert("dense".to_owned(), dense);
            points.push(Point {
                id: point_id_for(&format!("{repo}:vocab:{rel}")),
                vector,
                payload,
            });
        }
        backend
            .qdrant
            .upsert(&collection, &points)
            .await
            .map_err(|error| format!("qdrant upsert failed: {error}"))?;
        upserted += points.len();
    }

    Ok(json!({
        "repo": repo,
        "collection": collection,
        "records": records.len(),
        "upserted": upserted,
        "latency_ms": started.elapsed().as_secs_f64() * 1000.0,
    }))
}

/// Embed texts through the shared `embed_cache.db`, writing fresh vectors back.
async fn embed_with_cache(
    backend: &RetrievalBackend,
    paths: &RagPaths,
    texts: &[String],
    content_hashes: &[String],
) -> Result<Vec<Vec<f32>>, String> {
    let model = backend.embedder_model.clone();
    let cache_paths = paths.clone();
    let lookup_hashes = content_hashes.to_vec();
    let cached: Vec<Option<Vec<f32>>> =
        tokio::task::spawn_blocking(move || match EmbedCache::open(&cache_paths, &model) {
            Ok(cache) => lookup_hashes.iter().map(|hash| cache.get(hash)).collect(),
            Err(_) => vec![None; lookup_hashes.len()],
        })
        .await
        .map_err(|error| error.to_string())?;

    let mut embeddings: Vec<Option<Vec<f32>>> = cached;
    let missing: Vec<usize> = embeddings
        .iter()
        .enumerate()
        .filter_map(|(index, slot)| slot.is_none().then_some(index))
        .collect();
    if !missing.is_empty() {
        let to_embed: Vec<String> = missing.iter().map(|&index| texts[index].clone()).collect();
        let fresh = backend
            .ollama
            .embed_documents(&to_embed)
            .await
            .map_err(|error| format!("embedding failed: {error}"))?;
        if fresh.len() != missing.len() {
            return Err("embedding count mismatch".to_owned());
        }
        let model = backend.embedder_model.clone();
        let cache_paths = paths.clone();
        let rows: Vec<(String, Vec<f32>)> = missing
            .iter()
            .zip(fresh.iter())
            .map(|(&index, vector)| (content_hashes[index].clone(), vector.clone()))
            .collect();
        tokio::task::spawn_blocking(move || {
            if let Ok(cache) = EmbedCache::open(&cache_paths, &model) {
                for (hash, vector) in &rows {
                    let _ = cache.put(hash, vector);
                }
            }
        })
        .await
        .map_err(|error| error.to_string())?;
        for (&index, vector) in missing.iter().zip(fresh) {
            embeddings[index] = Some(vector);
        }
    }
    Ok(embeddings
        .into_iter()
        .map(Option::unwrap_or_default)
        .collect())
}

fn process_file(
    collection: &str,
    rel_path: &str,
    absolute: &Path,
    max_chars: usize,
    max_file_bytes: u64,
    test_files: &std::collections::BTreeSet<String>,
) -> Result<FileChunks, String> {
    let raw = rag_index::read_file_bounded(absolute, max_file_bytes)
        .map_err(|error| format!("read {rel_path}: {error}"))?;
    // Hash the exact bytes being chunked. A file may change after discovery;
    // reusing the preflight hash would claim that different content was
    // indexed and could suppress the next incremental update.
    let file_hash = rag_index::source_hash(&raw);
    let content = String::from_utf8_lossy(&raw).into_owned();
    let Some(language) = detect_language(rel_path) else {
        return Ok(FileChunks {
            rel_path: rel_path.to_owned(),
            file_hash,
            documents: Vec::new(),
        });
    };
    let mut chunks = chunk_code(&content, rel_path, Some(language), max_chars);
    let mut documents = Vec::new();
    for chunk in &mut chunks {
        enrich_chunk_metadata(chunk, Some(test_files));
        let chunk_id = chunk.chunk_id();
        let content_hash = chunk.content_hash();
        let mut payload = Map::new();
        payload.insert("file_path".to_owned(), json!(chunk.file_path));
        payload.insert("language".to_owned(), json!(chunk.language));
        payload.insert(
            "chunk_type".to_owned(),
            json!(chunk.chunk_type.as_python_value()),
        );
        payload.insert("name".to_owned(), json!(chunk.name));
        payload.insert("parent_name".to_owned(), json!(chunk.parent_name));
        payload.insert("start_line".to_owned(), json!(chunk.start_line));
        payload.insert("end_line".to_owned(), json!(chunk.end_line));
        payload.insert("content_hash".to_owned(), json!(content_hash));
        for (key, value) in &chunk.metadata {
            payload.insert(key.clone(), value.clone());
        }
        documents.push(PendingDocument {
            chunk_id: chunk_id.clone(),
            content: chunk.content.clone(),
            content_hash,
            payload,
            code_document: CodeDocument {
                chunk_id,
                collection: collection.to_owned(),
                file_path: chunk.file_path.clone(),
                name: chunk.name.clone(),
                parent_name: chunk.parent_name.clone(),
                chunk_type: chunk.chunk_type.as_python_value().to_owned(),
                language: chunk.language.clone(),
                start_line: chunk.start_line,
                end_line: chunk.end_line,
                code: chunk.content.clone(),
            },
        });
    }
    Ok(FileChunks {
        rel_path: rel_path.to_owned(),
        file_hash,
        documents,
    })
}

async fn flush_group(
    backend: &RetrievalBackend,
    paths: &RagPaths,
    collection: &str,
    group: &[FileChunks],
) -> Result<usize, String> {
    let documents: Vec<&PendingDocument> = group
        .iter()
        .flat_map(|file| file.documents.iter())
        .collect();
    if documents.is_empty() {
        return Ok(0);
    }

    // Cache lookups (blocking SQLite) — collect hits and the miss list.
    let model = backend.embedder_model.clone();
    let cache_paths = paths.clone();
    let hashes: Vec<String> = documents
        .iter()
        .map(|doc| doc.content_hash.clone())
        .collect();
    let cached: Vec<Option<Vec<f32>>> =
        tokio::task::spawn_blocking(move || match EmbedCache::open(&cache_paths, &model) {
            Ok(cache) => hashes.iter().map(|hash| cache.get(hash)).collect(),
            Err(_) => vec![None; hashes.len()],
        })
        .await
        .map_err(|error| error.to_string())?;

    let mut embeddings: Vec<Option<Vec<f32>>> = cached;
    let missing: Vec<usize> = embeddings
        .iter()
        .enumerate()
        .filter_map(|(index, slot)| slot.is_none().then_some(index))
        .collect();
    if !missing.is_empty() {
        let texts: Vec<String> = missing
            .iter()
            .map(|&index| documents[index].content.clone())
            .collect();
        let fresh = backend
            .ollama
            .embed_documents(&texts)
            .await
            .map_err(|error| format!("embedding failed: {error}"))?;
        if fresh.len() != missing.len() {
            return Err("embedding count mismatch".to_owned());
        }
        // Write-through to the shared cache.
        let model = backend.embedder_model.clone();
        let cache_paths = paths.clone();
        let cache_rows: Vec<(String, Vec<f32>)> = missing
            .iter()
            .zip(fresh.iter())
            .map(|(&index, vector)| (documents[index].content_hash.clone(), vector.clone()))
            .collect();
        tokio::task::spawn_blocking(move || {
            if let Ok(cache) = EmbedCache::open(&cache_paths, &model) {
                for (hash, vector) in &cache_rows {
                    let _ = cache.put(hash, vector);
                }
            }
        })
        .await
        .map_err(|error| error.to_string())?;
        for (&index, vector) in missing.iter().zip(fresh) {
            embeddings[index] = Some(vector);
        }
    }

    let mut points = Vec::with_capacity(documents.len());
    for (document, embedding) in documents.iter().zip(embeddings) {
        let Some(dense) = embedding else {
            return Err(format!("missing embedding for chunk {}", document.chunk_id));
        };
        if dense.len() != backend.embed_dim {
            return Err(format!(
                "embedding dim {} != expected {} for chunk {}",
                dense.len(),
                backend.embed_dim,
                document.chunk_id
            ));
        }
        let mut payload: BTreeMap<String, PayloadValue> = BTreeMap::new();
        payload.insert(
            "content".to_owned(),
            json_to_payload(&Value::String(document.content.clone())),
        );
        for (key, value) in &document.payload {
            payload.insert(key.clone(), json_to_payload(value));
        }
        let mut vector = BTreeMap::new();
        vector.insert("dense".to_owned(), dense);
        points.push(Point {
            id: point_id_for(&document.chunk_id),
            vector,
            payload,
        });
    }

    backend
        .qdrant
        .upsert(collection, &points)
        .await
        .map_err(|error| format!("qdrant upsert failed: {error}"))?;

    // Mirror into the SQLite code index only after the vector write landed.
    let code_documents: Vec<CodeDocument> = group
        .iter()
        .flat_map(|file| file.documents.iter().map(|doc| doc.code_document.clone()))
        .collect();
    let db_path = paths.home.join("rag.db");
    let inserted = tokio::task::spawn_blocking(move || -> Result<usize, String> {
        let mut index = LexicalIndex::open(&db_path).map_err(|error| error.to_string())?;
        index.ensure_schema().map_err(|error| error.to_string())?;
        index
            .upsert_code_chunks(&code_documents)
            .map_err(|error| error.to_string())
    })
    .await
    .map_err(|error| error.to_string())??;

    Ok(inserted)
}

async fn reset_code_index(
    paths: &RagPaths,
    collection: &str,
    languages: Option<Vec<String>>,
) -> Result<(), String> {
    let db_path = paths.home.join("rag.db");
    let collection = collection.to_owned();
    tokio::task::spawn_blocking(move || -> Result<(), String> {
        let index = LexicalIndex::open(&db_path).map_err(|error| error.to_string())?;
        index.ensure_schema().map_err(|error| error.to_string())?;
        match languages {
            Some(filter) => {
                for language in filter {
                    index
                        .delete_code_chunks_by_language(&collection, &language)
                        .map_err(|error| error.to_string())?;
                }
            }
            None => index
                .delete_code_chunks_by_collection(&collection)
                .map_err(|error| error.to_string())?,
        }
        Ok(())
    })
    .await
    .map_err(|error| error.to_string())?
}

async fn delete_file_chunks(
    backend: &RetrievalBackend,
    paths: &RagPaths,
    collection: &str,
    rel_path: &str,
) -> Result<(), String> {
    // Delete the local mirror first. If it fails, leave Qdrant untouched and
    // keep the prior state hash so the entire operation retries. Both deletes
    // are idempotent, making a Qdrant failure after this point recoverable.
    let db_path = paths.home.join("rag.db");
    let local_collection = collection.to_owned();
    let rel = rel_path.to_owned();
    tokio::task::spawn_blocking(move || -> Result<(), String> {
        let index = LexicalIndex::open(&db_path).map_err(|error| error.to_string())?;
        index.ensure_schema().map_err(|error| error.to_string())?;
        index
            .delete_code_chunks_by_file(&local_collection, &rel)
            .map_err(|error| error.to_string())?;
        Ok(())
    })
    .await
    .map_err(|error| error.to_string())??;
    let filter = QdrantFilter {
        must: vec![FieldCondition::match_value(
            "file_path".to_owned(),
            PayloadValue::String(rel_path.to_owned()),
        )],
    };
    backend
        .qdrant
        .delete_by_filter(collection, &filter)
        .await
        .map_err(|error| error.to_string())?;
    Ok(())
}

async fn ensure_collection(backend: &RetrievalBackend, collection: &str) -> Result<(), String> {
    let existing = backend
        .qdrant
        .collections()
        .await
        .map_err(|error| error.to_string())?;
    if !existing.iter().any(|name| name == collection) {
        backend
            .qdrant
            .create_collection(
                collection,
                CollectionVectorConfig {
                    size: backend.embed_dim,
                    distance: Distance::Cosine,
                },
            )
            .await
            .map_err(|error| error.to_string())?;
    }
    for (field, schema) in PAYLOAD_INDEXES {
        // Existing indexes make this a no-op server-side; failures are benign
        // (Python logs and continues too).
        let _ = backend
            .qdrant
            .create_payload_index(collection, field, schema)
            .await;
    }
    Ok(())
}

/// Python parity: chunk ids that are not UUIDs become `uuid5(NAMESPACE_DNS, id)`.
fn point_id_for(chunk_id: &str) -> String {
    if Uuid::parse_str(chunk_id).is_ok() {
        chunk_id.to_owned()
    } else {
        Uuid::new_v5(&Uuid::NAMESPACE_DNS, chunk_id.as_bytes()).to_string()
    }
}

fn json_to_payload(value: &Value) -> PayloadValue {
    match value {
        Value::Null => PayloadValue::Null,
        Value::Bool(flag) => PayloadValue::Bool(*flag),
        Value::Number(number) => number
            .as_i64()
            .map(PayloadValue::Integer)
            .or_else(|| number.as_f64().map(PayloadValue::Float))
            .unwrap_or(PayloadValue::Null),
        Value::String(text) => PayloadValue::String(text.clone()),
        Value::Array(values) => PayloadValue::List(values.iter().map(json_to_payload).collect()),
        Value::Object(map) => PayloadValue::Object(
            map.iter()
                .map(|(key, value)| (key.clone(), json_to_payload(value)))
                .collect(),
        ),
    }
}

async fn git_head(repo_path: &Path) -> Option<String> {
    let mut command = tokio::process::Command::new("git");
    command
        .args(["-C", &repo_path.to_string_lossy(), "rev-parse", "HEAD"])
        .kill_on_drop(true);
    let output = tokio::time::timeout(std::time::Duration::from_secs(10), command.output())
        .await
        .ok()?
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let head = String::from_utf8_lossy(&output.stdout).trim().to_owned();
    (!head.is_empty()).then_some(head)
}

/// Atomic (tmp-then-rename) state write, matching Python `IndexState.save`.
fn save_state(paths: &RagPaths, repo_path: &Path, state: &IndexState) -> Result<(), String> {
    let state_file = rag_storage::state_file_for(paths, repo_path);
    if let Some(parent) = state_file.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let tmp = state_file.with_extension(format!("json.{}.tmp", Uuid::new_v4()));
    let body = serde_json::json!({
        "last_commit": state.last_commit,
        "file_hashes": state.file_hashes,
    });
    let encoded = serde_json::to_vec_pretty(&body).map_err(|error| error.to_string())?;
    let mut file = std::fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&tmp)
        .map_err(|error| error.to_string())?;
    file.write_all(&encoded)
        .map_err(|error| error.to_string())?;
    file.sync_all().map_err(|error| error.to_string())?;
    drop(file);
    if let Err(error) = std::fs::rename(&tmp, &state_file) {
        let _ = std::fs::remove_file(&tmp);
        return Err(error.to_string());
    }
    if let Some(parent) = state_file.parent() {
        std::fs::File::open(parent)
            .and_then(|directory| directory.sync_all())
            .map_err(|error| error.to_string())?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{
        assemble_file_hashes, index_route, indexed_at_after_run, point_id_for, process_file,
        requested_repo_name, save_state, BTreeMap, IndexRunGuard, IndexState, RetrievalBackend,
        MAX_VOCAB_JSONL_BYTES,
    };
    use rag_config::RagPaths;
    use rag_index::IndexDiff;
    use serde_json::json;

    #[test]
    fn uuid5_matches_python() {
        // python: uuid.uuid5(uuid.NAMESPACE_DNS, "abc") ==
        // "6cb8e707-0fc5-5f55-88d4-d4fed43e64a8"
        assert_eq!(point_id_for("abc"), "6cb8e707-0fc5-5f55-88d4-d4fed43e64a8");
    }

    #[test]
    fn valid_uuid_passes_through() {
        let id = "00027383-b1ee-54fa-b4f2-c4314ac6e043";
        assert_eq!(point_id_for(id), id);
    }

    #[test]
    fn canonical_cli_repo_name_is_registered_and_legacy_name_still_works() {
        assert_eq!(
            requested_repo_name(&json!({"repo_name": "sample", "name": "legacy"})).as_deref(),
            Some("sample")
        );
        assert_eq!(
            requested_repo_name(&json!({"name": "legacy"})).as_deref(),
            Some("legacy")
        );
    }

    #[test]
    fn repo_lock_fails_fast_for_a_second_index_run() {
        let temp = tempfile::tempdir().unwrap();
        let repo = temp.path().join("repo");
        std::fs::create_dir(&repo).unwrap();
        let paths = RagPaths::from_home(temp.path().join("rag-home"));

        let first = IndexRunGuard::acquire(&paths, &repo).unwrap();
        let error = IndexRunGuard::acquire(&paths, &repo).expect_err("second lock");
        assert!(error.contains("already in progress"));
        drop(first);
        IndexRunGuard::acquire(&paths, &repo).expect("lock released");
    }

    #[test]
    fn failed_deletes_retain_the_previous_hash_for_the_next_retry() {
        let previous = std::collections::BTreeMap::from([
            ("changed.rs".to_owned(), "old-changed".to_owned()),
            ("deleted.rs".to_owned(), "old-deleted".to_owned()),
            ("removed-ok.rs".to_owned(), "old-removed".to_owned()),
            ("same.rs".to_owned(), "same".to_owned()),
        ]);
        let diff = IndexDiff {
            changed: vec!["changed.rs".to_owned()],
            deleted: vec!["deleted.rs".to_owned(), "removed-ok.rs".to_owned()],
            unchanged: vec!["same.rs".to_owned()],
            ..IndexDiff::default()
        };
        let retry =
            std::collections::BTreeSet::from(["changed.rs".to_owned(), "deleted.rs".to_owned()]);

        let next = assemble_file_hashes(
            std::collections::BTreeMap::new(),
            &diff,
            &previous,
            &retry,
            std::collections::BTreeMap::new(),
        );

        assert_eq!(
            next.get("changed.rs").map(String::as_str),
            Some("old-changed")
        );
        assert_eq!(
            next.get("deleted.rs").map(String::as_str),
            Some("old-deleted")
        );
        assert_eq!(next.get("same.rs").map(String::as_str), Some("same"));
        assert!(!next.contains_key("removed-ok.rs"));
    }

    #[test]
    fn partial_runs_do_not_claim_a_new_freshness_timestamp() {
        assert_eq!(
            indexed_at_after_run(
                Some("2026-01-01T00:00:00Z".to_owned()),
                false,
                "2026-07-18T00:00:00Z".to_owned(),
            )
            .as_deref(),
            Some("2026-01-01T00:00:00Z")
        );
        assert_eq!(
            indexed_at_after_run(None, false, "2026-07-18T00:00:00Z".to_owned()),
            None
        );
        assert_eq!(
            indexed_at_after_run(None, true, "2026-07-18T00:00:00Z".to_owned()).as_deref(),
            Some("2026-07-18T00:00:00Z")
        );
    }

    #[test]
    fn processed_hash_matches_the_exact_bytes_that_were_chunked() {
        let temp = tempfile::tempdir().unwrap();
        let source = temp.path().join("changing.rs");
        std::fs::write(&source, "fn before() {}\n").unwrap();
        let preflight = rag_index::file_hash(&source).unwrap();
        std::fs::write(&source, "fn after() {}\n").unwrap();

        let processed = process_file(
            "code_chunks",
            "changing.rs",
            &source,
            8_000,
            1024 * 1024,
            &std::collections::BTreeSet::new(),
        )
        .unwrap();

        assert_ne!(processed.file_hash, preflight);
        assert_eq!(processed.file_hash, rag_index::file_hash(&source).unwrap());
    }

    #[tokio::test]
    async fn full_reset_failure_leaves_state_invalidated_for_safe_retry() {
        use axum::{http::StatusCode, routing::delete, Router};

        let temp = tempfile::tempdir().unwrap();
        let repo = temp.path().join("repo");
        std::fs::create_dir(&repo).unwrap();
        std::fs::write(repo.join("lib.rs"), "fn current() {}\n").unwrap();
        let paths = RagPaths::from_home(temp.path().join("rag-home"));
        std::fs::create_dir_all(&paths.home).unwrap();

        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let mock = tokio::spawn(async move {
            axum::serve(
                listener,
                Router::new().route(
                    "/collections/{collection}",
                    delete(|| async { (StatusCode::INTERNAL_SERVER_ERROR, "reset failed") }),
                ),
            )
            .await
            .unwrap();
        });
        std::fs::write(
            &paths.config_path,
            format!("[qdrant]\nurl = \"http://{address}\"\n"),
        )
        .unwrap();
        save_state(
            &paths,
            &repo,
            &IndexState {
                last_commit: "old".to_owned(),
                file_hashes: BTreeMap::from([("lib.rs".to_owned(), "old-hash".to_owned())]),
            },
        )
        .unwrap();
        let settings = rag_config::load_settings(&paths).unwrap();
        let backend = RetrievalBackend::from_settings(&settings).unwrap();

        let error = index_route(
            &backend,
            &paths,
            &json!({"repo_path": repo.to_string_lossy(), "full": true}),
        )
        .await
        .expect_err("failed destructive reset must abort");
        assert!(error.contains("qdrant full reset failed"));
        assert!(IndexState::load(&paths, &repo)
            .unwrap()
            .file_hashes
            .is_empty());
        mock.abort();
    }

    #[tokio::test]
    async fn incremental_index_refuses_to_mask_corrupt_state() {
        let temp = tempfile::tempdir().unwrap();
        let repo = temp.path().join("repo");
        std::fs::create_dir(&repo).unwrap();
        std::fs::write(repo.join("lib.rs"), "fn current() {}\n").unwrap();
        let paths = RagPaths::from_home(temp.path().join("rag-home"));
        let state_path = rag_storage::state_file_for(&paths, &repo);
        std::fs::create_dir_all(state_path.parent().unwrap()).unwrap();
        std::fs::write(&state_path, "{not valid json").unwrap();
        let backend = RetrievalBackend::from_settings(&rag_config::Settings::default()).unwrap();

        let error = index_route(
            &backend,
            &paths,
            &json!({"repo_path": repo.to_string_lossy()}),
        )
        .await
        .expect_err("incremental indexing cannot safely infer deletions");

        assert!(error.contains("load index state"));
        assert_eq!(
            std::fs::read_to_string(state_path).unwrap(),
            "{not valid json"
        );
    }

    #[test]
    fn vocab_input_has_a_hard_file_size_limit() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("oversized.jsonl");
        let file = std::fs::File::create(&path).unwrap();
        file.set_len(MAX_VOCAB_JSONL_BYTES + 1).unwrap();

        let error = rag_index::read_file_bounded(&path, MAX_VOCAB_JSONL_BYTES)
            .expect_err("oversized vocab input must not be buffered");

        assert!(error.to_string().contains("larger than"));
    }
}
