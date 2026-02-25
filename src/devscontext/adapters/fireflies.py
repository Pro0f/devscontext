"""Fireflies adapter for fetching meeting transcript context.

This adapter connects to the Fireflies.ai GraphQL API to fetch meeting
transcripts and search for relevant discussions related to a task.

This adapter implements the Adapter interface for the plugin system.

Example:
    config = FirefliesConfig(api_key="your-api-key", enabled=True)
    adapter = FirefliesAdapter(config)
    context = await adapter.fetch_task_context("PROJ-123")
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar

import httpx

from devscontext.constants import (
    ADAPTER_FIREFLIES,
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    FIREFLIES_API_URL,
    FIREFLIES_CONTEXT_WINDOW,
    FIREFLIES_SEARCH_LIMIT,
    SOURCE_TYPE_MEETING,
)
from devscontext.logging import get_logger
from devscontext.models import ContextData, FirefliesConfig, MeetingContext, MeetingExcerpt
from devscontext.plugins.base import Adapter, SearchResult, SourceContext

if TYPE_CHECKING:
    from devscontext.models import JiraTicket

logger = get_logger(__name__)

# GraphQL query to search transcripts
SEARCH_TRANSCRIPTS_QUERY = """
query SearchTranscripts($query: String!, $limit: Int!) {
  transcripts(filter_string: $query, limit: $limit) {
    id
    title
    date
    participants
    summary {
      overview
      action_items
      keywords
    }
    sentences {
      text
      speaker_name
    }
  }
}
"""


class FirefliesAdapter(Adapter):
    """Adapter for fetching context from Fireflies meeting transcripts.

    Implements the Adapter interface for the plugin system.
    Connects to Fireflies.ai to search for meeting transcripts
    that mention a specific task ID or keywords.

    Class Attributes:
        name: Adapter identifier ("fireflies").
        source_type: Source category ("meeting").
        config_schema: Configuration model (FirefliesConfig).
    """

    # Adapter class attributes
    name: ClassVar[str] = ADAPTER_FIREFLIES
    source_type: ClassVar[str] = SOURCE_TYPE_MEETING
    config_schema: ClassVar[type[FirefliesConfig]] = FirefliesConfig

    def __init__(self, config: FirefliesConfig) -> None:
        """Initialize the Fireflies adapter.

        Args:
            config: Fireflies configuration with API key.
        """
        self._config = config
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    "Authorization": f"Bearer {self._config.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def search_transcripts(self, query: str) -> list[dict[str, Any]]:
        """Search Fireflies transcripts by query string.

        Args:
            query: Search query (e.g., ticket ID or keywords).

        Returns:
            List of transcript data dictionaries.
        """
        client = self._get_client()

        try:
            response = await client.post(
                FIREFLIES_API_URL,
                json={
                    "query": SEARCH_TRANSCRIPTS_QUERY,
                    "variables": {"query": query, "limit": FIREFLIES_SEARCH_LIMIT},
                },
            )
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                logger.warning(
                    "Fireflies GraphQL errors",
                    extra={"errors": data["errors"], "query": query},
                )
                return []

            transcripts = data.get("data", {}).get("transcripts") or []
            logger.info(
                "Fireflies search completed",
                extra={"query": query, "count": len(transcripts)},
            )
            return transcripts

        except httpx.HTTPStatusError as e:
            logger.warning(
                "Fireflies API error",
                extra={"status_code": e.response.status_code, "query": query},
            )
            return []

        except httpx.RequestError as e:
            logger.warning(
                "Fireflies network error",
                extra={"error": str(e), "query": query},
            )
            return []

    def _extract_relevant_excerpts(
        self,
        sentences: list[dict[str, Any]],
        search_terms: list[str],
    ) -> str:
        """Extract relevant sentences from transcript with surrounding context.

        Finds sentences mentioning search terms and includes ±N surrounding
        sentences for context.

        Args:
            sentences: List of sentence dictionaries with text and speaker_name.
            search_terms: Terms to search for in sentences.

        Returns:
            Formatted excerpt string with speaker names.
        """
        if not sentences or not search_terms:
            return ""

        # Find indices of sentences containing search terms
        matching_indices: set[int] = set()
        search_pattern = re.compile(
            "|".join(re.escape(term) for term in search_terms),
            re.IGNORECASE,
        )

        for i, sentence in enumerate(sentences):
            text = sentence.get("text", "")
            if search_pattern.search(text):
                matching_indices.add(i)

        if not matching_indices:
            return ""

        # Expand to include surrounding context
        indices_to_include: set[int] = set()
        for idx in matching_indices:
            for offset in range(-FIREFLIES_CONTEXT_WINDOW, FIREFLIES_CONTEXT_WINDOW + 1):
                new_idx = idx + offset
                if 0 <= new_idx < len(sentences):
                    indices_to_include.add(new_idx)

        # Build excerpt from consecutive ranges
        sorted_indices = sorted(indices_to_include)
        excerpt_parts: list[str] = []
        current_range: list[int] = []

        for idx in sorted_indices:
            if not current_range or idx == current_range[-1] + 1:
                current_range.append(idx)
            else:
                # Output current range and start new one
                if current_range:
                    excerpt_parts.append(self._format_sentence_range(sentences, current_range))
                current_range = [idx]

        # Don't forget the last range
        if current_range:
            excerpt_parts.append(self._format_sentence_range(sentences, current_range))

        return "\n\n[...]\n\n".join(excerpt_parts)

    def _format_sentence_range(
        self,
        sentences: list[dict[str, Any]],
        indices: list[int],
    ) -> str:
        """Format a range of sentences with speaker names.

        Args:
            sentences: All sentences from the transcript.
            indices: Indices of sentences to include.

        Returns:
            Formatted string with speaker attributions.
        """
        parts: list[str] = []
        current_speaker: str | None = None

        for idx in indices:
            sentence = sentences[idx]
            speaker = sentence.get("speaker_name", "Unknown")
            text = sentence.get("text", "").strip()

            if not text:
                continue

            if speaker != current_speaker:
                if parts:
                    parts.append("")  # Add blank line between speakers
                parts.append(f"**{speaker}:** {text}")
                current_speaker = speaker
            else:
                parts.append(text)

        return "\n".join(parts)

    def _parse_transcript(
        self,
        transcript: dict[str, Any],
        search_terms: list[str],
    ) -> MeetingExcerpt | None:
        """Parse a transcript into a MeetingExcerpt.

        Args:
            transcript: Raw transcript data from Fireflies API.
            search_terms: Terms used for searching (for excerpt extraction).

        Returns:
            MeetingExcerpt if valid, None otherwise.
        """
        try:
            # Parse date
            date_str = transcript.get("date")
            if date_str:
                try:
                    meeting_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    if meeting_date.tzinfo is None:
                        meeting_date = meeting_date.replace(tzinfo=UTC)
                except ValueError:
                    meeting_date = datetime.now(UTC)
            else:
                meeting_date = datetime.now(UTC)

            # Get participants
            participants = transcript.get("participants") or []
            if isinstance(participants, str):
                participants = [p.strip() for p in participants.split(",")]

            # Get summary data
            summary = transcript.get("summary") or {}
            overview = summary.get("overview") or ""
            action_items_raw = summary.get("action_items") or []
            if isinstance(action_items_raw, str):
                action_items = [
                    item.strip() for item in action_items_raw.split("\n") if item.strip()
                ]
            else:
                action_items = list(action_items_raw) if action_items_raw else []

            # Extract relevant excerpts from sentences
            sentences = transcript.get("sentences") or []
            excerpt = self._extract_relevant_excerpts(sentences, search_terms)

            # If no relevant excerpt found but we have an overview, use that
            if not excerpt and overview:
                excerpt = f"**Summary:** {overview}"
            elif not excerpt:
                return None  # No useful content

            return MeetingExcerpt(
                meeting_title=transcript.get("title") or "Untitled Meeting",
                meeting_date=meeting_date,
                participants=participants,
                excerpt=excerpt,
                action_items=action_items,
                decisions=[],  # Fireflies doesn't provide decisions directly
            )

        except Exception as e:
            logger.warning(
                "Failed to parse Fireflies transcript",
                extra={"error": str(e), "transcript_id": transcript.get("id")},
            )
            return None

    async def get_meeting_context(self, task_id: str) -> MeetingContext:
        """Get meeting context for a task ID.

        Searches for transcripts mentioning the task ID and extracts
        relevant excerpts.

        Args:
            task_id: The task identifier to search for.

        Returns:
            MeetingContext with relevant meeting excerpts.
        """
        if not self._config.enabled:
            logger.debug("Fireflies adapter is disabled")
            return MeetingContext()

        if not self._config.api_key:
            logger.warning("Fireflies adapter missing API key")
            return MeetingContext()

        # Search by task ID
        search_terms = [task_id]
        transcripts = await self.search_transcripts(task_id)

        # Parse transcripts into excerpts
        excerpts: list[MeetingExcerpt] = []
        for transcript in transcripts:
            excerpt = self._parse_transcript(transcript, search_terms)
            if excerpt:
                excerpts.append(excerpt)

        logger.info(
            "Fireflies context assembled",
            extra={"task_id": task_id, "meeting_count": len(excerpts)},
        )

        return MeetingContext(meetings=excerpts)

    async def fetch_task_context(
        self,
        task_id: str,
        ticket: JiraTicket | None = None,
    ) -> SourceContext:
        """Fetch context from Fireflies meeting transcripts.

        Implements the Adapter interface. Searches for meetings mentioning
        the task ID or keywords from the ticket.

        Args:
            task_id: The task identifier to search for in transcripts.
            ticket: Optional Jira ticket for keyword extraction.

        Returns:
            SourceContext with MeetingContext data.
        """
        if not self._config.enabled:
            logger.debug("Fireflies adapter is disabled")
            return SourceContext(
                source_name=self.name,
                source_type=self.source_type,
                data=None,
                raw_text="",
            )

        meeting_context = await self.get_meeting_context(task_id)

        if not meeting_context.meetings:
            return SourceContext(
                source_name=self.name,
                source_type=self.source_type,
                data=meeting_context,
                raw_text="",
                metadata={"task_id": task_id, "meeting_count": 0},
            )

        raw_text = self._format_meeting_context(meeting_context)

        return SourceContext(
            source_name=self.name,
            source_type=self.source_type,
            data=meeting_context,
            raw_text=raw_text,
            metadata={
                "task_id": task_id,
                "meeting_count": len(meeting_context.meetings),
            },
        )

    def _format_meeting_context(self, meeting_context: MeetingContext) -> str:
        """Format meeting context as raw text for synthesis."""
        parts: list[str] = []

        for meeting in meeting_context.meetings:
            content_parts = [f"## {meeting.meeting_title}"]
            content_parts.append(f"\n**Date:** {meeting.meeting_date.strftime('%Y-%m-%d')}")

            if meeting.participants:
                content_parts.append(f"**Participants:** {', '.join(meeting.participants)}")

            content_parts.append(f"\n### Relevant Discussion\n\n{meeting.excerpt}")

            if meeting.action_items:
                content_parts.append("\n### Action Items")
                for item in meeting.action_items:
                    content_parts.append(f"- {item}")

            if meeting.decisions:
                content_parts.append("\n### Decisions")
                for decision in meeting.decisions:
                    content_parts.append(f"- {decision}")

            parts.append("\n".join(content_parts))

        return "\n\n---\n\n".join(parts)

    async def search(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """Search Fireflies transcripts for items matching the query.

        Implements the Adapter interface.

        Args:
            query: Search terms to find in transcripts.
            max_results: Maximum number of results to return.

        Returns:
            List of SearchResult items.
        """
        if not self._config.enabled:
            return []

        transcripts = await self.search_transcripts(query)

        results: list[SearchResult] = []
        for transcript in transcripts[:max_results]:
            title = transcript.get("title") or "Untitled Meeting"
            date_str = transcript.get("date", "")

            # Get overview from summary
            summary = transcript.get("summary") or {}
            excerpt = summary.get("overview") or ""
            if not excerpt:
                # Fall back to first few sentences
                sentences = transcript.get("sentences") or []
                if sentences:
                    excerpt = " ".join(s.get("text", "") for s in sentences[:3])

            results.append(
                SearchResult(
                    source_name=self.name,
                    source_type=self.source_type,
                    title=title,
                    excerpt=excerpt[:500] if excerpt else "No excerpt available",
                    metadata={
                        "date": date_str,
                        "participants": transcript.get("participants") or [],
                    },
                )
            )

        return results

    async def fetch_context(self, task_id: str) -> list[ContextData]:
        """Fetch context from Fireflies (legacy Adapter interface).

        This method is kept for backward compatibility.

        Args:
            task_id: The task identifier to search for in transcripts.

        Returns:
            List of ContextData items, one per relevant meeting.
        """
        source_context = await self.fetch_task_context(task_id)

        if source_context.is_empty():
            return []

        meeting_context = source_context.data
        if not isinstance(meeting_context, MeetingContext):
            return []

        # Convert each meeting excerpt to ContextData
        results: list[ContextData] = []
        for meeting in meeting_context.meetings:
            content_parts = [f"## {meeting.meeting_title}"]
            content_parts.append(f"\n**Date:** {meeting.meeting_date.strftime('%Y-%m-%d')}")

            if meeting.participants:
                content_parts.append(f"**Participants:** {', '.join(meeting.participants)}")

            content_parts.append(f"\n### Relevant Discussion\n\n{meeting.excerpt}")

            if meeting.action_items:
                content_parts.append("\n### Action Items")
                for item in meeting.action_items:
                    content_parts.append(f"- {item}")

            if meeting.decisions:
                content_parts.append("\n### Decisions")
                for decision in meeting.decisions:
                    content_parts.append(f"- {decision}")

            content = "\n".join(content_parts)

            results.append(
                ContextData(
                    source=f"fireflies:{meeting.meeting_date.strftime('%Y-%m-%d')}",
                    source_type=self.source_type,
                    title=meeting.meeting_title,
                    content=content,
                    metadata={
                        "date": meeting.meeting_date.isoformat(),
                        "participants": meeting.participants,
                        "action_item_count": len(meeting.action_items),
                    },
                    relevance_score=0.8,
                )
            )

        return results

    async def health_check(self) -> bool:
        """Check if Fireflies is configured and accessible.

        Returns:
            True if healthy or disabled, False if there's an issue.
        """
        if not self._config.enabled:
            return True

        if not self._config.api_key:
            logger.warning("Fireflies adapter missing API key")
            return False

        try:
            # Simple query to verify API access
            client = self._get_client()
            response = await client.post(
                FIREFLIES_API_URL,
                json={
                    "query": "query { user { email } }",
                },
            )

            if response.status_code == 200:
                data = response.json()
                if "errors" not in data:
                    logger.info("Fireflies health check passed")
                    return True

            logger.warning(
                "Fireflies health check failed",
                extra={"status_code": response.status_code},
            )
            return False

        except Exception as e:
            logger.warning("Fireflies health check error", extra={"error": str(e)})
            return False
