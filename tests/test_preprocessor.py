"""Tests for the pre-processing pipeline."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from devscontext.agents.preprocessor import PreprocessingPipeline
from devscontext.models import (
    AgentsConfig,
    DevsContextConfig,
    DocsConfig,
    DocsContext,
    DocSection,
    FirefliesConfig,
    JiraComment,
    JiraConfig,
    JiraContext,
    JiraTicket,
    LinkedIssue,
    MeetingContext,
    MeetingExcerpt,
    PreprocessorConfig,
    SourcesConfig,
    StorageConfig,
    SynthesisConfig,
)
from devscontext.storage import PrebuiltContextStorage


@pytest.fixture
def config() -> DevsContextConfig:
    """Create test configuration."""
    return DevsContextConfig(
        sources=SourcesConfig(
            jira=JiraConfig(
                base_url="https://test.atlassian.net",
                email="test@example.com",
                api_token="test-token",
                enabled=True,
            ),
            fireflies=FirefliesConfig(enabled=False),
            docs=DocsConfig(enabled=True, paths=["./docs"]),
        ),
        synthesis=SynthesisConfig(
            plugin="llm",
            provider="anthropic",
            model="claude-haiku-4-5",
            api_key="test-key",
        ),
        agents=AgentsConfig(
            preprocessor=PreprocessorConfig(
                enabled=True,
                jira_project="TEST",
                context_ttl_hours=24,
            )
        ),
        storage=StorageConfig(path=".devscontext/test_cache.db"),
    )


@pytest.fixture
def sample_jira_context() -> JiraContext:
    """Create sample Jira context."""
    now = datetime.now(UTC)
    return JiraContext(
        ticket=JiraTicket(
            ticket_id="TEST-123",
            title="Implement user authentication",
            description="Add OAuth2 authentication flow",
            status="Ready for Development",
            labels=["auth", "security"],
            components=["backend"],
            acceptance_criteria="- User can log in\n- User can log out",
            created=now - timedelta(days=5),
            updated=now,
        ),
        comments=[
            JiraComment(
                author="Tech Lead",
                body="Use the existing auth service",
                created=now - timedelta(hours=2),
            )
        ],
        linked_issues=[
            LinkedIssue(
                ticket_id="TEST-100",
                title="Auth service setup",
                status="Done",
                link_type="blocks",
            )
        ],
    )


@pytest.fixture
def sample_meeting_context() -> MeetingContext:
    """Create sample meeting context."""
    now = datetime.now(UTC)
    return MeetingContext(
        meetings=[
            MeetingExcerpt(
                meeting_title="Sprint Planning",
                meeting_date=now - timedelta(days=1),
                participants=["Alice", "Bob"],
                excerpt="Discussed authentication approach. Decided to use OAuth2.",
                action_items=["Research OAuth2 providers"],
                decisions=["Use OAuth2 for authentication"],
            )
        ]
    )


@pytest.fixture
def sample_docs_context() -> DocsContext:
    """Create sample documentation context."""
    return DocsContext(
        sections=[
            DocSection(
                file_path="docs/auth.md",
                section_title="Authentication",
                content="Use JWT tokens with 24h expiration.",
                doc_type="architecture",
            ),
            DocSection(
                file_path="docs/standards.md",
                section_title="Coding Standards",
                content="Use async/await for all I/O.",
                doc_type="standards",
            ),
        ]
    )


class TestPreprocessingPipeline:
    """Tests for PreprocessingPipeline."""

    def test_compute_source_hash(
        self, config: DevsContextConfig, sample_jira_context: JiraContext
    ) -> None:
        """Test source hash computation."""
        storage = MagicMock(spec=PrebuiltContextStorage)
        pipeline = PreprocessingPipeline(config, storage)

        hash1 = pipeline._compute_source_hash(sample_jira_context.ticket)

        # Same ticket should produce same hash
        hash2 = pipeline._compute_source_hash(sample_jira_context.ticket)
        assert hash1 == hash2

        # Hash should be 16 characters (truncated SHA256)
        assert len(hash1) == 16

    def test_format_jira_for_extraction(
        self, config: DevsContextConfig, sample_jira_context: JiraContext
    ) -> None:
        """Test Jira formatting for extraction."""
        storage = MagicMock(spec=PrebuiltContextStorage)
        pipeline = PreprocessingPipeline(config, storage)

        formatted = pipeline._format_jira_for_extraction(sample_jira_context)

        assert "TEST-123" in formatted
        assert "Implement user authentication" in formatted
        assert "OAuth2 authentication" in formatted
        assert "acceptance_criteria" in formatted.lower() or "Acceptance Criteria" in formatted
        assert "Tech Lead" in formatted
        assert "TEST-100" in formatted  # Linked issue

    def test_format_meetings_for_extraction(
        self, config: DevsContextConfig, sample_meeting_context: MeetingContext
    ) -> None:
        """Test meeting formatting for extraction."""
        storage = MagicMock(spec=PrebuiltContextStorage)
        pipeline = PreprocessingPipeline(config, storage)

        formatted = pipeline._format_meetings_for_extraction(sample_meeting_context)

        assert "Sprint Planning" in formatted
        assert "Alice" in formatted
        assert "OAuth2" in formatted
        assert "Action Items" in formatted
        assert "Decisions" in formatted

    def test_format_docs_for_extraction(
        self, config: DevsContextConfig, sample_docs_context: DocsContext
    ) -> None:
        """Test docs formatting for extraction."""
        storage = MagicMock(spec=PrebuiltContextStorage)
        pipeline = PreprocessingPipeline(config, storage)

        formatted = pipeline._format_docs_for_extraction(sample_docs_context)

        assert "Authentication" in formatted
        assert "JWT tokens" in formatted
        assert "Coding Standards" in formatted
        assert "async/await" in formatted
        assert "[architecture]" in formatted
        assert "[standards]" in formatted

    def test_parse_gaps_valid_json(self, config: DevsContextConfig) -> None:
        """Test parsing gaps from valid JSON array."""
        storage = MagicMock(spec=PrebuiltContextStorage)
        pipeline = PreprocessingPipeline(config, storage)

        response = '["No acceptance criteria", "Missing architecture docs"]'
        gaps = pipeline._parse_gaps(response)

        assert len(gaps) == 2
        assert "No acceptance criteria" in gaps
        assert "Missing architecture docs" in gaps

    def test_parse_gaps_with_markdown_code_block(self, config: DevsContextConfig) -> None:
        """Test parsing gaps from JSON inside markdown code block."""
        storage = MagicMock(spec=PrebuiltContextStorage)
        pipeline = PreprocessingPipeline(config, storage)

        response = '```json\n["Gap 1", "Gap 2"]\n```'
        gaps = pipeline._parse_gaps(response)

        assert len(gaps) == 2
        assert "Gap 1" in gaps

    def test_parse_gaps_empty_array(self, config: DevsContextConfig) -> None:
        """Test parsing empty gaps array."""
        storage = MagicMock(spec=PrebuiltContextStorage)
        pipeline = PreprocessingPipeline(config, storage)

        response = "[]"
        gaps = pipeline._parse_gaps(response)

        assert gaps == []

    def test_parse_gaps_bullet_points_fallback(self, config: DevsContextConfig) -> None:
        """Test parsing gaps from bullet points when JSON fails."""
        storage = MagicMock(spec=PrebuiltContextStorage)
        pipeline = PreprocessingPipeline(config, storage)

        response = "- No acceptance criteria\n- Missing docs\n* Another gap"
        gaps = pipeline._parse_gaps(response)

        assert len(gaps) == 3
        assert "No acceptance criteria" in gaps
        assert "Missing docs" in gaps
        assert "Another gap" in gaps

    def test_calculate_quality_score_full(
        self,
        config: DevsContextConfig,
        sample_jira_context: JiraContext,
        sample_meeting_context: MeetingContext,
        sample_docs_context: DocsContext,
    ) -> None:
        """Test quality score calculation with all sources."""
        storage = MagicMock(spec=PrebuiltContextStorage)
        pipeline = PreprocessingPipeline(config, storage)

        score = pipeline._calculate_quality_score(
            sample_jira_context, sample_meeting_context, sample_docs_context
        )

        # Has description (0.2) + acceptance criteria (0.2) + meetings (0.2)
        # + architecture (0.2) + standards (0.2) = 1.0
        assert score == 1.0

    def test_calculate_quality_score_partial(
        self, config: DevsContextConfig, sample_jira_context: JiraContext
    ) -> None:
        """Test quality score with partial sources."""
        storage = MagicMock(spec=PrebuiltContextStorage)
        pipeline = PreprocessingPipeline(config, storage)

        # No meetings, no docs
        score = pipeline._calculate_quality_score(
            sample_jira_context,
            MeetingContext(meetings=[]),
            DocsContext(sections=[]),
        )

        # Has description (0.2) + acceptance criteria (0.2) = 0.4
        assert score == 0.4

    def test_calculate_quality_score_minimal(self, config: DevsContextConfig) -> None:
        """Test quality score with minimal context."""
        storage = MagicMock(spec=PrebuiltContextStorage)
        pipeline = PreprocessingPipeline(config, storage)

        now = datetime.now(UTC)
        minimal_jira = JiraContext(
            ticket=JiraTicket(
                ticket_id="TEST-999",
                title="Minimal ticket",
                description=None,  # No description
                status="Open",
                created=now,
                updated=now,
            ),
            comments=[],
            linked_issues=[],
        )

        score = pipeline._calculate_quality_score(
            minimal_jira,
            MeetingContext(meetings=[]),
            DocsContext(sections=[]),
        )

        assert score == 0.0


class TestPreprocessingPipelineIntegration:
    """Integration tests for PreprocessingPipeline."""

    @pytest.mark.asyncio
    async def test_process_stores_context(
        self,
        config: DevsContextConfig,
        sample_jira_context: JiraContext,
        sample_meeting_context: MeetingContext,
        sample_docs_context: DocsContext,
    ) -> None:
        """Test that process() stores the built context."""
        storage = AsyncMock(spec=PrebuiltContextStorage)
        storage.store = AsyncMock()

        with (
            patch.object(
                PreprocessingPipeline, "_deep_jira_fetch", return_value=sample_jira_context
            ),
            patch.object(
                PreprocessingPipeline, "_broad_meeting_search", return_value=sample_meeting_context
            ),
            patch.object(
                PreprocessingPipeline, "_thorough_doc_match", return_value=sample_docs_context
            ),
            patch.object(
                PreprocessingPipeline,
                "_multi_pass_synthesis",
                return_value=("# Synthesized\n\nContent", 0.8, ["Gap 1"]),
            ),
        ):
            pipeline = PreprocessingPipeline(config, storage)
            context = await pipeline.process("TEST-123")

            # Verify context is built correctly
            assert context.task_id == "TEST-123"
            assert context.synthesized == "# Synthesized\n\nContent"
            assert context.context_quality_score == 0.8
            assert context.gaps == ["Gap 1"]
            assert len(context.sources_used) > 0
            assert not context.is_expired()

            # Verify storage was called
            storage.store.assert_called_once()
            stored_context = storage.store.call_args[0][0]
            assert stored_context.task_id == "TEST-123"

    @pytest.mark.asyncio
    async def test_process_raises_on_jira_not_found(self, config: DevsContextConfig) -> None:
        """Test that process() raises when Jira ticket not found."""
        storage = AsyncMock(spec=PrebuiltContextStorage)

        with patch.object(PreprocessingPipeline, "_deep_jira_fetch", return_value=None):
            pipeline = PreprocessingPipeline(config, storage)

            with pytest.raises(ValueError, match="Could not fetch Jira ticket"):
                await pipeline.process("NONEXISTENT-999")


class TestGapDetection:
    """Tests for gap detection functionality."""

    def test_detect_gaps_no_acceptance_criteria(self, config: DevsContextConfig) -> None:
        """Test gap detected when no acceptance criteria."""
        storage = MagicMock(spec=PrebuiltContextStorage)
        pipeline = PreprocessingPipeline(config, storage)

        now = datetime.now(UTC)
        jira_ctx = JiraContext(
            ticket=JiraTicket(
                ticket_id="TEST-1",
                title="Test ticket",
                description="Some description",
                status="Open",
                created=now,
                updated=now,
                acceptance_criteria=None,  # No AC
            ),
            comments=[],
            linked_issues=[],
        )

        gaps = pipeline._detect_gaps(
            jira_ctx,
            MeetingContext(meetings=[]),
            DocsContext(sections=[]),
        )

        assert any("acceptance criteria" in g.lower() for g in gaps)

    def test_detect_gaps_no_meetings(
        self, config: DevsContextConfig, sample_jira_context: JiraContext
    ) -> None:
        """Test gap detected when no meeting discussions."""
        storage = MagicMock(spec=PrebuiltContextStorage)
        pipeline = PreprocessingPipeline(config, storage)

        gaps = pipeline._detect_gaps(
            sample_jira_context,
            MeetingContext(meetings=[]),  # No meetings
            DocsContext(sections=[]),
        )

        assert any("meeting" in g.lower() for g in gaps)

    def test_detect_gaps_no_architecture_docs(
        self, config: DevsContextConfig, sample_jira_context: JiraContext
    ) -> None:
        """Test gap detected when no architecture documentation."""
        storage = MagicMock(spec=PrebuiltContextStorage)
        pipeline = PreprocessingPipeline(config, storage)

        # Only standards docs, no architecture
        docs_ctx = DocsContext(
            sections=[
                DocSection(
                    file_path="CLAUDE.md",
                    section_title="Standards",
                    content="Coding standards",
                    doc_type="standards",
                )
            ]
        )

        gaps = pipeline._detect_gaps(
            sample_jira_context,
            MeetingContext(meetings=[]),
            docs_ctx,
        )

        # Should include service area from components
        assert any("architecture" in g.lower() for g in gaps)
        assert any("backend" in g.lower() for g in gaps)  # component name

    def test_detect_gaps_no_linked_issues(self, config: DevsContextConfig) -> None:
        """Test gap detected when no linked issues."""
        storage = MagicMock(spec=PrebuiltContextStorage)
        pipeline = PreprocessingPipeline(config, storage)

        now = datetime.now(UTC)
        jira_ctx = JiraContext(
            ticket=JiraTicket(
                ticket_id="TEST-1",
                title="Test ticket",
                description="Some description",
                status="Open",
                acceptance_criteria="Done when X",
                created=now,
                updated=now,
            ),
            comments=[],
            linked_issues=[],  # No linked issues
        )

        gaps = pipeline._detect_gaps(
            jira_ctx,
            MeetingContext(meetings=[]),
            DocsContext(sections=[]),
        )

        assert any("linked" in g.lower() or "related" in g.lower() for g in gaps)

    def test_detect_gaps_complete_context(
        self,
        config: DevsContextConfig,
        sample_jira_context: JiraContext,
        sample_meeting_context: MeetingContext,
        sample_docs_context: DocsContext,
    ) -> None:
        """Test minimal gaps when context is complete."""
        storage = MagicMock(spec=PrebuiltContextStorage)
        pipeline = PreprocessingPipeline(config, storage)

        gaps = pipeline._detect_gaps(
            sample_jira_context,
            sample_meeting_context,
            sample_docs_context,
        )

        # With complete context, should have no or minimal gaps
        # (may still flag missing dependencies check)
        assert len(gaps) <= 1


class TestAppendGapsToContext:
    """Tests for appending gaps to synthesized context."""

    def test_append_gaps_adds_section(self, config: DevsContextConfig) -> None:
        """Test that gaps are appended as a section."""
        storage = MagicMock(spec=PrebuiltContextStorage)
        pipeline = PreprocessingPipeline(config, storage)

        synthesized = "# Task Context\n\nSome content here."
        gaps = ["No acceptance criteria", "No meeting discussions"]
        quality_score = 0.4

        result = pipeline._append_gaps_to_context(synthesized, gaps, quality_score)

        assert "# Task Context" in result  # Original content preserved
        assert "Context Quality" in result
        assert "40%" in result  # Quality score
        assert "No acceptance criteria" in result
        assert "No meeting discussions" in result

    def test_append_gaps_empty_list(self, config: DevsContextConfig) -> None:
        """Test that empty gaps list returns original content."""
        storage = MagicMock(spec=PrebuiltContextStorage)
        pipeline = PreprocessingPipeline(config, storage)

        synthesized = "# Task Context\n\nSome content here."
        gaps: list[str] = []
        quality_score = 1.0

        result = pipeline._append_gaps_to_context(synthesized, gaps, quality_score)

        assert result == synthesized  # Unchanged

    def test_append_gaps_quality_labels(self, config: DevsContextConfig) -> None:
        """Test quality labels based on score."""
        storage = MagicMock(spec=PrebuiltContextStorage)
        pipeline = PreprocessingPipeline(config, storage)

        synthesized = "Content"
        gaps = ["A gap"]

        # Good (>=0.8)
        result = pipeline._append_gaps_to_context(synthesized, gaps, 0.9)
        assert "Good" in result

        # Moderate (>=0.6)
        result = pipeline._append_gaps_to_context(synthesized, gaps, 0.7)
        assert "Moderate" in result

        # Limited (>=0.4)
        result = pipeline._append_gaps_to_context(synthesized, gaps, 0.5)
        assert "Limited" in result

        # Incomplete (<0.4)
        result = pipeline._append_gaps_to_context(synthesized, gaps, 0.2)
        assert "Incomplete" in result
