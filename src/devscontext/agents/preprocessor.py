"""Pre-processing pipeline for building rich context.

This module provides the PreprocessingPipeline class that builds rich context
for Jira tickets without latency pressure. Unlike on-demand fetching, the
pipeline can make more API calls, cross-reference sources, and run multiple
synthesis passes.

The pipeline includes:
1. Deep Jira fetch (ticket + comments + linked issues + epic/parent)
2. Broad meeting search (by ticket ID + title keywords + epic name)
3. Thorough doc matching (by components, labels, keywords, parent context)
4. Multi-pass synthesis (extraction, combination, gap detection)

Example:
    pipeline = PreprocessingPipeline(config, storage)
    context = await pipeline.process("PROJ-123")
    print(f"Quality: {context.context_quality_score}")
    print(f"Gaps: {context.gaps}")
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from devscontext.logging import get_logger
from devscontext.models import (
    DocsContext,
    JiraContext,
    MeetingContext,
    PrebuiltContext,
)
from devscontext.plugins.registry import PluginRegistry
from devscontext.synthesis import create_provider
from devscontext.utils import extract_keywords

if TYPE_CHECKING:
    from devscontext.models import DevsContextConfig, JiraTicket
    from devscontext.storage import PrebuiltContextStorage
    from devscontext.synthesis import LLMProvider

logger = get_logger(__name__)


# =============================================================================
# MULTI-PASS SYNTHESIS PROMPTS
# =============================================================================

EXTRACTION_PROMPT_JIRA = """
Extract the key facts from this Jira ticket for a developer about to implement it.

Focus on:
- What needs to be done (requirements)
- Any acceptance criteria
- Technical constraints or dependencies
- Key decisions made in comments

Return a structured summary in markdown format. Be concise but don't omit important details.

Jira Ticket Data:
---
{jira_data}
---
"""

EXTRACTION_PROMPT_MEETINGS = """
Extract relevant decisions, action items, and discussions from these meeting excerpts.

Focus on:
- Technical decisions that affect implementation
- WHO made each decision and WHEN
- Any unresolved questions or debates
- Action items assigned to the team

Return a structured summary in markdown format. Include speaker names where available.

Meeting Excerpts:
---
{meeting_data}
---
"""

EXTRACTION_PROMPT_DOCS = """
Extract relevant technical context from these documentation sections.

Focus on:
- Architecture patterns to follow
- Coding standards that apply
- File paths and integration points
- Any ADRs (Architecture Decision Records) that apply

Return a structured summary in markdown format. Be specific and actionable.

Documentation:
---
{docs_data}
---
"""

COMBINATION_PROMPT = """
Combine these extracted facts into a unified context block for an AI coding assistant.

Use this structure:
## Task: {task_id} — {title}
### Requirements
### Key Decisions
### Architecture Context
### Coding Standards
### Related Work

Rules:
- Target 2000-3000 tokens. Be concise but complete.
- For each fact, note the source in [brackets] at the end.
- If sources conflict, note the conflict explicitly.
- Do NOT include generic advice. Only include specific, actionable context.

Extracted from Jira:
---
{jira_summary}
---

Extracted from Meetings:
---
{meeting_summary}
---

Extracted from Documentation:
---
{docs_summary}
---
"""

GAP_DETECTION_PROMPT = """
Review this context for a Jira ticket and identify what's MISSING that a developer might need.

Check for these common gaps:
1. Missing acceptance criteria (how to know when done?)
2. Missing architecture documentation (where does this code go?)
3. Missing coding standards (what patterns to follow?)
4. No meeting discussions (was this design reviewed?)
5. No related ADRs (should decisions be documented?)
6. Unclear dependencies (what needs to be done first?)
7. Missing test requirements (what needs to be tested?)

Return a JSON array of strings, each describing a gap. If no gaps, return [].

Example output:
["No acceptance criteria defined in ticket", "No architecture docs found"]

Context to review:
---
{context}
---

