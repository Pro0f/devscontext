"""Integration tests with real APIs.

These tests require real API credentials and are skipped in CI.
Run manually with:
    pytest tests/test_integration.py -v -s

Set the following environment variables:
    - JIRA_API_TOKEN: Jira API token
    - JIRA_BASE_URL: Jira instance URL (e.g., https://company.atlassian.net)
    - JIRA_EMAIL: Jira authentication email
    - FIREFLIES_API_KEY: Fireflies.ai API key
    - ANTHROPIC_API_KEY: Anthropic API key (for LLM synthesis)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from devscontext.config import load_devscontext_config
from devscontext.core import DevsContextCore

if TYPE_CHECKING:
    from devscontext.models import DevsContextConfig

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


@pytest.fixture
def real_config() -> DevsContextConfig:
    """Load real configuration from environment or config file."""
    # Try to load from config file first
    config = load_devscontext_config()

    # Override with environment variables if present
    jira_token = os.getenv("JIRA_API_TOKEN")
    jira_url = os.getenv("JIRA_BASE_URL")
    jira_email = os.getenv("JIRA_EMAIL")
    fireflies_key = os.getenv("FIREFLIES_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")

    if jira_token and jira_url and jira_email:
        config.sources.jira.api_token = jira_token
        config.sources.jira.base_url = jira_url
        config.sources.jira.email = jira_email
        config.sources.jira.enabled = True

    if fireflies_key:
        config.sources.fireflies.api_key = fireflies_key
        config.sources.fireflies.enabled = True

    if anthropic_key:
        config.synthesis.api_key = anthropic_key
        config.synthesis.provider = "anthropic"

    return config


@pytest.fixture
def real_core(real_config: DevsContextConfig) -> DevsContextCore:
    """Create a DevsContextCore with real configuration."""
    return DevsContextCore(real_config)


def has_jira_credentials() -> bool:
    """Check if Jira credentials are available."""
    return bool(
        os.getenv("JIRA_API_TOKEN") and os.getenv("JIRA_BASE_URL") and os.getenv("JIRA_EMAIL")
    )


def has_fireflies_credentials() -> bool:
    """Check if Fireflies credentials are available."""
    return bool(os.getenv("FIREFLIES_API_KEY"))


def has_anthropic_credentials() -> bool:
    """Check if Anthropic credentials are available."""
    return bool(os.getenv("ANTHROPIC_API_KEY"))


class TestJiraIntegration:
    """Integration tests for Jira adapter."""

    @pytest.mark.skipif(not has_jira_credentials(), reason="No Jira credentials")
    async def test_fetch_real_ticket(self, real_core: DevsContextCore) -> None:
        """Test fetching a real Jira ticket."""
        # Use a known ticket ID - update this for your project
        ticket_id = os.getenv("TEST_JIRA_TICKET", "TEST-1")

        result = await real_core.get_task_context(ticket_id)

        assert result.task_id == ticket_id
        assert result.synthesized  # non-empty
        assert result.fetch_duration_ms > 0

        # Should have jira in sources if ticket exists
        _jira_sources = [s for s in result.sources_used if s.startswith("jira:")]
        print(f"\nFetched context for {ticket_id} (jira sources: {len(_jira_sources)}):")
        print(f"  Sources: {result.sources_used}")
        print(f"  Duration: {result.fetch_duration_ms}ms")
        print(f"\nSynthesized output:\n{result.synthesized[:500]}...")

    @pytest.mark.skipif(not has_jira_credentials(), reason="No Jira credentials")
    async def test_jira_health_check(self, real_core: DevsContextCore) -> None:
        """Test Jira health check with real credentials."""
        health = await real_core.health_check()

        assert "jira" in health
        assert health["jira"] is True, "Jira health check failed"


class TestFirefliesIntegration:
    """Integration tests for Fireflies adapter."""

    @pytest.mark.skipif(not has_fireflies_credentials(), reason="No Fireflies credentials")
    async def test_fireflies_health_check(self, real_core: DevsContextCore) -> None:
        """Test Fireflies health check with real credentials."""
        health = await real_core.health_check()

        assert "fireflies" in health
        assert health["fireflies"] is True, "Fireflies health check failed"

    @pytest.mark.skipif(not has_fireflies_credentials(), reason="No Fireflies credentials")
    async def test_search_meeting_transcripts(self, real_core: DevsContextCore) -> None:
        """Test searching meeting transcripts."""
        # Use a known ticket ID that should appear in meeting transcripts
        ticket_id = os.getenv("TEST_JIRA_TICKET", "TEST-1")

        result = await real_core.get_task_context(ticket_id)

        # Check if any meeting sources were found
        meeting_sources = [s for s in result.sources_used if s.startswith("fireflies:")]
        print(f"\nMeeting sources found: {meeting_sources}")
        print(f"Total sources: {result.sources_used}")


class TestFullFlow:
    """End-to-end integration tests."""

    @pytest.mark.skipif(
        not (has_jira_credentials() and has_anthropic_credentials()),
        reason="Missing Jira or Anthropic credentials",
    )
    async def test_full_flow_with_synthesis(self, real_core: DevsContextCore) -> None:
        """Test full flow with real Jira data and LLM synthesis."""
        ticket_id = os.getenv("TEST_JIRA_TICKET", "TEST-1")

        result = await real_core.get_task_context(ticket_id)

        assert result.task_id == ticket_id
        assert result.synthesized
        assert len(result.sources_used) > 0
        assert result.fetch_duration_ms > 0

        # Print for manual inspection
        print(f"\n{'=' * 60}")
        print(f"Full Flow Test: {ticket_id}")
        print(f"{'=' * 60}")
        print(f"Sources used: {result.sources_used}")
        print(f"Duration: {result.fetch_duration_ms}ms")
        print(f"Cached: {result.cached}")
        print("\n--- SYNTHESIZED OUTPUT ---\n")
        print(result.synthesized)
        print(f"\n{'=' * 60}")

    @pytest.mark.skipif(
        not (has_jira_credentials() and has_fireflies_credentials()),
        reason="Missing Jira or Fireflies credentials",
    )
    async def test_cross_source_context(self, real_core: DevsContextCore) -> None:
        """Test that context is fetched from multiple sources."""
        ticket_id = os.getenv("TEST_JIRA_TICKET", "TEST-1")

        result = await real_core.get_task_context(ticket_id)

        # Check for sources from different adapters
        jira_sources = [s for s in result.sources_used if s.startswith("jira:")]
        fireflies_sources = [s for s in result.sources_used if s.startswith("fireflies:")]
        docs_sources = [s for s in result.sources_used if s.startswith("docs:")]

        print(f"\nCross-source context for {ticket_id}:")
        print(f"  Jira sources: {len(jira_sources)}")
        print(f"  Fireflies sources: {len(fireflies_sources)}")
        print(f"  Docs sources: {len(docs_sources)}")

        # At minimum, Jira should have data
        assert len(jira_sources) > 0 or "No context found" not in result.synthesized

    @pytest.mark.skipif(not has_jira_credentials(), reason="No Jira credentials")
    async def test_cache_behavior(self, real_core: DevsContextCore) -> None:
        """Test that caching works correctly."""
        ticket_id = os.getenv("TEST_JIRA_TICKET", "TEST-1")

        # First call - not cached
        result1 = await real_core.get_task_context(ticket_id)
        assert result1.cached is False

        # Second call - should be cached
        result2 = await real_core.get_task_context(ticket_id)
        assert result2.cached is True
        assert result2.fetch_duration_ms < result1.fetch_duration_ms

        print(f"\nCache test for {ticket_id}:")
        print(f"  First call: {result1.fetch_duration_ms}ms (cached={result1.cached})")
        print(f"  Second call: {result2.fetch_duration_ms}ms (cached={result2.cached})")

        # Third call with refresh - should not use cache
        result3 = await real_core.get_task_context(ticket_id, use_cache=False)
        assert result3.cached is False
        print(f"  Refresh call: {result3.fetch_duration_ms}ms (cached={result3.cached})")
