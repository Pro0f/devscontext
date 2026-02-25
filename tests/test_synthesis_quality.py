"""Tests for synthesis output quality using fixture data.

These tests use pre-saved fixture data to test synthesis without
making real API calls. This allows iterating on the synthesis
prompt and format without waiting for external APIs.

Run with:
    pytest tests/test_synthesis_quality.py -v -s
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

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
from devscontext.synthesis import SynthesisEngine


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

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_jira_fixture() -> JiraContext:
    """Load Jira ticket fixture data."""
    with open(FIXTURES_DIR / "jira_ticket.json") as f:
        data = json.load(f)

    ticket_data = data["ticket"]
    return JiraContext(
        ticket=JiraTicket(
            ticket_id=ticket_data["ticket_id"],
            title=ticket_data["title"],
            description=ticket_data["description"],
            status=ticket_data["status"],
            assignee=ticket_data["assignee"],
            labels=ticket_data["labels"],
            components=ticket_data["components"],
            acceptance_criteria=ticket_data["acceptance_criteria"],
            story_points=ticket_data["story_points"],
            sprint=ticket_data["sprint"],
            created=datetime.fromisoformat(ticket_data["created"]),
            updated=datetime.fromisoformat(ticket_data["updated"]),
        ),
        comments=[
            JiraComment(
                author=c["author"],
                body=c["body"],
                created=datetime.fromisoformat(c["created"]),
            )
            for c in data["comments"]
        ],
        linked_issues=[
            LinkedIssue(
                ticket_id=li["ticket_id"],
                title=li["title"],
                status=li["status"],
                link_type=li["link_type"],
            )
            for li in data["linked_issues"]
        ],
    )


def load_meeting_fixture() -> MeetingContext:
    """Load meeting transcript fixture data."""
    with open(FIXTURES_DIR / "meeting_transcript.json") as f:
        data = json.load(f)

    return MeetingContext(
        meetings=[
            MeetingExcerpt(
                meeting_title=m["meeting_title"],
                meeting_date=datetime.fromisoformat(m["meeting_date"]),
                participants=m["participants"],
                excerpt=m["excerpt"],
                action_items=m["action_items"],
                decisions=m["decisions"],
            )
            for m in data["meetings"]
        ]
    )


def load_docs_fixture() -> DocsContext:
    """Load documentation fixture data."""
    with open(FIXTURES_DIR / "docs_context.json") as f:
        data = json.load(f)

    return DocsContext(
        sections=[
            DocSection(
                file_path=s["file_path"],
                section_title=s["section_title"],
                content=s["content"],
                doc_type=s["doc_type"],
            )
            for s in data["sections"]
        ]
    )


@pytest.fixture
def jira_context() -> JiraContext:
    """Provide Jira fixture context."""
    return load_jira_fixture()


@pytest.fixture
def meeting_context() -> MeetingContext:
    """Provide meeting fixture context."""
    return load_meeting_fixture()


@pytest.fixture
def docs_context() -> DocsContext:
    """Provide docs fixture context."""
    return load_docs_fixture()


@pytest.fixture
def synthesis_engine() -> SynthesisEngine:
    """Create a synthesis engine (will use fallback without API key)."""
    config = SynthesisConfig(
        provider="anthropic",
        model="claude-haiku-4-5",
        api_key=None,  # No API key - will use fallback
    )
    return SynthesisEngine(config)


class TestSynthesisQuality:
    """Tests for synthesis output quality."""

    async def test_fallback_contains_all_sources(
        self,
        synthesis_engine: SynthesisEngine,
        jira_context: JiraContext,
        meeting_context: MeetingContext,
        docs_context: DocsContext,
    ) -> None:
        """Test that fallback output includes all source data."""
        result = await synthesis_engine.synthesize(
            task_id="AUTH-123",
            source_contexts=make_source_contexts(jira_context, meeting_context, docs_context),
        )

        # Should contain task ID
        assert "AUTH-123" in result

        # Should contain Jira data
        assert "OAuth2" in result or "OAuth" in result
        assert "Alice Chen" in result
        assert "In Progress" in result

        # Should contain meeting data
        assert "Sprint 42" in result or "Sprint" in result
        assert "PKCE" in result

        # Should contain docs data
        assert "auth-service" in result or "Authentication Service" in result

    async def test_fallback_includes_comments(
        self,
        synthesis_engine: SynthesisEngine,
        jira_context: JiraContext,
    ) -> None:
        """Test that comments are included in output."""
        result = await synthesis_engine.synthesize(
            task_id="AUTH-123",
            source_contexts=make_source_contexts(jira_context=jira_context),
        )

        # Should include comment authors
        assert "Bob Smith" in result
        assert "Carol Davis" in result

        # Should include comment content
        assert "PKCE" in result
        assert "vault" in result.lower()

    async def test_fallback_includes_linked_issues(
        self,
        synthesis_engine: SynthesisEngine,
        jira_context: JiraContext,
    ) -> None:
        """Test that linked issues are included."""
        result = await synthesis_engine.synthesize(
            task_id="AUTH-123",
            source_contexts=make_source_contexts(jira_context=jira_context),
        )

        # Should include linked ticket IDs
        assert "AUTH-100" in result
        assert "AUTH-125" in result

    async def test_fallback_includes_meeting_decisions(
        self,
        synthesis_engine: SynthesisEngine,
        meeting_context: MeetingContext,
    ) -> None:
        """Test that meeting decisions are highlighted."""
        result = await synthesis_engine.synthesize(
            task_id="AUTH-123",
            source_contexts=make_source_contexts(meeting_context=meeting_context),
        )

        # Should include decisions
        assert "PKCE" in result
        assert "Vault" in result or "vault" in result.lower()
        assert "refresh token rotation" in result.lower() or "rotate" in result.lower()

    async def test_fallback_includes_action_items(
        self,
        synthesis_engine: SynthesisEngine,
        meeting_context: MeetingContext,
    ) -> None:
        """Test that action items from meetings are included."""
        result = await synthesis_engine.synthesize(
            task_id="AUTH-123",
            source_contexts=make_source_contexts(meeting_context=meeting_context),
        )

        # Should include action items
        assert "Action Items" in result or "action" in result.lower()

    async def test_fallback_includes_standards(
        self,
        synthesis_engine: SynthesisEngine,
        docs_context: DocsContext,
    ) -> None:
        """Test that coding standards are included."""
        result = await synthesis_engine.synthesize(
            task_id="AUTH-123",
            source_contexts=make_source_contexts(docs_context=docs_context),
        )

        # Should include standards content
        assert "httpOnly" in result or "cookie" in result.lower()
        assert "security" in result.lower()

    async def test_combined_context_reasonable_length(
        self,
        synthesis_engine: SynthesisEngine,
        jira_context: JiraContext,
        meeting_context: MeetingContext,
        docs_context: DocsContext,
    ) -> None:
        """Test that combined output is a reasonable length."""
        result = await synthesis_engine.synthesize(
            task_id="AUTH-123",
            source_contexts=make_source_contexts(jira_context, meeting_context, docs_context),
        )

        # Should be substantial but not excessively long
        # Fallback format is verbose, real LLM synthesis would be more concise
        assert len(result) > 500, "Output too short - missing content"
        assert len(result) < 50000, "Output too long - may need truncation"

        # Print for manual inspection
        print(f"\n{'=' * 60}")
        print("COMBINED SYNTHESIS OUTPUT")
        print(f"{'=' * 60}")
        print(f"Length: {len(result)} characters")
        print(f"\n{result[:2000]}...")
        print(f"{'=' * 60}")


class TestRawDataFormatting:
    """Tests for the raw data formatting methods."""

    def test_format_jira_context(
        self,
        synthesis_engine: SynthesisEngine,
        jira_context: JiraContext,
    ) -> None:
        """Test Jira context formatting."""
        result = synthesis_engine._format_jira_context(jira_context)

        # Check structure
        assert "## JIRA TICKET" in result
        assert "**ID:** AUTH-123" in result
        assert "**Status:** In Progress" in result

        # Check content
        assert "OAuth2" in result
        assert "Alice Chen" in result

    def test_format_meeting_context(
        self,
        synthesis_engine: SynthesisEngine,
        meeting_context: MeetingContext,
    ) -> None:
        """Test meeting context formatting."""
        result = synthesis_engine._format_meeting_context(meeting_context)

        # Check structure
        assert "## MEETING TRANSCRIPTS" in result
        assert "Participants" in result
        assert "Action Items" in result
        assert "Decisions" in result

        # Check content
        assert "PKCE" in result
        assert "Alice Chen" in result

    def test_format_docs_context_split_by_type(
        self,
        synthesis_engine: SynthesisEngine,
        docs_context: DocsContext,
    ) -> None:
        """Test docs context formatting splits by doc type."""
        # Test architecture docs
        arch_result = synthesis_engine._format_architecture_docs(docs_context)
        assert "## ARCHITECTURE DOCS" in arch_result
        assert "**Source:**" in arch_result
        assert "auth-service" in arch_result

        # Test coding standards
        standards_result = synthesis_engine._format_coding_standards(docs_context)
        assert "## CODING STANDARDS" in standards_result
        assert "PKCE" in standards_result


class TestEdgeCases:
    """Tests for edge cases in synthesis."""

    async def test_empty_context_message(
        self,
        synthesis_engine: SynthesisEngine,
    ) -> None:
        """Test output when no context is provided."""
        result = await synthesis_engine.synthesize(
            task_id="EMPTY-1",
            source_contexts={},
        )

        assert "EMPTY-1" in result
        assert "No context found" in result

    async def test_partial_context_jira_only(
        self,
        synthesis_engine: SynthesisEngine,
        jira_context: JiraContext,
    ) -> None:
        """Test output with only Jira context."""
        result = await synthesis_engine.synthesize(
            task_id="AUTH-123",
            source_contexts=make_source_contexts(jira_context=jira_context),
        )

        assert "AUTH-123" in result
        assert "JIRA" in result
        # Should not mention missing sources
        assert "MEETING" not in result or "No meetings" not in result

    async def test_partial_context_meetings_only(
        self,
        synthesis_engine: SynthesisEngine,
        meeting_context: MeetingContext,
    ) -> None:
        """Test output with only meeting context."""
        result = await synthesis_engine.synthesize(
            task_id="AUTH-123",
            source_contexts=make_source_contexts(meeting_context=meeting_context),
        )

        assert "AUTH-123" in result
        assert "MEETING" in result
        # Should not mention Jira if not provided
        assert "JIRA TICKET" not in result
