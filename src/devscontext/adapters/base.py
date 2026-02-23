"""Base adapter interface for context sources.

This module defines the abstract base class that all context adapters must
implement. Adapters are responsible for fetching context from a specific
source (Jira, Fireflies, local docs, etc.) and returning it in a standardized
ContextData format.

Example:
    class MyAdapter(Adapter):
        @property
        def name(self) -> str:
            return "my_adapter"

        @property
        def source_type(self) -> str:
            return "custom"

        async def fetch_context(self, task_id: str) -> list[ContextData]:
            # Fetch and return context
            ...

        async def health_check(self) -> bool:
            # Check if adapter is healthy
            ...
"""

from abc import ABC, abstractmethod

from devscontext.models import ContextData

# Re-export ContextData for backwards compatibility
__all__ = ["Adapter", "ContextData"]


class Adapter(ABC):
    """Abstract base class for all context adapters.

    Subclasses must implement:
        - name: A unique identifier for this adapter
        - source_type: The category of source (issue_tracker, meeting, docs)
        - fetch_context: Fetch context related to a task
        - health_check: Verify the adapter is properly configured

    Adapters should:
        - Never raise exceptions that crash the MCP server
        - Return empty lists on errors (with logging)
        - Use async for all I/O operations
        - Cache HTTP clients for reuse
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the unique adapter name.

        Returns:
            A short, lowercase identifier (e.g., 'jira', 'fireflies').
        """
        ...

    @property
    @abstractmethod
    def source_type(self) -> str:
        """Return the type of source this adapter provides.

        Common values:
            - 'issue_tracker': Jira, Linear, GitHub Issues
            - 'meeting': Fireflies, Otter.ai
            - 'documentation': Local docs, Confluence

        Returns:
            The source type string.
        """
        ...

    @abstractmethod
    async def fetch_context(self, task_id: str) -> list[ContextData]:
        """Fetch context related to a task.

        This method should:
            - Return all relevant context for the given task ID
            - Handle errors gracefully (log and return empty list)
            - Use caching when appropriate

        Args:
            task_id: The task identifier (e.g., Jira ticket ID like 'PROJ-123').

        Returns:
            A list of ContextData items. Empty list if nothing found or on error.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the adapter is properly configured and can connect.

        This method should:
            - Verify configuration is valid
            - Test connectivity to the external service
            - Return True for disabled adapters (they're "healthy" by definition)

        Returns:
            True if the adapter is healthy/disabled, False if there's an issue.
        """
        ...
