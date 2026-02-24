"""Core orchestration logic for DevsContext.

This module contains the DevsContextCore class which coordinates
fetching context from multiple adapters, synthesizing the results
with an LLM, and caching for performance.

Example:
    config = DevsContextConfig(
        sources=SourcesConfig(
            jira=JiraConfig(enabled=True, base_url="https://..."),
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

from devscontext.adapters import FirefliesAdapter, JiraAdapter, LocalDocsAdapter
from devscontext.cache import SimpleCache
from devscontext.logging import get_logger
from devscontext.models import DocsContext, JiraContext, JiraTicket, MeetingContext, TaskContext
from devscontext.synthesis import SynthesisEngine
from devscontext.utils import extract_keywords

if TYPE_CHECKING:
    from devscontext.models import DevsContextConfig

logger = get_logger(__name__)


class DevsContextCore:
    """Core orchestration for fetching and synthesizing engineering context.

    This class coordinates:
        - Fetching context from Jira, Fireflies, and local docs in parallel
        - Synthesizing raw context into structured markdown via LLM
        - Caching results to avoid redundant API calls

    Adapters are initialized lazily on first use.
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

        # Lazy-initialized adapters
        self._jira: JiraAdapter | None = None
        self._fireflies: FirefliesAdapter | None = None
        self._docs: LocalDocsAdapter | None = None

        # Lazy-initialized synthesis engine
        self._synthesis: SynthesisEngine | None = None

        logger.info(
            "DevsContextCore initialized",
            extra={
                "cache_enabled": config.cache.enabled,
                "jira_enabled": config.sources.jira.enabled,
                "fireflies_enabled": config.sources.fireflies.enabled,
                "docs_enabled": config.sources.docs.enabled,
            },
        )

    def _get_jira(self) -> JiraAdapter | None:
        """Get or create the Jira adapter (lazy initialization)."""
        if self._jira is None and self._config.sources.jira.enabled:
            self._jira = JiraAdapter(self._config.sources.jira)
        return self._jira

    def _get_fireflies(self) -> FirefliesAdapter | None:
        """Get or create the Fireflies adapter (lazy initialization)."""
        if self._fireflies is None and self._config.sources.fireflies.enabled:
            self._fireflies = FirefliesAdapter(self._config.sources.fireflies)
        return self._fireflies

    def _get_docs(self) -> LocalDocsAdapter | None:
        """Get or create the local docs adapter (lazy initialization)."""
        if self._docs is None and self._config.sources.docs.enabled:
            self._docs = LocalDocsAdapter(self._config.sources.docs)
        return self._docs

    def _get_synthesis(self) -> SynthesisEngine:
        """Get or create the synthesis engine (lazy initialization)."""
        if self._synthesis is None:
            self._synthesis = SynthesisEngine(self._config.synthesis)
        return self._synthesis

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

        # Fetch context from adapters in parallel
        jira_context, meeting_context, docs_context = await self._fetch_all_context(task_id)

        # Build sources list
        sources_used: list[str] = []
        if jira_context and jira_context.ticket:
            sources_used.append(f"jira:{jira_context.ticket.ticket_id}")
        if meeting_context and meeting_context.meetings:
            sources_used.extend(
                f"fireflies:{m.meeting_date.strftime('%Y-%m-%d')}" for m in meeting_context.meetings
            )
        if docs_context and docs_context.sections:
            sources_used.extend(f"docs:{s.file_path}" for s in docs_context.sections)

        # Synthesize with LLM
        synthesis_engine = self._get_synthesis()
        synthesized = await synthesis_engine.synthesize(
            task_id=task_id,
            jira_context=jira_context,
            meeting_context=meeting_context,
            docs_context=docs_context,
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
    ) -> tuple[JiraContext | None, MeetingContext | None, DocsContext | None]:
        """Fetch context from all adapters.

        Strategy: Fetch Jira FIRST to get ticket data, then fetch meetings + docs
        in parallel (both benefit from ticket data for better matching).

        Args:
            task_id: The task identifier.

        Returns:
            Tuple of (JiraContext, MeetingContext, DocsContext), each may be None.
        """
        # Step 1: Fetch Jira first - we need ticket data for doc/meeting matching
        jira_result: JiraContext | None = None
        ticket: JiraTicket | None = None

        try:
            jira_result = await self._fetch_jira_context(task_id)
            if jira_result:
                ticket = jira_result.ticket
        except Exception as e:
            logger.warning("Jira fetch failed", extra={"error": str(e), "task_id": task_id})

        # Step 2: Fetch meetings and docs in parallel, passing ticket data
        meeting_coro = self._fetch_meeting_context(task_id, ticket)
        docs_coro = self._fetch_docs_context(task_id, ticket)

        results = await asyncio.gather(meeting_coro, docs_coro, return_exceptions=True)
        raw_meeting, raw_docs = results

        # Handle any exceptions with proper type narrowing
        meeting_result: MeetingContext | None = None
        if isinstance(raw_meeting, BaseException):
            logger.warning(
                "Fireflies fetch failed",
                extra={"error": str(raw_meeting), "task_id": task_id},
            )
        elif isinstance(raw_meeting, MeetingContext):
            meeting_result = raw_meeting

        docs_result: DocsContext | None = None
        if isinstance(raw_docs, BaseException):
            logger.warning(
                "Docs fetch failed",
                extra={"error": str(raw_docs), "task_id": task_id},
            )
        elif isinstance(raw_docs, DocsContext):
            docs_result = raw_docs

        return jira_result, meeting_result, docs_result

    async def _fetch_jira_context(self, task_id: str) -> JiraContext | None:
        """Fetch Jira context for a task."""
        jira = self._get_jira()
        if jira is None:
            return None
        return await jira.get_jira_context(task_id)

    async def _fetch_meeting_context(
        self,
        task_id: str,
        ticket: JiraTicket | None = None,
    ) -> MeetingContext | None:
        """Fetch meeting context for a task.

        Searches by task_id first, then also by title keywords if ticket is available.

        Args:
            task_id: The task identifier.
            ticket: Optional Jira ticket for keyword-enriched search.

        Returns:
            MeetingContext with relevant meeting excerpts.
        """
        fireflies = self._get_fireflies()
        if fireflies is None:
            return None

        # Always search by task_id
        context = await fireflies.get_meeting_context(task_id)

        # If we have ticket data, also search by title keywords
        if ticket and ticket.title:
            keywords = extract_keywords(ticket.title)
            if keywords:
                # Search by top 3 keywords joined
                keyword_query = " ".join(keywords[:3])
                additional = await fireflies.get_meeting_context(keyword_query)

                # Merge results, avoiding duplicates by meeting title + date
                if additional and additional.meetings:
                    existing_keys = {
                        (m.meeting_title, m.meeting_date.date())
                        for m in (context.meetings if context else [])
                    }
                    for meeting in additional.meetings:
                        key = (meeting.meeting_title, meeting.meeting_date.date())
                        if key not in existing_keys:
                            if context is None:
                                context = MeetingContext(meetings=[])
                            context.meetings.append(meeting)
                            existing_keys.add(key)

        return context

    async def _fetch_docs_context(
        self,
        task_id: str,
        ticket: JiraTicket | None = None,
    ) -> DocsContext | None:
        """Fetch documentation context for a task.

        If ticket data is available, uses component/label/keyword matching.
        Otherwise falls back to returning general standards only.

        Args:
            task_id: The task identifier.
            ticket: Optional Jira ticket for targeted doc matching.

        Returns:
            DocsContext with relevant documentation sections.
        """
        docs = self._get_docs()
        if docs is None:
            return None

        if ticket:
            # Use ticket data for targeted matching
            return await docs.find_relevant_docs(ticket)
        else:
            # Fallback: return general standards when no ticket data
            logger.info(
                "No ticket data available, falling back to general standards",
                extra={"task_id": task_id},
            )
            return await docs.get_standards()

    async def health_check(self) -> dict[str, bool]:
        """Check health of all configured adapters.

        Returns:
            Dictionary mapping adapter names to health status.
        """
        results: dict[str, bool] = {}

        # Check each adapter if configured
        jira = self._get_jira()
        if jira is not None:
            try:
                results["jira"] = await jira.health_check()
            except Exception as e:
                logger.warning("Jira health check failed", extra={"error": str(e)})
                results["jira"] = False

        fireflies = self._get_fireflies()
        if fireflies is not None:
            try:
                results["fireflies"] = await fireflies.health_check()
            except Exception as e:
                logger.warning("Fireflies health check failed", extra={"error": str(e)})
                results["fireflies"] = False

        docs = self._get_docs()
        if docs is not None:
            try:
                results["docs"] = await docs.health_check()
            except Exception as e:
                logger.warning("Docs health check failed", extra={"error": str(e)})
                results["docs"] = False

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
        jira = self._get_jira()
        if jira is None:
            return []
        return await jira.search_issues(query, max_results=5)

    async def _search_meetings(self, query: str) -> MeetingContext:
        """Search meeting transcripts for query."""
        fireflies = self._get_fireflies()
        if fireflies is None:
            return MeetingContext(meetings=[])
        return await fireflies.get_meeting_context(query)

    async def _search_docs(self, query: str) -> DocsContext:
        """Search local documentation for query."""
        docs = self._get_docs()
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

        docs = self._get_docs()
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
        """Close all adapter connections."""
        if self._jira is not None:
            await self._jira.close()
        if self._fireflies is not None:
            await self._fireflies.close()
        # LocalDocsAdapter doesn't have async resources to close
