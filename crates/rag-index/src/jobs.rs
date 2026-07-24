use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::{SystemTime, UNIX_EPOCH},
};

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum JobStatus {
    Queued,
    Scanning,
    Running,
    Completed,
    Failed,
    Interrupted,
    Cancelled,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct JobProgress {
    pub status: JobStatus,
    pub current_file: String,
    pub files_processed: usize,
    pub total_files: usize,
    pub chunks_seen: usize,
    pub chunks_total_estimate: usize,
    pub chunks_indexed: usize,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct IndexJob {
    pub job_id: String,
    pub repo_path: String,
    pub status: JobStatus,
    pub progress: JobProgress,
    pub started_at: f64,
    pub updated_at: f64,
    pub finished_at: Option<f64>,
    pub error: Option<String>,
}

impl IndexJob {
    pub fn new(job_id: impl Into<String>, repo_path: impl Into<String>) -> Self {
        let now = now();
        Self {
            job_id: job_id.into(),
            repo_path: repo_path.into(),
            status: JobStatus::Queued,
            progress: JobProgress {
                status: JobStatus::Queued,
                current_file: String::new(),
                files_processed: 0,
                total_files: 0,
                chunks_seen: 0,
                chunks_total_estimate: 0,
                chunks_indexed: 0,
            },
            started_at: now,
            updated_at: now,
            finished_at: None,
            error: None,
        }
    }

    pub fn mark_interrupted(&mut self) {
        if matches!(
            self.status,
            JobStatus::Queued | JobStatus::Scanning | JobStatus::Running
        ) {
            self.status = JobStatus::Interrupted;
            self.finished_at = Some(now());
            self.error = Some("Daemon restarted while this job was active.".to_owned());
            self.updated_at = now();
        }
    }
}

#[derive(Debug, Clone, Default)]
pub struct CancellationToken {
    cancelled: Arc<AtomicBool>,
}

impl CancellationToken {
    pub fn cancel(&self) {
        self.cancelled.store(true, Ordering::SeqCst);
    }

    pub fn is_cancelled(&self) -> bool {
        self.cancelled.load(Ordering::SeqCst)
    }
}

fn now() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs_f64())
        .unwrap_or_default()
}
