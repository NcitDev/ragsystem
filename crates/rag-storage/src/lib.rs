//! Read-only durable storage compatibility for Phase R1.

use std::collections::{BTreeMap, VecDeque};
use std::fs;
use std::path::{Path, PathBuf};

use rag_config::RagPaths;
use rusqlite::{Connection, OpenFlags, Row};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use thiserror::Error;

/// Highest SQLite schema version supported by this R1 reader.
///
/// Python currently leaves `PRAGMA user_version` at `0`. Any higher value means
/// a future writer may have changed semantics, so this reader refuses startup.
pub const SUPPORTED_SCHEMA_VERSION: i32 = 0;

/// Storage-layer failures.
#[derive(Debug, Error)]
pub enum StorageError {
    /// Filesystem failure.
    #[error("{context}: {source}")]
    Io {
        /// Operation context.
        context: &'static str,
        /// Source error.
        source: std::io::Error,
    },
    /// JSON failure.
    #[error("failed to parse JSON from {path}: {source}")]
    Json {
        /// File path.
        path: PathBuf,
        /// Source error.
        source: serde_json::Error,
    },
    /// SQLite failure.
    #[error("sqlite error at {path}: {source}")]
    Sqlite {
        /// Database path.
        path: PathBuf,
        /// Source error.
        source: rusqlite::Error,
    },
    /// Refused newer schema.
    #[error("sqlite schema version {found} is newer than supported version {supported}")]
    UnsupportedSchemaVersion {
        /// Found `PRAGMA user_version`.
        found: i32,
        /// Supported max version.
        supported: i32,
    },
}

/// Repository row from Python `repos.db`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RepoInfo {
    /// User-visible repository name.
    pub name: String,
    /// Absolute repository path recorded by Python.
    pub path: String,
    /// Qdrant collection name.
    pub collection: String,
    /// Last indexed timestamp, if any.
    pub last_indexed: Option<String>,
    /// Indexed chunk count.
    pub chunks_count: i64,
}

/// Read-only repository registry.
pub struct RepoRegistry {
    db_path: PathBuf,
    conn: Connection,
}

impl RepoRegistry {
    /// Open `~/.rag/repos.db` read-only.
    pub fn open(paths: &RagPaths) -> Result<Self, StorageError> {
        Self::open_path(paths.home.join("repos.db"))
    }

    /// Open an explicit registry DB read-only.
    pub fn open_path(db_path: impl Into<PathBuf>) -> Result<Self, StorageError> {
        let db_path = db_path.into();
        let conn = Connection::open_with_flags(&db_path, OpenFlags::SQLITE_OPEN_READ_ONLY)
            .map_err(|source| StorageError::Sqlite {
                path: db_path.clone(),
                source,
            })?;
        Ok(Self { db_path, conn })
    }

    /// Open or create the registry for Rust-owned stateful commands.
    pub fn open_writable(paths: &RagPaths) -> Result<Self, StorageError> {
        let db_path = paths.home.join("repos.db");
        let conn = Connection::open(&db_path).map_err(|source| StorageError::Sqlite {
            path: db_path.clone(),
            source,
        })?;
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS repos (
                name TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                collection TEXT NOT NULL,
                last_indexed TEXT,
                chunks_count INTEGER DEFAULT 0
            );",
        )
        .map_err(|source| StorageError::Sqlite {
            path: db_path.clone(),
            source,
        })?;
        Ok(Self { db_path, conn })
    }

    /// Insert or update a repository using the Python registry schema.
    pub fn upsert(&self, repo: &RepoInfo) -> Result<(), StorageError> {
        self.conn
            .execute(
                "INSERT INTO repos (name, path, collection, last_indexed, chunks_count)
                 VALUES (?, ?, ?, ?, ?)
                 ON CONFLICT(name) DO UPDATE SET path=excluded.path, collection=excluded.collection,
                 last_indexed=excluded.last_indexed, chunks_count=excluded.chunks_count",
                rusqlite::params![
                    repo.name,
                    repo.path,
                    repo.collection,
                    repo.last_indexed,
                    repo.chunks_count
                ],
            )
            .map_err(|source| StorageError::Sqlite {
                path: self.db_path.clone(),
                source,
            })?;
        Ok(())
    }

    /// List repos ordered by name, matching Python `RepoManager.list_repos`.
    pub fn list_repos(&self) -> Result<Vec<RepoInfo>, StorageError> {
        let mut stmt = self
            .conn
            .prepare(
                "SELECT name, path, collection, last_indexed, chunks_count FROM repos ORDER BY name",
            )
            .map_err(|source| StorageError::Sqlite {
                path: self.db_path.clone(),
                source,
            })?;
        let rows =
            stmt.query_map([], repo_info_from_row)
                .map_err(|source| StorageError::Sqlite {
                    path: self.db_path.clone(),
                    source,
                })?;
        collect_rows(rows, &self.db_path)
    }

    /// Get a repo by name.
    pub fn get(&self, name: &str) -> Result<Option<RepoInfo>, StorageError> {
        let mut stmt = self
            .conn
            .prepare(
                "SELECT name, path, collection, last_indexed, chunks_count FROM repos WHERE name = ?",
            )
            .map_err(|source| StorageError::Sqlite {
                path: self.db_path.clone(),
                source,
            })?;
        match stmt.query_row([name], repo_info_from_row) {
            Ok(repo) => Ok(Some(repo)),
            Err(rusqlite::Error::QueryReturnedNoRows) => Ok(None),
            Err(source) => Err(StorageError::Sqlite {
                path: self.db_path.clone(),
                source,
            }),
        }
    }
}

