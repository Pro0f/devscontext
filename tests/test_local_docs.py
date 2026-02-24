"""Tests for the local docs adapter."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from devscontext.adapters.local_docs import (
    LocalDocsAdapter,
    ParsedDoc,
    ParsedSection,
)
from devscontext.models import DocsConfig, JiraTicket


@pytest.fixture
def fixtures_path() -> Path:
    """Return path to test fixtures."""
    return Path(__file__).parent / "fixtures" / "docs"


@pytest.fixture
def docs_config(fixtures_path: Path) -> DocsConfig:
    """Create a test docs configuration."""
    return DocsConfig(
        paths=[str(fixtures_path)],
        enabled=True,
    )


@pytest.fixture
def adapter(docs_config: DocsConfig) -> LocalDocsAdapter:
    """Create a test local docs adapter."""
    return LocalDocsAdapter(docs_config)


@pytest.fixture
def sample_ticket() -> JiraTicket:
    """Create a sample Jira ticket for testing."""
    return JiraTicket(
        ticket_id="TEST-123",
        title="Add retry logic to payment webhook handler",
        description="We need to implement retry logic for failed webhook processing.",
        status="In Progress",
        assignee="Test User",
        labels=["payments", "backend"],
        components=["payments-service"],
        created=datetime.now(UTC),
        updated=datetime.now(UTC),
    )


class TestDocTypeClassification:
    """Tests for document type classification."""

    def test_architecture_path(self, adapter: LocalDocsAdapter):
        """Files in architecture directory should be classified as architecture."""
        path = Path("docs/architecture/payments.md")
        assert adapter._classify_doc_type(path) == "architecture"

    def test_arch_path(self, adapter: LocalDocsAdapter):
        """Files in arch directory should be classified as architecture."""
        path = Path("docs/arch/overview.md")
        assert adapter._classify_doc_type(path) == "architecture"

    def test_standards_path(self, adapter: LocalDocsAdapter):
        """Files in standards directory should be classified as standards."""
        path = Path("docs/standards/typescript.md")
        assert adapter._classify_doc_type(path) == "standards"

    def test_style_path(self, adapter: LocalDocsAdapter):
        """Files in style directory should be classified as standards."""
        path = Path("docs/style/code-style.md")
        assert adapter._classify_doc_type(path) == "standards"

    def test_coding_path(self, adapter: LocalDocsAdapter):
        """Files in coding directory should be classified as standards."""
        path = Path("docs/coding/guidelines.md")
        assert adapter._classify_doc_type(path) == "standards"

    def test_adr_path(self, adapter: LocalDocsAdapter):
        """Files in adr directory should be classified as adr."""
        path = Path("docs/adr/001-decision.md")
        assert adapter._classify_doc_type(path) == "adr"

    def test_adrs_path(self, adapter: LocalDocsAdapter):
        """Files in adrs directory should be classified as adr."""
        path = Path("docs/adrs/001-decision.md")
        assert adapter._classify_doc_type(path) == "adr"

    def test_claude_md(self, adapter: LocalDocsAdapter):
        """CLAUDE.md should be classified as standards."""
        path = Path("CLAUDE.md")
        assert adapter._classify_doc_type(path) == "standards"

    def test_cursorrules(self, adapter: LocalDocsAdapter):
        """.cursorrules should be classified as standards."""
        path = Path(".cursorrules")
        assert adapter._classify_doc_type(path) == "standards"

    def test_other_path(self, adapter: LocalDocsAdapter):
        """Files in other directories should be classified as other."""
        path = Path("docs/guides/getting-started.md")
        assert adapter._classify_doc_type(path) == "other"


class TestSectionSplitting:
    """Tests for markdown section splitting."""

    def test_split_by_h2(self, adapter: LocalDocsAdapter):
        """Should split content by ## headings."""
        content = """# Title

Introduction text.

## Section One

Content one.

## Section Two

Content two.
"""
        path = Path("test.md")
        sections = adapter._split_into_sections(path, content)

        assert len(sections) == 3
        # First section is preamble (before first ##)
        assert sections[0].section_title is None
        assert "Introduction" in sections[0].content
        # Second section
        assert sections[1].section_title == "Section One"
        assert "Content one" in sections[1].content
        # Third section
        assert sections[2].section_title == "Section Two"
        assert "Content two" in sections[2].content

    def test_split_by_h3(self, adapter: LocalDocsAdapter):
        """Should split content by ### headings."""
        content = """## Main Section

### Subsection One

Sub content one.

### Subsection Two

Sub content two.
"""
        path = Path("test.md")
        sections = adapter._split_into_sections(path, content)

        assert len(sections) == 3
        assert sections[0].section_title == "Main Section"
        assert sections[1].section_title == "Subsection One"
        assert sections[2].section_title == "Subsection Two"

    def test_no_headings(self, adapter: LocalDocsAdapter):
        """Content without headings becomes a single section."""
        content = "Just some text without any headings."
        path = Path("test.md")
        sections = adapter._split_into_sections(path, content)

        assert len(sections) == 1
        assert sections[0].section_title is None
        assert sections[0].content == "Just some text without any headings."

    def test_empty_content(self, adapter: LocalDocsAdapter):
        """Empty content returns no sections."""
        path = Path("test.md")
        sections = adapter._split_into_sections(path, "")
        assert len(sections) == 0

    def test_heading_levels(self, adapter: LocalDocsAdapter):
        """Should track heading levels correctly."""
        content = """## Level Two

Content.

### Level Three

More content.
"""
        path = Path("test.md")
        sections = adapter._split_into_sections(path, content)

        assert sections[0].heading_level == 2
        assert sections[1].heading_level == 3


