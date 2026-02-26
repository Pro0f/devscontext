"""RAG (Retrieval-Augmented Generation) support for local documentation.

This module provides optional embedding-based search for the LocalDocsAdapter.
When enabled, it uses semantic similarity instead of keyword matching for
finding relevant documentation sections.

The RAG feature is optional and requires additional dependencies:
    pip install devscontext[rag]

Example usage:
    from devscontext.rag import DocumentIndex, get_embedding_provider

    # Create embedding provider
    provider = get_embedding_provider(rag_config)

    # Create and load index
    index = DocumentIndex(rag_config.index_path)
    index.load()

    # Search for similar documents
    query_embedding = await provider.embed_query("payment webhook retry logic")
    results = index.search(query_embedding, top_k=10, threshold=0.3)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from devscontext.models import RagConfig
    from devscontext.rag.embeddings import EmbeddingProvider

# Lazy imports to avoid loading heavy dependencies unless RAG is used
_RAG_AVAILABLE: bool | None = None


def is_rag_available() -> bool:
    """Check if RAG dependencies are installed.

    Returns:
        True if sentence-transformers and numpy are available.
    """
    global _RAG_AVAILABLE
    if _RAG_AVAILABLE is None:
        try:
            import numpy  # noqa: F401
            import sentence_transformers  # noqa: F401

            _RAG_AVAILABLE = True
        except ImportError:
            _RAG_AVAILABLE = False
    return _RAG_AVAILABLE


def get_embedding_provider(config: RagConfig) -> EmbeddingProvider:
    """Factory function to create an embedding provider based on config.

    Args:
        config: RAG configuration specifying provider and model.

    Returns:
        An EmbeddingProvider instance.

    Raises:
        ImportError: If RAG dependencies are not installed.
        ValueError: If the embedding provider is not supported.
    """
    if not is_rag_available():
        raise ImportError(
            "RAG dependencies not installed. Install with: pip install devscontext[rag]"
        )

    from devscontext.rag.embeddings import (
        LocalEmbeddingProvider,
        OllamaEmbeddingProvider,
        OpenAIEmbeddingProvider,
    )

    providers: dict[str, type[EmbeddingProvider]] = {
        "local": LocalEmbeddingProvider,
        "openai": OpenAIEmbeddingProvider,
        "ollama": OllamaEmbeddingProvider,
    }

    provider_cls = providers.get(config.embedding_provider)
    if provider_cls is None:
        raise ValueError(
            f"Unknown embedding provider: {config.embedding_provider}. "
            f"Supported: {', '.join(providers.keys())}"
        )

    return provider_cls(config.embedding_model)


__all__ = [
    "DocumentIndex",
    "EmbeddingProvider",
    "get_embedding_provider",
    "is_rag_available",
]


def __getattr__(name: str) -> type:
    """Lazy import of RAG classes to avoid loading dependencies at import time."""
    if name == "DocumentIndex":
        from devscontext.rag.index import DocumentIndex

        return DocumentIndex
    if name == "EmbeddingProvider":
        from devscontext.rag.embeddings import EmbeddingProvider

        return EmbeddingProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