fn repo_info_from_row(row: &Row<'_>) -> rusqlite::Result<RepoInfo> {
    Ok(RepoInfo {
        name: row.get(0)?,
        path: row.get(1)?,
        collection: row.get(2)?,
        last_indexed: row.get(3)?,
        chunks_count: row.get(4)?,
    })
}

/// Python repository index state from `~/.rag/repos/<digest>/state.json`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(default)]
pub struct IndexState {
    /// Last indexed Git commit.
    pub last_commit: String,
    /// Relative path to 16-char content hash.
    pub file_hashes: BTreeMap<String, String>,
}

impl IndexState {
    /// Load read-only state for a repository path.
    pub fn load(paths: &RagPaths, repo_path: &Path) -> Result<Self, StorageError> {
        let state_path = state_file_for(paths, repo_path);
        if !state_path.exists() {
            return Ok(Self::default());
        }
        let text = fs::read_to_string(&state_path).map_err(|source| StorageError::Io {
            context: "read index state",
            source,
        })?;
        serde_json::from_str(&text).map_err(|source| StorageError::Json {
            path: state_path,
            source,
        })
    }
}

/// State directory for a repository path, matching Python's
/// `sha256(abs_path)[:16]` layout.
#[must_use]
pub fn state_dir_for(paths: &RagPaths, repo_path: &Path) -> PathBuf {
    let abs = repo_path
        .canonicalize()
        .unwrap_or_else(|_| repo_path.to_path_buf());
    let mut hasher = Sha256::new();
    hasher.update(abs.to_string_lossy().as_bytes());
    let digest = format!("{:x}", hasher.finalize());
    paths.home.join("repos").join(&digest[..16])
}

/// State file path for a repository path.
#[must_use]
pub fn state_file_for(paths: &RagPaths, repo_path: &Path) -> PathBuf {
    state_dir_for(paths, repo_path).join("state.json")
}

/// Read-only access to Python `rag.db`.
pub struct RagDatabase {
    db_path: PathBuf,
    conn: Connection,
}

impl RagDatabase {
    /// Open `~/.rag/rag.db` read-only and refuse newer schemas.
    pub fn open(paths: &RagPaths) -> Result<Self, StorageError> {
        Self::open_path(paths.home.join("rag.db"))
    }

    /// Open an explicit DB path read-only and refuse newer schemas.
    pub fn open_path(db_path: impl Into<PathBuf>) -> Result<Self, StorageError> {
        let db_path = db_path.into();
        let conn = Connection::open_with_flags(&db_path, OpenFlags::SQLITE_OPEN_READ_ONLY)
            .map_err(|source| StorageError::Sqlite {
                path: db_path.clone(),
                source,
            })?;
        let version: i32 = conn
            .query_row("PRAGMA user_version", [], |row| row.get(0))
            .map_err(|source| StorageError::Sqlite {
                path: db_path.clone(),
                source,
            })?;
        if version > SUPPORTED_SCHEMA_VERSION {
            return Err(StorageError::UnsupportedSchemaVersion {
                found: version,
                supported: SUPPORTED_SCHEMA_VERSION,
            });
        }
        Ok(Self { db_path, conn })
    }

    /// Return SQLite user version.
    pub fn user_version(&self) -> Result<i32, StorageError> {
        self.conn
            .query_row("PRAGMA user_version", [], |row| row.get(0))
            .map_err(|source| StorageError::Sqlite {
                path: self.db_path.clone(),
                source,
            })
    }

