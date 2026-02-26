"""Document index for RAG-based semantic search.

This module provides a document index that stores section metadata and
embeddings, enabling semantic similarity search using cosine similarity.

The index is stored as a JSON file with the following structure:
{
    "model": "all-MiniLM-L6-v2",
    "dimension": 384,
    "indexed_at": "2024-03-20T12:00:00Z",
    "sections": [
        {"file_path": "...", "section_title": "...", "content": "...", "doc_type": "..."}
    ],
    "embeddings": [[0.1, 0.2, ...], ...]
}

Example:
    index = DocumentIndex(".devscontext/doc_index.json")
    index.load()

    # Search for similar sections
    results = index.search(query_embedding, top_k=10, threshold=0.3)
    for section, score in results:
        print(f"{section.section_title}: {score:.3f}")
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from devscontext.logging import get_logger

logger = get_logger(__name__)


@dataclass
class IndexedSection:
    """A document section stored in the index.

    This mirrors ParsedSection from local_docs but is independent to avoid
    circular imports and allow the index to work without the full adapter.
    """

    file_path: str
    section_title: str | None
    content: str
    doc_type: str  # "architecture", "standards", "adr", "other"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "file_path": self.file_path,
            "section_title": self.section_title,
            "content": self.content,
            "doc_type": self.doc_type,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IndexedSection:
        """Create from dictionary loaded from JSON."""
        return cls(
            file_path=data["file_path"],
            section_title=data.get("section_title"),
            content=data["content"],
            doc_type=data.get("doc_type", "other"),
        )


class DocumentIndex:
    """Index for storing and searching document embeddings.

    Uses NumPy for efficient cosine similarity computation and stores
    the index as a JSON file for simplicity and portability.
    """

    def __init__(self, index_path: str = ".devscontext/doc_index.json") -> None:
        """Initialize the document index.

        Args:
            index_path: Path to the JSON index file.
        """
        self._index_path = Path(index_path)
        self._model: str | None = None
        self._dimension: int | None = None
        self._indexed_at: datetime | None = None
        self._sections: list[IndexedSection] = []
        self._embeddings: list[list[float]] = []
        self._embeddings_array = None  # Cached numpy array

    @property
    def is_loaded(self) -> bool:
        """Check if index has been loaded or built."""
        return len(self._sections) > 0

    @property
    def model(self) -> str | None:
        """Return the model used for embeddings."""
        return self._model

    @property
    def dimension(self) -> int | None:
        """Return the embedding dimension."""
        return self._dimension

    @property
    def section_count(self) -> int:
        """Return number of indexed sections."""
        return len(self._sections)

    def exists(self) -> bool:
        """Check if the index file exists."""
        return self._index_path.exists()

    def load(self) -> bool:
        """Load the index from disk.

        Returns:
            True if successfully loaded, False if file doesn't exist.

        Raises:
            ValueError: If the index file is corrupted or invalid.
        """
        if not self._index_path.exists():
            logger.debug("Index file not found", extra={"path": str(self._index_path)})
            return False

        try:
            with open(self._index_path) as f:
                data = json.load(f)

            self._model = data.get("model")
            self._dimension = data.get("dimension")

            indexed_at_str = data.get("indexed_at")
            if indexed_at_str:
                self._indexed_at = datetime.fromisoformat(indexed_at_str)

            self._sections = [IndexedSection.from_dict(s) for s in data.get("sections", [])]
            self._embeddings = data.get("embeddings", [])
            self._embeddings_array = None  # Clear cached array

            logger.info(
                "Loaded document index",
                extra={
                    "path": str(self._index_path),
                    "sections": len(self._sections),
                    "model": self._model,
                },
            )
            return True

        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid index file format: {e}") from e
        except KeyError as e:
            raise ValueError(f"Missing required field in index: {e}") from e

    def save(self) -> None:
        """Save the index to disk.

        Creates parent directories if needed.
        """
        self._index_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "model": self._model,
            "dimension": self._dimension,
            "indexed_at": (self._indexed_at.isoformat() if self._indexed_at else None),
            "sections": [s.to_dict() for s in self._sections],
            "embeddings": self._embeddings,
        }

        with open(self._index_path, "w") as f:
            json.dump(data, f, indent=2)

        logger.info(
            "Saved document index",
            extra={
                "path": str(self._index_path),
                "sections": len(self._sections),
            },
        )

    def add_sections(
        self,
        sections: list[IndexedSection],
        embeddings: list[list[float]],
        model: str,
    ) -> None:
        """Add sections with their embeddings to the index.

        This replaces any existing content in the index.

        Args:
            sections: List of document sections.
            embeddings: Corresponding embedding vectors.
            model: Name of the model used for embeddings.

        Raises:
            ValueError: If sections and embeddings have different lengths.
        """
        if len(sections) != len(embeddings):
            raise ValueError(
                f"Sections ({len(sections)}) and embeddings ({len(embeddings)}) "
                "must have the same length"
            )

        self._sections = sections
        self._embeddings = embeddings
        self._model = model
        self._dimension = len(embeddings[0]) if embeddings else None
        self._indexed_at = datetime.now(UTC)
        self._embeddings_array = None  # Clear cached array

        logger.info(
            "Added sections to index",
            extra={
                "sections": len(sections),
                "model": model,
                "dimension": self._dimension,
            },
        )

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        threshold: float = 0.0,
    ) -> list[tuple[IndexedSection, float]]:
        """Search for similar sections using cosine similarity.

        Args:
            query_embedding: Query vector to search with.
            top_k: Maximum number of results to return.
            threshold: Minimum similarity score (0-1) to include.

        Returns:
            List of (section, similarity_score) tuples, sorted by score descending.
        """
        if not self._sections or not self._embeddings:
            return []

        try:
            import numpy as np
        except ImportError as e:
            raise ImportError(
                "numpy not installed. Install with: pip install devscontext[rag]"
            ) from e

        # Cache the embeddings array for repeated queries
        if self._embeddings_array is None:
            self._embeddings_array = np.array(self._embeddings)

        query_vec = np.array(query_embedding)

        # Compute cosine similarity
        # cosine_sim = (A . B) / (||A|| * ||B||)
        query_norm = np.linalg.norm(query_vec)
        if query_norm == 0:
            return []

        doc_norms = np.linalg.norm(self._embeddings_array, axis=1)
        # Avoid division by zero
        doc_norms = np.where(doc_norms == 0, 1, doc_norms)

        similarities = np.dot(self._embeddings_array, query_vec) / (doc_norms * query_norm)

        # Filter by threshold and get top-k
        results = []
        for idx, score in enumerate(similarities):
            if score >= threshold:
                results.append((idx, float(score)))

        # Sort by score descending
        results.sort(key=lambda x: x[1], reverse=True)

        # Return top-k with section objects
        return [(self._sections[idx], score) for idx, score in results[:top_k]]

    def clear(self) -> None:
        """Clear all data from the index."""
        self._sections = []
        self._embeddings = []
        self._embeddings_array = None
        self._indexed_at = None
        logger.info("Cleared document index")

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about the index.

        Returns:
            Dictionary with index statistics.
        """
        doc_types = {}
        for section in self._sections:
            doc_types[section.doc_type] = doc_types.get(section.doc_type, 0) + 1

        return {
            "exists": self.exists(),
            "loaded": self.is_loaded,
            "model": self._model,
            "dimension": self._dimension,
            "section_count": len(self._sections),
            "indexed_at": (self._indexed_at.isoformat() if self._indexed_at else None),
            "doc_types": doc_types,
            "index_path": str(self._index_path),
        }

    def delete(self) -> bool:
        """Delete the index file from disk.

        Returns:
            True if deleted, False if file didn't exist.
        """
        if self._index_path.exists():
            self._index_path.unlink()
            self.clear()
            logger.info("Deleted index file", extra={"path": str(self._index_path)})
            return True
        return False
