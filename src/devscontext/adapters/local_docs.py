"""Local documentation adapter for finding relevant docs.

This adapter scans configured directories for markdown files, splits them
into sections, and matches them against Jira tickets using components,
labels, and keyword matching.

Optionally supports RAG (embedding-based) search when configured:
    pip install devscontext[rag]

This adapter implements the Adapter interface for the plugin system.

Example:
    config = DocsConfig(paths=["./docs/"])
    adapter = LocalDocsAdapter(config)
    docs = await adapter.fetch_task_context("PROJ-123", ticket)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from devscontext.constants import (
    ADAPTER_LOCAL_DOCS,
    SOURCE_TYPE_DOCUMENTATION,
)
from devscontext.logging import get_logger
from devscontext.models import ContextData, DocsConfig, DocsContext, DocSection
from devscontext.plugins.base import Adapter, SearchResult, SourceContext
from devscontext.utils import extract_keywords, truncate_text

if TYPE_CHECKING:
    from devscontext.models import JiraTicket
    from devscontext.rag.embeddings import EmbeddingProvider
    from devscontext.rag.index import DocumentIndex

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
    """Adapter for finding relevant local documentation.

    Implements the Adapter interface for the plugin system.
    Scans local directories for markdown files and matches them
    against tickets using components, labels, and keywords.

    Class Attributes:
        name: Adapter identifier ("local_docs").
        source_type: Source category ("documentation").
        config_schema: Configuration model (DocsConfig).
    """

    # Adapter class attributes
    name: ClassVar[str] = ADAPTER_LOCAL_DOCS
    source_type: ClassVar[str] = SOURCE_TYPE_DOCUMENTATION
    config_schema: ClassVar[type[DocsConfig]] = DocsConfig

    def __init__(self, config: DocsConfig) -> None:
        """Initialize the local docs adapter.

        Args:
            config: Documentation configuration with paths to scan.
        """
        self._config = config
        self._cache: dict[Path, ParsedDoc] = {}

        # RAG components (lazy-loaded when first needed)
        self._rag_index: DocumentIndex | None = None
        self._embedding_provider: EmbeddingProvider | None = None
        self._rag_initialized = False

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

        if (
            "adr" in path_parts
            or "adrs" in path_parts
            or "/adr/" in path_str
            or path_str.startswith("adr/")
        ):
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

    def _init_rag(self) -> bool:
        """Initialize RAG components if configured and available.

        Returns:
            True if RAG is ready to use, False otherwise.
        """
        if self._rag_initialized:
            return self._rag_index is not None and self._embedding_provider is not None

        self._rag_initialized = True

        # Check if RAG is configured
        if not self._config.rag or not self._config.rag.enabled:
            return False

        # Check if RAG dependencies are available
        try:
            from devscontext.rag import is_rag_available

            if not is_rag_available():
                logger.warning(
                    "RAG enabled but dependencies not installed. "
                    "Install with: pip install devscontext[rag]"
                )
                return False

            from devscontext.rag import DocumentIndex, get_embedding_provider

            # Initialize embedding provider
            self._embedding_provider = get_embedding_provider(self._config.rag)

            # Initialize and load document index
            self._rag_index = DocumentIndex(self._config.rag.index_path)
            if self._rag_index.exists():
                self._rag_index.load()
                logger.info(
                    "RAG index loaded",
                    extra={
                        "sections": self._rag_index.section_count,
                        "model": self._rag_index.model,
                    },
                )
            else:
                logger.warning(
                    "RAG enabled but index not found. "
                    "Run 'devscontext index-docs' to build the index."
                )
                return False

            return True

        except ImportError as e:
            logger.warning(
                "Failed to initialize RAG",
                extra={"error": str(e)},
            )
            return False
        except Exception as e:
            logger.warning(
                "Error initializing RAG, falling back to keyword matching",
                extra={"error": str(e)},
            )
            return False

    async def _find_docs_via_rag(self, ticket: JiraTicket) -> DocsContext:
        """Find relevant docs using embedding-based semantic search.

        Args:
            ticket: The Jira ticket to find docs for.

        Returns:
            DocsContext with relevant sections.
        """
        if not self._rag_index or not self._embedding_provider or not self._config.rag:
            return await self._find_docs_via_keywords(ticket)

        # Build query from ticket
        query = ticket.title
        if ticket.description:
            query += " " + ticket.description[:500]

        try:
            # Get query embedding
            query_embedding = await self._embedding_provider.embed_query(query)

            # Search index
            results = self._rag_index.search(
                query_embedding,
                top_k=self._config.rag.top_k,
                threshold=self._config.rag.similarity_threshold,
            )

            # Convert to DocSection, collecting matched sections
            matched_sections: list[DocSection] = []
            seen_keys: set[tuple[str, str | None]] = set()

            for indexed_section, _score in results:
                key = (indexed_section.file_path, indexed_section.section_title)
                if key not in seen_keys:
                    seen_keys.add(key)
                    content = truncate_text(indexed_section.content, MAX_SECTION_CHARS)
                    matched_sections.append(
                        DocSection(
                            file_path=indexed_section.file_path,
                            section_title=indexed_section.section_title,
                            content=content,
                            doc_type=indexed_section.doc_type,  # type: ignore[arg-type]
                        )
                    )

            # Always include standards (scan and add any not already matched)
            md_files = self._scan_directories()
            for file_path in md_files:
                parsed = self._parse_file(file_path)
                if parsed and parsed.doc_type == "standards":
                    for section in parsed.sections:
                        key = (str(section.file_path), section.section_title)
                        if key not in seen_keys:
                            seen_keys.add(key)
                            matched_sections.append(self._to_doc_section(section))

            # Cap at MAX_SECTIONS
            result_sections = matched_sections[:MAX_SECTIONS]

            logger.info(
                "Found relevant docs via RAG",
                extra={
                    "ticket_id": ticket.ticket_id,
                    "sections_found": len(result_sections),
                    "rag_matches": len(results),
                },
            )

            return DocsContext(sections=result_sections)

        except Exception as e:
            logger.warning(
                "RAG search failed, falling back to keyword matching",
                extra={"error": str(e)},
            )
            return await self._find_docs_via_keywords(ticket)

    async def _find_docs_via_keywords(self, ticket: JiraTicket) -> DocsContext:
        """Find relevant docs using keyword matching (original implementation).

        Args:
            ticket: The Jira ticket to find docs for.

        Returns:
            DocsContext with relevant sections.
        """
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
        text_for_keywords = ticket.title
        if ticket.description:
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
            "Found relevant docs via keywords",
            extra={
                "ticket_id": ticket.ticket_id,
                "sections_found": len(result_sections),
                "total_scanned": len(all_sections),
            },
        )

        return DocsContext(sections=result_sections)

    async def index_documents(self, rebuild: bool = False) -> dict[str, Any]:
        """Build or rebuild the RAG index for local documentation.

        This method scans all configured doc paths, generates embeddings for
        each section, and saves them to the index file.

        Args:
            rebuild: If True, clear existing index before building.

        Returns:
            Dictionary with indexing statistics.

        Raises:
            ImportError: If RAG dependencies are not installed.
            ValueError: If RAG is not configured.
        """
        if not self._config.rag:
            raise ValueError(
                "RAG not configured. Add 'rag' section to docs config in .devscontext.yaml"
            )

        from devscontext.rag import is_rag_available

        if not is_rag_available():
            raise ImportError(
                "RAG dependencies not installed. Install with: pip install devscontext[rag]"
            )

        from devscontext.rag import DocumentIndex, get_embedding_provider
        from devscontext.rag.index import IndexedSection

        # Initialize components
        provider = get_embedding_provider(self._config.rag)
        index = DocumentIndex(self._config.rag.index_path)

        # Handle rebuild
        if rebuild and index.exists():
            index.delete()
            logger.info("Cleared existing index for rebuild")

        # Scan and parse all documents
        md_files = self._scan_directories()
        all_sections: list[ParsedSection] = []

        for file_path in md_files:
            parsed = self._parse_file(file_path)
            if parsed:
                all_sections.extend(parsed.sections)

        if not all_sections:
            return {
                "status": "no_docs",
                "sections_indexed": 0,
                "files_scanned": len(md_files),
            }

        # Prepare text for embedding
        texts = []
        indexed_sections = []

        for section in all_sections:
            # Create text combining title and content for better embedding
            text_parts = []
            if section.section_title:
                text_parts.append(section.section_title)
            if section.content:
                text_parts.append(section.content)
            text = "\n".join(text_parts)

            texts.append(text)
            indexed_sections.append(
                IndexedSection(
                    file_path=str(section.file_path),
                    section_title=section.section_title,
                    content=section.content,
                    doc_type=section.doc_type,
                )
            )

        # Generate embeddings in batches
        logger.info(
            "Generating embeddings",
            extra={"sections": len(texts), "model": self._config.rag.embedding_model},
        )

        batch_size = 32
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            embeddings = await provider.embed(batch)
            all_embeddings.extend(embeddings)

        # Add to index and save
        index.add_sections(indexed_sections, all_embeddings, self._config.rag.embedding_model)
        index.save()

        stats = index.get_stats()
        logger.info(
            "Indexing complete",
            extra={
                "sections_indexed": len(indexed_sections),
                "dimension": stats.get("dimension"),
            },
        )

        return {
            "status": "success",
            "sections_indexed": len(indexed_sections),
            "files_scanned": len(md_files),
            "model": self._config.rag.embedding_model,
            "dimension": stats.get("dimension"),
            "index_path": str(self._config.rag.index_path),
        }

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
        return term_lower in section.content.lower()

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

        When RAG is enabled and the index exists, uses semantic search.
        Otherwise, falls back to keyword matching:
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

        # Try RAG if configured and available
        if self._init_rag():
            return await self._find_docs_via_rag(ticket)

        # Fall back to keyword matching
        return await self._find_docs_via_keywords(ticket)

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

    async def list_standards_areas(self) -> list[str]:
        """List available standards areas based on file names and section titles.

        Returns:
            List of area names (e.g., ["typescript", "testing", "error-handling"]).
        """
        if not self._config.enabled:
            return []

        md_files = self._scan_directories()
        areas: set[str] = set()

        for file_path in md_files:
            parsed = self._parse_file(file_path)
            if parsed and parsed.doc_type == "standards":
                # Add filename (without extension) as an area
                areas.add(file_path.stem.lower())

        return sorted(areas)

    async def search_docs(self, query: str, max_results: int = 10) -> DocsContext:
        """Search local documentation by keywords.

        Searches file names, section titles, and content for matching terms.

        Args:
            query: Search query string.
            max_results: Maximum number of sections to return.

        Returns:
            DocsContext with matching sections.
        """
        if not self._config.enabled:
            return DocsContext(sections=[])

        # Extract keywords from query
        keywords = extract_keywords(query)
        if not keywords:
            # If no keywords extracted, use the original query terms
            keywords = [w.lower() for w in query.split() if len(w) >= 3]

        if not keywords:
            return DocsContext(sections=[])

        md_files = self._scan_directories()
        all_sections: list[ParsedSection] = []

        # Parse all files
        for file_path in md_files:
            parsed = self._parse_file(file_path)
            if parsed:
                all_sections.extend(parsed.sections)

        # Score sections by keyword matches
        scored_sections: list[tuple[ParsedSection, int]] = []
        for section in all_sections:
            score = 0
            for keyword in keywords:
                if self._matches_term(section, keyword):
                    score += 1
            if score > 0:
                scored_sections.append((section, score))

        # Sort by score (highest first) and take top results
        scored_sections.sort(key=lambda x: -x[1])
        matched_sections = [s for s, _ in scored_sections[:max_results]]

        result_sections = [self._to_doc_section(s) for s in matched_sections]

        logger.info(
            "Docs search completed",
            extra={
                "query": query,
                "keywords": keywords,
                "sections_found": len(result_sections),
            },
        )

        return DocsContext(sections=result_sections)

    async def fetch_task_context(
        self,
        task_id: str,
        ticket: JiraTicket | None = None,
    ) -> SourceContext:
        """Fetch context from local docs.

        Implements the Adapter interface. Uses the ticket (if provided)
        to find relevant docs based on components, labels, and keywords.
        Falls back to standards if no ticket provided.

        Args:
            task_id: The task identifier.
            ticket: Optional Jira ticket for context-aware matching.

        Returns:
            SourceContext with DocsContext data.
        """
        if not self._config.enabled:
            return SourceContext(
                source_name=self.name,
                source_type=self.source_type,
                data=None,
                raw_text="",
            )

        if ticket:
            docs = await self.find_relevant_docs(ticket)
        else:
            docs = await self.get_standards()

        if not docs.sections:
            return SourceContext(
                source_name=self.name,
                source_type=self.source_type,
                data=docs,
                raw_text="",
                metadata={"task_id": task_id, "section_count": 0},
            )

        raw_text = self._format_docs_context(docs)

        return SourceContext(
            source_name=self.name,
            source_type=self.source_type,
            data=docs,
            raw_text=raw_text,
            metadata={
                "task_id": task_id,
                "section_count": len(docs.sections),
            },
        )

    def _format_docs_context(self, docs: DocsContext) -> str:
        """Format docs context as raw text for synthesis."""
        parts: list[str] = []
        for section in docs.sections:
            if section.section_title:
                parts.append(f"## {section.section_title}\n\n{section.content}")
            else:
                parts.append(section.content)
        return "\n\n---\n\n".join(parts)

    async def search(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """Search local docs for items matching the query.

        Implements the Adapter interface.

        Args:
            query: Search terms to find in docs.
            max_results: Maximum number of results to return.

        Returns:
            List of SearchResult items.
        """
        if not self._config.enabled:
            return []

        docs = await self.search_docs(query, max_results)

        results: list[SearchResult] = []
        for section in docs.sections:
            title = section.section_title or Path(section.file_path).name
            excerpt = truncate_text(section.content, 300)

            results.append(
                SearchResult(
                    source_name=self.name,
                    source_type=self.source_type,
                    title=title,
                    excerpt=excerpt,
                    metadata={
                        "file_path": section.file_path,
                        "doc_type": section.doc_type,
                    },
                )
            )

        return results

    async def fetch_context(self, task_id: str) -> list[ContextData]:
        """Fetch context from local docs (legacy Adapter interface).

        This method is kept for backward compatibility.

        Args:
            task_id: The task identifier.

        Returns:
            List of ContextData with standards.
        """
        source_context = await self.fetch_task_context(task_id)

        if source_context.is_empty():
            return []

        docs = source_context.data
        if not isinstance(docs, DocsContext):
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
                title="Documentation",
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

    async def close(self) -> None:
        """Clean up resources by clearing the document cache."""
        self.clear_cache()

    def clear_cache(self) -> None:
        """Clear the parsed document cache."""
        self._cache.clear()
        logger.debug("Cleared local docs cache")