    /// List table names in deterministic order.
    pub fn table_names(&self) -> Result<Vec<String>, StorageError> {
        let mut stmt = self
            .conn
            .prepare("SELECT name FROM sqlite_master WHERE type IN ('table', 'view') ORDER BY name")
            .map_err(|source| StorageError::Sqlite {
                path: self.db_path.clone(),
                source,
            })?;
        let rows = stmt
            .query_map([], |row| row.get::<_, String>(0))
            .map_err(|source| StorageError::Sqlite {
                path: self.db_path.clone(),
                source,
            })?;
        collect_rows(rows, &self.db_path)
    }

    /// Read Python query log rows newest-first.
    pub fn recent_queries(&self, limit: u32) -> Result<Vec<QueryLogRow>, StorageError> {
        let mut stmt = self
            .conn
            .prepare(
                "SELECT timestamp, query, results_count, latency_ms FROM query_log ORDER BY id DESC LIMIT ?",
            )
            .map_err(|source| StorageError::Sqlite {
                path: self.db_path.clone(),
                source,
            })?;
        let rows = stmt
            .query_map([limit], |row| {
                Ok(QueryLogRow {
                    timestamp: row.get(0)?,
                    query: row.get(1)?,
                    results_count: row.get(2)?,
                    latency_ms: row.get(3)?,
                })
            })
            .map_err(|source| StorageError::Sqlite {
                path: self.db_path.clone(),
                source,
            })?;
        collect_rows(rows, &self.db_path)
    }

    /// Read code-index chunks for a collection in path order.
    pub fn code_chunks(
        &self,
        collection: &str,
        limit: u32,
    ) -> Result<Vec<CodeChunk>, StorageError> {
        let mut stmt = self
            .conn
            .prepare(
                "SELECT chunk_id, collection, file_path, name, parent_name, chunk_type, language, \
                 start_line, end_line, code, token_estimate, updated_at \
                 FROM code_index WHERE collection = ? ORDER BY file_path, start_line LIMIT ?",
            )
            .map_err(|source| StorageError::Sqlite {
                path: self.db_path.clone(),
                source,
            })?;
        let rows = stmt
            .query_map((collection, limit), code_chunk_from_row)
            .map_err(|source| StorageError::Sqlite {
                path: self.db_path.clone(),
                source,
            })?;
        collect_rows(rows, &self.db_path)
    }

    /// True if any indexed chunk in the collection has exactly this symbol
    /// name (Python `_symbol_exists`, served from the SQLite mirror).
    pub fn symbol_named(&self, collection: &str, name: &str) -> bool {
        self.conn
            .query_row(
                "SELECT 1 FROM code_index WHERE collection = ? AND name = ? LIMIT 1",
                rusqlite::params![collection, name],
                |_| Ok(()),
            )
            .is_ok()
    }

    /// Port of Python `storage.db.search_code_chunks`: symbol-aware lexical
    /// retrieval over the SQLite code index (FTS candidates + LIKE fallback,
    /// ranked by `_score_code_row`). Returns raw unbounded scores.
    pub fn search_code_chunks(
        &self,
        query: &str,
        collection: Option<&str>,
        limit: usize,
        filters: Option<&serde_json::Map<String, serde_json::Value>>,
    ) -> Result<Vec<LexicalHit>, StorageError> {
        let terms = query_terms(query);
        if terms.is_empty() {
            return Ok(Vec::new());
        }
        let candidate_cap = (limit * 8).max(50);
        let mut candidates: std::collections::BTreeMap<String, CodeChunk> =
            std::collections::BTreeMap::new();

        // FTS candidates. Python swallows FTS errors and continues with LIKE.
        let _ = self.fts_candidates(&terms, collection, filters, candidate_cap, &mut candidates);
        self.like_candidates(&terms, collection, filters, candidate_cap, &mut candidates)?;

        let mut ranked: Vec<LexicalHit> = candidates
            .into_values()
            .map(|chunk| LexicalHit {
                score: score_code_row(&chunk, &terms),
                chunk,
            })
            .collect();
        ranked.sort_by(|left, right| {
            right
                .score
                .total_cmp(&left.score)
                .then_with(|| left.chunk.chunk_id.cmp(&right.chunk.chunk_id))
        });
        ranked.truncate(limit);
        Ok(ranked)
    }