class TestComponentMatching:
    """Tests for component-based doc matching."""

    async def test_matches_component_in_filename(
        self, adapter: LocalDocsAdapter, sample_ticket: JiraTicket
    ):
        """Should match docs where component appears in filename."""
        # sample_ticket has component "payments-service"
        # fixtures has architecture/payments-service.md
        docs = await adapter.find_relevant_docs(sample_ticket)

        # Should find the payments-service.md file
        file_paths = [s.file_path for s in docs.sections]
        assert any("payments-service" in fp for fp in file_paths)

    async def test_matches_component_in_content(
        self, adapter: LocalDocsAdapter, fixtures_path: Path
    ):
        """Should match docs where component appears in content."""
        ticket = JiraTicket(
            ticket_id="TEST-456",
            title="Fix user auth bug",
            description="Bug in authentication",
            status="Open",
            labels=[],
            components=["stripe"],  # Stripe appears in payments-service.md content
            created=datetime.now(UTC),
            updated=datetime.now(UTC),
        )

        docs = await adapter.find_relevant_docs(ticket)
        # Should find sections mentioning stripe
        contents = " ".join(s.content.lower() for s in docs.sections)
        assert "stripe" in contents


class TestLabelMatching:
    """Tests for label-based doc matching."""

    async def test_matches_label_in_heading(
        self, adapter: LocalDocsAdapter, fixtures_path: Path
    ):
        """Should match docs where label appears in section heading."""
        ticket = JiraTicket(
            ticket_id="TEST-789",
            title="Update error handling",
            description="Improve error handling",
            status="Open",
            labels=["error-handling"],  # Matches "Error Handling" heading
            components=[],
            created=datetime.now(UTC),
            updated=datetime.now(UTC),
        )

        docs = await adapter.find_relevant_docs(ticket)
        titles = [s.section_title for s in docs.sections if s.section_title]
        # Should have found Error Handling section
        assert any("Error" in t for t in titles)


