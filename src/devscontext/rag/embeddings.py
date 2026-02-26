"""Embedding providers for RAG-based document search.

This module provides abstract and concrete embedding providers that can
generate vector embeddings for text. These embeddings are used for semantic
similarity search in the document index.

Supported providers:
- local: Uses sentence-transformers (all-MiniLM-L6-v2 by default)
- openai: Uses OpenAI's text-embedding-3-small
- ollama: Uses locally-hosted Ollama models (mxbai-embed-large, nomic-embed-text)

Example:
    provider = LocalEmbeddingProvider("all-MiniLM-L6-v2")
    embeddings = await provider.embed(["Hello world", "How are you?"])
    query_emb = await provider.embed_query("greeting")
"""

from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from typing import Any

from devscontext.logging import get_logger

logger = get_logger(__name__)


class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers.

    Embedding providers generate vector representations of text that can
    be used for semantic similarity comparison.
    """

    def __init__(self, model: str) -> None:
        """Initialize the embedding provider.

        Args:
            model: Model identifier to use for embeddings.
        """
        self.model = model
        self._dimension: int | None = None

    @property
    def dimension(self) -> int:
        """Return the embedding dimension.

        Returns:
            Number of dimensions in the embedding vectors.

        Raises:
            RuntimeError: If dimension is not yet known (call embed first).
        """
        if self._dimension is None:
            raise RuntimeError("Dimension unknown until first embedding is generated")
        return self._dimension

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of texts.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors, one per input text.
        """
        ...

    async def embed_query(self, query: str) -> list[float]:
        """Generate embedding for a single query.

        This is a convenience method that wraps embed() for single queries.
        Some providers may override this for query-specific optimizations.

        Args:
            query: Query text to embed.

        Returns:
            Embedding vector for the query.
        """
        embeddings = await self.embed([query])
        return embeddings[0]


class LocalEmbeddingProvider(EmbeddingProvider):
    """Embedding provider using sentence-transformers.

    Uses locally-running models via the sentence-transformers library.
    The default model (all-MiniLM-L6-v2) is fast and produces 384-dimensional
    embeddings suitable for semantic similarity tasks.

    Requires: pip install sentence-transformers
    """

    def __init__(self, model: str = "all-MiniLM-L6-v2") -> None:
        """Initialize with a sentence-transformers model.

        Args:
            model: Model name from HuggingFace (default: all-MiniLM-L6-v2).
        """
        super().__init__(model)
        self._model_instance = None

    def _load_model(self) -> Any:  # Returns SentenceTransformer
        """Lazy-load the sentence-transformers model."""
        if self._model_instance is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:
                raise ImportError(
                    "sentence-transformers not installed. "
                    "Install with: pip install devscontext[rag]"
                ) from e

            logger.info(
                "Loading sentence-transformers model",
                extra={"model": self.model},
            )
            self._model_instance = SentenceTransformer(self.model)
            self._dimension = self._model_instance.get_sentence_embedding_dimension()

        return self._model_instance

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings using sentence-transformers.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors.
        """
        if not texts:
            return []

        model = self._load_model()

        # Run in thread pool to avoid blocking async event loop
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(
            None,
            lambda: model.encode(texts, show_progress_bar=False, convert_to_numpy=True),
        )

        # Convert numpy array to list of lists
        return [emb.tolist() for emb in embeddings]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Embedding provider using OpenAI's embedding API.

    Uses OpenAI's text-embedding-3-small model by default, which produces
    1536-dimensional embeddings with excellent semantic quality.

    Requires: pip install openai
    Environment: OPENAI_API_KEY must be set.
    """

    def __init__(self, model: str = "text-embedding-3-small") -> None:
        """Initialize with an OpenAI embedding model.

        Args:
            model: OpenAI embedding model name (default: text-embedding-3-small).
        """
        super().__init__(model)
        self._client = None

    def _get_client(self) -> Any:  # Returns AsyncOpenAI
        """Lazy-load the OpenAI client."""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as e:
                raise ImportError(
                    "openai package not installed. Install with: pip install devscontext[openai]"
                ) from e

            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY environment variable not set")

            self._client = AsyncOpenAI(api_key=api_key)

        return self._client

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings using OpenAI's API.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors.
        """
        if not texts:
            return []

        client = self._get_client()

        # OpenAI API accepts batch requests
        response = await client.embeddings.create(
            model=self.model,
            input=texts,
        )

        # Extract embeddings and set dimension
        embeddings = [item.embedding for item in response.data]
        if embeddings and self._dimension is None:
            self._dimension = len(embeddings[0])

        return embeddings


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Embedding provider using locally-hosted Ollama models.

    Uses Ollama's embedding API for models like mxbai-embed-large or
    nomic-embed-text. Requires Ollama to be running locally.

    Default model: mxbai-embed-large (1024 dimensions)
    Alternative: nomic-embed-text (768 dimensions)

    Requires: Ollama installed and running (https://ollama.ai)
    """

    def __init__(
        self, model: str = "mxbai-embed-large", base_url: str = "http://localhost:11434"
    ) -> None:
        """Initialize with an Ollama embedding model.

        Args:
            model: Ollama model name (default: mxbai-embed-large).
            base_url: Ollama API base URL (default: http://localhost:11434).
        """
        super().__init__(model)
        self.base_url = os.environ.get("OLLAMA_BASE_URL", base_url)
        self._client = None

    def _get_client(self) -> Any:  # Returns httpx.AsyncClient
        """Lazy-load the HTTP client."""
        if self._client is None:
            try:
                import httpx
            except ImportError as e:
                raise ImportError("httpx not installed (should be a core dependency)") from e

            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=60.0,  # Embedding can take time for large batches
            )

        return self._client

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings using Ollama's API.

        Note: Ollama doesn't support batch embedding, so we make
        individual requests for each text.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors.
        """
        if not texts:
            return []

        client = self._get_client()
        embeddings = []

        for text in texts:
            response = await client.post(
                "/api/embeddings",
                json={"model": self.model, "prompt": text},
            )
            response.raise_for_status()

            data = response.json()
            embedding = data.get("embedding", [])
            embeddings.append(embedding)

            # Set dimension from first response
            if self._dimension is None and embedding:
                self._dimension = len(embedding)

        return embeddings

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
