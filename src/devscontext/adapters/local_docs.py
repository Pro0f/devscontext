"""Local documentation adapter for finding relevant docs.

This adapter scans configured directories for markdown files, splits them
into sections, and matches them against Jira tickets using components,
labels, and keyword matching.

Example:
    config = DocsConfig(paths=["./docs/"])
    adapter = LocalDocsAdapter(config)
    docs = await adapter.find_relevant_docs(ticket)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from devscontext.adapters.base import Adapter
from devscontext.constants import (
    ADAPTER_LOCAL_DOCS,
    SOURCE_TYPE_DOCUMENTATION,
)
from devscontext.logging import get_logger
from devscontext.models import ContextData, DocSection, DocsContext
from devscontext.utils import extract_keywords, truncate_text

if TYPE_CHECKING:
    from devscontext.models import DocsConfig, JiraTicket

logger = get_logger(__name__)

# Constants for local docs
MAX_SECTIONS = 10
MAX_SECTION_CHARS = 1500
SPECIAL_STANDARDS_FILES = frozenset({"claude.md", ".cursorrules", "cursorrules"})

DocType = Literal["architecture", "standards", "adr", "other"]


@dataclass
class ParsedSection:
    """A parsed section from a markdown file."""

    file_path: Path
    section_title: str | None
    content: str
    doc_type: DocType
    heading_level: int = 2  # ## = 2, ### = 3


@dataclass
class ParsedDoc:
    """A parsed markdown document with sections and metadata."""

    file_path: Path
    doc_type: DocType
    sections: list[ParsedSection] = field(default_factory=list)
    mtime: float = 0.0


class LocalDocsAdapter(Adapter):
    """Adapter for finding relevant local documentation."""

    def __init__(self, config: DocsConfig) -> None:
        """Initialize the local docs adapter.

        Args:
            config: Documentation configuration with paths to scan.
        """
        self._config = config
        self._cache: dict[Path, ParsedDoc] = {}

    @property
    def name(self) -> str:
        """Return the adapter name."""
        return ADAPTER_LOCAL_DOCS

    @property
    def source_type(self) -> str:
        """Return the source type."""
        return SOURCE_TYPE_DOCUMENTATION

    def _classify_doc_type(self, file_path: Path) -> DocType:
        """Classify a document based on its path.

        Args:
            file_path: Path to the document.

        Returns:
            The document type classification.
        """
        # Check for special standards files first
        filename_lower = file_path.name.lower()
        if filename_lower in SPECIAL_STANDARDS_FILES:
            return "standards"

        # Check path components for classification
        path_parts = [p.lower() for p in file_path.parts]
        path_str = "/".join(path_parts)

        if "adr" in path_parts or "adrs" in path_parts or "/adr/" in path_str or path_str.startswith("adr/"):
            return "adr"
        if "architecture" in path_parts or "arch" in path_parts:
            return "architecture"
        if "standards" in path_parts or "style" in path_parts or "coding" in path_parts:
            return "standards"

        return "other"

    def _split_into_sections(self, file_path: Path, content: str) -> list[ParsedSection]:
        """Split markdown content into sections by headings.

        Splits on ## and ### headings. Content before the first heading
        is included as a section with no title.

        Args:
            file_path: Path to the file (for metadata).
            content: Raw markdown content.

        Returns:
            List of parsed sections.
        """
        doc_type = self._classify_doc_type(file_path)
        sections: list[ParsedSection] = []

        # Pattern to match ## or ### headings
        heading_pattern = re.compile(r"^(#{2,3})\s+(.+)$", re.MULTILINE)

        matches = list(heading_pattern.finditer(content))

        if not matches:
            # No headings found, treat entire content as one section
            stripped = content.strip()
            if stripped:
                sections.append(
                    ParsedSection(
                        file_path=file_path,
                        section_title=None,
                        content=stripped,
                        doc_type=doc_type,
                        heading_level=0,
                    )
                )
            return sections

        # Content before first heading
        first_match = matches[0]
        if first_match.start() > 0:
            preamble = content[: first_match.start()].strip()
            if preamble:
                sections.append(
                    ParsedSection(
                        file_path=file_path,
                        section_title=None,
                        content=preamble,
                        doc_type=doc_type,
                        heading_level=0,
                    )
                )

        # Process each heading and its content
        for i, match in enumerate(matches):
            heading_level = len(match.group(1))
            title = match.group(2).strip()

            # Content goes from end of this heading to start of next (or end of file)
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            section_content = content[start:end].strip()

            if section_content or title:
                sections.append(
                    ParsedSection(
                        file_path=file_path,
                        section_title=title,
                        content=section_content,
                        doc_type=doc_type,
                        heading_level=heading_level,
                    )
                )

        return sections

    def _parse_file(self, file_path: Path) -> ParsedDoc | None:
        """Parse a markdown file into sections with caching.

        Uses mtime for cache invalidation.

        Args:
            file_path: Path to the markdown file.

        Returns:
            ParsedDoc if successful, None if file cannot be read.
        """
        try:
            mtime = file_path.stat().st_mtime

            # Check cache
            if file_path in self._cache:
                cached = self._cache[file_path]
                if cached.mtime == mtime:
                    return cached

            content = file_path.read_text(encoding="utf-8")
            sections = self._split_into_sections(file_path, content)
            doc_type = self._classify_doc_type(file_path)

            parsed = ParsedDoc(
                file_path=file_path,
                doc_type=doc_type,
                sections=sections,
                mtime=mtime,
            )

            self._cache[file_path] = parsed
            return parsed

        except OSError as e:
            logger.warning(
                "Failed to read doc file",
                extra={"file_path": str(file_path), "error": str(e)},
            )
            return None

    def _scan_directories(self) -> list[Path]:
        """Scan configured directories for markdown files.

        Returns:
            List of paths to markdown files.
        """
        md_files: list[Path] = []

        for path_str in self._config.paths:
            path = Path(path_str)

            if not path.exists():
                logger.debug("Doc path does not exist", extra={"path": path_str})
                continue

            if path.is_file():
                if path.suffix.lower() in (".md", ".markdown"):
                    md_files.append(path)
            else:
                # Scan directory recursively
                for ext in ("*.md", "*.markdown"):
                    md_files.extend(path.rglob(ext))

                # Also look for special files like CLAUDE.md and .cursorrules
                for special in SPECIAL_STANDARDS_FILES:
                    special_path = path / special
                    if special_path.exists() and special_path not in md_files:
                        md_files.append(special_path)

        return md_files

    def _matches_term(self, section: ParsedSection, term: str) -> bool:
        """Check if a section matches a search term.

        Matches against filename (without extension), section title, and content.

        Args:
            section: The section to check.
            term: The search term (lowercase).

        Returns:
            True if the section matches the term.
        """
        term_lower = term.lower()

        # Check filename (without extension)
        filename = section.file_path.stem.lower()
        if term_lower in filename:
            return True

        # Check section title
        if section.section_title and term_lower in section.section_title.lower():
            return True

        # Check content
        if term_lower in section.content.lower():
            return True

        return False

    def _to_doc_section(self, section: ParsedSection) -> DocSection:
        """Convert a ParsedSection to a DocSection model.

        Truncates content to MAX_SECTION_CHARS.

        Args:
            section: The parsed section.

        Returns:
            DocSection model.
        """
        content = truncate_text(section.content, MAX_SECTION_CHARS)

        return DocSection(
            file_path=str(section.file_path),
            section_title=section.section_title,
            content=content,
            doc_type=section.doc_type,
        )

    async def find_relevant_docs(self, ticket: JiraTicket) -> DocsContext:
        """Find documentation relevant to a Jira ticket.

        Matching strategy:
        1. Match by ticket components → filenames and headings
        2. Match by ticket labels → filenames and headings
        3. Match by keywords from title → doc titles and content
        4. Always include general coding standards

        Args:
            ticket: The Jira ticket to find docs for.

        Returns:
            DocsContext with relevant sections (max 10, deduplicated).
        """
        if not self._config.enabled:
            return DocsContext(sections=[])

        md_files = self._scan_directories()
        all_sections: list[ParsedSection] = []

        # Parse all files
        for file_path in md_files:
            parsed = self._parse_file(file_path)
            if parsed:
                all_sections.extend(parsed.sections)

        matched_sections: list[ParsedSection] = []
        seen_keys: set[tuple[str, str | None]] = set()

        def add_section(section: ParsedSection) -> None:
            """Add section if not already seen."""
            key = (str(section.file_path), section.section_title)
            if key not in seen_keys:
                seen_keys.add(key)
                matched_sections.append(section)

        # 1. Match by components
        for component in ticket.components:
            for section in all_sections:
                if self._matches_term(section, component):
                    add_section(section)

        # 2. Match by labels
        for label in ticket.labels:
            for section in all_sections:
                if self._matches_term(section, label):
                    add_section(section)

        # 3. Match by keywords from title
        # Combine title and first part of description for keyword extraction
        text_for_keywords = ticket.title
        if ticket.description:
            # Take first 500 chars of description
            text_for_keywords += " " + ticket.description[:500]

        keywords = extract_keywords(text_for_keywords)
        for keyword in keywords:
            for section in all_sections:
                if self._matches_term(section, keyword):
                    add_section(section)

        # 4. Always include general coding standards
        for section in all_sections:
            if section.doc_type == "standards":
                add_section(section)

        # Cap at MAX_SECTIONS
        result_sections = [self._to_doc_section(s) for s in matched_sections[:MAX_SECTIONS]]

        logger.info(
            "Found relevant docs",
            extra={
                "ticket_id": ticket.ticket_id,
                "sections_found": len(result_sections),
                "total_scanned": len(all_sections),
            },
        )

        return DocsContext(sections=result_sections)

    async def get_standards(self, area: str | None = None) -> DocsContext:
        """Get coding standards documentation.

        Args:
            area: Optional area to filter by (e.g., "testing", "error-handling").
                  If None, returns all standards.

        Returns:
            DocsContext with standards sections.
        """
        if not self._config.enabled:
            return DocsContext(sections=[])

        md_files = self._scan_directories()
        standards_sections: list[ParsedSection] = []

        # Parse all files and collect standards
        for file_path in md_files:
            parsed = self._parse_file(file_path)
            if parsed and parsed.doc_type == "standards":
                standards_sections.extend(parsed.sections)

        # Filter by area if specified
        if area:
            area_lower = area.lower()
            filtered: list[ParsedSection] = []
            for section in standards_sections:
                # Check filename
                if area_lower in section.file_path.stem.lower():
                    filtered.append(section)
                    continue
                # Check section title
                if section.section_title and area_lower in section.section_title.lower():
                    filtered.append(section)
                    continue
                # Check content for area mention
                if area_lower in section.content.lower():
                    filtered.append(section)

            standards_sections = filtered

        # Cap and convert
        result_sections = [self._to_doc_section(s) for s in standards_sections[:MAX_SECTIONS]]

        logger.info(
            "Retrieved standards",
            extra={
                "area": area,
                "sections_found": len(result_sections),
            },
        )

        return DocsContext(sections=result_sections)

    async def fetch_context(self, task_id: str) -> list[ContextData]:
        """Fetch context from local docs (for Adapter interface compliance).

        This method is less useful for local docs since we need a JiraTicket,
        not just a task_id. Returns standards as fallback.

        Args:
            task_id: The task identifier.

        Returns:
            List of ContextData with standards.
        """
        if not self._config.enabled:
            return []

        docs = await self.get_standards()

        if not docs.sections:
            return []

        # Format all sections as content
        parts: list[str] = []
        for section in docs.sections:
            if section.section_title:
                parts.append(f"## {section.section_title}\n{section.content}")
            else:
                parts.append(section.content)

        content = "\n\n".join(parts)

        return [
            ContextData(
                source=f"local_docs:{task_id}",
                source_type=self.source_type,
                title="Coding Standards",
                content=content,
                metadata={"section_count": len(docs.sections)},
            )
        ]

    async def health_check(self) -> bool:
        """Check if local docs adapter is properly configured.

        Returns:
            True if at least one configured path exists.
        """
        if not self._config.enabled:
            return True

        for path_str in self._config.paths:
            path = Path(path_str)
            if path.exists():
                return True

        logger.warning(
            "No configured doc paths exist",
            extra={"paths": self._config.paths},
        )
        return False

    def clear_cache(self) -> None:
        """Clear the parsed document cache."""
        self._cache.clear()
        logger.debug("Cleared local docs cache")
