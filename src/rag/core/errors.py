"""Custom error hierarchy for the RAG system."""


class RAGError(Exception):
    """Base error for all RAG operations."""


class EmbeddingError(RAGError):
    """Error during embedding generation."""


class VectorStoreError(RAGError):
    """Error during vector store operations."""


class IndexError(RAGError):
    """Error during indexing."""


class LSPError(RAGError):
    """Error during LSP operations."""


class ConfigError(RAGError):
    """Error in configuration."""


class RerankerError(RAGError):
    """Error during reranking."""
