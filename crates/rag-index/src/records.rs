use std::path::Path;

use serde::{Deserialize, Serialize};

use crate::discovery::short_sha256;

pub const SUMMARY_COLLECTION: &str = "module_summaries";
pub const LOD_L0_COLLECTION: &str = "lod_l0";
pub const LOD_L1_COLLECTION: &str = "lod_l1";
pub const VOCAB_SUFFIX: &str = "_vocab";

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SummaryRecord {
    pub collection: String,
    pub id: String,
    pub content: String,
    pub chunk_type: String,
    pub module_path: String,
    pub file_path: String,
    pub member_count: Option<usize>,
    pub file_count: Option<usize>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct VocabRecord {
    pub file_path: String,
    pub name: String,
    pub summary: String,
    pub repo: String,
    pub language: String,
    pub chunk_type: String,
    pub content_hash: String,
    pub chunk_id: String,
}

pub fn vocab_collection_for(code_collection: &str) -> String {
    format!("{code_collection}{VOCAB_SUFFIX}")
}

impl VocabRecord {
    pub fn new(
        repo: impl Into<String>,
        file_path: impl Into<String>,
        summary: impl Into<String>,
    ) -> Self {
        let repo = repo.into();
        let file_path = file_path.into();
        let summary = summary.into();
        let name = Path::new(&file_path)
            .file_stem()
            .and_then(|value| value.to_str())
            .unwrap_or("")
            .to_owned();
        let language = Path::new(&file_path)
            .extension()
            .and_then(|value| value.to_str())
            .unwrap_or("")
            .to_owned();
        let content_hash = short_sha256(format!("{file_path}:{summary}").as_bytes());
        Self {
            chunk_id: format!("{repo}:vocab:{file_path}"),
            file_path,
            name,
            summary,
            repo,
            language,
            chunk_type: "vocab_summary".to_owned(),
            content_hash,
        }
    }
}
