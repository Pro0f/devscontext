"""Core orchestration logic for DevsContext.

This module contains the ContextOrchestrator class which coordinates
fetching context from multiple adapters, synthesizing the results,
and caching for performance.

Example:
    config = load_config()
    orchestrator = ContextOrchestrator(config)
    result = await orchestrator.get_task_context("PROJ-123")
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from devscontext.adapters import (
    Adapter,
    FirefliesAdapter,
    JiraAdapter,
    LocalDocsAdapter,
)
from devscontext.cache import SimpleCache
from devscontext.constants import DEFAULT_CACHE_MAX_SIZE, DEFAULT_CACHE_TTL_SECONDS
from devscontext.logging import get_logger
from devscontext.synthesis import format_context_for_llm, synthesize_context

if TYPE_CHECKING:
    from devscontext.config import Config
    from devscontext.models import ContextData

logger = get_logger(__name__)


class ContextOrchestrator:
    """Orchestrates context fetching from multiple adapters.

    This class is the main coordinator for DevsContext. It:
        - Initializes adapters based on configuration
        - Fetches context from all adapters in parallel
        - Synthesizes and formats the results
        - Caches results for performance

    Attributes:
        _config: The application configuration.
        _cache: In-memory TTL cache.
        _adapters: List of initialized adapters.
    """

    def __init__(self, config: Config) -> None:
        """Initialize the orchestrator.

        Args:
            config: Application configuration.
        """
        self._config = config
        self._cache = SimpleCache(
            ttl=config.cache.ttl_seconds or DEFAULT_CACHE_TTL_SECONDS,
            max_size=config.cache.max_size or DEFAULT_CACHE_MAX_SIZE,
        )
        self._adapters: list[Adapter] = self._initialize_adapters()

        logger.info(
            "ContextOrchestrator initialized",
            extra={"adapter_count": len(self._adapters)},
        )

    def _initialize_adapters(self) -> list[Adapter]:
        """Initialize all configured adapters.

        Returns:
            List of enabled adapters.
        """
        adapters: list[Adapter] = []

        if self._config.adapters.jira.enabled:
            adapters.append(JiraAdapter(self._config.adapters.jira))
            logger.debug("Jira adapter enabled")

        if self._config.adapters.fireflies.enabled:
            adapters.append(FirefliesAdapter(self._config.adapters.fireflies))
            logger.debug("Fireflies adapter enabled")

        if self._config.adapters.local_docs.enabled:
            adapters.append(LocalDocsAdapter(self._config.adapters.local_docs))
            logger.debug("Local docs adapter enabled")

        return adapters

    async def get_task_context(
        self,
        task_id: str,
        *,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """Get aggregated context for a task.

        Fetches context from all configured adapters in parallel,
        synthesizes the results, and formats them for LLM consumption.

        Args:
            task_id: The task identifier (e.g., Jira ticket ID).
            use_cache: Whether to use cached results.

        Returns:
            Dictionary containing:
                - task_id: The queried task ID
                - context: Formatted context string
                - sources: List of sources that contributed
                - item_count: Number of context items
                - cached: Whether result was from cache
        """
        start_time = time.monotonic()
        cache_key = f"context:{task_id}"

        # Check cache
        if use_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                logger.info(
                    "Cache hit for task context",
                    extra={"task_id": task_id},
                )
                cached_dict = dict(cached) if isinstance(cached, dict) else {}
                cached_dict["cached"] = True
                return cached_dict

        # Fetch context from all adapters in parallel
        all_context: list[ContextData] = []

        tasks = [adapter.fetch_context(task_id) for adapter in self._adapters]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                adapter_name = self._adapters[i].name if i < len(self._adapters) else "unknown"
                logger.error(
                    "Adapter fetch failed",
                    extra={"adapter": adapter_name, "error": str(result)},
                )
                continue
            all_context.extend(result)

        # Synthesize and format
        synthesized = synthesize_context(all_context)
        formatted = format_context_for_llm(synthesized)

        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.info(
            "Fetched task context",
            extra={
                "task_id": task_id,
                "source_count": len(synthesized),
                "duration_ms": duration_ms,
            },
        )

        response: dict[str, Any] = {
            "task_id": task_id,
            "context": formatted,
            "sources": [item.source for item in synthesized],
            "item_count": len(synthesized),
            "cached": False,
        }

        if use_cache:
            self._cache.set(cache_key, response)

        return response

    async def search_context(self, query: str) -> dict[str, Any]:
        """Search across all sources by keyword.

        Args:
            query: The search query.

        Returns:
            Dictionary containing search results and metadata.
        """
        start_time = time.monotonic()
        sources = [adapter.name for adapter in self._adapters]

        # TODO: Implement real search across adapters
        logger.info(
            "Search context (stub)",
            extra={"query": query, "sources": sources},
        )

        results = f"""## Search Results

No real search implemented yet. Query: "{query}"

This will search across:
- Jira tickets (title, description, comments)
- Meeting transcripts (full text search)
- Local documentation (keyword matching)
"""

        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.info(
            "Search completed",
            extra={"query": query, "duration_ms": duration_ms},
        )

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
        logger.info(
            "Get standards (stub)",
            extra={"area": area},
        )

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

    async def health_check(self) -> dict[str, Any]:
        """Check health of all adapters.

        Returns:
            Dictionary with:
                - healthy: Overall health status
                - adapters: Per-adapter health status
        """
        results: dict[str, bool] = {}

        for adapter in self._adapters:
            try:
                results[adapter.name] = await adapter.health_check()
            except Exception as e:
                logger.exception(
                    "Health check failed",
                    extra={"adapter": adapter.name, "error": str(e)},
                )
                results[adapter.name] = False

        overall_healthy = all(results.values()) if results else True

        logger.info(
            "Health check completed",
            extra={"healthy": overall_healthy, "adapters": results},
        )

        return {
            "healthy": overall_healthy,
            "adapters": results,
        }

    def invalidate_cache(self, task_id: str | None = None) -> None:
        """Invalidate cached context.

        Args:
            task_id: Specific task to invalidate, or None to clear all.
        """
        if task_id:
            self._cache.invalidate(f"context:{task_id}")
            logger.debug("Cache invalidated", extra={"task_id": task_id})
        else:
            self._cache.clear()
            logger.debug("Cache cleared")