    fn fts_candidates(
        &self,
        terms: &[String],
        collection: Option<&str>,
        filters: Option<&serde_json::Map<String, serde_json::Value>>,
        cap: usize,
        candidates: &mut std::collections::BTreeMap<String, CodeChunk>,
    ) -> Result<(), StorageError> {
        let mut params: Vec<SqlValue> = vec![SqlValue::Text(fts_match_expression(terms))];
        let mut clause = String::new();
        if let Some(collection) = collection {
            clause.push_str(" AND collection = ?");
            params.push(SqlValue::Text(collection.to_owned()));
        }
        clause.push_str(&filter_clause(filters, &mut params));
        params.push(SqlValue::Integer(cap as i64));
        let sql = format!(
            "SELECT chunk_id FROM code_index_fts WHERE code_index_fts MATCH ?{clause} LIMIT ?"
        );
        let ids: Vec<String> = {
            let mut stmt = self
                .conn
                .prepare(&sql)
                .map_err(|source| StorageError::Sqlite {
                    path: self.db_path.clone(),
                    source,
                })?;
            let rows = stmt
                .query_map(rusqlite::params_from_iter(params), |row| {
                    row.get::<_, String>(0)
                })
                .map_err(|source| StorageError::Sqlite {
                    path: self.db_path.clone(),
                    source,
                })?;
            collect_rows(rows, &self.db_path)?
        };
        if ids.is_empty() {
            return Ok(());
        }
        let placeholders = ids.iter().map(|_| "?").collect::<Vec<_>>().join(",");
        let sql = format!(
            "SELECT chunk_id, collection, file_path, name, parent_name, chunk_type, language, \
             start_line, end_line, code, token_estimate, updated_at \
             FROM code_index WHERE chunk_id IN ({placeholders})"
        );
        let mut stmt = self
            .conn
            .prepare(&sql)
            .map_err(|source| StorageError::Sqlite {
                path: self.db_path.clone(),
                source,
            })?;
        let rows = stmt
            .query_map(rusqlite::params_from_iter(ids), code_chunk_from_row)
            .map_err(|source| StorageError::Sqlite {
                path: self.db_path.clone(),
                source,
            })?;
        for chunk in collect_rows(rows, &self.db_path)? {
            candidates.insert(chunk.chunk_id.clone(), chunk);
        }
        Ok(())
    }

    fn like_candidates(
        &self,
        terms: &[String],
        collection: Option<&str>,
        filters: Option<&serde_json::Map<String, serde_json::Value>>,
        cap: usize,
        candidates: &mut std::collections::BTreeMap<String, CodeChunk>,
    ) -> Result<(), StorageError> {
        let mut params: Vec<SqlValue> = Vec::new();
        let mut collection_where = String::new();
        if let Some(collection) = collection {
            collection_where = "collection = ? AND ".to_owned();
            params.push(SqlValue::Text(collection.to_owned()));
        }
        let mut like_clauses = Vec::new();
        for term in terms.iter().take(8) {
            like_clauses
                .push("(name LIKE ? OR parent_name LIKE ? OR file_path LIKE ? OR code LIKE ?)");
            let pattern = format!("%{term}%");
            params.push(SqlValue::Text(term.clone()));
            params.push(SqlValue::Text(term.clone()));
            params.push(SqlValue::Text(pattern.clone()));
            params.push(SqlValue::Text(pattern));
        }
        let filter = filter_clause(filters, &mut params);
        params.push(SqlValue::Integer(cap as i64));
        let sql = format!(
            "SELECT chunk_id, collection, file_path, name, parent_name, chunk_type, language, \
             start_line, end_line, code, token_estimate, updated_at \
             FROM code_index WHERE {collection_where}({like_or}){filter} LIMIT ?",
            like_or = like_clauses.join(" OR "),
        );
        let mut stmt = self
            .conn
            .prepare(&sql)
            .map_err(|source| StorageError::Sqlite {
                path: self.db_path.clone(),
                source,
            })?;
        let rows = stmt
            .query_map(rusqlite::params_from_iter(params), code_chunk_from_row)
            .map_err(|source| StorageError::Sqlite {
                path: self.db_path.clone(),
                source,
            })?;
        for chunk in collect_rows(rows, &self.db_path)? {
            candidates.insert(chunk.chunk_id.clone(), chunk);
        }
        Ok(())
    }
}

type SqlValue = rusqlite::types::Value;

fn code_file_from_row(row: &Row<'_>) -> rusqlite::Result<CodeFileItem> {
    let symbols_raw: Option<String> = row.get(5)?;
    Ok(CodeFileItem {
        file_path: row.get(0)?,
        language: row.get::<_, Option<String>>(1)?.unwrap_or_default(),
        chunk_count: row.get(2)?,
        symbol_count: row.get(3)?,
        updated_at: row.get::<_, Option<f64>>(4)?.unwrap_or_default(),
        symbols: symbols_raw
            .unwrap_or_default()
            .split(", ")
            .filter(|value| !value.is_empty())
            .take(20)
            .map(str::to_owned)
            .collect(),
        score: 0.0,
    })
}

