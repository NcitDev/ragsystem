use std::{
    path::Path,
    time::{SystemTime, UNIX_EPOCH},
};

use rusqlite::{params, Connection, Row};
use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::symbols::{EdgeRelation, FileSymbols, RefKind};

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

/// A stored definition site (`symbol_defs` row).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SymbolDefRow {
    /// Repo-relative path.
    pub file_path: String,
    /// Bare identifier.
    pub name: String,
    /// Dotted path through enclosing definitions.
    pub qualified_name: String,
    /// Immediately enclosing definition name.
    pub parent_name: String,
    /// Normalized kind (`class`, `method`, `property`, ...).
    pub kind: String,
    /// Source language.
    pub language: String,
    /// Declaration text up to the body.
    pub signature: String,
    /// First line (1-based, inclusive).
    pub start_line: usize,
    /// Last line (1-based, inclusive).
    pub end_line: usize,
    /// Line of the identifier itself (1-based).
    pub name_line: usize,
    /// Column of the identifier (0-based).
    pub name_col: usize,
}

/// A stored reference site (`symbol_refs` row).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SymbolRefRow {
    /// Repo-relative path.
    pub file_path: String,
    /// The referenced identifier.
    pub name: String,
    /// `call` / `type` / `import` / `ident`.
    pub kind: String,
    /// Qualified name of the enclosing definition.
    pub container: String,
    /// Bare name of the enclosing definition.
    pub container_name: String,
    /// Source language.
    pub language: String,
    /// 1-based line.
    pub line: usize,
    /// 0-based column.
    pub col: usize,
    /// Trimmed source line.
    pub context: String,
}

/// A stored structural edge (`symbol_edges` row).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SymbolEdgeRow {
    /// Repo-relative path.
    pub file_path: String,
    /// Bare name of the source symbol.
    pub from_name: String,
    /// Qualified name of the source symbol.
    pub from_qualified: String,
    /// Bare name of the target symbol.
    pub to_name: String,
    /// `calls` / `inherits` / `implements` / `imports`.
    pub relation: String,
    /// Source language.
    pub language: String,
    /// 1-based line.
    pub line: usize,
    /// Trimmed source line.
    pub context: String,
}

/// Row counts per symbol table, for health/diagnostics endpoints.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
pub struct SymbolIndexStats {
    /// Files with symbol rows in the collection.
    pub files: usize,
    /// `symbol_defs` rows in the collection.
    pub definitions: usize,
    /// `symbol_refs` rows in the collection.
    pub references: usize,
    /// `symbol_edges` rows in the collection.
    pub edges: usize,
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

    /// Create every table this crate writes.
    ///
    /// Deliberately does **not** touch `PRAGMA user_version`: `rag-storage`
    /// opens this same file (`~/.rag/rag.db`) read-only and
    /// `RagDatabase::open_path` hard-fails when `user_version` exceeds
    /// `SUPPORTED_SCHEMA_VERSION` (currently `0`). Additive
    /// `CREATE TABLE IF NOT EXISTS` is invisible to that reader; bumping the
    /// pragma would lock it out of the repo registry, the query log and the
    /// lexical search path all at once.
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

