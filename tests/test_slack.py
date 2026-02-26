"""Tests for the Slack adapter."""

import pytest
from pytest_httpx import HTTPXMock

from devscontext.adapters.slack import SlackAdapter
from devscontext.models import SlackConfig


@pytest.fixture
def slack_config() -> SlackConfig:
    """Create a test Slack configuration."""
    return SlackConfig(
        bot_token="xoxb-test-token",
        channels=["engineering", "payments-team"],
        include_threads=True,
        max_messages=20,
        lookback_days=30,
        enabled=True,
    )


@pytest.fixture
def slack_adapter(slack_config: SlackConfig) -> SlackAdapter:
    """Create a test Slack adapter."""
    return SlackAdapter(slack_config)


# Sample Slack API responses
SAMPLE_CONVERSATIONS_LIST = {
    "ok": True,
    "channels": [
        {"id": "C123456", "name": "engineering"},
        {"id": "C234567", "name": "payments-team"},
        {"id": "C345678", "name": "random"},
    ],
}

SAMPLE_CHANNEL_HISTORY = {
    "ok": True,
    "messages": [
        {
            "type": "message",
            "user": "U123456",
            "text": "Hey team, let's discuss PROJ-123 implementation",
            "ts": "1704067200.000000",
            "thread_ts": "1704067200.000000",
            "reply_count": 2,
        },
        {
            "type": "message",
            "user": "U234567",
            "text": "We decided to use the new API endpoint",
            "ts": "1704067300.000000",
        },
    ],
}

SAMPLE_THREAD_REPLIES = {
    "ok": True,
    "messages": [
        {
            "type": "message",
            "user": "U123456",
            "text": "Hey team, let's discuss PROJ-123 implementation",
            "ts": "1704067200.000000",
        },
        {
            "type": "message",
            "user": "U234567",
            "text": "I'll implement the webhook handler",
            "ts": "1704067250.000000",
            "thread_ts": "1704067200.000000",
        },
        {
            "type": "message",
            "user": "U345678",
            "text": "Let's go with the async approach",
            "ts": "1704067260.000000",
            "thread_ts": "1704067200.000000",
        },
    ],
}

SAMPLE_USER_INFO = {
    "ok": True,
    "user": {
        "id": "U123456",
        "profile": {
            "display_name": "Alice",
            "real_name": "Alice Smith",
        },
    },
}

SAMPLE_AUTH_TEST = {
    "ok": True,
    "user_id": "U123456",
    "team_id": "T123456",
}

SAMPLE_SEARCH_MESSAGES = {
    "ok": True,
    "messages": {
        "matches": [
            {
                "type": "message",
                "user": "U123456",
                "text": "Discussing PROJ-123 requirements",
                "ts": "1704067200.000000",
                "channel": {"id": "C123456", "name": "engineering"},
                "permalink": "https://team.slack.com/archives/C123456/p1704067200000000",
            },
        ],
    },
}

EMPTY_SEARCH_RESPONSE = {"ok": True, "messages": {"matches": []}}

ERROR_RESPONSE = {"ok": False, "error": "not_authed"}

RATE_LIMITED_RESPONSE = {"ok": False, "error": "ratelimited", "retry_after": 1}


class TestSlackAdapter:
    """Tests for SlackAdapter."""

    def test_name(self, slack_adapter: SlackAdapter) -> None:
        """Test adapter name."""
        assert slack_adapter.name == "slack"

    def test_source_type(self, slack_adapter: SlackAdapter) -> None:
        """Test adapter source type."""
        assert slack_adapter.source_type == "communication"

    @pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
    async def test_fetch_task_context_returns_source_context(
        self, slack_adapter: SlackAdapter, httpx_mock: HTTPXMock
    ) -> None:
        """Test that fetch_task_context returns a SourceContext."""
        import re

        # Mock search API (tries this first)
        httpx_mock.add_response(
            url=re.compile(r".*/search\.messages.*"),
            json=EMPTY_SEARCH_RESPONSE,
        )
        # Mock conversations.list
        httpx_mock.add_response(
            url=re.compile(r".*/conversations\.list.*"),
            json=SAMPLE_CONVERSATIONS_LIST,
        )
        # Mock conversations.history for channels (reusable)
        httpx_mock.add_response(
            url=re.compile(r".*/conversations\.history.*"),
            json=SAMPLE_CHANNEL_HISTORY,
        )
        httpx_mock.add_response(
            url=re.compile(r".*/conversations\.history.*"),
            json=SAMPLE_CHANNEL_HISTORY,
        )
        # Mock user lookups (enough for all users)
        for _ in range(5):
            httpx_mock.add_response(
                url=re.compile(r".*/users\.info.*"),
                json=SAMPLE_USER_INFO,
            )
        # Mock thread replies
        httpx_mock.add_response(
            url=re.compile(r".*/conversations\.replies.*"),
            json=SAMPLE_THREAD_REPLIES,
        )

        result = await slack_adapter.fetch_task_context("PROJ-123")

        assert result.source_name == "slack"
        assert result.source_type == "communication"

    async def test_fetch_task_context_disabled_returns_empty(self) -> None:
        """Test that fetch_task_context returns empty when adapter is disabled."""
        config = SlackConfig(bot_token="test-token", enabled=False)
        adapter = SlackAdapter(config)

        result = await adapter.fetch_task_context("PROJ-123")

        assert result.is_empty()

    async def test_fetch_task_context_no_token_returns_empty(self) -> None:
        """Test that fetch_task_context returns empty when no token configured."""
        config = SlackConfig(bot_token="", enabled=True)
        adapter = SlackAdapter(config)

        result = await adapter.fetch_task_context("PROJ-123")

        assert result.is_empty()

    async def test_health_check_success(
        self, slack_adapter: SlackAdapter, httpx_mock: HTTPXMock
    ) -> None:
        """Test health check when API is accessible."""
        import re

        httpx_mock.add_response(
            url=re.compile(r".*/auth\.test.*"),
            json=SAMPLE_AUTH_TEST,
        )

        result = await slack_adapter.health_check()

        assert result is True

    async def test_health_check_fails_on_error(
        self, slack_adapter: SlackAdapter, httpx_mock: HTTPXMock
    ) -> None:
        """Test health check fails on API error."""
        import re

        httpx_mock.add_response(
            url=re.compile(r".*/auth\.test.*"),
            json=ERROR_RESPONSE,
        )

        result = await slack_adapter.health_check()

        assert result is False

    async def test_health_check_disabled(self) -> None:
        """Test health check when adapter is disabled."""
        config = SlackConfig(bot_token="test-token", enabled=False)
        adapter = SlackAdapter(config)

        result = await adapter.health_check()

        assert result is True  # Disabled adapters are "healthy"

    async def test_health_check_no_token(self) -> None:
        """Test health check fails when no token configured."""
        config = SlackConfig(bot_token="", enabled=True)
        adapter = SlackAdapter(config)

        result = await adapter.health_check()

        assert result is False

    async def test_search_returns_results(
        self, slack_adapter: SlackAdapter, httpx_mock: HTTPXMock
    ) -> None:
        """Test search returns SearchResult items."""
        import re

        # Mock search API
        httpx_mock.add_response(
            url=re.compile(r".*/search\.messages.*"),
            json=SAMPLE_SEARCH_MESSAGES,
        )

        results = await slack_adapter.search("PROJ-123")

        assert len(results) == 1
        assert results[0].source_name == "slack"
        assert "PROJ-123" in results[0].excerpt

    async def test_search_disabled_returns_empty(self) -> None:
        """Test search returns empty when adapter is disabled."""
        config = SlackConfig(bot_token="test-token", enabled=False)
        adapter = SlackAdapter(config)

        results = await adapter.search("PROJ-123")

        assert len(results) == 0