/// Aggregated per-file row from the code index (Python `list_code_files`).
#[derive(Debug, Clone, PartialEq, serde::Serialize)]
pub struct CodeFileItem {
    /// Repo-relative path.
    pub file_path: String,
    /// Detected language.
    pub language: String,
    /// Chunks indexed for the file.
    pub chunk_count: i64,
    /// Named symbols in the file.
    pub symbol_count: i64,
    /// Last index update timestamp.
    pub updated_at: f64,
    /// Up to 20 symbol names.
    pub symbols: Vec<String>,
    /// Relevance score (used by `related_test_files`).
    pub score: f64,
}

impl RagDatabase {
    /// Python `list_code_files`: aggregated per-file rows (all files, not just
    /// tests). Used by graph impact/affected for indexed-file membership and
    /// `updated_at` staleness checks.
    pub fn list_code_files(
        &self,
        collection: &str,
        limit: usize,
    ) -> Result<Vec<CodeFileItem>, StorageError> {
        let mut stmt = self
            .conn
            .prepare(
                "SELECT file_path, MAX(language), COUNT(*), COUNT(NULLIF(name, '')), \
                 MAX(updated_at), GROUP_CONCAT(NULLIF(name, ''), ', ') \
                 FROM code_index WHERE collection = ? \
                 GROUP BY file_path ORDER BY COUNT(*) DESC, file_path ASC LIMIT ?",
            )
            .map_err(|source| StorageError::Sqlite {
                path: self.db_path.clone(),
                source,
            })?;
        let rows = stmt
            .query_map(
                rusqlite::params![collection, limit as i64],
                code_file_from_row,
            )
            .map_err(|source| StorageError::Sqlite {
                path: self.db_path.clone(),
                source,
            })?;
        collect_rows(rows, &self.db_path)
    }

    /// Python `list_code_files(tests_only=True)`: aggregated test files.
    pub fn list_test_files(
        &self,
        collection: &str,
        limit: usize,
    ) -> Result<Vec<CodeFileItem>, StorageError> {
        let mut stmt = self
            .conn
            .prepare(
                "SELECT file_path, MAX(language), COUNT(*), COUNT(NULLIF(name, '')), \
                 MAX(updated_at), GROUP_CONCAT(NULLIF(name, ''), ', ') \
                 FROM code_index \
                 WHERE collection = ? AND \
                 (file_path LIKE '%/test/%' OR file_path LIKE '%/tests/%' OR file_path LIKE '%Test.%') \
                 GROUP BY file_path ORDER BY COUNT(*) DESC, file_path ASC LIMIT ?",
            )
            .map_err(|source| StorageError::Sqlite {
                path: self.db_path.clone(),
                source,
            })?;
        let rows = stmt
            .query_map(
                rusqlite::params![collection, limit as i64],
                code_file_from_row,
            )
            .map_err(|source| StorageError::Sqlite {
                path: self.db_path.clone(),
                source,
            })?;
        collect_rows(rows, &self.db_path)
    }

    /// Python `related_test_files`: rank tests near the impacted files by
    /// basename anchors and module prefixes.
    pub fn related_test_files(
        &self,
        collection: &str,
        file_paths: &[String],
        limit: usize,
    ) -> Result<Vec<CodeFileItem>, StorageError> {
        let candidates = self.list_test_files(collection, (limit * 4).max(100))?;
        if file_paths.is_empty() {
            return Ok(candidates.into_iter().take(limit).collect());
        }
        let mut anchors: std::collections::BTreeSet<String> = std::collections::BTreeSet::new();
        let mut modules: std::collections::BTreeSet<String> = std::collections::BTreeSet::new();
        for path in file_paths {
            let parts: Vec<&str> = path.split('/').filter(|part| !part.is_empty()).collect();
            if let Some(last) = parts.last() {
                let base = last.split('.').next().unwrap_or_default().to_lowercase();
                let anchor = base
                    .strip_suffix("test")
                    .or_else(|| base.strip_suffix("spec"))
                    .unwrap_or(&base)
                    .to_owned();
                anchors.insert(anchor);
            }
            if parts.len() > 1 {
                let take = parts.len().saturating_sub(1).clamp(1, 3);
                modules.insert(parts[..take].join("/").to_lowercase());
            }
        }
        let mut ranked: Vec<CodeFileItem> = Vec::new();
        for mut item in candidates {
            let path = item.file_path.to_lowercase();
            let base = path
                .rsplit('/')
                .next()
                .unwrap_or_default()
                .split('.')
                .next()
                .unwrap_or_default()
                .to_owned();
            let mut score: f64 = 0.0;
            for anchor in &anchors {
                if !anchor.is_empty() && base.contains(anchor.as_str()) {
                    score += 5.0;
                } else if !anchor.is_empty() && path.contains(anchor.as_str()) {
                    score += 2.0;
                }
            }
            if modules
                .iter()
                .any(|module| path.starts_with(module.as_str()))
            {
                score += 1.0;
            }
            if score > 0.0 {
                item.score = (score * 1000.0).round() / 1000.0;
                ranked.push(item);
            }
        }
        ranked.sort_by(|left, right| right.score.total_cmp(&left.score));
        ranked.truncate(limit);
        Ok(ranked)
    }
}

