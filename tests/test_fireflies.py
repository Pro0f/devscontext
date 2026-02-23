"""Tests for the Fireflies adapter."""

import pytest
from pytest_httpx import HTTPXMock

from devscontext.adapters.fireflies import FirefliesAdapter
from devscontext.config import FirefliesConfig
from devscontext.constants import FIREFLIES_API_URL


@pytest.fixture
def fireflies_config() -> FirefliesConfig:
    """Create a test Fireflies configuration."""
    return FirefliesConfig(
        api_key="test-api-key",
        enabled=True,
    )


@pytest.fixture
def fireflies_adapter(fireflies_config: FirefliesConfig) -> FirefliesAdapter:
    """Create a test Fireflies adapter."""
    return FirefliesAdapter(fireflies_config)


# Sample Fireflies GraphQL responses
SAMPLE_TRANSCRIPTS_RESPONSE = {
    "data": {
        "transcripts": [
            {
                "id": "transcript-123",
                "title": "Sprint Planning - Auth Implementation",
                "date": "2024-01-15T10:00:00Z",
                "participants": ["Sarah", "Mike", "Developer"],
                "summary": {
                    "overview": "Discussion about authentication implementation for PROJ-123",
                    "action_items": [
                        "Implement PKCE flow",
                        "Set up vault integration",
                    ],
                    "keywords": ["auth", "PROJ-123", "OAuth"],
                },
                "sentences": [
                    {"text": "Let's discuss PROJ-123 today.", "speaker_name": "Sarah"},
                    {"text": "We need to implement authentication.", "speaker_name": "Sarah"},
                    {"text": "I think we should use OAuth.", "speaker_name": "Mike"},
                    {"text": "Good idea, let's go with Google OAuth.", "speaker_name": "Sarah"},
                    {"text": "Make sure to use PKCE for security.", "speaker_name": "Mike"},
                    {"text": "Agreed, I'll handle PROJ-123.", "speaker_name": "Developer"},
                    {"text": "Great, let's move on.", "speaker_name": "Sarah"},
                ],
            }
        ]
    }
}

EMPTY_TRANSCRIPTS_RESPONSE = {"data": {"transcripts": []}}

GRAPHQL_ERROR_RESPONSE = {
    "errors": [{"message": "Authentication failed"}],
    "data": None,
}

SAMPLE_USER_RESPONSE = {"data": {"user": {"email": "test@example.com"}}}


