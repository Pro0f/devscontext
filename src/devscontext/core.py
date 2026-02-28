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

Demo mode:
    # Run without configuration using sample data
    core = DevsContextCore(demo_mode=True)
    result = await core.get_task_context("PROJ-123")  # Returns demo context
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
from devscontext.storage import PrebuiltContextStorage

if TYPE_CHECKING:
    from devscontext.models import DevsContextConfig, PrebuiltContext

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

    Demo mode:
        When demo_mode=True, the core returns realistic sample data without
        requiring any configuration or external API connections.
    """

    def __init__(
        self,
        config: DevsContextConfig | None = None,
        *,
        demo_mode: bool = False,
    ) -> None:
        """Initialize the core with configuration.

        Args:
            config: DevsContextConfig containing sources, synthesis, and cache settings.
                    Optional if demo_mode is True.
            demo_mode: If True, use sample data instead of real adapters.
                       No configuration required in demo mode.
        """
        self._demo_mode = demo_mode
        self._config = config
        self._cache: SimpleCache | None = None
        self._storage: PrebuiltContextStorage | None = None
        self._storage_initialized = True
        self._registry: PluginRegistry | None = None

        # In demo mode, skip all initialization
        if demo_mode:
            logger.info("DevsContextCore initialized in demo mode")
            return

        # Normal mode requires config
        if config is None:
            raise ValueError("config is required when demo_mode is False")

        # Initialize cache if enabled
        if config.cache.enabled:
            self._cache = SimpleCache(
                ttl=config.cache.ttl_seconds,
                max_size=config.cache.max_size,
            )

        # Initialize pre-built context storage if configured
        if config.storage.path:
            self._storage = PrebuiltContextStorage(config.storage.path)
            self._storage_initialized = False

        # Initialize plugin registry
        self._registry = PluginRegistry()
        self._registry.register_builtin_plugins()
        self._registry.discover_plugins()
        self._registry.load_from_config(config)

        synthesis = self._registry.get_synthesis()
        logger.info(
            "DevsContextCore initialized",
            extra={
                "cache_enabled": config.cache.enabled,
                "adapters_loaded": list(self._registry.get_active_adapters().keys()),
                "synthesis_plugin": synthesis.name if synthesis else None,
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

        In demo mode, returns realistic sample context without external calls.

        Args:
            task_id: The task identifier (e.g., Jira ticket ID).
            use_cache: Whether to use cached results.

        Returns:
            TaskContext with synthesized markdown and metadata.
        """
        # Demo mode: return sample data immediately
        if self._demo_mode:
            return await self._get_demo_context(task_id)

        start_time = time.monotonic()
        cache_key = f"context:{task_id}"

        # Check pre-built context storage first (instant return with rich context)
        if use_cache and self._storage is not None:
            prebuilt = await self._get_prebuilt_context(task_id)
            if prebuilt is not None and not prebuilt.is_expired():
                logger.info(
                    "Pre-built context hit",
                    extra={
                        "task_id": task_id,
                        "quality_score": prebuilt.context_quality_score,
                    },
                )
                return TaskContext(
                    task_id=task_id,
                    synthesized=prebuilt.synthesized,
                    sources_used=prebuilt.sources_used,
                    fetch_duration_ms=0,
                    synthesized_at=prebuilt.built_at,
                    cached=True,
                    prebuilt=True,
                )

        # Check in-memory cache
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
                    f"fireflies:{m.meeting_date.strftime('%Y-%m-%d')}" for m in ctx.data.meetings
                )
            elif name == "local_docs" and isinstance(ctx.data, DocsContext):
                sources_used.extend(f"docs:{s.file_path}" for s in ctx.data.sections)

        # Synthesize using plugin interface
        if self._registry is None:
            synthesized = f"## Task: {task_id}\n\nNo synthesis plugin configured."
        else:
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
        # This method is only called in non-demo mode where registry is initialized
        assert self._registry is not None

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
        if self._demo_mode:
            return {"demo": True}

        if self._registry is None:
            return {}

        results = await self._registry.health_check_all()
        logger.info("Health check completed", extra={"adapters": results})
        return results

    async def get_status(self) -> str:
        """Get configuration and health status of all sources.

        Returns a formatted status report including:
        - Version
        - Source adapter connectivity
        - Synthesis configuration
        - Pre-processing agent status
        - Cache status

        Returns:
            Formatted status string.
        """
        from devscontext.constants import VERSION

        lines = [f"DevsContext v{VERSION}", "", "Sources:"]

        # Demo mode
        if self._demo_mode:
            lines.append("  ✅ Demo Mode — sample data")
            lines.extend(["", "Synthesis:", "  Demo mode (no LLM)"])
            lines.extend(["", "Pre-processing:", "  Agent: disabled", "  Pre-built contexts: 0"])
            lines.extend(["", "Cache:", "  Disabled"])
            return "\n".join(lines)

        # Check each adapter's health
        if self._registry is not None:
            adapters = self._registry.get_active_adapters()
            if not adapters:
                lines.append("  No sources configured")
            else:
                for name, adapter in adapters.items():
                    healthy = await adapter.health_check()
                    status_icon = "✅" if healthy else "❌"
                    detail = self._get_adapter_detail(name, adapter)
                    display_name = name.replace("_", " ").title()
                    lines.append(f"  {status_icon} {display_name} — {detail}")
        else:
            lines.append("  No sources configured")

        # Synthesis info
        lines.extend(["", "Synthesis:"])
        if self._config and self._config.synthesis:
            synth = self._config.synthesis
            lines.append(f"  Provider: {synth.provider} ({synth.model})")
            lines.append(f"  Max output: {synth.max_output_tokens} tokens")
        else:
            lines.append("  Not configured")

        # Pre-processing info
        lines.extend(["", "Pre-processing:"])
        if self._config and self._config.agents and self._config.agents.preprocessor.enabled:
            count = await self._get_prebuilt_count()
            lines.append("  Agent: enabled")
            lines.append(f"  Pre-built contexts: {count}")
        else:
            lines.append("  Agent: disabled")
            lines.append("  Pre-built contexts: 0")

        # Cache info
        lines.extend(["", "Cache:"])
        if self._cache and self._config:
            ttl_minutes = self._config.cache.ttl_seconds // 60
            lines.append(f"  TTL: {ttl_minutes} minutes")
            lines.append(f"  Cached entries: {len(self._cache)}")
        else:
            lines.append("  Disabled")

        return "\n".join(lines)

    def _get_adapter_detail(self, name: str, adapter: object) -> str:
        """Get status detail string for an adapter.

        Args:
            name: Adapter name.
            adapter: Adapter instance.

        Returns:
            Status detail string.
        """
        config = getattr(adapter, "_config", None)
        if not config:
            return "not configured"

        if not getattr(config, "enabled", True):
            return "disabled"

        # Source-specific details
        if name == "jira" and hasattr(config, "base_url") and config.base_url:
            return f"connected ({config.base_url})"
        elif name == "github" and hasattr(config, "repos") and config.repos:
            repos = ", ".join(config.repos[:2])
            if len(config.repos) > 2:
                repos += f" +{len(config.repos) - 2} more"
            return f"connected ({repos})"
        elif name == "local_docs" and hasattr(config, "paths"):
            return f"{len(config.paths)} paths configured"
        elif name == "fireflies":
            return "connected"
        elif name == "slack":
            if getattr(config, "bot_token", ""):
                return "connected"
            return "not configured"
        elif name == "gmail":
            if getattr(config, "credentials_file", ""):
                return "connected"
            return "not configured"

        return "connected"

    async def _get_prebuilt_count(self) -> int:
        """Get count of pre-built contexts from storage.

        Returns:
            Number of pre-built contexts.
        """
        if self._storage is None:
            return 0
        try:
            if not self._storage_initialized:
                await self._storage.initialize()
                self._storage_initialized = True
            contexts = await self._storage.list_all()
            return len(contexts)
        except Exception:
            return 0

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
        # Demo mode: return sample search results
        if self._demo_mode:
            return self._get_demo_search_results(query)

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
        if self._registry is None:
            return []
        jira = self._registry.get_adapter("jira")
        if jira is None:
            return []
        return await jira.search_issues(query, max_results=5)  # type: ignore[attr-defined,no-any-return]

    async def _search_meetings(self, query: str) -> MeetingContext:
        """Search meeting transcripts for query."""
        if self._registry is None:
            return MeetingContext(meetings=[])
        fireflies = self._registry.get_adapter("fireflies")
        if fireflies is None:
            return MeetingContext(meetings=[])
        return await fireflies.get_meeting_context(query)  # type: ignore[attr-defined,no-any-return]

    async def _search_docs(self, query: str) -> DocsContext:
        """Search local documentation for query."""
        if self._registry is None:
            return DocsContext(sections=[])
        docs = self._registry.get_adapter("local_docs")
        if docs is None:
            return DocsContext(sections=[])
        return await docs.search_docs(query, max_results=5)  # type: ignore[attr-defined,no-any-return]

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
        # Demo mode: return sample standards
        if self._demo_mode:
            return self._get_demo_standards(area)

        start_time = time.monotonic()
        logger.info("Get standards", extra={"area": area})

        docs = None
        if self._registry is not None:
            docs = self._registry.get_adapter("local_docs")
        available_areas: list[str] = []

        if docs is None:
            content = self._get_standards_not_configured_message()
            section_count = 0
        else:
            docs_context = await docs.get_standards(area)  # type: ignore[attr-defined]
            available_areas = await docs.list_standards_areas()  # type: ignore[attr-defined]

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

    async def _get_prebuilt_context(self, task_id: str) -> PrebuiltContext | None:
        """Get pre-built context from storage, initializing if needed.

        Args:
            task_id: Task identifier.

        Returns:
            PrebuiltContext if found, None otherwise.
        """
        if self._storage is None:
            return None

        try:
            # Initialize storage on first access
            if not self._storage_initialized:
                await self._storage.initialize()
                self._storage_initialized = True

            return await self._storage.get(task_id)

        except Exception as e:
            logger.warning(
                "Failed to get pre-built context",
                extra={"task_id": task_id, "error": str(e)},
            )
            return None

    def _get_demo_search_results(self, query: str) -> dict[str, str | list[str] | int]:
        """Get demo search results for any query.

        Args:
            query: The search query.

        Returns:
            Dictionary with formatted demo results.
        """
        results = f"""## Search Results for "{query}"

### Jira Tickets
- **PROJ-123**: Add retry logic to payment webhook handler [In Progress] — Alex Chen
- **PROJ-456**: Payment webhook initial implementation [Done]

### Meeting Discussions

**Sprint 23 Planning - Payments Team** (2024-03-15)
Discussion about webhook retry approaches. Decision: Use SQS visibility timeout
for retry scheduling instead of cron jobs.

### Documentation

**Webhook Processing Flow** [architecture]
*Source: docs/architecture/payments-service.md*
Webhook flow: Stripe → POST /webhooks/stripe → Signature Check → SQS Queue...

**Error Handling** [standards]
*Source: docs/standards/typescript.md*
Use Result<T, E> pattern for operations that can fail. Never throw exceptions...
"""

        return {
            "query": query,
            "results": results,
            "sources": ["jira", "fireflies", "docs"],
            "result_count": 5,
            "duration_ms": 50,
        }

    def _get_demo_standards(self, area: str | None) -> dict[str, str | None | int | list[str]]:
        """Get demo coding standards.

        Args:
            area: Optional area filter.

        Returns:
            Dictionary with demo standards content.
        """
        content = """# Coding Standards

## Error Handling

### Result Pattern
Use `Result<T, E>` pattern for operations that can fail. Never throw exceptions from business logic.

```typescript
import { Result, ok, err } from '@/utils/result';

async function processWebhook(event: WebhookEvent): Promise<Result<void, WebhookError>> {
    const validated = validateEvent(event);
    if (!validated.ok) {
        return err(new WebhookError('VALIDATION_FAILED', validated.error));
    }
    return ok(undefined);
}
```

## Testing

### Mocking SQS
Use `@aws-sdk/client-sqs-mock` for unit tests:

```typescript
import { mockClient } from 'aws-sdk-client-mock';
import { SQSClient, SendMessageCommand } from '@aws-sdk/client-sqs';

const sqsMock = mockClient(SQSClient);

it('should retry failed webhooks', async () => {
    sqsMock.on(SendMessageCommand).resolves({ MessageId: 'test-123' });
    await retryWebhook(failedEvent);
    expect(sqsMock.calls()).toHaveLength(1);
});
```
"""

        return {
            "area": area,
            "content": content,
            "section_count": 2,
            "available_areas": ["typescript", "testing", "error-handling"],
            "duration_ms": 10,
        }

    async def _get_demo_context(self, task_id: str) -> TaskContext:
        """Get demo context with sample data.

        Returns realistic sample context for PROJ-123 (payment webhook retry).
        Uses pre-baked synthesis output - no LLM required.

        Args:
            task_id: The task identifier (ignored, always returns PROJ-123 context).

        Returns:
            TaskContext with sample synthesized markdown.
        """
        from devscontext.demo_data import DEMO_TASK_ID, get_demo_synthesis

        # Always return the demo context regardless of task_id
        # This makes any ticket ID work in demo mode
        synthesized = get_demo_synthesis()

        logger.info(
            "Demo context returned",
            extra={"requested_task_id": task_id, "demo_task_id": DEMO_TASK_ID},
        )

        return TaskContext(
            task_id=DEMO_TASK_ID,
            synthesized=synthesized,
            sources_used=["jira:PROJ-123", "fireflies:2024-03-15", "docs:payments-service.md"],
            fetch_duration_ms=50,  # Fast since it's demo
            synthesized_at=datetime.now(UTC),
            cached=False,
            prebuilt=False,
        )

    async def close(self) -> None:
        """Close all adapter connections and clean up resources."""
        if self._registry is not None:
            await self._registry.close_all()
        if self._storage is not None:
            await self._storage.close()
