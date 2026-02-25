"""Core orchestration logic for DevsContext.

This module contains the DevsContextCore class which coordinates
fetching context from multiple adapters, synthesizing the results
with an LLM, and caching for performance.

Uses the plugin registry for adapter and synthesis plugin management,
supporting the primary/secondary source fetch strategy.

Example:
    config = DevsContextConfig(
        sources=SourcesConfig(
            jira=JiraConfig(enabled=True, base_url="https://...", primary=True),
            docs=DocsConfig(enabled=True, primary=False),
        ),
        synthesis=SynthesisConfig(provider="anthropic"),
    )
    core = DevsContextCore(config)
    result = await core.get_task_context("PROJ-123")
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from devscontext.cache import SimpleCache
from devscontext.logging import get_logger
from devscontext.models import DocsContext, JiraContext, JiraTicket, MeetingContext, TaskContext
from devscontext.plugins.base import SourceContext
from devscontext.plugins.registry import PluginRegistry

if TYPE_CHECKING:
    from devscontext.models import DevsContextConfig

logger = get_logger(__name__)


class DevsContextCore:
    """Core orchestration for fetching and synthesizing engineering context.

    This class coordinates:
        - Fetching context from adapters using the plugin registry
        - Primary adapters are fetched first (e.g., Jira)
        - Secondary adapters are fetched in parallel using primary context
        - Synthesizing raw context into structured markdown via synthesis plugins
        - Caching results to avoid redundant API calls

    Uses PluginRegistry for managing adapters and synthesis plugins.
    """

    def __init__(self, config: DevsContextConfig) -> None:
        """Initialize the core with configuration.

        Args:
            config: DevsContextConfig containing sources, synthesis, and cache settings.
        """
        self._config = config

        # Initialize cache if enabled
        self._cache: SimpleCache | None = None
        if config.cache.enabled:
            self._cache = SimpleCache(
                ttl=config.cache.ttl_seconds,
                max_size=config.cache.max_size,
            )

        # Initialize plugin registry
        self._registry = PluginRegistry()
        self._registry.register_builtin_plugins()
        self._registry.discover_plugins()
        self._registry.load_from_config(config)

        logger.info(
            "DevsContextCore initialized",
            extra={
                "cache_enabled": config.cache.enabled,
                "adapters_loaded": list(self._registry.get_active_adapters().keys()),
                "synthesis_plugin": (
                    self._registry.get_synthesis().name if self._registry.get_synthesis() else None
                ),
            },
        )

    async def get_task_context(
        self,
        task_id: str,
        *,
        use_cache: bool = True,
    ) -> TaskContext:
        """Get aggregated and synthesized context for a task.

        Fetches context from all configured adapters in parallel,
        then uses the LLM to synthesize into structured markdown.

        Args:
            task_id: The task identifier (e.g., Jira ticket ID).
            use_cache: Whether to use cached results.

        Returns:
            TaskContext with synthesized markdown and metadata.
        """
        start_time = time.monotonic()
        cache_key = f"context:{task_id}"

        # Check cache
        if use_cache and self._cache is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                logger.info("Cache hit for task context", extra={"task_id": task_id})
                # Return a copy with cached=True
                if isinstance(cached, TaskContext):
                    return TaskContext(
                        task_id=cached.task_id,
                        synthesized=cached.synthesized,
                        sources_used=cached.sources_used,
                        fetch_duration_ms=cached.fetch_duration_ms,
                        synthesized_at=cached.synthesized_at,
                        cached=True,
                    )

        # Fetch context from adapters using new plugin interface
        source_contexts = await self._fetch_all_context(task_id)

        # Build sources list from source contexts
        sources_used: list[str] = []
        for name, ctx in source_contexts.items():
            if ctx.is_empty():
                continue

            if name == "jira" and isinstance(ctx.data, JiraContext):
                sources_used.append(f"jira:{ctx.data.ticket.ticket_id}")
            elif name == "fireflies" and isinstance(ctx.data, MeetingContext):
                sources_used.extend(
                    f"fireflies:{m.meeting_date.strftime('%Y-%m-%d')}"
                    for m in ctx.data.meetings
                )
            elif name == "local_docs" and isinstance(ctx.data, DocsContext):
                sources_used.extend(f"docs:{s.file_path}" for s in ctx.data.sections)

        # Synthesize using plugin interface
        synthesis = self._registry.get_synthesis()
        if synthesis is None:
            synthesized = f"## Task: {task_id}\n\nNo synthesis plugin configured."
        else:
            synthesized = await synthesis.synthesize(
                task_id=task_id,
                source_contexts=source_contexts,
            )

        duration_ms = int((time.monotonic() - start_time) * 1000)

        logger.info(
            "Task context fetched and synthesized",
            extra={
                "task_id": task_id,
                "source_count": len(sources_used),
                "duration_ms": duration_ms,
            },
        )

        result = TaskContext(
            task_id=task_id,
            synthesized=synthesized,
            sources_used=sources_used,
            fetch_duration_ms=duration_ms,
            synthesized_at=datetime.now(UTC),
            cached=False,
        )

        # Store in cache
        if use_cache and self._cache is not None:
            self._cache.set(cache_key, result)

        return result

    async def _fetch_all_context(
        self,
        task_id: str,
    ) -> dict[str, SourceContext]:
        """Fetch context from all adapters using the plugin interface.

        Uses two-phase fetch strategy:
        1. Fetch from primary adapters first (typically Jira)
        2. Fetch from secondary adapters in parallel, passing primary context

        This allows secondary adapters (docs, meetings) to use ticket data
        for better context matching (components, labels, keywords).

        Args:
            task_id: The task identifier.

        Returns:
            Dict mapping adapter names to their SourceContext.
        """
        source_contexts: dict[str, SourceContext] = {}

        # Phase 1: Fetch from primary adapters (typically Jira)
        # Primary adapters are fetched first, their context is shared with secondary
        ticket: JiraTicket | None = None
        primary_adapters = self._registry.get_primary_adapters()

        for name, adapter in primary_adapters.items():
            try:
                ctx = await adapter.fetch_task_context(task_id)
                source_contexts[name] = ctx
                # Extract Jira ticket if available for secondary adapters
                if isinstance(ctx.data, JiraContext):
                    ticket = ctx.data.ticket
            except Exception as e:
                logger.warning(
                    f"Primary adapter {name} fetch failed",
                    extra={"error": str(e), "task_id": task_id},
                )

        # Phase 2: Fetch from secondary adapters in parallel
        # Pass ticket data for context-aware matching
        secondary_adapters = self._registry.get_secondary_adapters()

        if secondary_adapters:
            coros = []
            adapter_names = []

            for name, adapter in secondary_adapters.items():
                coros.append(adapter.fetch_task_context(task_id, ticket))
                adapter_names.append(name)

            results = await asyncio.gather(*coros, return_exceptions=True)

            for name, result in zip(adapter_names, results, strict=True):
                if isinstance(result, BaseException):
                    logger.warning(
                        f"Secondary adapter {name} fetch failed",
                        extra={"error": str(result), "task_id": task_id},
                    )
                elif isinstance(result, SourceContext):
                    source_contexts[name] = result

        return source_contexts

    async def health_check(self) -> dict[str, bool]:
        """Check health of all configured adapters.

        Returns:
            Dictionary mapping adapter names to health status.
        """
        results = await self._registry.health_check_all()
        logger.info("Health check completed", extra={"adapters": results})
        return results

    def invalidate_cache(self, task_id: str | None = None) -> None:
        """Invalidate cached context.

        Args:
            task_id: Specific task to invalidate, or None to clear all.
        """
        if self._cache is None:
            return

        if task_id:
            self._cache.invalidate(f"context:{task_id}")
            logger.debug("Cache invalidated", extra={"task_id": task_id})
        else:
            self._cache.clear()
            logger.debug("Cache cleared")

    async def search_context(self, query: str) -> dict[str, str | list[str] | int]:
        """Search across all sources by keyword.

        Searches Jira, meetings, and local docs in parallel for freeform queries
        like "how do we handle retries?" or "what was decided about payments?".

        No LLM synthesis - returns formatted search results directly.
        No caching - queries are too varied.

        Args:
            query: The search query.

        Returns:
            Dictionary with formatted results and metadata.
        """
        start_time = time.monotonic()
        logger.info("Search context", extra={"query": query})

        # Search all sources in parallel
        jira_coro = self._search_jira(query)
        meetings_coro = self._search_meetings(query)
        docs_coro = self._search_docs(query)

        results = await asyncio.gather(jira_coro, meetings_coro, docs_coro, return_exceptions=True)

        jira_results, meeting_results, docs_results = results

        # Format results into markdown
        sections: list[str] = [f'## Search Results for "{query}"']
        sources_used: list[str] = []
        total_results = 0

        # Format Jira results
        if isinstance(jira_results, list) and jira_results:
            sources_used.append("jira")
            total_results += len(jira_results)
            sections.append(self._format_jira_search_results(jira_results))
        elif isinstance(jira_results, BaseException):
            logger.warning("Jira search failed", extra={"error": str(jira_results)})

        # Format meeting results
        if isinstance(meeting_results, MeetingContext) and meeting_results.meetings:
            sources_used.append("fireflies")
            total_results += len(meeting_results.meetings)
            sections.append(self._format_meeting_search_results(meeting_results))
        elif isinstance(meeting_results, BaseException):
            logger.warning("Meeting search failed", extra={"error": str(meeting_results)})

        # Format docs results
        if isinstance(docs_results, DocsContext) and docs_results.sections:
            sources_used.append("docs")
            total_results += len(docs_results.sections)
            sections.append(self._format_docs_search_results(docs_results))
        elif isinstance(docs_results, BaseException):
            logger.warning("Docs search failed", extra={"error": str(docs_results)})

        # Handle no results
        if total_results == 0:
            sections.append("\nNo results found.")

        duration_ms = int((time.monotonic() - start_time) * 1000)

        logger.info(
            "Search completed",
            extra={
                "query": query,
                "result_count": total_results,
                "sources": sources_used,
                "duration_ms": duration_ms,
            },
        )

        return {
            "query": query,
            "results": "\n\n".join(sections),
            "sources": sources_used if sources_used else ["none"],
            "result_count": total_results,
            "duration_ms": duration_ms,
        }

    async def _search_jira(self, query: str) -> list[JiraTicket]:
        """Search Jira for matching issues."""
        jira = self._registry.get_adapter("jira")
        if jira is None:
            return []
        return await jira.search_issues(query, max_results=5)

    async def _search_meetings(self, query: str) -> MeetingContext:
        """Search meeting transcripts for query."""
        fireflies = self._registry.get_adapter("fireflies")
        if fireflies is None:
            return MeetingContext(meetings=[])
        return await fireflies.get_meeting_context(query)

    async def _search_docs(self, query: str) -> DocsContext:
        """Search local documentation for query."""
        docs = self._registry.get_adapter("local_docs")
        if docs is None:
            return DocsContext(sections=[])
        return await docs.search_docs(query, max_results=5)

    def _format_jira_search_results(self, tickets: list[JiraTicket]) -> str:
        """Format Jira search results as markdown."""
        parts = ["### Jira Tickets"]
        for ticket in tickets:
            status_badge = f"[{ticket.status}]"
            assignee = f" — {ticket.assignee}" if ticket.assignee else ""
            parts.append(f"- **{ticket.ticket_id}**: {ticket.title} {status_badge}{assignee}")
        return "\n".join(parts)

    def _format_meeting_search_results(self, context: MeetingContext) -> str:
        """Format meeting search results as markdown."""
        parts = ["### Meeting Discussions"]
        for meeting in context.meetings:
            date_str = meeting.meeting_date.strftime("%Y-%m-%d")
            parts.append(f"\n**{meeting.meeting_title}** ({date_str})")
            # Truncate excerpt for search results
            excerpt = meeting.excerpt
            if len(excerpt) > 300:
                excerpt = excerpt[:300] + "..."
            parts.append(excerpt)
        return "\n".join(parts)

    def _format_docs_search_results(self, context: DocsContext) -> str:
        """Format docs search results as markdown."""
        parts = ["### Documentation"]
        for section in context.sections:
            title = section.section_title or section.file_path
            doc_type = f"[{section.doc_type}]"
            parts.append(f"\n**{title}** {doc_type}")
            parts.append(f"*Source: {section.file_path}*")
            # Truncate content for search results
            content = section.content
            if len(content) > 200:
                content = content[:200] + "..."
            parts.append(content)
        return "\n".join(parts)

    async def get_standards(
        self, area: str | None = None
    ) -> dict[str, str | None | int | list[str]]:
        """Get coding standards from local documentation.

        Args:
            area: Optional area to filter (e.g., 'typescript', 'testing').

        Returns:
            Dictionary containing standards content and metadata.
        """
        start_time = time.monotonic()
        logger.info("Get standards", extra={"area": area})

        docs = self._registry.get_adapter("local_docs")
        available_areas: list[str] = []

        if docs is None:
            content = self._get_standards_not_configured_message()
            section_count = 0
        else:
            docs_context = await docs.get_standards(area)
            available_areas = await docs.list_standards_areas()

            if docs_context.sections:
                # Format sections into markdown with header
                title = f"# Coding Standards: {area}" if area else "# Coding Standards"
                parts: list[str] = [title, ""]

                for section in docs_context.sections:
                    # Add source file info
                    source_info = f"*Source: {section.file_path}*"
                    if section.section_title:
                        parts.append(f"## {section.section_title}")
                        parts.append(source_info)
                        parts.append("")
                        parts.append(section.content)
                    else:
                        parts.append(source_info)
                        parts.append("")
                        parts.append(section.content)
                    parts.append("")  # Blank line between sections

                content = "\n".join(parts)
                section_count = len(docs_context.sections)
            elif area and available_areas:
                # Area specified but no matches - show available areas
                content = self._get_no_matching_standards_message(area, available_areas)
                section_count = 0
            else:
                content = self._get_standards_not_configured_message()
                section_count = 0

        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.info(
            "Get standards completed",
            extra={"area": area, "duration_ms": duration_ms, "section_count": section_count},
        )

        return {
            "area": area,
            "content": content,
            "section_count": section_count,
            "available_areas": available_areas,
            "duration_ms": duration_ms,
        }

    def _get_standards_not_configured_message(self) -> str:
        """Generate message when no standards are configured."""
        return """# Coding Standards

No standards documents found.

## How to Configure

1. Create markdown files in your docs directory
2. Configure `sources.docs.paths` in `.devscontext.yaml`
3. Place files in a `standards/` subdirectory

### Example Structure

```
docs/
  standards/
    typescript.md
    testing.md
    api-design.md
```

### Example .devscontext.yaml

```yaml
sources:
  docs:
    enabled: true
    paths:
      - ./docs
```

Files in the `standards/` directory will be automatically recognized as coding standards.
"""

    def _get_no_matching_standards_message(self, area: str, available_areas: list[str]) -> str:
        """Generate message when no standards match the requested area."""
        areas_list = "\n".join(f"- `{a}`" for a in available_areas)
        return f"""# Coding Standards: {area}

No standards found for "{area}".

## Available Areas

{areas_list}

Try one of the areas above, or omit the area parameter to see all standards.
"""

    async def close(self) -> None:
        """Close all adapter connections and clean up resources."""
        await self._registry.close_all()