/// A lexical code-index hit with its raw navigation score.
#[derive(Debug, Clone, PartialEq)]
pub struct LexicalHit {
    /// Raw unbounded lexical score (Python `_score_code_row`).
    pub score: f64,
    /// Matching code-index row.
    pub chunk: CodeChunk,
}

/// Append the Python `INSERT INTO query_log` row using a short-lived writable
/// connection (the shared handle stays read-only). Failures are the caller's
/// choice to ignore, matching Python's non-critical logging.
pub fn log_query(
    paths: &RagPaths,
    query: &str,
    results_count: i64,
    latency_ms: f64,
) -> Result<(), StorageError> {
    let db_path = paths.home.join("rag.db");
    let conn = Connection::open(&db_path).map_err(|source| StorageError::Sqlite {
        path: db_path.clone(),
        source,
    })?;
    conn.execute(
        "INSERT INTO query_log (timestamp, query, results_count, latency_ms) \
         VALUES (strftime('%Y-%m-%dT%H:%M:%f','now','localtime'), ?1, ?2, ?3)",
        rusqlite::params![query, results_count, latency_ms],
    )
    .map_err(|source| StorageError::Sqlite {
        path: db_path,
        source,
    })?;
    Ok(())
}

/// Python-compatible embedding cache over `~/.rag/embed_cache.db`.
///
/// Keys are `"{model}:{content_hash}"` and dense vectors are stored as packed
/// native-endian `f32` blobs, exactly like Python `core/cache.py`.
pub struct EmbedCache {
    db_path: PathBuf,
    conn: Connection,
    model: String,
    ttl_seconds: f64,
}

impl EmbedCache {
    /// Open (and create if missing) the shared cache database.
    pub fn open(paths: &RagPaths, model: impl Into<String>) -> Result<Self, StorageError> {
        let db_path = paths.home.join("embed_cache.db");
        let conn = Connection::open(&db_path).map_err(|source| StorageError::Sqlite {
            path: db_path.clone(),
            source,
        })?;
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS embed_cache (
                content_hash TEXT PRIMARY KEY,
                dense       BLOB NOT NULL,
                sparse_idx  BLOB,
                sparse_val  BLOB,
                created_at  REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cache_stats (
                id          INTEGER PRIMARY KEY CHECK (id = 1),
                hit_count   INTEGER NOT NULL DEFAULT 0,
                miss_count  INTEGER NOT NULL DEFAULT 0
            );",
        )
        .map_err(|source| StorageError::Sqlite {
            path: db_path.clone(),
            source,
        })?;
        Ok(Self {
            db_path,
            conn,
            model: model.into(),
            ttl_seconds: 30.0 * 86_400.0,
        })
    }

    fn key(&self, content_hash: &str) -> String {
        format!("{}:{}", self.model, content_hash)
    }

    /// Cached dense vector for a chunk content hash, or `None` on miss/expiry.
    pub fn get(&self, content_hash: &str) -> Option<Vec<f32>> {
        let key = self.key(content_hash);
        let row: Option<(Vec<u8>, f64)> = self
            .conn
            .query_row(
                "SELECT dense, created_at FROM embed_cache WHERE content_hash = ?",
                [&key],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .ok();
        let (blob, created_at) = row?;
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|duration| duration.as_secs_f64())
            .unwrap_or_default();
        if now - created_at > self.ttl_seconds {
            let _ = self
                .conn
                .execute("DELETE FROM embed_cache WHERE content_hash = ?", [&key]);
            return None;
        }
        Some(unpack_floats(&blob))
    }

    /// Insert or replace a cached vector.
    pub fn put(&self, content_hash: &str, dense: &[f32]) -> Result<(), StorageError> {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|duration| duration.as_secs_f64())
            .unwrap_or_default();
        self.conn
            .execute(
                "INSERT OR REPLACE INTO embed_cache \
                 (content_hash, dense, sparse_idx, sparse_val, created_at) \
                 VALUES (?1, ?2, NULL, NULL, ?3)",
                rusqlite::params![self.key(content_hash), pack_floats(dense), now],
            )
            .map_err(|source| StorageError::Sqlite {
                path: self.db_path.clone(),
                source,
            })?;
        Ok(())
    }
}

