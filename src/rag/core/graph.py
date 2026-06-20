"""Code knowledge graph built from LSP/metadata at index time.

Nodes = code symbols (functions, classes, files).
Edges = calls, references, inheritance, imports.

Supports:
- Multi-hop traversal for "trace the flow" queries
- Community detection (Louvain) for module clustering
- Serialization to disk for fast reload without re-indexing
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx
import structlog

from rag.config import RAG_HOME

logger = structlog.get_logger()

GRAPH_CACHE_PATH = RAG_HOME / "code_graph.pkl"


@dataclass
class Community:
    """A cluster of related code symbols."""

    id: int
    members: list[str] = field(default_factory=list)  # node IDs
    label: str = ""  # LLM-generated summary
    files: list[str] = field(default_factory=list)  # unique file paths


class CodeGraph:
    """In-memory code knowledge graph with community detection."""

    def __init__(self) -> None:
        self.graph = nx.DiGraph()
        self.communities: dict[int, Community] = {}
        self._node_to_community: dict[str, int] = {}

    def build_from_chunks(self, chunks: list[dict[str, Any]]) -> None:
        """Build graph from Qdrant chunk payloads collected at index time."""
        self.graph.clear()
        self.communities.clear()
        self._node_to_community.clear()

        for chunk in chunks:
            node_id = self._make_node_id(chunk)
            if not node_id:
                continue

            self.graph.add_node(node_id, **{
                "file_path": chunk.get("file_path", ""),
                "name": chunk.get("name", ""),
                "parent_name": chunk.get("parent_name", ""),
                "chunk_type": chunk.get("chunk_type", ""),
                "language": chunk.get("language", ""),
                "patterns": chunk.get("patterns", []),
                "domains": chunk.get("domains", []),
            })

            # Edges from call graph
            for call in chunk.get("calls", []):
                call_id = call if ":" in call else f"?:{call}"
                self.graph.add_edge(node_id, call_id, relation="calls")

            for caller in chunk.get("called_by", []):
                caller_id = caller if ":" in caller else f"?:{caller}"
                self.graph.add_edge(caller_id, node_id, relation="calls")

            # Edges from inheritance
            for parent in chunk.get("inherits_from", []):
                parent_id = f"?:{parent}"
                self.graph.add_edge(node_id, parent_id, relation="inherits")

            # Edges from imports (file-level)
            for imp in chunk.get("imports", []):
                imp_id = f"import:{imp}"
                self.graph.add_edge(node_id, imp_id, relation="imports")

        logger.info(
            "graph_built",
            nodes=self.graph.number_of_nodes(),
            edges=self.graph.number_of_edges(),
        )

    def detect_communities(self) -> dict[int, Community]:
        """Run Louvain community detection. Returns communities dict."""
        if self.graph.number_of_nodes() == 0:
            return {}

        # Louvain works on undirected graphs
        undirected = self.graph.to_undirected()
        try:
            partition = nx.community.louvain_communities(undirected, seed=42)
        except Exception as e:
            logger.warning("community_detection_failed", error=str(e))
            return {}

        self.communities.clear()
        self._node_to_community.clear()

        for comm_id, members in enumerate(partition):
            member_list = sorted(members)
            files = sorted({
                self.graph.nodes[n].get("file_path", "")
                for n in member_list
                if n in self.graph.nodes and self.graph.nodes[n].get("file_path")
            })

            community = Community(
                id=comm_id,
                members=member_list,
                files=files,
            )
            self.communities[comm_id] = community

            for node in member_list:
                self._node_to_community[node] = comm_id

        logger.info("communities_detected", count=len(self.communities))
        return self.communities

    def get_community_for_node(self, node_id: str) -> int | None:
        """Get community ID for a node."""
        return self._node_to_community.get(node_id)

    def get_community_members(self, community_id: int) -> list[str]:
        """Get all node IDs in a community."""
        comm = self.communities.get(community_id)
        return comm.members if comm else []

    def traverse(
        self,
        start_node: str,
        max_hops: int = 3,
        direction: str = "both",
    ) -> list[str]:
        """Multi-hop traversal from a start node. Returns connected node IDs."""
        if start_node not in self.graph:
            # Try fuzzy match by name
            candidates = [
                n for n in self.graph.nodes
                if start_node.lower() in n.lower()
            ]
            if not candidates:
                return []
            start_node = candidates[0]

        visited: set[str] = set()
        frontier = {start_node}

        for _ in range(max_hops):
            next_frontier: set[str] = set()
            for node in frontier:
                if node in visited:
                    continue
                visited.add(node)

                if direction in ("out", "both"):
                    for succ in self.graph.successors(node):
                        if self.graph.edges[node, succ].get("relation") in ("calls", "inherits"):
                            next_frontier.add(succ)
                if direction in ("in", "both"):
                    for pred in self.graph.predecessors(node):
                        if self.graph.edges[pred, node].get("relation") in ("calls", "inherits"):
                            next_frontier.add(pred)

            frontier = next_frontier - visited
            if not frontier:
                break

        visited.discard(start_node)
        return sorted(visited)

    def get_callers(self, node_id: str) -> list[str]:
        """Who calls this node?"""
        if node_id not in self.graph:
            return []
        return [
            pred for pred in self.graph.predecessors(node_id)
            if self.graph.edges[pred, node_id].get("relation") == "calls"
        ]

    def get_callees(self, node_id: str) -> list[str]:
        """What does this node call?"""
        if node_id not in self.graph:
            return []
        return [
            succ for succ in self.graph.successors(node_id)
            if self.graph.edges[node_id, succ].get("relation") == "calls"
        ]

    def save(self, path: Path | None = None) -> None:
        """Serialize graph to disk."""
        path = path or GRAPH_CACHE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "graph": nx.node_link_data(self.graph),
            "communities": {
                k: {"id": v.id, "members": v.members, "label": v.label, "files": v.files}
                for k, v in self.communities.items()
            },
            "node_to_community": self._node_to_community,
        }
        with open(path, "wb") as f:
            pickle.dump(data, f)
        logger.info("graph_saved", path=str(path))

    def load(self, path: Path | None = None) -> bool:
        """Load graph from disk. Returns True if loaded successfully."""
        path = path or GRAPH_CACHE_PATH
        if not path.exists():
            return False
        try:
            with open(path, "rb") as f:
                data = pickle.load(f)
            self.graph = nx.node_link_graph(data["graph"])
            self.communities = {
                k: Community(**v) for k, v in data["communities"].items()
            }
            self._node_to_community = data["node_to_community"]
            logger.info(
                "graph_loaded",
                nodes=self.graph.number_of_nodes(),
                communities=len(self.communities),
            )
            return True
        except Exception as e:
            logger.warning("graph_load_failed", error=str(e))
            return False

    def stats(self) -> dict[str, Any]:
        return {
            "nodes": self.graph.number_of_nodes(),
            "edges": self.graph.number_of_edges(),
            "communities": len(self.communities),
            "connected_components": nx.number_weakly_connected_components(self.graph) if self.graph.number_of_nodes() > 0 else 0,
        }

    @staticmethod
    def _make_node_id(chunk: dict[str, Any]) -> str:
        """Create a unique node ID from chunk metadata."""
        fp = chunk.get("file_path", "")
        name = chunk.get("name", "")
        parent = chunk.get("parent_name", "")
        if not fp or not name:
            return ""
        if parent:
            return f"{fp}:{parent}.{name}"
        return f"{fp}:{name}"


# Singleton for query-time access
_graph: CodeGraph | None = None


def get_graph() -> CodeGraph:
    """Get or create the singleton code graph."""
    global _graph
    if _graph is None:
        _graph = CodeGraph()
        _graph.load()  # Try loading from cache
    return _graph
