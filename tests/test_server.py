"""Tests for the MCP server."""

import pytest

from devscontext.config import Config
from devscontext.core import ContextOrchestrator


@pytest.fixture
def config() -> Config:
    """Create a test configuration."""
    return Config()


@pytest.fixture
def orchestrator(config: Config) -> ContextOrchestrator:
    """Create a test orchestrator."""
    return ContextOrchestrator(config)


class TestContextOrchestrator:
    """Tests for ContextOrchestrator."""

    async def test_get_task_context_returns_dict(self, orchestrator: ContextOrchestrator) -> None:
        """Test that get_task_context returns a dict with expected keys."""
        result = await orchestrator.get_task_context("TEST-123")

        assert isinstance(result, dict)
        assert "task_id" in result
        assert "context" in result
        assert "sources" in result
        assert "item_count" in result

    async def test_get_task_context_task_id_matches(
        self, orchestrator: ContextOrchestrator
    ) -> None:
        """Test that the task_id in response matches input."""
        result = await orchestrator.get_task_context("PROJ-456")

        assert result["task_id"] == "PROJ-456"

    async def test_health_check_returns_status(self, orchestrator: ContextOrchestrator) -> None:
        """Test that health_check returns expected structure."""
        result = await orchestrator.health_check()

        assert isinstance(result, dict)
        assert "healthy" in result
        assert "adapters" in result
        assert isinstance(result["healthy"], bool)

    async def test_cache_invalidation(self, orchestrator: ContextOrchestrator) -> None:
        """Test cache invalidation."""
        # Get context (should cache)
        await orchestrator.get_task_context("CACHE-TEST")

        # Invalidate specific task
        orchestrator.invalidate_cache("CACHE-TEST")

        # Get again (should not use cache)
        result = await orchestrator.get_task_context("CACHE-TEST")
        assert result["task_id"] == "CACHE-TEST"

    async def test_cache_clear_all(self, orchestrator: ContextOrchestrator) -> None:
        """Test clearing entire cache."""
        await orchestrator.get_task_context("CACHE-1")
        await orchestrator.get_task_context("CACHE-2")

        # Clear all
        orchestrator.invalidate_cache()

        # Verify we can still get context
        result = await orchestrator.get_task_context("CACHE-1")
        assert result["task_id"] == "CACHE-1"
