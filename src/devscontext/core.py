"""Core orchestration logic for DevsContext."""

import asyncio
from typing import Any

from devscontext.adapters import (
    Adapter,
    ContextData,
    FirefliesAdapter,
    JiraAdapter,
    LocalDocsAdapter,
)
from devscontext.cache import ContextCache
from devscontext.config import Config
from devscontext.synthesis import format_context_for_llm, synthesize_context


class ContextOrchestrator:
    """Orchestrates context fetching from multiple adapters."""

    def __init__(self, config: Config) -> None:
        """Initialize the orchestrator.

        Args:
            config: Application configuration.
        """
        self._config = config
        self._cache = ContextCache(
            ttl=config.cache.ttl_seconds,
            max_size=config.cache.max_size,
        )
        self._adapters: list[Adapter] = self._initialize_adapters()

    def _initialize_adapters(self) -> list[Adapter]:
        """Initialize all configured adapters."""
        adapters: list[Adapter] = []

        if self._config.adapters.jira.enabled:
            adapters.append(JiraAdapter(self._config.adapters.jira))

        if self._config.adapters.fireflies.enabled:
            adapters.append(FirefliesAdapter(self._config.adapters.fireflies))

        if self._config.adapters.local_docs.enabled:
            adapters.append(LocalDocsAdapter(self._config.adapters.local_docs))

        return adapters

    async def get_task_context(
        self,
        task_id: str,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """Get aggregated context for a task.

        Args:
            task_id: The task identifier (e.g., Jira ticket ID).
            use_cache: Whether to use cached results.

        Returns:
            Dictionary containing formatted context and metadata.
        """
        cache_key = f"context:{task_id}"

        if use_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached  # type: ignore

        # Fetch context from all adapters in parallel
        all_context: list[ContextData] = []

        tasks = [adapter.fetch_context(task_id) for adapter in self._adapters]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                # TODO: Log the error
                continue
            all_context.extend(result)

        # Synthesize and format
        synthesized = synthesize_context(all_context)
        formatted = format_context_for_llm(synthesized)

        response: dict[str, Any] = {
            "task_id": task_id,
            "context": formatted,
            "sources": [item.source for item in synthesized],
            "item_count": len(synthesized),
        }

        if use_cache:
            self._cache.set(cache_key, response)

        return response

    async def health_check(self) -> dict[str, Any]:
        """Check health of all adapters.

        Returns:
            Dictionary with health status for each adapter.
        """
        results: dict[str, bool] = {}

        for adapter in self._adapters:
            try:
                results[adapter.name] = await adapter.health_check()
            except Exception:
                results[adapter.name] = False

        return {
            "healthy": all(results.values()),
            "adapters": results,
        }

    async def search_context(self, query: str) -> dict[str, Any]:
        """Search across all sources by keyword.

        Args:
            query: The search query.

        Returns:
            Dictionary containing search results and metadata.
        """
        # TODO: Implement real search across adapters
        # For now, return stub data
        sources = [adapter.name for adapter in self._adapters]

        results = f"""## Search Results

No real search implemented yet. Query: "{query}"

This will search across:
- Jira tickets (title, description, comments)
- Meeting transcripts (full text search)
- Local documentation (keyword matching)
"""

        return {
            "query": query,
            "results": results,
            "sources": sources if sources else ["none configured"],
            "result_count": 0,
        }

    async def get_standards(self, area: str | None = None) -> dict[str, Any]:
        """Get coding standards from local documentation.

        Args:
            area: Optional area to filter (e.g., 'typescript', 'testing').

        Returns:
            Dictionary containing standards content.
        """
        # TODO: Implement real standards fetching from local_docs adapter
        # For now, return stub data
        area_filter = f" for {area}" if area else ""

        content = f"""## Coding Standards{area_filter}

No standards documents configured yet.

To add standards:
1. Create markdown files in your docs directory
2. Configure `local_docs.paths` in .devscontext.yaml
3. Name files like `standards-typescript.md`, `standards-testing.md`, etc.

Example structure:
```
docs/
  standards/
    typescript.md
    testing.md
    api-design.md
```
"""

        return {
            "area": area,
            "content": content,
        }

    def invalidate_cache(self, task_id: str | None = None) -> None:
        """Invalidate cached context.

        Args:
            task_id: Specific task to invalidate, or None to clear all.
        """
        if task_id:
            self._cache.invalidate(f"context:{task_id}")
        else:
            self._cache.clear()
