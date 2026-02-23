"""Tests for the Jira adapter."""

import pytest

from devscontext.adapters.jira import JiraAdapter
from devscontext.config import JiraConfig


@pytest.fixture
def jira_config() -> JiraConfig:
    """Create a test Jira configuration."""
    return JiraConfig(
        base_url="https://test.atlassian.net",
        email="test@example.com",
        api_token="test-token",
        enabled=True,
    )


@pytest.fixture
def jira_adapter(jira_config: JiraConfig) -> JiraAdapter:
    """Create a test Jira adapter."""
    return JiraAdapter(jira_config)


class TestJiraAdapter:
    """Tests for JiraAdapter."""

    def test_name(self, jira_adapter: JiraAdapter) -> None:
        """Test adapter name."""
        assert jira_adapter.name == "jira"

    def test_source_type(self, jira_adapter: JiraAdapter) -> None:
        """Test adapter source type."""
        assert jira_adapter.source_type == "issue_tracker"

    async def test_fetch_context_returns_list(
        self, jira_adapter: JiraAdapter
    ) -> None:
        """Test that fetch_context returns a list of ContextData."""
        result = await jira_adapter.fetch_context("TEST-123")

        assert isinstance(result, list)
        assert len(result) > 0

    async def test_fetch_context_has_required_fields(
        self, jira_adapter: JiraAdapter
    ) -> None:
        """Test that returned context has required fields."""
        result = await jira_adapter.fetch_context("TEST-123")
        context = result[0]

        assert context.source == "jira:TEST-123"
        assert context.source_type == "issue_tracker"
        assert context.title
        assert context.content

    async def test_health_check_with_config(
        self, jira_adapter: JiraAdapter
    ) -> None:
        """Test health check when configured."""
        result = await jira_adapter.health_check()

        assert isinstance(result, bool)
        assert result is True  # Should pass with test config

    async def test_health_check_disabled(self) -> None:
        """Test health check when adapter is disabled."""
        config = JiraConfig(enabled=False)
        adapter = JiraAdapter(config)

        result = await adapter.health_check()

        assert result is True  # Disabled adapters are "healthy"