class TestKeywordMatching:
    """Tests for keyword-based doc matching."""

    async def test_extracts_keywords_from_title(
        self, adapter: LocalDocsAdapter, sample_ticket: JiraTicket
    ):
        """Should extract keywords from ticket title and match docs."""
        # Title: "Add retry logic to payment webhook handler"
        # Keywords: webhook, payment, handler, retry, logic
        docs = await adapter.find_relevant_docs(sample_ticket)

        # Should find sections about webhooks and payments
        all_content = " ".join(s.content.lower() for s in docs.sections)
        assert "webhook" in all_content

    async def test_matches_keyword_in_content(
        self, adapter: LocalDocsAdapter, fixtures_path: Path
    ):
        """Should match docs where keywords appear in content."""
        ticket = JiraTicket(
            ticket_id="TEST-101",
            title="Implement PostgreSQL migration",
            description="Add database migration",
            status="Open",
            labels=[],
            components=[],
            created=datetime.now(UTC),
            updated=datetime.now(UTC),
        )

        docs = await adapter.find_relevant_docs(ticket)
        # Should find architecture doc mentioning PostgreSQL
        all_content = " ".join(s.content.lower() for s in docs.sections)
        assert "postgresql" in all_content


class TestStandardsInclusion:
    """Tests for always-included standards."""

    async def test_includes_standards_regardless_of_match(
        self, adapter: LocalDocsAdapter, fixtures_path: Path
    ):
        """Should always include standards docs."""
        # Ticket with no matching terms
        ticket = JiraTicket(
            ticket_id="TEST-999",
            title="Completely unrelated task",
            description="Nothing matching",
            status="Open",
            labels=[],
            components=[],
            created=datetime.now(UTC),
            updated=datetime.now(UTC),
        )

        docs = await adapter.find_relevant_docs(ticket)

        # Should still include standards
        doc_types = [s.doc_type for s in docs.sections]
        assert "standards" in doc_types


class TestDeduplication:
    """Tests for section deduplication."""

    async def test_no_duplicate_sections(
        self, adapter: LocalDocsAdapter, sample_ticket: JiraTicket
    ):
        """Should not return duplicate sections."""
        docs = await adapter.find_relevant_docs(sample_ticket)

        # Check for duplicates by (file_path, section_title)
        seen = set()
        for section in docs.sections:
            key = (section.file_path, section.section_title)
            assert key not in seen, f"Duplicate section found: {key}"
            seen.add(key)


class TestSectionCapping:
    """Tests for max sections limit."""

    async def test_caps_at_10_sections(
        self, adapter: LocalDocsAdapter, sample_ticket: JiraTicket
    ):
        """Should return at most 10 sections."""
        docs = await adapter.find_relevant_docs(sample_ticket)
        assert len(docs.sections) <= 10


class TestContentTruncation:
    """Tests for content truncation."""

    async def test_truncates_long_sections(
        self, adapter: LocalDocsAdapter, sample_ticket: JiraTicket
    ):
        """Should truncate sections longer than 1500 chars."""
        docs = await adapter.find_relevant_docs(sample_ticket)

        for section in docs.sections:
            # 1500 + "... [truncated]" suffix
            assert len(section.content) <= 1516


class TestGetStandards:
    """Tests for get_standards method."""

    async def test_returns_all_standards(self, adapter: LocalDocsAdapter):
        """Should return all standards when no area specified."""
        docs = await adapter.get_standards()

        assert len(docs.sections) > 0
        for section in docs.sections:
            assert section.doc_type == "standards"

    async def test_filters_by_area_filename(self, adapter: LocalDocsAdapter):
        """Should filter by area matching filename."""
        docs = await adapter.get_standards(area="testing")

        # Should only include sections from testing.md or matching testing
        assert len(docs.sections) > 0
        for section in docs.sections:
            # Either filename matches or content/title matches
            matches = (
                "testing" in section.file_path.lower()
                or (section.section_title and "test" in section.section_title.lower())
                or "test" in section.content.lower()
            )
            assert matches

    async def test_filters_by_area_content(self, adapter: LocalDocsAdapter):
        """Should filter by area appearing in content."""
        docs = await adapter.get_standards(area="error")

        # Should find error handling sections
        assert len(docs.sections) > 0

    async def test_empty_when_disabled(self):
        """Should return empty when adapter disabled."""
        config = DocsConfig(paths=["./docs/"], enabled=False)
        adapter = LocalDocsAdapter(config)

        docs = await adapter.get_standards()
        assert len(docs.sections) == 0