fn pack_floats(values: &[f32]) -> Vec<u8> {
    let mut bytes = Vec::with_capacity(values.len() * 4);
    for value in values {
        bytes.extend_from_slice(&value.to_le_bytes());
    }
    bytes
}

fn unpack_floats(data: &[u8]) -> Vec<f32> {
    data.chunks_exact(4)
        .map(|chunk| f32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]))
        .collect()
}

/// Port of Python `storage.db._query_terms`: identifiers from quoted spans
/// first, then the whole query; case-insensitive dedupe capped at 12 terms.
#[must_use]
pub fn query_terms(query: &str) -> Vec<String> {
    let mut ordered = Vec::new();
    for span in quoted_spans(query) {
        push_identifiers(&span, &mut ordered);
    }
    push_identifiers(query, &mut ordered);
    let mut seen = std::collections::HashSet::new();
    let mut out = Vec::new();
    for term in ordered {
        if term.len() < 3 {
            continue;
        }
        if seen.insert(term.to_ascii_lowercase()) {
            out.push(term);
            if out.len() == 12 {
                break;
            }
        }
    }
    out
}

fn quoted_spans(query: &str) -> Vec<String> {
    let chars: Vec<char> = query.chars().collect();
    let mut spans = Vec::new();
    let mut index = 0;
    while index < chars.len() {
        if chars[index] == '\'' || chars[index] == '"' {
            if let Some(close) = chars[index + 1..]
                .iter()
                .position(|c| *c == '\'' || *c == '"')
            {
                let content: String = chars[index + 1..index + 1 + close].iter().collect();
                if (3..=120).contains(&content.chars().count()) {
                    spans.push(content);
                    index += close + 2;
                    continue;
                }
                index += close + 1;
                continue;
            }
        }
        index += 1;
    }
    spans
}

fn push_identifiers(text: &str, out: &mut Vec<String>) {
    let mut current = String::new();
    for character in text.chars() {
        let continues = character.is_ascii_alphanumeric() || character == '_';
        let starts = character.is_ascii_alphabetic() || character == '_';
        if current.is_empty() {
            if starts {
                current.push(character);
            }
        } else if continues {
            current.push(character);
        } else {
            if current.len() >= 3 {
                out.push(std::mem::take(&mut current));
            }
            current.clear();
        }
    }
    if current.len() >= 3 {
        out.push(current);
    }
}

fn fts_match_expression(terms: &[String]) -> String {
    terms
        .iter()
        .map(|term| format!("\"{}\"", term.replace('"', "\"\"")))
        .collect::<Vec<_>>()
        .join(" OR ")
}

fn filter_clause(
    filters: Option<&serde_json::Map<String, serde_json::Value>>,
    params: &mut Vec<SqlValue>,
) -> String {
    let Some(filters) = filters else {
        return String::new();
    };
    const ALLOWED: [&str; 5] = ["file_path", "name", "parent_name", "chunk_type", "language"];
    let mut clauses = Vec::new();
    for (key, value) in filters {
        if !ALLOWED.contains(&key.as_str()) {
            continue;
        }
        match value {
            serde_json::Value::Array(values) => {
                let scalars: Vec<SqlValue> = values
                    .iter()
                    .filter(|value| !value.is_null())
                    .filter_map(json_scalar_to_sql)
                    .collect();
                if scalars.is_empty() {
                    continue;
                }
                let placeholders = scalars.iter().map(|_| "?").collect::<Vec<_>>().join(",");
                clauses.push(format!("{key} IN ({placeholders})"));
                params.extend(scalars);
            }
            value => {
                if let Some(scalar) = json_scalar_to_sql(value) {
                    clauses.push(format!("{key} = ?"));
                    params.push(scalar);
                }
            }
        }
    }
    if clauses.is_empty() {
        String::new()
    } else {
        format!(" AND {}", clauses.join(" AND "))
    }
}

fn json_scalar_to_sql(value: &serde_json::Value) -> Option<SqlValue> {
    match value {
        serde_json::Value::String(text) => Some(SqlValue::Text(text.clone())),
        serde_json::Value::Bool(flag) => Some(SqlValue::Integer(i64::from(*flag))),
        serde_json::Value::Number(number) => number
            .as_i64()
            .map(SqlValue::Integer)
            .or_else(|| number.as_f64().map(SqlValue::Real)),
        _ => None,
    }
}

