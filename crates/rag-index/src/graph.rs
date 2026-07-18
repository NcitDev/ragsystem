use std::collections::{BTreeMap, BTreeSet, VecDeque};

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AstDefinition {
    pub file_path: String,
    pub line: usize,
    pub name: String,
    pub kind: String,
    pub signature: String,
    pub start_line: usize,
    pub end_line: usize,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AstUsage {
    pub file_path: String,
    pub line: usize,
    pub name: String,
    pub context: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AstReference {
    pub from: String,
    pub to: String,
    pub relation: GraphRelation,
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GraphRelation {
    Calls,
    CalledBy,
    Inherits,
    Imports,
    References,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct GraphNode {
    pub id: String,
    pub file_path: String,
    pub name: String,
    pub parent_name: String,
    pub chunk_type: String,
    pub language: String,
    pub patterns: Vec<String>,
    pub domains: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CallTreeEdge {
    pub caller: String,
    pub callee: String,
    pub depth: usize,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct AstGraph {
    pub nodes: BTreeMap<String, GraphNode>,
    pub edges: Vec<AstReference>,
}

impl AstGraph {
    pub fn upsert_node(&mut self, node: GraphNode) {
        self.nodes.insert(node.id.clone(), node);
    }

    pub fn add_edge(
        &mut self,
        from: impl Into<String>,
        to: impl Into<String>,
        relation: GraphRelation,
    ) {
        let edge = AstReference {
            from: from.into(),
            to: to.into(),
            relation,
        };
        if !self.edges.contains(&edge) {
            self.edges.push(edge);
            self.edges
                .sort_by(|a, b| (&a.from, &a.to, &a.relation).cmp(&(&b.from, &b.to, &b.relation)));
        }
    }

    pub fn callees(&self, node: &str) -> Vec<String> {
        self.edges
            .iter()
            .filter(|edge| edge.from == node && edge.relation == GraphRelation::Calls)
            .map(|edge| edge.to.clone())
            .collect()
    }

    pub fn callers(&self, node: &str) -> Vec<String> {
        self.edges
            .iter()
            .filter(|edge| edge.to == node && edge.relation == GraphRelation::Calls)
            .map(|edge| edge.from.clone())
            .collect()
    }

    pub fn traverse(&self, start: &str, max_hops: usize) -> Vec<String> {
        let mut seen = BTreeSet::new();
        let mut queue = VecDeque::from([(start.to_owned(), 0usize)]);
        while let Some((node, depth)) = queue.pop_front() {
            if depth >= max_hops {
                continue;
            }
            for edge in self
                .edges
                .iter()
                .filter(|edge| edge.from == node || edge.to == node)
            {
                if !matches!(
                    edge.relation,
                    GraphRelation::Calls | GraphRelation::Inherits
                ) {
                    continue;
                }
                let next = if edge.from == node {
                    &edge.to
                } else {
                    &edge.from
                };
                if next != start && seen.insert(next.clone()) {
                    queue.push_back((next.clone(), depth + 1));
                }
            }
        }
        seen.into_iter().collect()
    }
}
