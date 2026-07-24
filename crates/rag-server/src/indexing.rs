//! Live indexing write path: port of Python `core/indexer.py` for the Rust
//! daemon. Incremental by git-state + per-file hash, embeds through Ollama
//! with the shared `embed_cache.db`, upserts to Qdrant with deterministic
//! UUIDv5 point ids, and mirrors chunks into the SQLite code index.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

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

/// In-process per-repo run lock (Python parity: non-blocking flock that fails
/// fast with "another index run holds the lock").
static ACTIVE_INDEX_RUNS: std::sync::OnceLock<
    std::sync::Mutex<std::collections::BTreeSet<PathBuf>>,
> = std::sync::OnceLock::new();

struct IndexRunGuard(PathBuf);

impl IndexRunGuard {
    fn acquire(repo_path: &Path) -> Result<Self, String> {
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
        Ok(Self(repo_path.to_path_buf()))
    }
}

impl Drop for IndexRunGuard {
    fn drop(&mut self) {
        if let Some(lock) = ACTIVE_INDEX_RUNS.get() {
            if let Ok(mut active) = lock.lock() {
                active.remove(&self.0);
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
    let repo_name = body
        .get("name")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|name| !name.is_empty())
        .map(str::to_owned);
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

    let settings = rag_config::load_settings(paths).unwrap_or_default();
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

    // Discover + hash on a blocking thread (walks the repo, reads files).
    let scan_repo = repo_path.clone();
    let skip_dirs = settings.index.skip_dirs.clone();
    let language_filter = languages.clone();
    let (current_hashes, test_files) = tokio::task::spawn_blocking(move || -> Result<_, String> {
        let skip: Vec<&str> = skip_dirs.iter().map(String::as_str).collect();
        let files = rag_index::discover_files(&scan_repo, None, &skip)
            .map_err(|error| error.to_string())?;
        let mut hashes = BTreeMap::new();
        // Python `_discover_test_files`: stems of test_*.py / *_test.py,
        // used for the has_unit_test quality signal.
        let mut test_files: std::collections::BTreeSet<String> = std::collections::BTreeSet::new();
        for file in files {
            let Ok(rel) = file.strip_prefix(&scan_repo) else {
                continue;
            };
            let rel = rel.to_string_lossy().replace('\\', "/");
            if let Some(stem) = std::path::Path::new(&rel)
                .file_stem()
                .and_then(|value| value.to_str())
            {
                if rel.ends_with(".py") && (stem.starts_with("test_") || stem.ends_with("_test")) {
                    test_files.insert(stem.to_owned());
                }
            }
            if let Some(filter) = &language_filter {
                match detect_language(&rel) {
                    Some(language) if filter.iter().any(|item| item == language) => {}
                    _ => continue,
                }
            }
            if let Ok(hash) = rag_index::file_hash(&file) {
                hashes.insert(rel, hash);
            }
        }
        Ok((hashes, test_files))
    })
    .await
    .map_err(|error| error.to_string())??;
    let test_files = std::sync::Arc::new(test_files);

    // Serialize runs per repository (Python uses a non-blocking flock and
    // fails fast; concurrent runs would race state.json, Qdrant and SQLite).
    let _run_guard = IndexRunGuard::acquire(&repo_path)?;

    let stored_state = IndexState::load(paths, &repo_path).unwrap_or_default();
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
                let _ = backend
                    .qdrant
                    .delete_by_filter(&collection, &qdrant_filter)
                    .await;
                reset_code_index(paths, &collection, Some(filter.clone())).await?;
            }
            _ => {
                let _ = backend.qdrant.drop_collection(&collection).await;
                reset_code_index(paths, &collection, None).await?;
            }
        }
    }

    ensure_collection(backend, &collection).await?;

    let mut files_to_process: Vec<String> = diff.added.clone();
    files_to_process.extend(diff.changed.iter().cloned());
    files_to_process.sort();

    let mut errors: Vec<String> = Vec::new();
    let mut chunks_indexed = 0usize;
    let mut files_processed = 0usize;
    let mut promoted_hashes: BTreeMap<String, String> = BTreeMap::new();

    // Deleted files: drop their chunks from Qdrant and the code index.
    for removed in &diff.deleted {
        if let Err(error) = delete_file_chunks(backend, paths, &collection, removed).await {
            errors.push(format!("delete {removed}: {error}"));
        }
    }

    for group in files_to_process.chunks(FILES_PER_FLUSH) {
        // Chunk + enrich the group on a blocking thread.
        let group_paths: Vec<(String, PathBuf)> = group
            .iter()
            .map(|rel| (rel.clone(), repo_path.join(rel)))
            .collect();
        let group_hashes: BTreeMap<String, String> = group
            .iter()
            .filter_map(|rel| {
                current_hashes
                    .get(rel)
                    .map(|hash| (rel.clone(), hash.clone()))
            })
            .collect();
        let target_collection = collection.clone();
        let max_chars = settings.index.max_chunk_chars as usize;
        let group_test_files = std::sync::Arc::clone(&test_files);
        let chunked = tokio::task::spawn_blocking(move || -> Vec<Result<FileChunks, String>> {
            group_paths
                .into_iter()
                .map(|(rel, absolute)| {
                    process_file(
                        &target_collection,
                        &rel,
                        &absolute,
                        group_hashes.get(&rel),
                        max_chars,
                        &group_test_files,
                    )
                })
                .collect()
        })
        .await
        .map_err(|error| error.to_string())?;

        let mut group_files: Vec<FileChunks> = Vec::new();
        for outcome in chunked {
            match outcome {
                Ok(file) => group_files.push(file),
                Err(error) => errors.push(error),
            }
        }
        if group_files.is_empty() {
            continue;
        }

        // Changed files must not leave stale chunks behind.
        for file in &group_files {
            if previous_hashes.contains_key(&file.rel_path) {
                if let Err(error) =
                    delete_file_chunks(backend, paths, &collection, &file.rel_path).await
                {
                    errors.push(format!("stale-delete {}: {error}", file.rel_path));
                }
            }
        }

        match flush_group(backend, paths, &collection, &group_files).await {
            Ok(count) => {
                chunks_indexed += count;
                files_processed += group_files.len();
                for file in &group_files {
                    promoted_hashes.insert(file.rel_path.clone(), file.file_hash.clone());
                }
            }
            Err(error) => {
                // Python parity: a failed flush drops that batch's hashes so
                // the files re-process next run; the run itself continues.
                errors.push(format!(
                    "flush failed ({} files): {error}",
                    group_files.len()
                ));
            }
        }
    }

    // New state: unchanged files keep prior hashes; processed files use fresh
    // hashes only when their flush succeeded; deleted files drop out.
    // Out-of-scope languages keep their prior hashes untouched.
    let mut new_hashes: BTreeMap<String, String> = previous_out_of_scope;
    for rel in &diff.unchanged {
        if let Some(hash) = previous_hashes.get(rel) {
            new_hashes.insert(rel.clone(), hash.clone());
        }
    }
    new_hashes.extend(promoted_hashes);
    let state = IndexState {
        last_commit: git_head(&repo_path).unwrap_or_default(),
        file_hashes: new_hashes,
    };
    if let Err(error) = save_state(paths, &repo_path, &state) {
        errors.push(format!("state save failed: {error}"));
    }

    let total_points = backend.qdrant.count(&collection, None).await.unwrap_or(0);
    if let Some(name) = &repo_name {
        let registry_result = RepoRegistry::open_writable(paths).and_then(|registry| {
            registry.upsert(&RepoInfo {
                name: name.clone(),
                path: repo_path.to_string_lossy().into_owned(),
                collection: collection.clone(),
                last_indexed: Some(chrono::Utc::now().to_rfc3339()),
                chunks_count: total_points as i64,
            })
        });
        if let Err(error) = registry_result {
            errors.push(format!("registry update failed: {error}"));
        }
    } else if explicit_collection.is_some() {
        // Python parity: an explicit collection that belongs to a registered
        // repo refreshes that repo's stats.
        let updated = RepoRegistry::open_writable(paths).and_then(|registry| {
            if let Some(mut repo) = registry
                .list_repos()?
                .into_iter()
                .find(|repo| repo.collection == collection)
            {
                repo.chunks_count = total_points as i64;
                repo.last_indexed = Some(chrono::Utc::now().to_rfc3339());
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
    let raw = std::fs::read_to_string(&jsonl_path)
        .map_err(|error| format!("JSONL not found: {} ({error})", jsonl_path.display()))?;

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
    known_hash: Option<&String>,
    max_chars: usize,
    test_files: &std::collections::BTreeSet<String>,
) -> Result<FileChunks, String> {
    let raw = std::fs::read(absolute).map_err(|error| format!("read {rel_path}: {error}"))?;
    let file_hash = match known_hash {
        Some(hash) => hash.clone(),
        None => rag_index::file_hash(absolute).map_err(|error| error.to_string())?,
    };
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
    let db_path = paths.home.join("rag.db");
    let collection = collection.to_owned();
    let rel = rel_path.to_owned();
    tokio::task::spawn_blocking(move || -> Result<(), String> {
        let index = LexicalIndex::open(&db_path).map_err(|error| error.to_string())?;
        index.ensure_schema().map_err(|error| error.to_string())?;
        index
            .delete_code_chunks_by_file(&collection, &rel)
            .map_err(|error| error.to_string())?;
        Ok(())
    })
    .await
    .map_err(|error| error.to_string())??;
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

fn git_head(repo_path: &Path) -> Option<String> {
    let output = std::process::Command::new("git")
        .args(["-C", &repo_path.to_string_lossy(), "rev-parse", "HEAD"])
        .output()
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
    let tmp = state_file.with_extension("json.tmp");
    let body = serde_json::json!({
        "last_commit": state.last_commit,
        "file_hashes": state.file_hashes,
    });
    std::fs::write(
        &tmp,
        serde_json::to_string_pretty(&body).unwrap_or_default(),
    )
    .map_err(|error| error.to_string())?;
    std::fs::rename(&tmp, &state_file).map_err(|error| error.to_string())?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::point_id_for;

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
}