class TestCaching:
    """Tests for file caching behavior."""

    def test_caches_parsed_files(self, adapter: LocalDocsAdapter, fixtures_path: Path):
        """Should cache parsed files."""
        test_file = fixtures_path / "standards" / "typescript.md"

        # First parse
        doc1 = adapter._parse_file(test_file)
        assert doc1 is not None

        # Second parse should return cached version
        doc2 = adapter._parse_file(test_file)
        assert doc2 is doc1  # Same object

    def test_invalidates_cache_on_mtime_change(
        self, adapter: LocalDocsAdapter, fixtures_path: Path
    ):
        """Should re-parse file when mtime changes."""
        test_file = fixtures_path / "standards" / "typescript.md"

        # First parse
        doc1 = adapter._parse_file(test_file)
        assert doc1 is not None

        # Manually change cached mtime to simulate file change
        adapter._cache[test_file] = ParsedDoc(
            file_path=test_file,
            doc_type="standards",
            sections=[],
            mtime=0.0,  # Old mtime
        )

        # Second parse should re-parse
        doc2 = adapter._parse_file(test_file)
        assert doc2 is not None
        assert len(doc2.sections) > 0  # Has actual sections

    def test_clear_cache(self, adapter: LocalDocsAdapter, fixtures_path: Path):
        """Should clear cache when requested."""
        test_file = fixtures_path / "standards" / "typescript.md"

        # Parse to populate cache
        adapter._parse_file(test_file)
        assert len(adapter._cache) > 0

        # Clear cache
        adapter.clear_cache()
        assert len(adapter._cache) == 0


class TestHealthCheck:
    """Tests for health check."""

    async def test_healthy_when_paths_exist(self, adapter: LocalDocsAdapter):
        """Should return True when configured paths exist."""
        result = await adapter.health_check()
        assert result is True

    async def test_healthy_when_disabled(self):
        """Should return True when adapter disabled."""
        config = DocsConfig(paths=["./nonexistent/"], enabled=False)
        adapter = LocalDocsAdapter(config)

        result = await adapter.health_check()
        assert result is True

    async def test_unhealthy_when_no_paths_exist(self):
        """Should return False when no configured paths exist."""
        config = DocsConfig(paths=["./nonexistent1/", "./nonexistent2/"], enabled=True)
        adapter = LocalDocsAdapter(config)

        result = await adapter.health_check()
        assert result is False


class TestFetchContext:
    """Tests for fetch_context (Adapter interface)."""

    async def test_returns_standards_as_context(self, adapter: LocalDocsAdapter):
        """Should return standards as ContextData."""
        context = await adapter.fetch_context("TEST-123")

        assert len(context) > 0
        assert context[0].source == "local_docs:TEST-123"
        assert context[0].source_type == "documentation"
        assert "section_count" in context[0].metadata

    async def test_empty_when_disabled(self):
        """Should return empty when adapter disabled."""
        config = DocsConfig(paths=["./docs/"], enabled=False)
        adapter = LocalDocsAdapter(config)

        context = await adapter.fetch_context("TEST-123")
        assert len(context) == 0


class TestScanDirectories:
    """Tests for directory scanning."""

    def test_finds_md_files(self, adapter: LocalDocsAdapter, fixtures_path: Path):
        """Should find .md files in configured paths."""
        files = adapter._scan_directories()

        assert len(files) > 0
        assert all(f.suffix.lower() in (".md", ".markdown") for f in files)

    def test_scans_recursively(self, adapter: LocalDocsAdapter, fixtures_path: Path):
        """Should scan subdirectories."""
        files = adapter._scan_directories()

        # Should find files in subdirectories
        paths_str = [str(f) for f in files]
        assert any("architecture" in p for p in paths_str)
        assert any("standards" in p for p in paths_str)

    def test_handles_missing_paths(self):
        """Should handle missing paths gracefully."""
        config = DocsConfig(
            paths=["./nonexistent/", "./also-nonexistent/"],
            enabled=True,
        )
        adapter = LocalDocsAdapter(config)

        files = adapter._scan_directories()
        assert files == []
