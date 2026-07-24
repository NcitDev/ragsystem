//! Phase R3 indexing and structural-data foundation.
//!
//! This crate intentionally stops at deterministic local contracts. It does not
//! own Qdrant, retrieval orchestration, CLI, or TUI behavior.

pub mod chunker;
pub mod discovery;
pub mod enrich;
pub mod enrich_python;
pub mod graph;
pub mod jobs;
pub mod lexical;
pub mod lsp;
pub mod records;

pub use chunker::{chunk_code, supported_extensions, supported_languages, Chunk, ChunkType};
pub use discovery::{diff_index_state, discover_files, file_hash, IndexDiff, IndexState};
pub use graph::{
    AstDefinition, AstGraph, AstReference, AstUsage, CallTreeEdge, GraphNode, GraphRelation,
};
pub use jobs::{CancellationToken, IndexJob, JobProgress, JobStatus};
pub use lexical::{CodeDocument, CodeSearchHit, LexicalIndex};
pub use lsp::{detect_lsp_servers, LspServerSpec, LspServerStatus};
pub use records::{SummaryRecord, VocabRecord};
