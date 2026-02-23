"""Base adapter interface for context sources."""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class ContextData(BaseModel):
    """Structured context data from an adapter."""

    source: str
    source_type: str
    title: str
    content: str
    metadata: dict[str, Any] = {}
    relevance_score: float = 1.0


class Adapter(ABC):
    """Base class for all context adapters."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the adapter name."""
        ...

    @property
    @abstractmethod
    def source_type(self) -> str:
        """Return the type of source (e.g., 'issue_tracker', 'meeting', 'docs')."""
        ...

    @abstractmethod
    async def fetch_context(self, task_id: str) -> list[ContextData]:
        """Fetch context related to a task.

        Args:
            task_id: The task identifier (e.g., Jira ticket ID).

        Returns:
            List of context data items.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the adapter is properly configured and can connect.

        Returns:
            True if healthy, False otherwise.
        """
        ...
