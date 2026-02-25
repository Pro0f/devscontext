"""Tests for the Jira watcher."""

from unittest.mock import AsyncMock

import pytest
from pytest_httpx import HTTPXMock

from devscontext.agents.watcher import JiraWatcher
from devscontext.models import (
    AgentsConfig,
    AgentTriggerConfig,
    DevsContextConfig,
    JiraConfig,
    PreprocessorConfig,
    SourcesConfig,
    StorageConfig,
)


@pytest.fixture
def config() -> DevsContextConfig:
    """Create test configuration."""
    return DevsContextConfig(
        sources=SourcesConfig(
            jira=JiraConfig(
                base_url="https://test.atlassian.net",
                email="test@example.com",
                api_token="test-token",
                project="TEST",
                enabled=True,
            )
        ),
        agents=AgentsConfig(
            preprocessor=PreprocessorConfig(
                enabled=True,
                trigger=AgentTriggerConfig(poll_interval_minutes=5),
                jira_status="Ready for Development",
                jira_project="TEST",
            )
        ),
        storage=StorageConfig(path=".devscontext/test_cache.db"),
    )


@pytest.fixture
def mock_pipeline() -> AsyncMock:
    """Create mock preprocessing pipeline."""
    pipeline = AsyncMock()
    pipeline.process = AsyncMock()
    return pipeline


@pytest.fixture
def watcher(config: DevsContextConfig, mock_pipeline: AsyncMock) -> JiraWatcher:
    """Create test watcher."""
    return JiraWatcher(config, mock_pipeline)


# Sample Jira search response
SAMPLE_SEARCH_RESPONSE = {
    "issues": [
        {"key": "TEST-123"},
        {"key": "TEST-456"},
        {"key": "TEST-789"},
    ],
    "total": 3,
}


class TestJiraWatcher:
    """Tests for JiraWatcher."""

    def test_build_jql_single_project(self, watcher: JiraWatcher) -> None:
        """Test JQL query building with single project."""
        jql = watcher._build_jql()
        assert 'project = "TEST"' in jql
        assert 'status = "Ready for Development"' in jql
        assert "updated >= -1h" in jql

    def test_build_jql_multiple_projects(self, config: DevsContextConfig) -> None:
        """Test JQL query building with multiple projects."""
        config.agents.preprocessor.jira_project = ["PROJ1", "PROJ2", "PROJ3"]
        pipeline = AsyncMock()
        watcher = JiraWatcher(config, pipeline)

        jql = watcher._build_jql()
        assert "project IN (PROJ1, PROJ2, PROJ3)" in jql
        assert 'status = "Ready for Development"' in jql

    async def test_poll_once_returns_new_tickets(
        self, watcher: JiraWatcher, httpx_mock: HTTPXMock
    ) -> None:
        """Test polling returns new ticket IDs."""
        import re

        httpx_mock.add_response(
            url=re.compile(r"https://test\.atlassian\.net/rest/api/3/search.*"),
            json=SAMPLE_SEARCH_RESPONSE,
        )

        new_tickets = await watcher.poll_once()

        assert len(new_tickets) == 3
        assert "TEST-123" in new_tickets
        assert "TEST-456" in new_tickets
        assert "TEST-789" in new_tickets

    async def test_poll_once_filters_processed(
        self, watcher: JiraWatcher, httpx_mock: HTTPXMock
    ) -> None:
        """Test polling filters out already-processed tickets."""
        import re

        httpx_mock.add_response(
            url=re.compile(r"https://test\.atlassian\.net/rest/api/3/search.*"),
            json=SAMPLE_SEARCH_RESPONSE,
        )

        # Mark some as already processed
        watcher._processed_tickets.add("TEST-123")
        watcher._processed_tickets.add("TEST-456")

        new_tickets = await watcher.poll_once()

        assert len(new_tickets) == 1
        assert "TEST-789" in new_tickets

    async def test_poll_once_handles_api_error(
        self, watcher: JiraWatcher, httpx_mock: HTTPXMock
    ) -> None:
        """Test polling handles API errors gracefully."""
        import re

        httpx_mock.add_response(
            url=re.compile(r"https://test\.atlassian\.net/rest/api/3/search.*"),
            status_code=500,
        )

        new_tickets = await watcher.poll_once()

        assert new_tickets == []

    async def test_poll_once_disabled_jira_returns_empty(self, config: DevsContextConfig) -> None:
        """Test polling with disabled Jira returns empty list."""
        config.sources.jira.enabled = False
        pipeline = AsyncMock()
        watcher = JiraWatcher(config, pipeline)

        new_tickets = await watcher.poll_once()
        assert new_tickets == []

    async def test_process_ticket_calls_pipeline(
        self, watcher: JiraWatcher, mock_pipeline: AsyncMock
    ) -> None:
        """Test processing ticket calls the pipeline."""
        result = await watcher.process_ticket("TEST-123")

        assert result is True
        mock_pipeline.process.assert_called_once_with("TEST-123")
        assert "TEST-123" in watcher._processed_tickets

    async def test_process_ticket_handles_error(
        self, watcher: JiraWatcher, mock_pipeline: AsyncMock
    ) -> None:
        """Test processing handles pipeline errors."""
        mock_pipeline.process.side_effect = Exception("Pipeline failed")

        result = await watcher.process_ticket("TEST-123")

        assert result is False
        assert "TEST-123" not in watcher._processed_tickets

    async def test_run_once_returns_count(
        self, watcher: JiraWatcher, httpx_mock: HTTPXMock
    ) -> None:
        """Test run_once returns count of processed tickets."""
        import re

        httpx_mock.add_response(
            url=re.compile(r"https://test\.atlassian\.net/rest/api/3/search.*"),
            json={"issues": [{"key": "TEST-123"}, {"key": "TEST-456"}], "total": 2},
        )

        processed = await watcher.run_once()

        assert processed == 2

    def test_stop_sets_running_flag(self, watcher: JiraWatcher) -> None:
        """Test stop method sets running flag to False."""
        watcher._running = True
        watcher.stop()
        assert watcher._running is False

    def test_get_processed_count(self, watcher: JiraWatcher) -> None:
        """Test getting processed ticket count."""
        watcher._processed_tickets.add("TEST-1")
        watcher._processed_tickets.add("TEST-2")

        assert watcher.get_processed_count() == 2

    def test_clear_processed(self, watcher: JiraWatcher) -> None:
        """Test clearing processed tickets."""
        watcher._processed_tickets.add("TEST-1")
        watcher._processed_tickets.add("TEST-2")

        watcher.clear_processed()

        assert watcher.get_processed_count() == 0

    async def test_close_closes_client(self, watcher: JiraWatcher) -> None:
        """Test closing watcher closes HTTP client."""
        # Create a client first
        _ = watcher._get_client()
        assert watcher._client is not None

        await watcher.close()
        assert watcher._client is None
