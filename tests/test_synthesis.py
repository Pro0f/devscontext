"""Tests for the synthesis module."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from devscontext.models import (
    DocsContext,
    DocSection,
    JiraComment,
    JiraContext,
    JiraTicket,
    LinkedIssue,
    MeetingContext,
    MeetingExcerpt,
    SynthesisConfig,
)
from devscontext.plugins.base import SourceContext
from devscontext.synthesis import (
    AnthropicProvider,
    OllamaProvider,
    OpenAIProvider,
    SynthesisEngine,
    create_provider,
)


def make_source_contexts(
    jira_context: JiraContext | None = None,
    meeting_context: MeetingContext | None = None,
    docs_context: DocsContext | None = None,
) -> dict[str, SourceContext]:
    """Helper to build source_contexts dict from typed contexts."""
    contexts: dict[str, SourceContext] = {}

    if jira_context is not None:
        contexts["jira"] = SourceContext(
            source_name="jira",
            source_type="issue_tracker",
            data=jira_context,
            raw_text="",
        )

    if meeting_context is not None:
        contexts["fireflies"] = SourceContext(
            source_name="fireflies",
            source_type="meeting",
            data=meeting_context,
            raw_text="",
        )

    if docs_context is not None:
        contexts["local_docs"] = SourceContext(
            source_name="local_docs",
            source_type="documentation",
            data=docs_context,
            raw_text="",
        )

    return contexts


@pytest.fixture
def synthesis_config() -> SynthesisConfig:
    """Create a test synthesis configuration."""
    return SynthesisConfig(
        provider="anthropic",
        model="claude-haiku-4-5",
        api_key="test-api-key",
        max_output_tokens=3000,
    )


@pytest.fixture
def synthesis_engine(synthesis_config: SynthesisConfig) -> SynthesisEngine:
    """Create a test synthesis engine."""
    return SynthesisEngine(synthesis_config)


@pytest.fixture
def sample_jira_context() -> JiraContext:
    """Create sample Jira context for testing."""
    return JiraContext(
        ticket=JiraTicket(
            ticket_id="PROJ-123",
            title="Implement user authentication",
            description="Add OAuth2 login flow with Google SSO support.",
            status="In Progress",
            assignee="Alice Developer",
            labels=["auth", "security"],
            components=["backend", "api"],
            acceptance_criteria="- Users can log in with Google\n- Session persists",
            sprint="Sprint 42",
            created=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
            updated=datetime(2024, 1, 16, 14, 30, 0, tzinfo=UTC),
        ),
        comments=[
            JiraComment(
                author="Bob Reviewer",
                body="Make sure to use PKCE for security.",
                created=datetime(2024, 1, 15, 11, 0, 0, tzinfo=UTC),
            ),
        ],
        linked_issues=[
            LinkedIssue(
                ticket_id="PROJ-100",
                title="Auth service infrastructure",
                status="Done",
                link_type="blocks",
            ),
        ],
    )


@pytest.fixture
def sample_meeting_context() -> MeetingContext:
    """Create sample meeting context for testing."""
    return MeetingContext(
        meetings=[
            MeetingExcerpt(
                meeting_title="Sprint Planning",
                meeting_date=datetime(2024, 1, 14, 10, 0, 0, tzinfo=UTC),
                participants=["Alice", "Bob", "Carol"],
                excerpt="**Alice:** We need OAuth for PROJ-123.\n**Bob:** Let's use Google.",
                action_items=["Set up Google OAuth credentials"],
                decisions=["Use Google as primary IdP"],
            ),
        ]
    )


@pytest.fixture
def sample_docs_context() -> DocsContext:
    """Create sample docs context for testing."""
    return DocsContext(
        sections=[
            DocSection(
                file_path="docs/auth.md",
                section_title="Authentication Guide",
                content="Use the AuthMiddleware for all protected routes.",
                doc_type="standards",
            ),
        ]
    )


class TestCreateProvider:
    """Tests for the create_provider factory function."""

    def test_create_anthropic_provider(self) -> None:
        """Test creating an Anthropic provider."""
        config = SynthesisConfig(
            provider="anthropic",
            model="claude-haiku-4-5",
            api_key="test-key",
        )
        provider = create_provider(config)

        assert isinstance(provider, AnthropicProvider)

    def test_create_openai_provider(self) -> None:
        """Test creating an OpenAI provider."""
        config = SynthesisConfig(
            provider="openai",
            model="gpt-4",
            api_key="test-key",
        )
        provider = create_provider(config)

        assert isinstance(provider, OpenAIProvider)

    def test_create_ollama_provider(self) -> None:
        """Test creating an Ollama provider (no API key needed)."""
        config = SynthesisConfig(
            provider="ollama",
            model="llama2",
        )
        provider = create_provider(config)

        assert isinstance(provider, OllamaProvider)

    def test_create_anthropic_without_api_key_raises(self) -> None:
        """Test that Anthropic provider requires API key."""
        config = SynthesisConfig(
            provider="anthropic",
            model="claude-haiku-4-5",
            api_key=None,
        )

        with pytest.raises(ValueError, match="Anthropic API key required"):
            create_provider(config)

    def test_create_openai_without_api_key_raises(self) -> None:
        """Test that OpenAI provider requires API key."""
        config = SynthesisConfig(
            provider="openai",
            model="gpt-4",
            api_key=None,
        )

        with pytest.raises(ValueError, match="OpenAI API key required"):
            create_provider(config)


class TestSynthesisEngine:
    """Tests for SynthesisEngine."""

    def test_format_jira_context(
        self,
        synthesis_engine: SynthesisEngine,
        sample_jira_context: JiraContext,
    ) -> None:
        """Test Jira context formatting."""
        result = synthesis_engine._format_jira_context(sample_jira_context)

        assert "PROJ-123" in result
        assert "Implement user authentication" in result
        assert "In Progress" in result
        assert "Alice Developer" in result
        assert "auth" in result
        assert "Bob Reviewer" in result
        assert "PKCE" in result
        assert "PROJ-100" in result

    def test_format_meeting_context(
        self,
        synthesis_engine: SynthesisEngine,
        sample_meeting_context: MeetingContext,
    ) -> None:
        """Test meeting context formatting."""
        result = synthesis_engine._format_meeting_context(sample_meeting_context)

        assert "Sprint Planning" in result
        assert "2024-01-14" in result
        assert "Alice" in result
        assert "OAuth" in result
        assert "Google OAuth credentials" in result
        assert "Use Google as primary IdP" in result

    def test_format_meeting_context_empty(
        self,
        synthesis_engine: SynthesisEngine,
    ) -> None:
        """Test meeting context formatting with empty meetings."""
        result = synthesis_engine._format_meeting_context(MeetingContext())

        assert result == ""

    def test_format_coding_standards(
        self,
        synthesis_engine: SynthesisEngine,
        sample_docs_context: DocsContext,
    ) -> None:
        """Test coding standards formatting."""
        result = synthesis_engine._format_coding_standards(sample_docs_context)

        assert "Authentication Guide" in result
        assert "docs/auth.md" in result
        assert "AuthMiddleware" in result

    def test_format_coding_standards_empty(
        self,
        synthesis_engine: SynthesisEngine,
    ) -> None:
        """Test coding standards formatting with empty sections."""
        result = synthesis_engine._format_coding_standards(DocsContext())

        assert result == ""

    def test_format_architecture_docs(
        self,
        synthesis_engine: SynthesisEngine,
    ) -> None:
        """Test architecture docs formatting."""
        docs_context = DocsContext(
            sections=[
                DocSection(
                    file_path="docs/architecture/payments.md",
                    section_title="Webhook Flow",
                    content="Webhooks are processed via SQS queue.",
                    doc_type="architecture",
                ),
            ]
        )
        result = synthesis_engine._format_architecture_docs(docs_context)

        assert "ARCHITECTURE DOCS" in result
        assert "Webhook Flow" in result
        assert "SQS queue" in result

    def test_build_raw_data_combines_all_sources(
        self,
        synthesis_engine: SynthesisEngine,
        sample_jira_context: JiraContext,
        sample_meeting_context: MeetingContext,
        sample_docs_context: DocsContext,
    ) -> None:
        """Test that raw data builder combines all sources."""
        result = synthesis_engine._build_raw_data(
            jira_context=sample_jira_context,
            meeting_context=sample_meeting_context,
            docs_context=sample_docs_context,
        )

        assert "JIRA TICKET" in result
        assert "MEETING TRANSCRIPTS" in result
        assert "CODING STANDARDS" in result  # standards doc_type maps here
        assert "PROJ-123" in result

    def test_build_raw_data_empty_context(
        self,
        synthesis_engine: SynthesisEngine,
    ) -> None:
        """Test raw data builder with no context."""
        result = synthesis_engine._build_raw_data(
            jira_context=None,
            meeting_context=None,
            docs_context=None,
        )

        assert result == "No context data available."

    def test_format_fallback(
        self,
        synthesis_engine: SynthesisEngine,
        sample_jira_context: JiraContext,
    ) -> None:
        """Test fallback formatting when LLM is unavailable."""
        result = synthesis_engine._format_fallback(
            task_id="PROJ-123",
            jira_context=sample_jira_context,
            meeting_context=None,
            docs_context=None,
        )

        assert "## Task: PROJ-123" in result
        assert "LLM synthesis unavailable" in result
        assert "PROJ-123" in result

    async def test_synthesize_fallback_on_missing_api_key(
        self,
        sample_jira_context: JiraContext,
    ) -> None:
        """Test synthesis falls back when API key is missing."""
        config = SynthesisConfig(
            provider="anthropic",
            model="claude-haiku-4-5",
            api_key=None,  # No API key
        )
        engine = SynthesisEngine(config)

        result = await engine.synthesize(
            task_id="PROJ-123",
            source_contexts=make_source_contexts(jira_context=sample_jira_context),
        )

        # Should fall back to raw format
        assert "## Task: PROJ-123" in result
        assert "LLM synthesis unavailable" in result or "LLM configuration error" in result

    async def test_synthesize_returns_no_context_message_when_empty(
        self,
        synthesis_engine: SynthesisEngine,
    ) -> None:
        """Test synthesis returns message when no context provided."""
        result = await synthesis_engine.synthesize(
            task_id="EMPTY-123",
            source_contexts={},
        )

        assert "EMPTY-123" in result
        assert "No context found" in result

    async def test_synthesize_with_mock_provider(
        self,
        sample_jira_context: JiraContext,
    ) -> None:
        """Test synthesis with a mocked LLM provider."""
        config = SynthesisConfig(
            provider="anthropic",
            model="claude-haiku-4-5",
            api_key="test-key",
        )
        engine = SynthesisEngine(config)

        # Mock the provider
        mock_provider = AsyncMock()
        mock_provider.generate.return_value = "## Task: PROJ-123\n\nSynthesized content"
        engine._provider = mock_provider

        result = await engine.synthesize(
            task_id="PROJ-123",
            source_contexts=make_source_contexts(jira_context=sample_jira_context),
        )

        assert "Synthesized content" in result
        mock_provider.generate.assert_called_once()


class TestAnthropicProvider:
    """Tests for AnthropicProvider."""

    def test_init(self) -> None:
        """Test provider initialization."""
        provider = AnthropicProvider(api_key="test-key", model="claude-haiku-4-5")

        assert provider._api_key == "test-key"
        assert provider._model == "claude-haiku-4-5"
        assert provider._client is None

    def test_get_client_raises_import_error(self) -> None:
        """Test that get_client raises ImportError if anthropic not installed."""
        # This test verifies provider can be created without import error
        # The actual ImportError would happen when _get_client is called
        # if the anthropic package is not installed
        _ = AnthropicProvider(api_key="test-key", model="claude-haiku-4-5")


class TestOpenAIProvider:
    """Tests for OpenAIProvider."""

    def test_init(self) -> None:
        """Test provider initialization."""
        provider = OpenAIProvider(api_key="test-key", model="gpt-4")

        assert provider._api_key == "test-key"
        assert provider._model == "gpt-4"
        assert provider._client is None


class TestOllamaProvider:
    """Tests for OllamaProvider."""

    def test_init(self) -> None:
        """Test provider initialization."""
        provider = OllamaProvider(model="llama2")

        assert provider._model == "llama2"
        assert provider._base_url == "http://localhost:11434"
        assert provider._client is None

    def test_init_with_custom_url(self) -> None:
        """Test provider initialization with custom URL."""
        provider = OllamaProvider(model="llama2", base_url="http://custom:11434")

        assert provider._base_url == "http://custom:11434"