Return ONLY a JSON array, no other text.
"""


class PreprocessingPipeline:
    """Builds rich context for tickets not under latency pressure.

    Unlike on-demand fetching, this pipeline can:
    - Make more API calls for deeper context
    - Cross-reference multiple sources
    - Run multiple LLM synthesis passes
    - Detect and report gaps in context
    """

    def __init__(
        self,
        config: DevsContextConfig,
        storage: PrebuiltContextStorage,
    ) -> None:
        """Initialize the pipeline.

        Args:
            config: DevsContext configuration.
            storage: Storage for pre-built context.
        """
        self._config = config
        self._storage = storage

        # Initialize plugin registry for adapters
        self._registry = PluginRegistry()
        self._registry.register_builtin_plugins()
        self._registry.load_from_config(config)

        # LLM provider for synthesis
        self._provider: LLMProvider | None = None

    def _get_provider(self) -> LLMProvider:
        """Get or create LLM provider."""
        if self._provider is None:
            self._provider = create_provider(self._config.synthesis)
        return self._provider

    async def process(self, task_id: str) -> PrebuiltContext:
        """Run full preprocessing pipeline for a task.

        Args:
            task_id: Jira ticket ID to process.

        Returns:
            PrebuiltContext with synthesized content and quality metrics.
        """
        logger.info("Starting preprocessing pipeline", extra={"task_id": task_id})

        # 1. Deep fetch from all sources
        jira_ctx = await self._deep_jira_fetch(task_id)
        if jira_ctx is None:
            raise ValueError(f"Could not fetch Jira ticket: {task_id}")

        meeting_ctx = await self._broad_meeting_search(jira_ctx.ticket)
        docs_ctx = await self._thorough_doc_match(jira_ctx.ticket)

        # 2. Multi-pass synthesis
        synthesized, quality_score, gaps = await self._multi_pass_synthesis(
            task_id=task_id,
            jira_ctx=jira_ctx,
            meeting_ctx=meeting_ctx,
            docs_ctx=docs_ctx,
        )

        # 3. Build sources list
        sources_used = [f"jira:{task_id}"]
        for meeting in meeting_ctx.meetings:
            sources_used.append(f"fireflies:{meeting.meeting_date.strftime('%Y-%m-%d')}")
        for section in docs_ctx.sections:
            sources_used.append(f"docs:{section.file_path}")

        # 4. Calculate expiration and hash
        ttl_hours = self._config.agents.preprocessor.context_ttl_hours
        now = datetime.now(UTC)
        expires_at = now + timedelta(hours=ttl_hours)
        source_data_hash = self._compute_source_hash(jira_ctx.ticket)

        # 5. Build and store context
        context = PrebuiltContext(
            task_id=task_id,
            synthesized=synthesized,
            sources_used=sources_used,
            context_quality_score=quality_score,
            gaps=gaps,
            built_at=now,
            expires_at=expires_at,
            source_data_hash=source_data_hash,
        )

        await self._storage.store(context)

        logger.info(
            "Preprocessing complete",
            extra={
                "task_id": task_id,
                "quality_score": quality_score,
                "gaps_count": len(gaps),
                "sources_count": len(sources_used),
            },
        )

        return context

    def _compute_source_hash(self, ticket: JiraTicket) -> str:
        """Compute hash of source data for staleness detection.

        Uses the Jira ticket's updated timestamp as the primary indicator
        of freshness.

        Args:
            ticket: Jira ticket to hash.

        Returns:
            Hash string.
        """
        # Simple approach: hash the updated timestamp
        data = ticket.updated.isoformat()
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    async def _deep_jira_fetch(self, task_id: str) -> JiraContext | None:
        """Fetch ticket with all related context.

        Fetches:
        - Main ticket with full description
        - All comments (not just recent)
        - All linked issues with their summaries
        - Epic/parent ticket if available (TODO: implement)

        Args:
            task_id: Jira ticket ID.

        Returns:
            JiraContext with full data, or None if not found.
        """
        jira = self._registry.get_adapter("jira")
        if jira is None:
            logger.warning("Jira adapter not available")
            return None

        try:
            # Use the adapter's fetch method which already does deep fetching
            ctx = await jira.fetch_task_context(task_id)
            if ctx.is_empty():
                return None

            if isinstance(ctx.data, JiraContext):
                return ctx.data
            return None

        except Exception as e:
            logger.error(
                "Failed to fetch Jira context",
                extra={"task_id": task_id, "error": str(e)},
            )
            return None

    async def _broad_meeting_search(self, ticket: JiraTicket) -> MeetingContext:
        """Search for meetings with multiple strategies.

        Searches by:
        - Ticket ID (e.g., "PROJ-123")
        - Keywords from ticket title
        - Epic/feature name if available (TODO: implement)

        Args:
            ticket: Jira ticket to search for.

        Returns:
            MeetingContext with all found excerpts.
        """
        fireflies = self._registry.get_adapter("fireflies")
        if fireflies is None:
            return MeetingContext(meetings=[])

        try:
            # Strategy 1: Search by ticket ID
            ctx_by_id = await fireflies.fetch_task_context(ticket.ticket_id, ticket)

            # Strategy 2: Search by title keywords
            keywords = extract_keywords(ticket.title)
            keyword_query = " ".join(keywords[:3])  # Use top 3 keywords

            all_meetings = []
            if isinstance(ctx_by_id.data, MeetingContext):
                all_meetings.extend(ctx_by_id.data.meetings)

            # Search by keywords if we have them
            if keyword_query:
                ctx_by_keywords = await fireflies.fetch_task_context(keyword_query, ticket)
                if isinstance(ctx_by_keywords.data, MeetingContext):
                    # Deduplicate by meeting title + date
                    existing = {(m.meeting_title, m.meeting_date) for m in all_meetings}
                    for meeting in ctx_by_keywords.data.meetings:
                        key = (meeting.meeting_title, meeting.meeting_date)
                        if key not in existing:
                            all_meetings.append(meeting)
                            existing.add(key)

            return MeetingContext(meetings=all_meetings)

        except Exception as e:
            logger.warning(
                "Meeting search failed",
                extra={"task_id": ticket.ticket_id, "error": str(e)},
            )
            return MeetingContext(meetings=[])

    async def _thorough_doc_match(self, ticket: JiraTicket) -> DocsContext:
        """Match documentation with multiple strategies.

        Matches by:
        - Components (e.g., "payments" component -> payments.md)
        - Labels (e.g., "api" label -> api-design.md)
        - Keywords from ticket title
        - Always includes standards (CLAUDE.md, .cursorrules)

        Args:
            ticket: Jira ticket to match docs for.

        Returns:
            DocsContext with all matched sections.
        """
        docs = self._registry.get_adapter("local_docs")
        if docs is None:
            return DocsContext(sections=[])

        try:
            # Use the adapter's fetch which already does multi-strategy matching
            ctx = await docs.fetch_task_context(ticket.ticket_id, ticket)

            if isinstance(ctx.data, DocsContext):
                return ctx.data
            return DocsContext(sections=[])

        except Exception as e:
            logger.warning(
                "Doc matching failed",
                extra={"task_id": ticket.ticket_id, "error": str(e)},
            )
            return DocsContext(sections=[])

    async def _multi_pass_synthesis(
        self,
        task_id: str,
        jira_ctx: JiraContext,
        meeting_ctx: MeetingContext,
        docs_ctx: DocsContext,
    ) -> tuple[str, float, list[str]]:
        """Run multi-pass synthesis with dedicated prompts.

        Pass 1 - Clean Extraction:
            Extract key facts from each source independently.

        Pass 2 - Combination:
            Combine extracted facts into unified context.

        Pass 3 - Gap Detection:
            Identify missing context that developers might need.

        Args:
            task_id: Jira ticket ID.
            jira_ctx: Jira context with ticket, comments, links.
            meeting_ctx: Meeting excerpts.
            docs_ctx: Documentation sections.

        Returns:
            Tuple of (synthesized_markdown, quality_score, gaps_list).
        """
        provider = self._get_provider()
        max_tokens = self._config.synthesis.max_output_tokens

        # === Pass 1: Extraction ===
        logger.debug("Pass 1: Extracting from sources")

        # Extract from Jira
        jira_data = self._format_jira_for_extraction(jira_ctx)
        jira_prompt = EXTRACTION_PROMPT_JIRA.format(jira_data=jira_data)
        jira_summary = await provider.generate(jira_prompt, max_tokens=1500)

        # Extract from meetings (if any)
        meeting_summary = "No meeting discussions found."
        if meeting_ctx.meetings:
            meeting_data = self._format_meetings_for_extraction(meeting_ctx)
            meeting_prompt = EXTRACTION_PROMPT_MEETINGS.format(meeting_data=meeting_data)
            meeting_summary = await provider.generate(meeting_prompt, max_tokens=1500)

        # Extract from docs (if any)
        docs_summary = "No relevant documentation found."
        if docs_ctx.sections:
            docs_data = self._format_docs_for_extraction(docs_ctx)
            docs_prompt = EXTRACTION_PROMPT_DOCS.format(docs_data=docs_data)
            docs_summary = await provider.generate(docs_prompt, max_tokens=1500)

        # === Pass 2: Combination ===
        logger.debug("Pass 2: Combining extracted facts")

        combination_prompt = COMBINATION_PROMPT.format(
            task_id=task_id,
            title=jira_ctx.ticket.title,
            jira_summary=jira_summary,
            meeting_summary=meeting_summary,
            docs_summary=docs_summary,
        )
        synthesized = await provider.generate(combination_prompt, max_tokens=max_tokens)

        # === Pass 3: Gap Detection ===
        logger.debug("Pass 3: Detecting gaps")

        gap_prompt = GAP_DETECTION_PROMPT.format(context=synthesized)
        gap_response = await provider.generate(gap_prompt, max_tokens=500)
        gaps = self._parse_gaps(gap_response)

        # === Calculate Quality Score ===
        quality_score = self._calculate_quality_score(jira_ctx, meeting_ctx, docs_ctx)

        return synthesized, quality_score, gaps

    def _format_jira_for_extraction(self, ctx: JiraContext) -> str:
        """Format Jira context for extraction prompt."""
        parts = [
            f"## Ticket: {ctx.ticket.ticket_id}",
            f"**Title:** {ctx.ticket.title}",
            f"**Status:** {ctx.ticket.status}",
        ]

        if ctx.ticket.description:
            parts.append(f"\n**Description:**\n{ctx.ticket.description}")

        if ctx.ticket.acceptance_criteria:
            parts.append(f"\n**Acceptance Criteria:**\n{ctx.ticket.acceptance_criteria}")

        if ctx.ticket.labels:
            parts.append(f"\n**Labels:** {', '.join(ctx.ticket.labels)}")

        if ctx.ticket.components:
            parts.append(f"\n**Components:** {', '.join(ctx.ticket.components)}")

        if ctx.comments:
            parts.append("\n**Comments:**")
            for comment in ctx.comments:
                date_str = comment.created.strftime("%Y-%m-%d")
                parts.append(f"\n*{comment.author} ({date_str}):*\n{comment.body}")

        if ctx.linked_issues:
            parts.append("\n**Linked Issues:**")
            for link in ctx.linked_issues:
                parts.append(f"- {link.link_type}: {link.ticket_id} ({link.status}) — {link.title}")

        return "\n".join(parts)

    def _format_meetings_for_extraction(self, ctx: MeetingContext) -> str:
        """Format meeting context for extraction prompt."""
        parts = []
        for meeting in ctx.meetings:
            date_str = meeting.meeting_date.strftime("%Y-%m-%d")
            parts.append(f"## {meeting.meeting_title} ({date_str})")
            if meeting.participants:
                parts.append(f"**Participants:** {', '.join(meeting.participants)}")
            parts.append(f"\n{meeting.excerpt}")

            if meeting.action_items:
                parts.append("\n**Action Items:**")
                for item in meeting.action_items:
                    parts.append(f"- {item}")

            if meeting.decisions:
                parts.append("\n**Decisions:**")
                for decision in meeting.decisions:
                    parts.append(f"- {decision}")

            parts.append("")  # Blank line between meetings

        return "\n".join(parts)

    def _format_docs_for_extraction(self, ctx: DocsContext) -> str:
        """Format documentation context for extraction prompt."""
        parts = []
        for section in ctx.sections:
            title = section.section_title or section.file_path
            parts.append(f"## {title}")
            parts.append(f"*Source: {section.file_path}* [{section.doc_type}]")
            parts.append(f"\n{section.content}")
            parts.append("")  # Blank line between sections

        return "\n".join(parts)

    def _parse_gaps(self, response: str) -> list[str]:
        """Parse gap detection response into list of gaps."""
        import json

        try:
            # Try to parse as JSON array
            response = response.strip()
            # Handle markdown code blocks
            if response.startswith("```"):
                lines = response.split("\n")
                response = "\n".join(lines[1:-1])

            gaps = json.loads(response)
            if isinstance(gaps, list):
                return [str(g) for g in gaps if g]
            return []
        except json.JSONDecodeError:
            # If not valid JSON, try to extract bullet points
            gaps = []
            for line in response.split("\n"):
                line = line.strip()
                if line.startswith("- ") or line.startswith("* "):
                    gaps.append(line[2:])
                elif line.startswith('"') and line.endswith('"'):
                    gaps.append(line[1:-1])
            return gaps

    def _calculate_quality_score(
        self,
        jira_ctx: JiraContext,
        meeting_ctx: MeetingContext,
        docs_ctx: DocsContext,
    ) -> float:
        """Calculate context quality score based on completeness.

        Score components (0-1 each, averaged):
        - Has description: 0.2
        - Has acceptance criteria: 0.2
        - Has meeting context: 0.2
        - Has architecture docs: 0.2
        - Has coding standards: 0.2

        Returns:
            Quality score between 0 and 1.
        """
        score = 0.0

        # Has description (0.2)
        if jira_ctx.ticket.description:
            score += 0.2

        # Has acceptance criteria (0.2)
        if jira_ctx.ticket.acceptance_criteria:
            score += 0.2

        # Has meeting context (0.2)
        if meeting_ctx.meetings:
            score += 0.2

        # Has architecture docs (0.2)
        has_arch = any(s.doc_type == "architecture" for s in docs_ctx.sections)
        if has_arch:
            score += 0.2

        # Has coding standards (0.2)
        has_standards = any(s.doc_type == "standards" for s in docs_ctx.sections)
        if has_standards:
            score += 0.2

        return score

    async def close(self) -> None:
        """Close resources."""
        await self._registry.close_all()