class TestFirefliesAdapter:
    """Tests for FirefliesAdapter."""

    def test_name(self, fireflies_adapter: FirefliesAdapter) -> None:
        """Test adapter name."""
        assert fireflies_adapter.name == "fireflies"

    def test_source_type(self, fireflies_adapter: FirefliesAdapter) -> None:
        """Test adapter source type."""
        assert fireflies_adapter.source_type == "meeting"

    async def test_fetch_context_returns_list(
        self, fireflies_adapter: FirefliesAdapter, httpx_mock: HTTPXMock
    ) -> None:
        """Test that fetch_context returns a list with matching transcripts."""
        httpx_mock.add_response(
            url=FIREFLIES_API_URL,
            json=SAMPLE_TRANSCRIPTS_RESPONSE,
        )

        result = await fireflies_adapter.fetch_context("PROJ-123")

        assert isinstance(result, list)
        assert len(result) == 1

    async def test_fetch_context_has_required_fields(
        self, fireflies_adapter: FirefliesAdapter, httpx_mock: HTTPXMock
    ) -> None:
        """Test that returned context has required fields."""
        httpx_mock.add_response(
            url=FIREFLIES_API_URL,
            json=SAMPLE_TRANSCRIPTS_RESPONSE,
        )

        result = await fireflies_adapter.fetch_context("PROJ-123")
        context = result[0]

        assert context.source.startswith("fireflies:")
        assert context.source_type == "meeting"
        assert "Sprint Planning" in context.title
        assert "PROJ-123" in context.content
        assert context.metadata["participants"] == ["Sarah", "Mike", "Developer"]

    async def test_fetch_context_extracts_relevant_excerpts(
        self, fireflies_adapter: FirefliesAdapter, httpx_mock: HTTPXMock
    ) -> None:
        """Test that excerpts are extracted with surrounding context."""
        httpx_mock.add_response(
            url=FIREFLIES_API_URL,
            json=SAMPLE_TRANSCRIPTS_RESPONSE,
        )

        result = await fireflies_adapter.fetch_context("PROJ-123")
        context = result[0]

        # Should include sentences mentioning PROJ-123 and surrounding context
        assert "PROJ-123" in context.content
        assert "Sarah" in context.content  # Speaker attribution
        assert "Mike" in context.content

    async def test_fetch_context_includes_action_items(
        self, fireflies_adapter: FirefliesAdapter, httpx_mock: HTTPXMock
    ) -> None:
        """Test that action items are included."""
        httpx_mock.add_response(
            url=FIREFLIES_API_URL,
            json=SAMPLE_TRANSCRIPTS_RESPONSE,
        )

        result = await fireflies_adapter.fetch_context("PROJ-123")
        context = result[0]

        assert "Action Items" in context.content
        assert "PKCE" in context.content
        assert "vault" in context.content

    async def test_fetch_context_empty_on_no_results(
        self, fireflies_adapter: FirefliesAdapter, httpx_mock: HTTPXMock
    ) -> None:
        """Test that fetch_context returns empty list when no transcripts found."""
        httpx_mock.add_response(
            url=FIREFLIES_API_URL,
            json=EMPTY_TRANSCRIPTS_RESPONSE,
        )

        result = await fireflies_adapter.fetch_context("NOTFOUND-999")

        assert isinstance(result, list)
        assert len(result) == 0

    async def test_fetch_context_empty_on_api_error(
        self, fireflies_adapter: FirefliesAdapter, httpx_mock: HTTPXMock
    ) -> None:
        """Test that fetch_context returns empty list on API error."""
        httpx_mock.add_response(
            url=FIREFLIES_API_URL,
            status_code=500,
        )

        result = await fireflies_adapter.fetch_context("PROJ-123")

        assert isinstance(result, list)
        assert len(result) == 0

    async def test_fetch_context_empty_on_graphql_error(
        self, fireflies_adapter: FirefliesAdapter, httpx_mock: HTTPXMock
    ) -> None:
        """Test that fetch_context returns empty list on GraphQL error."""
        httpx_mock.add_response(
            url=FIREFLIES_API_URL,
            json=GRAPHQL_ERROR_RESPONSE,
        )

        result = await fireflies_adapter.fetch_context("PROJ-123")

        assert isinstance(result, list)
        assert len(result) == 0

    async def test_fetch_context_disabled_returns_empty(self) -> None:
        """Test that fetch_context returns empty list when adapter is disabled."""
        config = FirefliesConfig(api_key="test-key", enabled=False)
        adapter = FirefliesAdapter(config)

        result = await adapter.fetch_context("PROJ-123")

        assert isinstance(result, list)
        assert len(result) == 0

    async def test_fetch_context_no_api_key_returns_empty(self) -> None:
        """Test that fetch_context returns empty when no API key configured."""
        config = FirefliesConfig(api_key="", enabled=True)
        adapter = FirefliesAdapter(config)

        result = await adapter.fetch_context("PROJ-123")

        assert isinstance(result, list)
        assert len(result) == 0

    async def test_health_check_success(
        self, fireflies_adapter: FirefliesAdapter, httpx_mock: HTTPXMock
    ) -> None:
        """Test health check when API is accessible."""
        httpx_mock.add_response(
            url=FIREFLIES_API_URL,
            json=SAMPLE_USER_RESPONSE,
            status_code=200,
        )

        result = await fireflies_adapter.health_check()

        assert result is True

    async def test_health_check_fails_on_error(
        self, fireflies_adapter: FirefliesAdapter, httpx_mock: HTTPXMock
    ) -> None:
        """Test health check fails on API error."""
        httpx_mock.add_response(
            url=FIREFLIES_API_URL,
            status_code=401,
        )

        result = await fireflies_adapter.health_check()

        assert result is False

    async def test_health_check_disabled(self) -> None:
        """Test health check when adapter is disabled."""
        config = FirefliesConfig(api_key="test-key", enabled=False)
        adapter = FirefliesAdapter(config)

        result = await adapter.health_check()

        assert result is True  # Disabled adapters are "healthy"

    async def test_health_check_no_api_key(self) -> None:
        """Test health check fails when no API key configured."""
        config = FirefliesConfig(api_key="", enabled=True)
        adapter = FirefliesAdapter(config)

        result = await adapter.health_check()

        assert result is False

    async def test_get_meeting_context(
        self, fireflies_adapter: FirefliesAdapter, httpx_mock: HTTPXMock
    ) -> None:
        """Test get_meeting_context returns MeetingContext."""
        httpx_mock.add_response(
            url=FIREFLIES_API_URL,
            json=SAMPLE_TRANSCRIPTS_RESPONSE,
        )

        result = await fireflies_adapter.get_meeting_context("PROJ-123")

        assert len(result.meetings) == 1
        meeting = result.meetings[0]
        assert meeting.meeting_title == "Sprint Planning - Auth Implementation"
        assert "Sarah" in meeting.participants
        assert len(meeting.action_items) == 2

    async def test_search_transcripts(
        self, fireflies_adapter: FirefliesAdapter, httpx_mock: HTTPXMock
    ) -> None:
        """Test search_transcripts returns transcript data."""
        httpx_mock.add_response(
            url=FIREFLIES_API_URL,
            json=SAMPLE_TRANSCRIPTS_RESPONSE,
        )

        result = await fireflies_adapter.search_transcripts("PROJ-123")

        assert len(result) == 1
        assert result[0]["id"] == "transcript-123"
        assert result[0]["title"] == "Sprint Planning - Auth Implementation"


