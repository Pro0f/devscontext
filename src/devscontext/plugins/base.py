"""Base plugin interfaces for DevsContext.

This module defines the abstract base classes for the plugin system:

- Adapter: Interface for data sources (Jira, Fireflies, Slack, etc.)
- SynthesisPlugin: Interface for synthesis strategies (LLM, template, etc.)

Adapters and plugins must implement these interfaces to integrate with DevsContext.
The core system uses these interfaces to fetch, search, and synthesize context
without knowing the specific implementation details.

Design Principles:
- All I/O operations are async
- Adapters never raise exceptions that crash the MCP server
- Adapters handle their own resource lifecycle (HTTP clients, etc.)
- Config validation is done via Pydantic models
- Graceful degradation: if a source fails, others continue

Example Adapter:
    class SlackAdapter(Adapter):
        name = "slack"
        source_type = "communication"
        config_schema = SlackConfig

        def __init__(self, config: SlackConfig):
            self._config = config
            self._client = None

        async def fetch_task_context(self, task_id, ticket=None):
            messages = await self._search_messages(task_id)
            return SourceContext(
                source_name="slack",
                source_type="communication",
                data={"messages": messages},
                raw_text=self._format_messages(messages),
            )

Example Synthesis Plugin:
    class TemplateSynthesis(SynthesisPlugin):
        name = "template"
        config_schema = TemplateConfig

        async def synthesize(self, task_id, source_contexts):
            return self._template.render(task_id=task_id, **source_contexts)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from devscontext.models import JiraTicket


# =============================================================================
# DATA MODELS
# =============================================================================


class SourceContext(BaseModel):
    """Container for context data returned by a source plugin.

    This is a flexible container that can hold any type of source-specific data.
    The `data` field holds structured data (dicts, lists, Pydantic models),
    while `raw_text` provides a pre-formatted text representation for synthesis.

    Attributes:
        source_name: The plugin name that produced this context (e.g., "jira").
        source_type: Category of the source (e.g., "issue_tracker", "meeting").
        data: The structured source-specific data. Can be any type.
        raw_text: Pre-formatted text representation of the data for synthesis.
        metadata: Additional metadata about the context (timestamps, counts, etc.).
        fetched_at: When this context was fetched (UTC).
    """

    source_name: str = Field(..., description="Plugin name that produced this context")
    source_type: str = Field(..., description="Category of source (issue_tracker, meeting, etc.)")
    data: Any = Field(default=None, description="Structured source-specific data")
    raw_text: str = Field(default="", description="Pre-formatted text for synthesis")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    fetched_at: datetime = Field(
        default_factory=lambda: datetime.now().astimezone(),
        description="When context was fetched (UTC)",
    )

    model_config = {"arbitrary_types_allowed": True}

    def is_empty(self) -> bool:
        """Check if this context has no meaningful data."""
        return not self.data and not self.raw_text


class SearchResult(BaseModel):
    """A single search result from a source plugin.

    Search results are returned by SourcePlugin.search() and represent
    a single item that matched the search query.

    Attributes:
        source_name: The plugin name that produced this result.
        source_type: Category of the source.
        title: Human-readable title for the result.
        excerpt: Relevant excerpt or snippet showing the match.
        url: Optional URL to the source item.
        relevance_score: Score from 0.0 to 1.0 indicating match quality.
        metadata: Additional source-specific metadata.
    """

    source_name: str = Field(..., description="Plugin name that produced this result")
    source_type: str = Field(..., description="Category of source")
    title: str = Field(..., description="Human-readable title")
    excerpt: str = Field(..., description="Relevant excerpt showing the match")
    url: str | None = Field(default=None, description="URL to the source item")
    relevance_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Relevance score from 0.0 to 1.0",
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


# =============================================================================
# ADAPTER INTERFACE
# =============================================================================


class Adapter(ABC):
    """Abstract base class for all context adapters.

    An adapter provides context data from a specific system (Jira, Slack,
    Fireflies, local docs, etc.). Adapters must implement the interface methods
    to integrate with DevsContext.

    Class Attributes:
        name: Unique identifier for this adapter (e.g., "jira", "slack").
        source_type: Category of source (e.g., "issue_tracker", "communication").
        config_schema: Pydantic model class for validating adapter configuration.

    Implementation Requirements:
        - All I/O must be async
        - Never raise exceptions that crash the server - log and return empty
        - Handle resource lifecycle (create/close HTTP clients)
        - Support graceful degradation when dependencies unavailable

    Example:
        class MyAdapter(Adapter):
            name = "my_source"
            source_type = "custom"
            config_schema = MyConfig

            def __init__(self, config: MyConfig):
                self._config = config

            async def fetch_task_context(self, task_id, ticket=None):
                data = await self._fetch_data(task_id)
                return SourceContext(
                    source_name=self.name,
                    source_type=self.source_type,
                    data=data,
                    raw_text=self._format_data(data),
                )
    """

    # Class attributes that subclasses must define
    name: ClassVar[str]
    source_type: ClassVar[str]
    config_schema: ClassVar[type[BaseModel]]

    @abstractmethod
    async def fetch_task_context(
        self,
        task_id: str,
        ticket: JiraTicket | None = None,
    ) -> SourceContext:
        """Fetch context related to a specific task.

        This is the primary method for getting context. The task_id is typically
        a Jira ticket ID, but adapters can interpret it as needed. The optional
        ticket parameter provides Jira ticket data for enriched matching (e.g.,
        using ticket components/labels to find relevant docs).

        Args:
            task_id: The task identifier (e.g., "PROJ-123").
            ticket: Optional Jira ticket data for context-aware matching.
                   Non-Jira adapters use this for keyword extraction, etc.

        Returns:
            SourceContext with the fetched data. Return empty context on errors.
        """
        ...

    @abstractmethod
    async def search(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """Search this source for items matching the query.

        Used by the search_context MCP tool for freeform keyword search.
        This should be a fast, lightweight search - no LLM processing.

        Args:
            query: The search query string.
            max_results: Maximum number of results to return.

        Returns:
            List of SearchResult items. Empty list if nothing found or on error.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the adapter is properly configured and can connect.

        Should verify:
        - Configuration is valid
        - External service is reachable (if applicable)
        - Authentication is working

        Returns:
            True if healthy, False if there's an issue.
        """
        ...

    async def close(self) -> None:  # noqa: B027
        """Clean up resources (HTTP clients, connections, etc.).

        Override this method if your adapter holds resources that need cleanup.
        The default implementation does nothing.
        """
        pass

    def format_for_synthesis(self, context: SourceContext) -> str:
        """Format context data for LLM synthesis.

        Override this to provide custom formatting. The default implementation
        returns the raw_text field from the context.

        Args:
            context: The source context to format.

        Returns:
            Formatted text string for inclusion in synthesis prompt.
        """
        return context.raw_text


# =============================================================================
# SYNTHESIS PLUGIN INTERFACE
# =============================================================================


class SynthesisPlugin(ABC):
    """Abstract base class for synthesis plugins.

    A synthesis plugin combines context from multiple adapters into a unified,
    structured output suitable for AI coding assistants. Different strategies
    can be implemented: LLM-based synthesis, template-based, or passthrough.

    Class Attributes:
        name: Unique identifier for this plugin (e.g., "llm", "template").
        config_schema: Pydantic model class for validating plugin configuration.

    Implementation Requirements:
        - Must be async
        - Should handle missing sources gracefully
        - Should provide fallback if primary synthesis fails

    Example:
        class TemplateSynthesis(SynthesisPlugin):
            name = "template"
            config_schema = TemplateConfig

            def __init__(self, config: TemplateConfig):
                self._template = load_template(config.template_path)

            async def synthesize(self, task_id, source_contexts):
                return self._template.render(
                    task_id=task_id,
                    contexts=source_contexts,
                )
    """

    # Class attributes that subclasses must define
    name: ClassVar[str]
    config_schema: ClassVar[type[BaseModel]]

    @abstractmethod
    async def synthesize(
        self,
        task_id: str,
        source_contexts: dict[str, SourceContext],
    ) -> str:
        """Synthesize context from multiple adapters into unified output.

        Takes context data from all enabled adapters and combines it
        into a structured markdown document suitable for AI coding assistants.

        Args:
            task_id: The task identifier (e.g., "PROJ-123").
            source_contexts: Dict mapping adapter names to their SourceContext.
                           Keys are adapter names (e.g., "jira", "fireflies").

        Returns:
            Synthesized markdown text combining all source context.
        """
        ...

    async def close(self) -> None:  # noqa: B027
        """Clean up resources (LLM clients, etc.).

        Override this method if your plugin holds resources that need cleanup.
        The default implementation does nothing.
        """
        pass