class TestDecisionExtraction:
    """Tests for decision/action extraction logic."""

    def test_extract_decisions_finds_decided(
        self, slack_adapter: SlackAdapter
    ) -> None:
        """Test that 'decided' pattern is extracted."""
        text = "We decided to use PostgreSQL for this feature."
        decisions = slack_adapter._extract_decisions(text)
        assert len(decisions) >= 1
        assert "PostgreSQL" in decisions[0]

    def test_extract_decisions_finds_lets_go_with(
        self, slack_adapter: SlackAdapter
    ) -> None:
        """Test that 'let's go with' pattern is extracted."""
        text = "Let's go with the async implementation approach."
        decisions = slack_adapter._extract_decisions(text)
        assert len(decisions) >= 1

    def test_extract_decisions_finds_agreed(
        self, slack_adapter: SlackAdapter
    ) -> None:
        """Test that 'agreed' pattern is extracted."""
        text = "Agreed: we'll use the new API endpoint."
        decisions = slack_adapter._extract_decisions(text)
        assert len(decisions) >= 1

    def test_extract_action_items_finds_ill(
        self, slack_adapter: SlackAdapter
    ) -> None:
        """Test that \"I'll\" pattern is extracted."""
        text = "I'll implement the webhook handler tomorrow."
        actions = slack_adapter._extract_action_items(text)
        assert len(actions) >= 1
        assert "webhook" in actions[0]

    def test_extract_action_items_finds_can_you(
        self, slack_adapter: SlackAdapter
    ) -> None:
        """Test that '@user can you' pattern is extracted."""
        text = "@alice can you review the PR when you get a chance?"
        actions = slack_adapter._extract_action_items(text)
        assert len(actions) >= 1

    def test_extract_decisions_empty_on_no_match(
        self, slack_adapter: SlackAdapter
    ) -> None:
        """Test that no decisions extracted from plain text."""
        text = "Just a regular message about the project."
        decisions = slack_adapter._extract_decisions(text)
        assert len(decisions) == 0

    def test_extract_action_items_empty_on_no_match(
        self, slack_adapter: SlackAdapter
    ) -> None:
        """Test that no actions extracted from plain text."""
        text = "Just discussing some ideas here."
        actions = slack_adapter._extract_action_items(text)
        assert len(actions) == 0


class TestChannelHistoryCache:
    """Tests for channel history caching."""

    def test_cache_set_and_get(self, slack_adapter: SlackAdapter) -> None:
        """Test cache stores and retrieves values."""
        slack_adapter._channel_cache.set("C123", [{"text": "test"}])
        result = slack_adapter._channel_cache.get("C123")
        assert result == [{"text": "test"}]

    def test_cache_miss_returns_none(self, slack_adapter: SlackAdapter) -> None:
        """Test cache returns None for missing keys."""
        result = slack_adapter._channel_cache.get("NOTEXIST")
        assert result is None

    def test_cache_clear(self, slack_adapter: SlackAdapter) -> None:
        """Test cache clear removes all entries."""
        slack_adapter._channel_cache.set("C123", [{"text": "test"}])
        slack_adapter._channel_cache.clear()
        result = slack_adapter._channel_cache.get("C123")
        assert result is None


class TestRateLimiter:
    """Tests for rate limiter."""

    async def test_rate_limiter_allows_first_request(
        self, slack_adapter: SlackAdapter
    ) -> None:
        """Test rate limiter allows first request immediately."""
        # Should not raise or block significantly
        await slack_adapter._rate_limiter.acquire()
        # If we get here, it passed
        assert True
