"""Tests for the DevsContextCore orchestration."""

import pytest

from devscontext.core import DevsContextCore
from devscontext.models import (
    DevsContextConfig,
    DocsConfig,
    SourcesConfig,
    TaskContext,
)


@pytest.fixture
def config() -> DevsContextConfig:
    """Create a test configuration with all adapters disabled."""
    return DevsContextConfig(
        sources=SourcesConfig(
            docs=DocsConfig(enabled=False),
        ),
    )


@pytest.fixture
def core(config: DevsContextConfig) -> DevsContextCore:
    """Create a test DevsContextCore."""
    return DevsContextCore(config)


class TestDevsContextCore:
    """Tests for DevsContextCore."""

    async def test_get_task_context_returns_task_context(self, core: DevsContextCore) -> None:
        """Test that get_task_context returns a TaskContext."""
        result = await core.get_task_context("TEST-123")

        assert isinstance(result, TaskContext)
        assert result.task_id == "TEST-123"
        assert isinstance(result.synthesized, str)
        assert isinstance(result.sources_used, list)
        assert result.fetch_duration_ms >= 0

    async def test_get_task_context_task_id_matches(self, core: DevsContextCore) -> None:
        """Test that the task_id in response matches input."""
        result = await core.get_task_context("PROJ-456")

        assert result.task_id == "PROJ-456"

    async def test_get_task_context_no_adapters_enabled(self, core: DevsContextCore) -> None:
        """Test that context is still returned when no adapters enabled."""
        result = await core.get_task_context("TEST-123")

        assert result.task_id == "TEST-123"
        assert "No context found" in result.synthesized

    async def test_health_check_returns_dict(self, core: DevsContextCore) -> None:
        """Test that health_check returns expected structure."""
        result = await core.health_check()

        assert isinstance(result, dict)
        # When no adapters enabled, dict should be empty
        assert result == {}

    async def test_cache_invalidation(self, core: DevsContextCore) -> None:
        """Test cache invalidation."""
        # Get context (should cache)
        await core.get_task_context("CACHE-TEST")

        # Invalidate specific task
        core.invalidate_cache("CACHE-TEST")

        # Get again (should not use cache)
        result = await core.get_task_context("CACHE-TEST")
        assert result.task_id == "CACHE-TEST"
        assert result.cached is False

    async def test_cache_clear_all(self, core: DevsContextCore) -> None:
        """Test clearing entire cache."""
        await core.get_task_context("CACHE-1")
        await core.get_task_context("CACHE-2")

        # Clear all
        core.invalidate_cache()

        # Verify we can still get context
        result = await core.get_task_context("CACHE-1")
        assert result.task_id == "CACHE-1"
        assert result.cached is False

    async def test_cache_hit(self, core: DevsContextCore) -> None:
        """Test that cache hit returns cached=True."""
        # First call - not cached
        result1 = await core.get_task_context("CACHE-HIT")
        assert result1.cached is False

        # Second call - should be cached
        result2 = await core.get_task_context("CACHE-HIT")
        assert result2.cached is True

    async def test_use_cache_false_bypasses_cache(self, core: DevsContextCore) -> None:
        """Test that use_cache=False bypasses cache."""
        # First call
        await core.get_task_context("BYPASS-CACHE")

        # Second call with use_cache=False
        result = await core.get_task_context("BYPASS-CACHE", use_cache=False)
        assert result.cached is False