/// Port of Python `storage.db._score_code_row` symbol-aware ranking.
#[must_use]
pub fn score_code_row(chunk: &CodeChunk, terms: &[String]) -> f64 {
    let text = format!(
        "{} {} {} {}",
        chunk.file_path, chunk.name, chunk.parent_name, chunk.code
    )
    .to_lowercase();
    let name = chunk.name.to_lowercase();
    let parent = chunk.parent_name.to_lowercase();
    let path = chunk.file_path.to_lowercase();
    let mut score = 1.0;
    for term in terms {
        let term = term.to_lowercase();
        if term == name {
            score += 4.0;
        } else if term == parent {
            score += 2.5;
        } else if path.contains(&term) {
            score += 1.5;
        }
        score += text.matches(&term).count().min(8) as f64 * 0.25;
    }
    if chunk.chunk_type == "function" || chunk.chunk_type == "method" {
        score += 0.6;
    }
    score
}

/// Query log row shape.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct QueryLogRow {
    /// Timestamp string.
    pub timestamp: String,
    /// Query text.
    pub query: String,
    /// Result count.
    pub results_count: Option<i64>,
    /// Latency in milliseconds.
    pub latency_ms: Option<f64>,
}

/// SQLite code index row shape.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CodeChunk {
    /// Chunk id.
    pub chunk_id: String,
    /// Collection name.
    pub collection: String,
    /// File path.
    pub file_path: String,
    /// Symbol name.
    pub name: String,
    /// Parent symbol name.
    pub parent_name: String,
    /// Chunk kind.
    pub chunk_type: String,
    /// Language.
    pub language: String,
    /// Start line.
    pub start_line: i64,
    /// End line.
    pub end_line: i64,
    /// Source text.
    pub code: String,
    /// Token estimate.
    pub token_estimate: i64,
    /// Update timestamp.
    pub updated_at: f64,
}

fn code_chunk_from_row(row: &Row<'_>) -> rusqlite::Result<CodeChunk> {
    Ok(CodeChunk {
        chunk_id: row.get(0)?,
        collection: row.get(1)?,
        file_path: row.get(2)?,
        name: row.get(3)?,
        parent_name: row.get(4)?,
        chunk_type: row.get(5)?,
        language: row.get(6)?,
        start_line: row.get(7)?,
        end_line: row.get(8)?,
        code: row.get(9)?,
        token_estimate: row.get(10)?,
        updated_at: row.get(11)?,
    })
}

/// Structured daemon event entry from Python's in-memory ring.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EventEntry {
    /// Unix timestamp.
    pub ts: f64,
    /// Event name.
    pub event: String,
    /// Additional structured fields.
    #[serde(flatten)]
    pub fields: BTreeMap<String, Value>,
}

/// Bounded in-process event ring.
#[derive(Debug, Clone)]
pub struct EventRing {
    max_len: usize,
    events: VecDeque<EventEntry>,
}

impl EventRing {
    /// Create a ring. Python uses 500 for server events.
    #[must_use]
    pub fn new(max_len: usize) -> Self {
        Self {
            max_len,
            events: VecDeque::new(),
        }
    }

    /// Push an event and trim older entries.
    pub fn push(&mut self, event: EventEntry) {
        self.events.push_back(event);
        while self.events.len() > self.max_len {
            self.events.pop_front();
        }
    }

    /// Recent events filtered by `after_ts`, then limited from the tail.
    #[must_use]
    pub fn recent(&self, limit: usize, after_ts: f64) -> Vec<EventEntry> {
        let mut events: Vec<_> = self
            .events
            .iter()
            .filter(|event| after_ts <= 0.0 || event.ts > after_ts)
            .cloned()
            .collect();
        if events.len() > limit {
            events.drain(0..events.len() - limit);
        }
        events
    }
}

/// Structured log record shape for the Rust server/TUI boundary.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StructuredLogRecord {
    /// Unix timestamp.
    pub ts: String,
    /// Level name.
    pub level: String,
    /// Event/message.
    pub event: String,
    /// Additional fields.
    pub fields: BTreeMap<String, String>,
}

fn collect_rows<T>(
    rows: rusqlite::MappedRows<'_, impl FnMut(&Row<'_>) -> rusqlite::Result<T>>,
    db_path: &Path,
) -> Result<Vec<T>, StorageError> {
    let mut out = Vec::new();
    for row in rows {
        out.push(row.map_err(|source| StorageError::Sqlite {
            path: db_path.to_path_buf(),
            source,
        })?);
    }
    Ok(out)
}