            -- `file_path` and `language` are stored once per file, not on
            -- every symbol row: on a 1M-LOC repo the path alone repeated
            -- across millions of reference rows dominated the database.
            CREATE TABLE IF NOT EXISTS symbol_files (
                file_id INTEGER PRIMARY KEY,
                collection TEXT NOT NULL,
                file_path TEXT NOT NULL,
                language TEXT NOT NULL DEFAULT '',
                updated_at REAL NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_symbol_files_key
                ON symbol_files(collection, file_path);
            CREATE INDEX IF NOT EXISTS idx_symbol_files_language
                ON symbol_files(collection, language);

            CREATE TABLE IF NOT EXISTS symbol_defs (
                file_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                qualified_name TEXT NOT NULL DEFAULT '',
                parent_name TEXT NOT NULL DEFAULT '',
                kind TEXT NOT NULL DEFAULT '',
                signature TEXT NOT NULL DEFAULT '',
                start_line INTEGER NOT NULL DEFAULT 0,
                end_line INTEGER NOT NULL DEFAULT 0,
                name_line INTEGER NOT NULL DEFAULT 0,
                name_col INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_symbol_defs_name ON symbol_defs(name);
            CREATE INDEX IF NOT EXISTS idx_symbol_defs_qualified ON symbol_defs(qualified_name);
            CREATE INDEX IF NOT EXISTS idx_symbol_defs_file ON symbol_defs(file_id);

            CREATE TABLE IF NOT EXISTS symbol_refs (
                file_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT '',
                container TEXT NOT NULL DEFAULT '',
                container_name TEXT NOT NULL DEFAULT '',
                line INTEGER NOT NULL DEFAULT 0,
                col INTEGER NOT NULL DEFAULT 0,
                context TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_symbol_refs_name ON symbol_refs(name, kind);
            CREATE INDEX IF NOT EXISTS idx_symbol_refs_container
                ON symbol_refs(container_name, kind);
            CREATE INDEX IF NOT EXISTS idx_symbol_refs_file ON symbol_refs(file_id);

            CREATE TABLE IF NOT EXISTS symbol_edges (
                file_id INTEGER NOT NULL,
                from_name TEXT NOT NULL DEFAULT '',
                from_qualified TEXT NOT NULL DEFAULT '',
                to_name TEXT NOT NULL,
                relation TEXT NOT NULL,
                line INTEGER NOT NULL DEFAULT 0,
                context TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_symbol_edges_to ON symbol_edges(to_name, relation);
            CREATE INDEX IF NOT EXISTS idx_symbol_edges_from ON symbol_edges(from_name, relation);
            CREATE INDEX IF NOT EXISTS idx_symbol_edges_file ON symbol_edges(file_id);
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

    pub fn delete_code_chunks_by_file(
        &self,
        collection: &str,
        file_path: &str,
    ) -> Result<(), LexicalError> {
        let ids = self
            .conn
            .prepare("SELECT chunk_id FROM code_index WHERE collection = ? AND file_path = ?")?
            .query_map(params![collection, file_path], |row| {
                row.get::<_, String>(0)
            })?
            .collect::<Result<Vec<_>, _>>()?;
        for id in ids {
            self.conn
                .execute("DELETE FROM code_index_fts WHERE chunk_id = ?", params![id])?;
        }
        self.conn.execute(
            "DELETE FROM code_index WHERE collection = ? AND file_path = ?",
            params![collection, file_path],
        )?;
        Ok(())
    }

    /// Delete every chunk of one language in a collection (Python
    /// `--full --lang X` reset).
    pub fn delete_code_chunks_by_language(
        &self,
        collection: &str,
        language: &str,
    ) -> Result<(), LexicalError> {
        self.conn.execute(
            "DELETE FROM code_index WHERE collection = ? AND language = ?",
            params![collection, language],
        )?;
        self.conn.execute(
            "DELETE FROM code_index_fts WHERE collection = ? AND language = ?",
            params![collection, language],
        )?;
        Ok(())
    }

    pub fn delete_code_chunks_by_collection(&self, collection: &str) -> Result<(), LexicalError> {
        self.conn.execute(
            "DELETE FROM code_index_fts WHERE collection = ?",
            params![collection],
        )?;
        self.conn.execute(
            "DELETE FROM code_index WHERE collection = ?",
            params![collection],
        )?;
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

    // -----------------------------------------------------------------
    // symbol index — write path
    // -----------------------------------------------------------------

    /// Replace every symbol row for one file in one transaction.
    ///
    /// This is the only write entry point, and it mirrors the code-chunk
    /// lifecycle exactly: the indexer deletes and re-adds a file's rows
    /// whenever the file changes, so delete-then-insert is atomic per file.
    /// Returns the number of rows written.
    pub fn replace_file_symbols(
        &mut self,
        collection: &str,
        file: &FileSymbols,
    ) -> Result<usize, LexicalError> {
        let now = unix_now();
        let tx = self.conn.transaction()?;
        tx.execute(
            "INSERT INTO symbol_files (collection, file_path, language, updated_at)
             VALUES (?, ?, ?, ?)
             ON CONFLICT(collection, file_path)
             DO UPDATE SET language = excluded.language, updated_at = excluded.updated_at",
            params![collection, file.file_path, file.language, now],
        )?;
        let file_id: i64 = tx.query_row(
            "SELECT file_id FROM symbol_files WHERE collection = ? AND file_path = ?",
            params![collection, file.file_path],
            |row| row.get(0),
        )?;
        for table in SYMBOL_TABLES {
            tx.execute(
                &format!("DELETE FROM {table} WHERE file_id = ?"),
                params![file_id],
            )?;
        }
        let mut written = 0;
        for def in &file.definitions {
            tx.execute(
                "INSERT INTO symbol_defs (
                    file_id, name, qualified_name, parent_name, kind, signature,
                    start_line, end_line, name_line, name_col
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                params![
                    file_id,
                    def.name,
                    def.qualified_name,
                    def.parent_name,
                    def.kind,
                    def.signature,
                    def.start_line as i64,
                    def.end_line as i64,
                    def.name_line as i64,
                    def.name_col as i64
                ],
            )?;
            written += 1;
        }
        for reference in &file.references {
            tx.execute(
                "INSERT INTO symbol_refs (
                    file_id, name, kind, container, container_name, line, col, context
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                params![
                    file_id,
                    reference.name,
                    reference.kind.as_str(),
                    reference.container,
                    reference.container_name,
                    reference.line as i64,
                    reference.col as i64,
                    reference.context
                ],
            )?;
            written += 1;
        }
        for edge in &file.edges {
            tx.execute(
                "INSERT INTO symbol_edges (
                    file_id, from_name, from_qualified, to_name, relation, line, context
                ) VALUES (?, ?, ?, ?, ?, ?, ?)",
                params![
                    file_id,
                    edge.from_name,
                    edge.from_qualified,
                    edge.to_name,
                    edge.relation.as_str(),
                    edge.line as i64,
                    edge.context
                ],
            )?;
            written += 1;
        }
        tx.commit()?;
        Ok(written)
    }

    /// Drop every symbol row for one file (incremental re-index / deletion).
    pub fn delete_symbols_by_file(
        &self,
        collection: &str,
        file_path: &str,
    ) -> Result<(), LexicalError> {
        self.delete_symbols_where(
            "file_id IN (SELECT file_id FROM symbol_files WHERE collection = ? AND file_path = ?)",
            params![collection, file_path],
        )?;
        self.conn.execute(
            "DELETE FROM symbol_files WHERE collection = ? AND file_path = ?",
            params![collection, file_path],
        )?;
        Ok(())
    }

    /// Drop every symbol row of one language (`--full --lang X` reset).
    ///
    /// Language-scoped, so a `--lang kotlin` run cannot wipe the Java rows —
    /// the same invariant the Qdrant and code-chunk write paths hold.
    pub fn delete_symbols_by_language(
        &self,
        collection: &str,
        language: &str,
    ) -> Result<(), LexicalError> {
        self.delete_symbols_where(
            "file_id IN (SELECT file_id FROM symbol_files WHERE collection = ? AND language = ?)",
            params![collection, language],
        )?;
        self.conn.execute(
            "DELETE FROM symbol_files WHERE collection = ? AND language = ?",
            params![collection, language],
        )?;
        Ok(())
    }

    /// Drop every symbol row of a collection (`--full` reset).
    pub fn delete_symbols_by_collection(&self, collection: &str) -> Result<(), LexicalError> {
        self.delete_symbols_where(
            "file_id IN (SELECT file_id FROM symbol_files WHERE collection = ?)",
            params![collection],
        )?;
        self.conn.execute(
            "DELETE FROM symbol_files WHERE collection = ?",
            params![collection],
        )?;
        Ok(())
    }

    fn delete_symbols_where(
        &self,
        predicate: &str,
        args: impl rusqlite::Params + Clone,
    ) -> Result<(), LexicalError> {
        for table in SYMBOL_TABLES {
            self.conn.execute(
                &format!("DELETE FROM {table} WHERE {predicate}"),
                args.clone(),
            )?;
        }
        Ok(())
    }

    // -----------------------------------------------------------------
    // symbol index — query path
    // -----------------------------------------------------------------

    /// `ast-index symbol <name>`: definitions of an exact identifier.
    ///
    /// Ordered so the thing a developer means comes first: real declarations,
    /// then properties, then Rust `impl` blocks (which reuse the type's name).
    pub fn resolve_symbol(
        &self,
        collection: &str,
        name: &str,
        limit: usize,
    ) -> Result<Vec<SymbolDefRow>, LexicalError> {
        self.query_definitions(
            &format!(
                "{DEF_SELECT} WHERE f.collection = ? AND d.name = ?
                 ORDER BY CASE d.kind WHEN 'impl' THEN 2 WHEN 'property' THEN 1 ELSE 0 END,
                          f.file_path, d.start_line
                 LIMIT ?"
            ),
            params![collection, name, bounded(limit) as i64],
        )
    }

    /// Definitions whose *qualified* name matches exactly (`Greeter.hello`).
    pub fn resolve_qualified_symbol(
        &self,
        collection: &str,
        qualified_name: &str,
        limit: usize,
    ) -> Result<Vec<SymbolDefRow>, LexicalError> {
        self.query_definitions(
            &format!(
                "{DEF_SELECT} WHERE f.collection = ? AND d.qualified_name = ?
                 ORDER BY f.file_path, d.start_line LIMIT ?"
            ),
            params![collection, qualified_name, bounded(limit) as i64],
        )
    }

    /// Every definition in one file, in source order (`/context-pack`).
    pub fn file_definitions(
        &self,
        collection: &str,
        file_path: &str,
        limit: usize,
    ) -> Result<Vec<SymbolDefRow>, LexicalError> {
        self.query_definitions(
            &format!(
                "{DEF_SELECT} WHERE f.collection = ? AND f.file_path = ?
                 ORDER BY d.start_line LIMIT ?"
            ),
            params![collection, file_path, bounded(limit) as i64],
        )
    }

    /// `ast-index usages <name>`: every reference site for an identifier.
    ///
    /// The definition's own name site is never stored, so this is usages in
    /// the CLI sense. Call sites sort first because they are what a developer
    /// asking "who uses this" almost always wants.
    pub fn symbol_usages(
        &self,
        collection: &str,
        name: &str,
        limit: usize,
    ) -> Result<Vec<SymbolRefRow>, LexicalError> {
        self.query_references(
            &format!(
                "{REF_SELECT} WHERE f.collection = ? AND r.name = ?
                 ORDER BY CASE r.kind
                              WHEN 'call' THEN 0 WHEN 'member' THEN 1
                              WHEN 'type' THEN 2 WHEN 'import' THEN 3 ELSE 4 END,
                          f.file_path, r.line
                 LIMIT ?"
            ),
            params![collection, name, bounded(limit) as i64],
        )
    }

    /// `ast-index callers <name>`: call sites naming this symbol.
    ///
    /// Each row carries the calling file, the 1-based line, the enclosing
    /// function (`container` / `container_name`) and the trimmed source line,
    /// which is exactly the `path:` + `  :line  context` shape the CLI printed.
    pub fn symbol_callers(
        &self,
        collection: &str,
        name: &str,
        limit: usize,
    ) -> Result<Vec<SymbolRefRow>, LexicalError> {
        self.query_references(
            &format!(
                "{REF_SELECT} WHERE f.collection = ? AND r.name = ? AND r.kind = 'call'
                 ORDER BY f.file_path, r.line LIMIT ?"
            ),
            params![collection, name, bounded(limit) as i64],
        )
    }

    /// `ast-index call-tree <name>` (one hop): symbols called *by* this one.
    ///
    /// Matches the enclosing definition by bare name, so `hello` finds the
    /// calls inside `Greeter.hello`. Pass a dotted name to
    /// [`Self::symbol_callees_qualified`] when the bare name is ambiguous.
    pub fn symbol_callees(
        &self,
        collection: &str,
        name: &str,
        limit: usize,
    ) -> Result<Vec<SymbolRefRow>, LexicalError> {
        self.query_references(
            &format!(
                "{REF_SELECT} WHERE f.collection = ? AND r.container_name = ? AND r.kind = 'call'
                 ORDER BY f.file_path, r.line LIMIT ?"
            ),
            params![collection, name, bounded(limit) as i64],
        )
    }

    /// Callees of one exact qualified definition (`Greeter.hello`).
    pub fn symbol_callees_qualified(
        &self,
        collection: &str,
        qualified_name: &str,
        limit: usize,
    ) -> Result<Vec<SymbolRefRow>, LexicalError> {
        self.query_references(
            &format!(
                "{REF_SELECT} WHERE f.collection = ? AND r.container = ? AND r.kind = 'call'
                 ORDER BY f.file_path, r.line LIMIT ?"
            ),
            params![collection, qualified_name, bounded(limit) as i64],
        )
    }

    /// `ast-index implementations <name>`: types that extend or implement it.
    pub fn symbol_implementations(
        &self,
        collection: &str,
        name: &str,
        limit: usize,
    ) -> Result<Vec<SymbolEdgeRow>, LexicalError> {
        self.query_edges(
            &format!(
                "{EDGE_SELECT} WHERE f.collection = ? AND e.to_name = ?
                     AND e.relation IN ('inherits', 'implements')
                 ORDER BY e.relation, f.file_path, e.line LIMIT ?"
            ),
            params![collection, name, bounded(limit) as i64],
        )
    }

    /// Base types of a symbol — the inverse of [`Self::symbol_implementations`].
    pub fn symbol_supertypes(
        &self,
        collection: &str,
        name: &str,
        limit: usize,
    ) -> Result<Vec<SymbolEdgeRow>, LexicalError> {
        self.query_edges(
            &format!(
                "{EDGE_SELECT} WHERE f.collection = ? AND e.from_name = ?
                     AND e.relation IN ('inherits', 'implements')
                 ORDER BY e.relation, f.file_path, e.line LIMIT ?"
            ),
            params![collection, name, bounded(limit) as i64],
        )
    }

    /// Edges of one relation pointing at `name` (`imports`, `calls`, ...).
    pub fn symbol_edges_to(
        &self,
        collection: &str,
        name: &str,
        relation: EdgeRelation,
        limit: usize,
    ) -> Result<Vec<SymbolEdgeRow>, LexicalError> {
        self.query_edges(
            &format!(
                "{EDGE_SELECT} WHERE f.collection = ? AND e.to_name = ? AND e.relation = ?
                 ORDER BY f.file_path, e.line LIMIT ?"
            ),
            params![collection, name, relation.as_str(), bounded(limit) as i64],
        )
    }

    /// `ast-index refs <name>` reduced to what `related_files` needs: one row
    /// per file that mentions `name`, with the strongest relation it has.
    ///
    /// Relation strength follows the retrieval layer's own ordering —
    /// `implementor` beats `usage` beats `reference`.
    pub fn symbol_related_files(
        &self,
        collection: &str,
        name: &str,
        limit: usize,
    ) -> Result<Vec<RelatedFileRow>, LexicalError> {
        let mut stmt = self.conn.prepare(
            "SELECT file_path, relation, name, line, rank FROM (
                 SELECT f.file_path AS file_path,
                        CASE WHEN e.relation IN ('inherits','implements') THEN 'implementor'
                             ELSE 'reference' END AS relation,
                        e.from_name AS name,
                        e.line AS line,
                        CASE WHEN e.relation IN ('inherits','implements') THEN 0 ELSE 2 END AS rank
                 FROM symbol_edges e JOIN symbol_files f ON f.file_id = e.file_id
                 WHERE f.collection = ?1 AND e.to_name = ?2
                 UNION ALL
                 SELECT f.file_path AS file_path,
                        CASE WHEN r.kind IN ('call','member') THEN 'usage'
                             ELSE 'reference' END AS relation,
                        CASE WHEN r.container_name = '' THEN ?2 ELSE r.container_name END AS name,
                        r.line AS line,
                        CASE WHEN r.kind IN ('call','member') THEN 1 ELSE 2 END AS rank
                 FROM symbol_refs r JOIN symbol_files f ON f.file_id = r.file_id
                 WHERE f.collection = ?1 AND r.name = ?2
             )
             ORDER BY rank, file_path, line",
        )?;
        // Dedupe to one row per file in Rust: SQLite's bare-column-with-MIN()
        // behavior is an implementation detail, and this stays deterministic.
        let rows = stmt.query_map(params![collection, name], |row| {
            Ok(RelatedFileRow {
                file_path: row.get(0)?,
                relation: row.get(1)?,
                name: row.get(2)?,
                line: row.get::<_, i64>(3)? as usize,
            })
        })?;
        let mut seen = std::collections::BTreeSet::new();
        let mut out = Vec::new();
        for row in rows {
            let row = row?;
            if !seen.insert(row.file_path.clone()) {
                continue;
            }
            out.push(row);
            if out.len() >= bounded(limit) {
                break;
            }
        }
        Ok(out)
    }

    /// True when the collection has any symbol data at all.
    ///
    /// The retrieval layer needs this to decide between the native index and
    /// its degraded path, the same way `ast_index::is_available` did.
    pub fn has_symbol_index(&self, collection: &str) -> Result<bool, LexicalError> {
        let found: i64 = self.conn.query_row(
            "SELECT EXISTS(
                 SELECT 1 FROM symbol_defs d JOIN symbol_files f ON f.file_id = d.file_id
                 WHERE f.collection = ? LIMIT 1
             )",
            params![collection],
            |row| row.get(0),
        )?;
        Ok(found != 0)
    }

    /// Row counts per symbol table for one collection.
    pub fn symbol_index_stats(&self, collection: &str) -> Result<SymbolIndexStats, LexicalError> {
        let count = |table: &str| -> Result<usize, LexicalError> {
            let value: i64 = self.conn.query_row(
                &format!(
                    "SELECT COUNT(*) FROM {table} t
                     JOIN symbol_files f ON f.file_id = t.file_id
                     WHERE f.collection = ?"
                ),
                params![collection],
                |row| row.get(0),
            )?;
            Ok(value.max(0) as usize)
        };
        Ok(SymbolIndexStats {
            files: {
                let value: i64 = self.conn.query_row(
                    "SELECT COUNT(*) FROM symbol_files WHERE collection = ?",
                    params![collection],
                    |row| row.get(0),
                )?;
                value.max(0) as usize
            },
            definitions: count("symbol_defs")?,
            references: count("symbol_refs")?,
            edges: count("symbol_edges")?,
        })
    }

    fn query_definitions(
        &self,
        sql: &str,
        args: impl rusqlite::Params,
    ) -> Result<Vec<SymbolDefRow>, LexicalError> {
        let mut stmt = self.conn.prepare(sql)?;
        let rows = stmt.query_map(args, |row| {
            Ok(SymbolDefRow {
                file_path: row.get(0)?,
                name: row.get(1)?,
                qualified_name: row.get(2)?,
                parent_name: row.get(3)?,
                kind: row.get(4)?,
                language: row.get(5)?,
                signature: row.get(6)?,
                start_line: row.get::<_, i64>(7)? as usize,
                end_line: row.get::<_, i64>(8)? as usize,
                name_line: row.get::<_, i64>(9)? as usize,
                name_col: row.get::<_, i64>(10)? as usize,
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    fn query_references(
        &self,
        sql: &str,
        args: impl rusqlite::Params,
    ) -> Result<Vec<SymbolRefRow>, LexicalError> {
        let mut stmt = self.conn.prepare(sql)?;
        let rows = stmt.query_map(args, |row| {
            Ok(SymbolRefRow {
                file_path: row.get(0)?,
                name: row.get(1)?,
                kind: row.get(2)?,
                container: row.get(3)?,
                container_name: row.get(4)?,
                language: row.get(5)?,
                line: row.get::<_, i64>(6)? as usize,
                col: row.get::<_, i64>(7)? as usize,
                context: row.get(8)?,
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    fn query_edges(
        &self,
        sql: &str,
        args: impl rusqlite::Params,
    ) -> Result<Vec<SymbolEdgeRow>, LexicalError> {
        let mut stmt = self.conn.prepare(sql)?;
        let rows = stmt.query_map(args, |row| {
            Ok(SymbolEdgeRow {
                file_path: row.get(0)?,
                from_name: row.get(1)?,
                from_qualified: row.get(2)?,
                to_name: row.get(3)?,
                relation: row.get(4)?,
                language: row.get(5)?,
                line: row.get::<_, i64>(6)? as usize,
                context: row.get(7)?,
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }
}

/// One structurally related file (`related_files` input).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RelatedFileRow {
    /// Repo-relative path of the related file.
    pub file_path: String,
    /// `implementor` / `usage` / `reference`, strongest first.
    pub relation: String,
    /// A label for the link: the referencing symbol, or the query symbol.
    pub name: String,
    /// 1-based line the strongest link was seen on.
    pub line: usize,
}

impl SymbolRefRow {
    /// Typed view of the stored `kind` column.
    #[must_use]
    pub fn ref_kind(&self) -> RefKind {
        RefKind::parse(&self.kind)
    }
}

impl SymbolEdgeRow {
    /// Typed view of the stored `relation` column.
    #[must_use]
    pub fn edge_relation(&self) -> EdgeRelation {
        EdgeRelation::parse(&self.relation)
    }
}

/// The three per-file symbol tables, all keyed by `symbol_files.file_id`.
const SYMBOL_TABLES: [&str; 3] = ["symbol_defs", "symbol_refs", "symbol_edges"];

/// `file_path`/`language` live once per file, so every query re-attaches them
/// through this join rather than storing them on millions of rows.
const DEF_SELECT: &str = "SELECT f.file_path, d.name, d.qualified_name, d.parent_name, d.kind, \
     f.language, d.signature, d.start_line, d.end_line, d.name_line, d.name_col \
     FROM symbol_defs d JOIN symbol_files f ON f.file_id = d.file_id";

const REF_SELECT: &str = "SELECT f.file_path, r.name, r.kind, r.container, r.container_name, \
     f.language, r.line, r.col, r.context \
     FROM symbol_refs r JOIN symbol_files f ON f.file_id = r.file_id";

const EDGE_SELECT: &str = "SELECT f.file_path, e.from_name, e.from_qualified, e.to_name, \
     e.relation, f.language, e.line, e.context \
     FROM symbol_edges e JOIN symbol_files f ON f.file_id = e.file_id";

/// Hard ceiling on any symbol query so a hostile `limit` cannot ask SQLite for
/// the whole table (`/resolve` used to pass its limit straight through).
const MAX_SYMBOL_ROWS: usize = 1000;

fn bounded(limit: usize) -> usize {
    limit.min(MAX_SYMBOL_ROWS)
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

#[cfg(test)]
mod symbol_tests {
    use super::*;
    use crate::symbols::extract_symbols;

    const APP: &str = "class Greeter:\n\
                       \x20   def hello(self, name):\n\
                       \x20       return greet(name)\n\
                       \n\
                       def build_message(name):\n\
                       \x20   return Greeter().hello(name)\n";

    const OTHER: &str = "from app import Greeter\n\
                         \n\
                         class LoudGreeter(Greeter):\n\
                         \x20   def hello(self, name):\n\
                         \x20       return Greeter().hello(name).upper()\n";

    const KOTLIN: &str = "class Sink {\n\
                          \x20   fun drain() {\n\
                          \x20       Greeter().hello(\"x\")\n\
                          \x20   }\n\
                          }\n";

    fn seeded() -> LexicalIndex {
        let mut index = LexicalIndex::in_memory().expect("index");
        for (collection, path, language, source) in [
            ("repo", "app.py", "python", APP),
            ("repo", "other.py", "python", OTHER),
            ("repo", "Sink.kt", "kotlin", KOTLIN),
            // Same file path in a different collection: nothing below may
            // ever touch it.
            ("second", "app.py", "python", APP),
        ] {
            let file = extract_symbols(source, path, Some(language));
            index
                .replace_file_symbols(collection, &file)
                .expect("write symbols");
        }
        index
    }

    #[test]
    fn schema_creation_does_not_lock_out_the_read_only_reader() {
        // `rag-storage::RagDatabase::open_path` refuses `PRAGMA user_version`
        // above `SUPPORTED_SCHEMA_VERSION` (0) and opens this very file
        // (`~/.rag/rag.db`). Additive tables must leave the pragma alone.
        let dir = tempfile::tempdir().expect("temp dir");
        let path = dir.path().join("rag.db");
        let index = LexicalIndex::open(&path).expect("open");
        index.ensure_schema().expect("idempotent");
        let version: i32 = index
            .conn
            .query_row("PRAGMA user_version", [], |row| row.get(0))
            .expect("pragma");
        assert_eq!(version, 0);

        let tables: Vec<String> = index
            .conn
            .prepare("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")
            .expect("prepare")
            .query_map([], |row| row.get(0))
            .expect("query")
            .collect::<Result<_, _>>()
            .expect("rows");
        for expected in ["code_index", "symbol_defs", "symbol_edges", "symbol_refs"] {
            assert!(tables.contains(&expected.to_owned()), "missing {expected}");
        }
    }

    #[test]
    fn resolve_returns_definitions_with_spans_and_ranks_impl_blocks_last() {
        let index = seeded();
        let hits = index.resolve_symbol("repo", "hello", 10).expect("resolve");
        assert_eq!(hits.len(), 2);
        assert_eq!(hits[0].file_path, "app.py");
        assert_eq!(hits[0].qualified_name, "Greeter.hello");
        assert_eq!(hits[0].kind, "method");
        assert_eq!((hits[0].start_line, hits[0].end_line), (2, 3));
        assert_eq!(hits[0].signature, "def hello(self, name)");
        assert_eq!(hits[1].file_path, "other.py");

        let mut rust = LexicalIndex::in_memory().expect("index");
        let file = extract_symbols(
            "pub struct Greeter;\nimpl Greeter { pub fn hello(&self) {} }\n",
            "lib.rs",
            Some("rust"),
        );
        rust.replace_file_symbols("repo", &file).expect("write");
        let kinds: Vec<String> = rust
            .resolve_symbol("repo", "Greeter", 10)
            .expect("resolve")
            .into_iter()
            .map(|row| row.kind)
            .collect();
        assert_eq!(kinds, vec!["struct".to_owned(), "impl".to_owned()]);
    }

    #[test]
    fn resolve_by_qualified_name_and_by_file() {
        let index = seeded();
        let hits = index
            .resolve_qualified_symbol("repo", "LoudGreeter.hello", 10)
            .expect("resolve");
        assert_eq!(hits.len(), 1);
        assert_eq!(hits[0].file_path, "other.py");

        let in_file = index.file_definitions("repo", "app.py", 10).expect("file");
        assert_eq!(
            in_file
                .iter()
                .map(|row| row.qualified_name.as_str())
                .collect::<Vec<_>>(),
            vec!["Greeter", "Greeter.hello", "build_message"]
        );
    }

    #[test]
    fn usages_span_files_and_exclude_the_definition_site() {
        let index = seeded();
        let usages = index.symbol_usages("repo", "Greeter", 50).expect("usages");
        let seen: Vec<(String, usize, String)> = usages
            .iter()
            .map(|row| (row.file_path.clone(), row.line, row.kind.clone()))
            .collect();
        // Calls sort ahead of type/import references.
        assert_eq!(
            seen,
            vec![
                ("Sink.kt".to_owned(), 3, "call".to_owned()),
                ("app.py".to_owned(), 6, "call".to_owned()),
                ("other.py".to_owned(), 5, "call".to_owned()),
                ("other.py".to_owned(), 3, "type".to_owned()),
                ("other.py".to_owned(), 1, "import".to_owned()),
            ]
        );
        // `class Greeter:` on app.py line 1 is the definition, never a usage.
        assert!(!usages
            .iter()
            .any(|row| row.file_path == "app.py" && row.line == 1));
    }

    #[test]
    fn callers_carry_the_calling_function_and_a_renderable_line() {
        let index = seeded();
        let callers = index.symbol_callers("repo", "hello", 50).expect("callers");
        let rendered: Vec<(String, usize, String, String)> = callers
            .iter()
            .map(|row| {
                (
                    row.file_path.clone(),
                    row.line,
                    row.container.clone(),
                    row.context.clone(),
                )
            })
            .collect();
        assert_eq!(
            rendered,
            vec![
                (
                    "Sink.kt".to_owned(),
                    3,
                    "Sink.drain".to_owned(),
                    "Greeter().hello(\"x\")".to_owned()
                ),
                (
                    "app.py".to_owned(),
                    6,
                    "build_message".to_owned(),
                    "return Greeter().hello(name)".to_owned()
                ),
                (
                    "other.py".to_owned(),
                    5,
                    "LoudGreeter.hello".to_owned(),
                    "return Greeter().hello(name).upper()".to_owned()
                ),
            ]
        );
        // Only call sites, never type or import references.
        assert!(callers.iter().all(|row| row.ref_kind() == RefKind::Call));
    }

    #[test]
    fn callees_resolve_by_bare_and_qualified_container() {
        let index = seeded();
        let bare: Vec<String> = index
            .symbol_callees("repo", "hello", 50)
            .expect("callees")
            .into_iter()
            .map(|row| row.name)
            .collect();
        // `Greeter.hello` calls `greet`; `LoudGreeter.hello` calls
        // `Greeter`/`hello`/`upper`.
        assert!(bare.contains(&"greet".to_owned()));
        assert!(bare.contains(&"upper".to_owned()));

        let qualified: Vec<String> = index
            .symbol_callees_qualified("repo", "Greeter.hello", 50)
            .expect("callees")
            .into_iter()
            .map(|row| row.name)
            .collect();
        assert_eq!(qualified, vec!["greet".to_owned()]);
    }

    #[test]
    fn implementations_and_supertypes_are_inverses() {
        let index = seeded();
        let implementors = index
            .symbol_implementations("repo", "Greeter", 10)
            .expect("implementations");
        assert_eq!(implementors.len(), 1);
        assert_eq!(implementors[0].from_name, "LoudGreeter");
        assert_eq!(implementors[0].file_path, "other.py");
        assert_eq!(implementors[0].edge_relation(), EdgeRelation::Inherits);

        let supertypes = index
            .symbol_supertypes("repo", "LoudGreeter", 10)
            .expect("supertypes");
        assert_eq!(
            supertypes
                .iter()
                .map(|row| row.to_name.as_str())
                .collect::<Vec<_>>(),
            vec!["Greeter"]
        );

        let imports = index
            .symbol_edges_to("repo", "Greeter", EdgeRelation::Imports, 10)
            .expect("imports");
        assert_eq!(imports.len(), 1);
        assert_eq!(imports[0].file_path, "other.py");
    }

    #[test]
    fn related_files_keeps_one_row_per_file_with_the_strongest_relation() {
        let index = seeded();
        let related = index
            .symbol_related_files("repo", "Greeter", 10)
            .expect("related");
        assert_eq!(
            related
                .iter()
                .map(|row| (row.file_path.as_str(), row.relation.as_str()))
                .collect::<Vec<_>>(),
            // other.py both subclasses and calls: the subclass link wins.
            vec![
                ("other.py", "implementor"),
                ("Sink.kt", "usage"),
                ("app.py", "usage"),
            ]
        );
    }

    #[test]
    fn per_file_delete_removes_exactly_that_files_rows() {
        let index = seeded();
        let before = index.symbol_index_stats("repo").expect("stats");
        let other_before = index.symbol_index_stats("second").expect("stats");

        index
            .delete_symbols_by_file("repo", "other.py")
            .expect("delete");

        // Nothing from other.py survives...
        assert!(index
            .file_definitions("repo", "other.py", 100)
            .expect("defs")
            .is_empty());
        assert!(index
            .symbol_usages("repo", "Greeter", 100)
            .expect("usages")
            .iter()
            .all(|row| row.file_path != "other.py"));
        assert!(index
            .symbol_implementations("repo", "Greeter", 100)
            .expect("impls")
            .is_empty());

        // ...and everything else does, in both collections.
        assert!(!index
            .file_definitions("repo", "app.py", 100)
            .expect("defs")
            .is_empty());
        assert!(!index
            .file_definitions("repo", "Sink.kt", 100)
            .expect("defs")
            .is_empty());
        assert_eq!(
            index.symbol_index_stats("second").expect("stats"),
            other_before,
            "the same path in another collection must be untouched"
        );

        let after = index.symbol_index_stats("repo").expect("stats");
        assert!(after.definitions < before.definitions);
        assert!(after.references < before.references);
        assert!(after.edges < before.edges);
    }

    #[test]
    fn rewriting_a_file_replaces_rather_than_duplicates() {
        let mut index = seeded();
        let before = index.symbol_index_stats("repo").expect("stats");
        let file = extract_symbols(APP, "app.py", Some("python"));
        index
            .replace_file_symbols("repo", &file)
            .expect("rewrite same content");
        assert_eq!(index.symbol_index_stats("repo").expect("stats"), before);

        // A shrinking edit drops the stale rows.
        let shrunk = extract_symbols(
            "def build_message(name):\n    return name\n",
            "app.py",
            Some("python"),
        );
        index
            .replace_file_symbols("repo", &shrunk)
            .expect("rewrite");
        assert_eq!(
            index
                .file_definitions("repo", "app.py", 100)
                .expect("defs")
                .into_iter()
                .map(|row| row.qualified_name)
                .collect::<Vec<_>>(),
            vec!["build_message".to_owned()]
        );
    }

    #[test]
    fn language_scoped_delete_leaves_other_languages_alone() {
        let index = seeded();
        index
            .delete_symbols_by_language("repo", "kotlin")
            .expect("delete");
        assert!(index
            .file_definitions("repo", "Sink.kt", 100)
            .expect("defs")
            .is_empty());
        assert!(!index
            .file_definitions("repo", "app.py", 100)
            .expect("defs")
            .is_empty());
    }

    #[test]
    fn collection_delete_and_availability_probe() {
        let index = seeded();
        assert!(index.has_symbol_index("repo").expect("probe"));
        assert!(!index.has_symbol_index("missing").expect("probe"));

        index
            .delete_symbols_by_collection("repo")
            .expect("delete collection");
        assert!(!index.has_symbol_index("repo").expect("probe"));
        assert_eq!(
            index.symbol_index_stats("repo").expect("stats"),
            SymbolIndexStats::default()
        );
        assert!(index.has_symbol_index("second").expect("probe"));
    }

    #[test]
    fn queries_are_bounded_even_for_a_hostile_limit() {
        let index = seeded();
        // `usize::MAX` used to reach arithmetic that panicked in the CLI
        // bridge; here it must simply clamp.
        assert!(
            index
                .symbol_usages("repo", "Greeter", usize::MAX)
                .expect("usages")
                .len()
                <= MAX_SYMBOL_ROWS
        );
        assert!(
            index
                .resolve_symbol("repo", "hello", usize::MAX)
                .expect("resolve")
                .len()
                <= MAX_SYMBOL_ROWS
        );
        assert!(
            index
                .symbol_related_files("repo", "Greeter", usize::MAX)
                .expect("related")
                .len()
                <= MAX_SYMBOL_ROWS
        );
    }

    #[test]
    fn code_chunks_and_symbols_share_the_database_without_interfering() {
        let mut index = seeded();
        index
            .upsert_code_chunks(&[CodeDocument {
                chunk_id: "c1".to_owned(),
                collection: "repo".to_owned(),
                file_path: "app.py".to_owned(),
                name: "hello".to_owned(),
                parent_name: "Greeter".to_owned(),
                chunk_type: "method".to_owned(),
                language: "python".to_owned(),
                start_line: 2,
                end_line: 3,
                code: "def hello(self, name):\n    return greet(name)".to_owned(),
            }])
            .expect("chunk");

        index
            .delete_code_chunks_by_file("repo", "app.py")
            .expect("delete chunks");
        // Deleting chunks must not delete symbols, and vice versa.
        assert!(!index
            .file_definitions("repo", "app.py", 100)
            .expect("defs")
            .is_empty());

        index
            .delete_symbols_by_file("repo", "app.py")
            .expect("delete symbols");
        assert!(index
            .search_code_chunks("hello", Some("repo"), 5)
            .expect("search")
            .is_empty());
    }
}
