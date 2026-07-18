//! Shared wire contracts for the Rust migration.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

/// Deterministic retrieval strategies supported by both runtimes.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SearchStrategy {
    /// Hierarchical module to file to chunk drill-down.
    #[default]
    LodDrill,
    /// Flat filtered multi-query retrieval.
    Hybrid,
    /// Structural caller/callee traversal.
    GraphWalk,
    /// Project/module summary retrieval.
    Global,
}

impl SearchStrategy {
    /// Parse current names and legacy aliases emitted by older planners.
    #[must_use]
    pub fn from_compatible_name(value: &str) -> Self {
        match value {
            "hybrid" | "filtered" | "naive" | "aggregate" => Self::Hybrid,
            "graph_walk" => Self::GraphWalk,
            "global" => Self::Global,
            _ => Self::LodDrill,
        }
    }
}

/// Typed, application-owned search plan produced by all planner adapters.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SearchPlan {
    /// Expanded queries, in stable execution order.
    #[serde(default)]
    pub queries: Vec<String>,
    /// Validated payload filters.
    #[serde(default)]
    pub filters: Map<String, Value>,
    /// Deterministic execution strategy.
    #[serde(default)]
    pub strategy: SearchStrategy,
    /// Requested result count.
    #[serde(default = "default_top_k")]
    pub top_k: usize,
}

impl Default for SearchPlan {
    fn default() -> Self {
        Self {
            queries: Vec::new(),
            filters: Map::new(),
            strategy: SearchStrategy::LodDrill,
            top_k: default_top_k(),
        }
    }
}

const fn default_top_k() -> usize {
    20
}

/// Serialized shape of the public Python `GET /health` response.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct HealthResponse {
    /// Overall daemon health (`ok` or `degraded` in the Python implementation).
    pub status: String,
    /// Per-component state, kept ordered for deterministic fixture output.
    pub components: BTreeMap<String, String>,
}

impl HealthResponse {
    /// Health reported by the bounded R0 daemon before external components are ported.
    #[must_use]
    pub fn r0() -> Self {
        Self {
            status: "degraded".to_owned(),
            components: BTreeMap::from([
                ("embedder".to_owned(), "not_initialized".to_owned()),
                ("ollama".to_owned(), "unavailable".to_owned()),
                ("qdrant".to_owned(), "error".to_owned()),
                ("reranker".to_owned(), "disabled".to_owned()),
            ]),
        }
    }
}

/// Stable error envelope used by the Python HTTP exception handler.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ErrorResponse {
    /// Human-readable error.
    pub error: String,
    /// Machine-readable error code.
    pub code: String,
    /// Optional safe detail.
    pub detail: Option<String>,
}

#[cfg(test)]
mod tests {
    use super::{ErrorResponse, HealthResponse};

    #[test]
    fn health_serialization_matches_python_shape() {
        let value = serde_json::to_value(HealthResponse::r0()).expect("health serializes");
        assert_eq!(value["status"], "degraded");
        assert!(value["components"].is_object());
        assert_eq!(value["components"]["reranker"], "disabled");
    }

    #[test]
    fn captured_health_fixture_remains_deserializable() {
        let fixture = include_str!("../../../tests/contracts/health.json");
        let captured: HealthResponse = serde_json::from_str(fixture).expect("valid health fixture");
        assert_eq!(captured.status, "ok");
        assert_eq!(captured.components["qdrant"], "ok");
    }

    #[test]
    fn captured_auth_error_uses_stable_envelope() {
        let fixture = include_str!("../../../tests/contracts/auth-error.json");
        let captured: ErrorResponse = serde_json::from_str(fixture).expect("valid error fixture");
        assert_eq!(captured.code, "HTTP_ERROR");
        assert_eq!(captured.detail, None);
    }
}
