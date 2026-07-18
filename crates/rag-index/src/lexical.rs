use std::{
    path::Path,
    time::{SystemTime, UNIX_EPOCH},
};

use rusqlite::{params, Connection, Row};
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum LexicalError {
    #[error("sqlite error: {0}")]
    Sqlite(#[from] rusqlite::Error),
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CodeDocument {
    pub chunk_id: String,
    pub collection: String,
    pub file_path: String,
    pub name: String,
    pub parent_name: String,
    pub chunk_type: String,
    pub language: String,
    pub start_line: usize,
    pub end_line: usize,
    pub code: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CodeSearchHit {
    pub chunk_id: String,
    pub collection: String,
    pub file_path: String,
    pub name: String,
    pub parent_name: String,
    pub chunk_type: String,
    pub language: String,
    pub start_line: usize,
    pub end_line: usize,
    pub lines: String,
    pub code: String,
    pub token_estimate: usize,
    pub score: f64,
    pub citation: String,
}

pub struct LexicalIndex {
    conn: Connection,
}

impl LexicalIndex {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, LexicalError> {
        let conn = Connection::open(path)?;
        let index = Self { conn };
        index.ensure_schema()?;
        Ok(index)
    }

    pub fn in_memory() -> Result<Self, LexicalError> {
        let conn = Connection::open_in_memory()?;
        let index = Self { conn };
        index.ensure_schema()?;
        Ok(index)
    }

    pub fn ensure_schema(&self) -> Result<(), LexicalError> {
        self.conn.execute_batch(
            "
            CREATE TABLE IF NOT EXISTS code_index (
                chunk_id TEXT PRIMARY KEY,
                collection TEXT NOT NULL,
                file_path TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                parent_name TEXT NOT NULL DEFAULT '',
                chunk_type TEXT NOT NULL DEFAULT '',
                language TEXT NOT NULL DEFAULT '',
                start_line INTEGER NOT NULL DEFAULT 0,
                end_line INTEGER NOT NULL DEFAULT 0,
                code TEXT NOT NULL,
                token_estimate INTEGER NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS code_index_fts USING fts5(
                chunk_id UNINDEXED,
                collection UNINDEXED,
                file_path,
                name,
                parent_name,
                chunk_type,
                language,
                code,
                tokenize = 'unicode61 tokenchars ''_$'''
            );
            CREATE INDEX IF NOT EXISTS idx_code_collection_file ON code_index(collection, file_path);
            CREATE INDEX IF NOT EXISTS idx_code_symbol ON code_index(collection, name, parent_name);
            ",
        )?;
        Ok(())
    }

    pub fn upsert_code_chunks(&mut self, docs: &[CodeDocument]) -> Result<usize, LexicalError> {
        let tx = self.conn.transaction()?;
        let now = unix_now();
        let mut inserted = 0;
        for doc in docs {
            if doc.chunk_id.is_empty() {
                continue;
            }
            tx.execute(
                "DELETE FROM code_index WHERE chunk_id = ?",
                params![doc.chunk_id],
            )?;
            tx.execute(
                "DELETE FROM code_index_fts WHERE chunk_id = ?",
                params![doc.chunk_id],
            )?;
            let token_estimate = token_estimate(&doc.code);
            tx.execute(
                "INSERT INTO code_index (
                    chunk_id, collection, file_path, name, parent_name, chunk_type,
                    language, start_line, end_line, code, token_estimate, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                params![
                    doc.chunk_id,
                    doc.collection,
                    doc.file_path,
                    doc.name,
                    doc.parent_name,
                    doc.chunk_type,
                    doc.language,
                    doc.start_line as i64,
                    doc.end_line as i64,
                    doc.code,
                    token_estimate as i64,
                    now
                ],
            )?;
            tx.execute(
                "INSERT INTO code_index_fts (
                    chunk_id, collection, file_path, name, parent_name, chunk_type, language, code
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                params![
                    doc.chunk_id,
                    doc.collection,
                    doc.file_path,
                    doc.name,
                    doc.parent_name,
                    doc.chunk_type,
                    doc.language,
                    doc.code
                ],
            )?;
            inserted += 1;
        }
        tx.commit()?;
        Ok(inserted)
    }

    /// Atomically replace every lexical chunk for one file. This prevents
    /// stale chunk IDs when edits change line ranges, while keeping the FTS
    /// mirror and content table consistent on failure.
    pub fn replace_code_chunks_for_file(
        &mut self,
        collection: &str,
        file_path: &str,
        docs: &[CodeDocument],
    ) -> Result<usize, LexicalError> {
        let tx = self.conn.transaction()?;
        tx.execute(
            "DELETE FROM code_index_fts WHERE collection = ? AND file_path = ?",
            params![collection, file_path],
        )?;
        tx.execute(
            "DELETE FROM code_index WHERE collection = ? AND file_path = ?",
            params![collection, file_path],
        )?;
        let now = unix_now();
        let mut inserted = 0;
        for doc in docs {
            if doc.chunk_id.is_empty() {
                continue;
            }
            let token_estimate = token_estimate(&doc.code);
            tx.execute(
                "INSERT INTO code_index (
                    chunk_id, collection, file_path, name, parent_name, chunk_type,
                    language, start_line, end_line, code, token_estimate, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                params![
                    doc.chunk_id,
                    doc.collection,
                    doc.file_path,
                    doc.name,
                    doc.parent_name,
                    doc.chunk_type,
                    doc.language,
                    doc.start_line as i64,
                    doc.end_line as i64,
                    doc.code,
                    token_estimate as i64,
                    now
                ],
            )?;
            tx.execute(
                "INSERT INTO code_index_fts (
                    chunk_id, collection, file_path, name, parent_name, chunk_type, language, code
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                params![
                    doc.chunk_id,
                    doc.collection,
                    doc.file_path,
                    doc.name,
                    doc.parent_name,
                    doc.chunk_type,
                    doc.language,
                    doc.code
                ],
            )?;
            inserted += 1;
        }
        tx.commit()?;
        Ok(inserted)
    }

    pub fn delete_code_chunks_by_file(
        &self,
        collection: &str,
        file_path: &str,
    ) -> Result<(), LexicalError> {
        let tx = self.conn.unchecked_transaction()?;
        let ids = tx
            .prepare("SELECT chunk_id FROM code_index WHERE collection = ? AND file_path = ?")?
            .query_map(params![collection, file_path], |row| {
                row.get::<_, String>(0)
            })?
            .collect::<Result<Vec<_>, _>>()?;
        for id in ids {
            tx.execute("DELETE FROM code_index_fts WHERE chunk_id = ?", params![id])?;
        }
        tx.execute(
            "DELETE FROM code_index WHERE collection = ? AND file_path = ?",
            params![collection, file_path],
        )?;
        tx.commit()?;
        Ok(())
    }

    /// Delete every chunk of one language in a collection (Python
    /// `--full --lang X` reset).
    pub fn delete_code_chunks_by_language(
        &self,
        collection: &str,
        language: &str,
    ) -> Result<(), LexicalError> {
        let tx = self.conn.unchecked_transaction()?;
        tx.execute(
            "DELETE FROM code_index WHERE collection = ? AND language = ?",
            params![collection, language],
        )?;
        tx.execute(
            "DELETE FROM code_index_fts WHERE collection = ? AND language = ?",
            params![collection, language],
        )?;
        tx.commit()?;
        Ok(())
    }

    pub fn delete_code_chunks_by_collection(&self, collection: &str) -> Result<(), LexicalError> {
        let tx = self.conn.unchecked_transaction()?;
        tx.execute(
            "DELETE FROM code_index_fts WHERE collection = ?",
            params![collection],
        )?;
        tx.execute(
            "DELETE FROM code_index WHERE collection = ?",
            params![collection],
        )?;
        tx.commit()?;
        Ok(())
    }

    pub fn search_code_chunks(
        &self,
        query: &str,
        collection: Option<&str>,
        limit: usize,
    ) -> Result<Vec<CodeSearchHit>, LexicalError> {
        let terms = query_terms(query);
        if terms.is_empty() {
            return Ok(Vec::new());
        }
        let mut candidates = Vec::new();
        let collection_clause =
            collection.map_or(String::new(), |_| " AND collection = ?".to_owned());
        let sql = format!(
            "SELECT * FROM code_index WHERE (name LIKE ? OR parent_name LIKE ? OR file_path LIKE ? OR code LIKE ?){collection_clause} LIMIT ?"
        );
        for term in &terms {
            let exact = term.to_owned();
            let pattern = format!("%{term}%");
            let mut stmt = self.conn.prepare(&sql)?;
            let mut rows = if let Some(collection) = collection {
                stmt.query(params![
                    exact,
                    exact,
                    pattern,
                    pattern,
                    collection,
                    (limit * 8).max(50) as i64
                ])?
            } else {
                stmt.query(params![
                    exact,
                    exact,
                    pattern,
                    pattern,
                    (limit * 8).max(50) as i64
                ])?
            };
            while let Some(row) = rows.next()? {
                candidates.push(hit_from_row(row, &terms)?);
            }
        }
        candidates.sort_by(|a, b| {
            b.score
                .total_cmp(&a.score)
                .then_with(|| a.file_path.cmp(&b.file_path))
        });
        candidates.dedup_by(|a, b| a.chunk_id == b.chunk_id);
        candidates.truncate(limit);
        Ok(candidates)
    }
}

fn hit_from_row(row: &Row<'_>, terms: &[String]) -> rusqlite::Result<CodeSearchHit> {
    let code: String = row.get("code")?;
    let start_line: usize = row.get::<_, i64>("start_line")? as usize;
    let end_line: usize = row.get::<_, i64>("end_line")? as usize;
    let file_path: String = row.get("file_path")?;
    let name: String = row.get("name")?;
    let parent_name: String = row.get("parent_name")?;
    let score = score_row(&file_path, &name, &parent_name, &code, terms);
    Ok(CodeSearchHit {
        chunk_id: row.get("chunk_id")?,
        collection: row.get("collection")?,
        file_path: file_path.clone(),
        name: name.clone(),
        parent_name: parent_name.clone(),
        chunk_type: row.get("chunk_type")?,
        language: row.get("language")?,
        start_line,
        end_line,
        lines: format!("{start_line}-{end_line}"),
        token_estimate: row.get::<_, i64>("token_estimate")? as usize,
        code,
        score,
        citation: format!(
            "{}:{}-{} ({}{})",
            file_path,
            start_line,
            end_line,
            if parent_name.is_empty() {
                ""
            } else {
                &parent_name
            },
            if parent_name.is_empty() || name.is_empty() {
                name
            } else {
                format!(".{name}")
            }
        ),
    })
}

fn query_terms(query: &str) -> Vec<String> {
    let mut out = Vec::new();
    for token in query
        .split(|ch: char| !(ch == '_' || ch == '$' || ch.is_ascii_alphanumeric()))
        .filter(|token| token.len() >= 3)
    {
        if !out
            .iter()
            .any(|existing: &String| existing.eq_ignore_ascii_case(token))
        {
            out.push(token.to_owned());
        }
    }
    out.truncate(12);
    out
}

fn score_row(file_path: &str, name: &str, parent_name: &str, code: &str, terms: &[String]) -> f64 {
    let haystack = format!("{file_path} {name} {parent_name} {code}").to_ascii_lowercase();
    let mut score = 1.0;
    for term in terms {
        let term = term.to_ascii_lowercase();
        if term == name.to_ascii_lowercase() {
            score += 4.0;
        } else if term == parent_name.to_ascii_lowercase() {
            score += 2.5;
        } else if file_path.to_ascii_lowercase().contains(&term) {
            score += 1.5;
        }
        score += haystack.matches(&term).count().min(8) as f64 * 0.25;
    }
    score
}

fn token_estimate(text: &str) -> usize {
    text.len().div_ceil(4).max(1)
}

fn unix_now() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs_f64())
        .unwrap_or_default()
}