class TestExcerptExtraction:
    """Tests for excerpt extraction logic."""

    def test_extract_relevant_excerpts_finds_matches(
        self, fireflies_adapter: FirefliesAdapter
    ) -> None:
        """Test that excerpt extraction finds matching sentences."""
        sentences = [
            {"text": "Hello everyone.", "speaker_name": "Alice"},
            {"text": "Let's discuss PROJ-123 today.", "speaker_name": "Alice"},
            {"text": "Sounds good.", "speaker_name": "Bob"},
            {"text": "I have some updates.", "speaker_name": "Bob"},
        ]

        result = fireflies_adapter._extract_relevant_excerpts(sentences, ["PROJ-123"])

        assert "PROJ-123" in result
        assert "Alice" in result

    def test_extract_relevant_excerpts_includes_context(
        self, fireflies_adapter: FirefliesAdapter
    ) -> None:
        """Test that surrounding sentences are included."""
        sentences = [
            {"text": "First sentence.", "speaker_name": "Alice"},
            {"text": "Second sentence.", "speaker_name": "Alice"},
            {"text": "This mentions PROJ-123.", "speaker_name": "Bob"},
            {"text": "Fourth sentence.", "speaker_name": "Bob"},
            {"text": "Fifth sentence.", "speaker_name": "Alice"},
        ]

        result = fireflies_adapter._extract_relevant_excerpts(sentences, ["PROJ-123"])

        # Should include sentences around the match (±3 context window)
        assert "PROJ-123" in result
        # Context should be included
        assert "First sentence" in result or "Second sentence" in result

    def test_extract_relevant_excerpts_no_matches(
        self, fireflies_adapter: FirefliesAdapter
    ) -> None:
        """Test that empty string returned when no matches."""
        sentences = [
            {"text": "Hello everyone.", "speaker_name": "Alice"},
            {"text": "Goodbye.", "speaker_name": "Bob"},
        ]

        result = fireflies_adapter._extract_relevant_excerpts(sentences, ["NOTFOUND"])

        assert result == ""

    def test_extract_relevant_excerpts_empty_sentences(
        self, fireflies_adapter: FirefliesAdapter
    ) -> None:
        """Test handling of empty sentences list."""
        result = fireflies_adapter._extract_relevant_excerpts([], ["PROJ-123"])

        assert result == ""

    def test_extract_relevant_excerpts_case_insensitive(
        self, fireflies_adapter: FirefliesAdapter
    ) -> None:
        """Test that search is case insensitive."""
        sentences = [
            {"text": "Let's discuss proj-123 today.", "speaker_name": "Alice"},
        ]

        result = fireflies_adapter._extract_relevant_excerpts(sentences, ["PROJ-123"])

        assert "proj-123" in result
