"""Jira adapter for fetching issue context.

This adapter connects to the Jira REST API (v3) to fetch ticket details,
comments, and linked issues. It handles Atlassian Document Format (ADF)
conversion and assembles all data into a structured context block.

This adapter implements the SourcePlugin interface for the plugin system.

Example:
    config = JiraConfig(base_url="https://company.atlassian.net", ...)
    adapter = JiraAdapter(config)
    context = await adapter.fetch_task_context("PROJ-123")
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any, ClassVar

import httpx

from devscontext.constants import (
    ADAPTER_JIRA,
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    JIRA_API_BASE_PATH,
    JIRA_MAX_COMMENTS,
    JIRA_TICKET_FIELDS,
    SOURCE_TYPE_ISSUE_TRACKER,
)
from devscontext.logging import get_logger
from devscontext.models import (
    ContextData,
    JiraComment,
    JiraConfig,
    JiraContext,
    JiraTicket,
    LinkedIssue,
)
from devscontext.plugins.base import Adapter, SearchResult, SourceContext

logger = get_logger(__name__)


class JiraAdapter(Adapter):
    """Adapter for fetching context from Jira issues.

    Implements the Adapter interface for the plugin system.
    Provides context from Jira tickets, comments, and linked issues.

    Class Attributes:
        name: Adapter identifier ("jira").
        source_type: Source category ("issue_tracker").
        config_schema: Configuration model (JiraConfig).
    """

    # Adapter class attributes
    name: ClassVar[str] = ADAPTER_JIRA
    source_type: ClassVar[str] = SOURCE_TYPE_ISSUE_TRACKER
    config_schema: ClassVar[type[JiraConfig]] = JiraConfig

    def __init__(self, config: JiraConfig) -> None:
        """Initialize the Jira adapter.

        Args:
            config: Jira configuration with credentials and settings.
        """
        self._config = config
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._config.base_url.rstrip("/"),
                auth=(self._config.email, self._config.api_token),
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get_ticket(self, ticket_id: str) -> JiraTicket | None:
        """Fetch ticket details from Jira."""
        start_time = time.monotonic()
        client = self._get_client()

        try:
            response = await client.get(
                f"{JIRA_API_BASE_PATH}/issue/{ticket_id}",
                params={"fields": JIRA_TICKET_FIELDS},
            )
            response.raise_for_status()
            data = response.json()

            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.info(
                "Fetched Jira ticket",
                extra={"ticket_id": ticket_id, "duration_ms": duration_ms},
            )

            return self._parse_ticket(data["key"], data.get("fields", {}))

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning("Jira ticket not found", extra={"ticket_id": ticket_id})
                return None
            logger.error(
                "Jira API error",
                extra={"ticket_id": ticket_id, "status_code": e.response.status_code},
            )
            return None

        except httpx.RequestError as e:
            logger.exception("Network error fetching Jira ticket", extra={"error": str(e)})
            return None

    async def get_comments(self, ticket_id: str) -> list[JiraComment]:
        """Fetch comments for a Jira ticket."""
        client = self._get_client()

        try:
            response = await client.get(
                f"{JIRA_API_BASE_PATH}/issue/{ticket_id}/comment",
                params={"maxResults": JIRA_MAX_COMMENTS, "orderBy": "-created"},
            )
            response.raise_for_status()
            data = response.json()

            logger.info(
                "Fetched Jira comments",
                extra={"ticket_id": ticket_id, "count": len(data.get("comments", []))},
            )

            return [self._parse_comment(c) for c in data.get("comments", [])]

        except httpx.HTTPStatusError:
            logger.warning("Failed to fetch Jira comments", extra={"ticket_id": ticket_id})
            return []

        except httpx.RequestError as e:
            logger.exception("Network error fetching comments", extra={"error": str(e)})
            return []

    async def get_linked_issues(self, ticket_id: str) -> list[LinkedIssue]:
        """Fetch linked issues for a Jira ticket."""
        start_time = time.monotonic()
        client = self._get_client()

        try:
            response = await client.get(
                f"{JIRA_API_BASE_PATH}/issue/{ticket_id}",
                params={"fields": "issuelinks"},
            )
            response.raise_for_status()
            data = response.json()

            links = data.get("fields", {}).get("issuelinks", [])
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.info(
                "Fetched linked issues",
                extra={"ticket_id": ticket_id, "count": len(links), "duration_ms": duration_ms},
            )

            return [linked for link in links if (linked := self._parse_linked_issue(link))]

        except httpx.HTTPStatusError:
            logger.warning("Failed to fetch linked issues", extra={"ticket_id": ticket_id})
            return []

        except httpx.RequestError as e:
            logger.exception("Network error fetching linked issues", extra={"error": str(e)})
            return []

    async def get_ticket_full_context(self, ticket_id: str) -> JiraContext | None:
        """Fetch full context for a Jira ticket (ticket, comments, linked issues)."""
        start_time = time.monotonic()

        results = await asyncio.gather(
            self.get_ticket(ticket_id),
            self.get_comments(ticket_id),
            self.get_linked_issues(ticket_id),
            return_exceptions=True,
        )

        ticket_result = results[0]
        comments_result = results[1]
        linked_result = results[2]

        # Handle exceptions from gather
        ticket: JiraTicket | None = None
        if isinstance(ticket_result, JiraTicket):
            ticket = ticket_result
        elif isinstance(ticket_result, Exception):
            ticket = None

        comments: list[JiraComment] = []
        if isinstance(comments_result, list):
            comments = comments_result

        linked_issues: list[LinkedIssue] = []
        if isinstance(linked_result, list):
            linked_issues = linked_result

        duration_ms = int((time.monotonic() - start_time) * 1000)

        if ticket is None:
            logger.warning("Ticket not found", extra={"ticket_id": ticket_id})
            return None

        logger.info(
            "Assembled full ticket context",
            extra={
                "ticket_id": ticket_id,
                "comment_count": len(comments),
                "linked_count": len(linked_issues),
                "duration_ms": duration_ms,
            },
        )

        return JiraContext(
            ticket=ticket,
            comments=comments,
            linked_issues=linked_issues,
        )

    async def get_jira_context(self, task_id: str) -> JiraContext | None:
        """Alias for get_ticket_full_context for consistency with other adapters."""
        return await self.get_ticket_full_context(task_id)

    async def search_issues(
        self,
        query: str,
        max_results: int = 5,
    ) -> list[JiraTicket]:
        """Search for issues using JQL text search.

        Performs a full-text search across issue summary and description.
        Returns lightweight ticket summaries (no comments or linked issues).

        Args:
            query: Search terms to find in issues.
            max_results: Maximum number of results to return.

        Returns:
            List of matching JiraTicket objects (lightweight, no comments).
        """
        if not self._config.enabled:
            return []

        start_time = time.monotonic()
        client = self._get_client()

        # Build JQL query with text search
        # Escape quotes in the query for JQL
        escaped_query = query.replace('"', '\\"')
        jql = f'text ~ "{escaped_query}" ORDER BY updated DESC'

        try:
            response = await client.get(
                f"{JIRA_API_BASE_PATH}/search",
                params={
                    "jql": jql,
                    "maxResults": max_results,
                    "fields": "summary,status,assignee,labels,updated",
                },
            )
            response.raise_for_status()
            data = response.json()

            issues = data.get("issues", [])
            duration_ms = int((time.monotonic() - start_time) * 1000)

            logger.info(
                "Jira search completed",
                extra={
                    "query": query,
                    "result_count": len(issues),
                    "duration_ms": duration_ms,
                },
            )

            # Parse into lightweight tickets
            results: list[JiraTicket] = []
            for issue in issues:
                key = issue.get("key", "")
                fields = issue.get("fields", {})
                results.append(self._parse_search_result(key, fields))

            return results

        except httpx.HTTPStatusError as e:
            logger.warning(
                "Jira search failed",
                extra={"query": query, "status_code": e.response.status_code},
            )
            return []

        except httpx.RequestError as e:
            logger.warning(
                "Jira search network error",
                extra={"query": query, "error": str(e)},
            )
            return []

    def _parse_search_result(self, key: str, fields: dict[str, Any]) -> JiraTicket:
        """Parse a search result into a lightweight JiraTicket."""
        assignee = None
        if fields.get("assignee"):
            assignee = fields["assignee"].get("displayName")

        updated = self._parse_datetime(fields.get("updated"))

        return JiraTicket(
            ticket_id=key,
            title=fields.get("summary", ""),
            description=None,  # Not fetched for search results
            status=fields.get("status", {}).get("name", "Unknown"),
            assignee=assignee,
            labels=fields.get("labels", []),
            components=[],  # Not fetched for search results
            acceptance_criteria=None,
            story_points=None,
            sprint=None,
            created=updated,  # Use updated as approximation
            updated=updated,
        )

    def _parse_ticket(self, key: str, fields: dict[str, Any]) -> JiraTicket:
        """Parse ticket data from Jira API response."""
        description = self._extract_text_from_adf(fields.get("description"))

        # Parse datetime fields
        created = self._parse_datetime(fields.get("created"))
        updated = self._parse_datetime(fields.get("updated"))

        # Get assignee display name
        assignee = None
        if fields.get("assignee"):
            assignee = fields["assignee"].get("displayName")

        # Get components
        components = [c.get("name", "") for c in fields.get("components", [])]

        # Get sprint (from custom field if available)
        sprint = None
        if fields.get("sprint"):
            sprint = fields["sprint"].get("name") if isinstance(fields["sprint"], dict) else None

        return JiraTicket(
            ticket_id=key,
            title=fields.get("summary", ""),
            description=description,
            status=fields.get("status", {}).get("name", "Unknown"),
            assignee=assignee,
            labels=fields.get("labels", []),
            components=components,
            acceptance_criteria=None,  # Would need custom field mapping
            story_points=None,  # Would need custom field mapping
            sprint=sprint,
            created=created,
            updated=updated,
        )

    def _parse_comment(self, comment_data: dict[str, Any]) -> JiraComment:
        """Parse comment data from Jira API response."""
        author_data = comment_data.get("author", {})
        body = self._extract_text_from_adf(comment_data.get("body")) or ""
        created = self._parse_datetime(comment_data.get("created"))

        return JiraComment(
            author=author_data.get("displayName", "Unknown"),
            body=body,
            created=created,
        )

    def _parse_linked_issue(self, link: dict[str, Any]) -> LinkedIssue | None:
        """Parse linked issue data from Jira API response."""
        link_type = link.get("type", {}).get("name", "Related")

        if "outwardIssue" in link:
            issue = link["outwardIssue"]
            link_direction = link.get("type", {}).get("outward", link_type)
        elif "inwardIssue" in link:
            issue = link["inwardIssue"]
            link_direction = link.get("type", {}).get("inward", link_type)
        else:
            return None

        return LinkedIssue(
            ticket_id=issue["key"],
            title=issue.get("fields", {}).get("summary", ""),
            status=issue.get("fields", {}).get("status", {}).get("name", "Unknown"),
            link_type=link_direction,
        )

    def _parse_datetime(self, value: str | None) -> datetime:
        """Parse ISO datetime string to timezone-aware datetime."""
        if not value:
            return datetime.now(UTC)
        try:
            # Jira returns ISO format like "2024-01-15T10:30:00.000+0000"
            dt = datetime.fromisoformat(value.replace("+0000", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except ValueError:
            return datetime.now(UTC)

    def _extract_text_from_adf(self, adf: dict[str, Any] | str | None) -> str | None:
        """Extract plain text from Atlassian Document Format."""
        if adf is None:
            return None
        if isinstance(adf, str):
            return adf

        def extract_from_node(node: dict[str, Any]) -> str:
            if node.get("type") == "text":
                return str(node.get("text", ""))
            content = node.get("content", [])
            texts = [extract_from_node(child) for child in content]
            if node.get("type") in ("paragraph", "heading", "listItem"):
                return "".join(texts) + "\n"
            return "".join(texts)

        try:
            return extract_from_node(adf).strip()
        except Exception:
            logger.warning("Failed to parse ADF document")
            return None

    def _format_context_content(self, context: JiraContext) -> str:
        """Format ticket context as markdown."""
        parts: list[str] = []

        # Description
        parts.append(f"## Description\n{context.ticket.description or 'No description'}")

        # Details
        parts.append("\n## Details")
        parts.append(f"- **Status:** {context.ticket.status}")
        if context.ticket.assignee:
            parts.append(f"- **Assignee:** {context.ticket.assignee}")
        if context.ticket.labels:
            parts.append(f"- **Labels:** {', '.join(context.ticket.labels)}")
        if context.ticket.components:
            parts.append(f"- **Components:** {', '.join(context.ticket.components)}")
        if context.ticket.sprint:
            parts.append(f"- **Sprint:** {context.ticket.sprint}")

        # Comments
        if context.comments:
            parts.append(f"\n## Comments ({len(context.comments)})")
            for comment in context.comments[:10]:
                date_str = comment.created.strftime("%Y-%m-%d")
                parts.append(f"\n**{comment.author}** ({date_str}):")
                parts.append(comment.body)

        # Linked issues
        if context.linked_issues:
            parts.append(f"\n## Linked Issues ({len(context.linked_issues)})")
            for linked in context.linked_issues:
                parts.append(
                    f"- [{linked.ticket_id}] {linked.title} ({linked.status}) - {linked.link_type}"
                )

        return "\n".join(parts)

    async def fetch_task_context(
        self,
        task_id: str,
        ticket: JiraTicket | None = None,
    ) -> SourceContext:
        """Fetch context from a Jira issue.

        Implements the SourcePlugin interface. Fetches the ticket, comments,
        and linked issues, returning them as a SourceContext.

        Args:
            task_id: The Jira ticket ID (e.g., "PROJ-123").
            ticket: Ignored for Jira adapter (we fetch fresh data).

        Returns:
            SourceContext with JiraContext data, or empty context if disabled/error.
        """
        if not self._config.enabled:
            logger.debug("Jira adapter is disabled")
            return SourceContext(
                source_name=self.name,
                source_type=self.source_type,
                data=None,
                raw_text="",
            )

        context = await self.get_ticket_full_context(task_id)
        if context is None:
            return SourceContext(
                source_name=self.name,
                source_type=self.source_type,
                data=None,
                raw_text="",
                metadata={"task_id": task_id, "error": "not_found"},
            )

        raw_text = self._format_context_content(context)

        return SourceContext(
            source_name=self.name,
            source_type=self.source_type,
            data=context,
            raw_text=raw_text,
            metadata={
                "task_id": task_id,
                "status": context.ticket.status,
                "assignee": context.ticket.assignee,
                "labels": context.ticket.labels,
                "components": context.ticket.components,
                "comment_count": len(context.comments),
                "linked_issue_count": len(context.linked_issues),
            },
        )

    async def search(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """Search for Jira issues matching the query.

        Implements the SourcePlugin interface. Performs JQL text search
        across issue summary and description.

        Args:
            query: Search terms to find in issues.
            max_results: Maximum number of results to return.

        Returns:
            List of SearchResult items.
        """
        if not self._config.enabled:
            return []

        tickets = await self.search_issues(query, max_results)

        results: list[SearchResult] = []
        for ticket in tickets:
            # Build excerpt from title and status
            excerpt = f"{ticket.title}\n\nStatus: {ticket.status}"
            if ticket.assignee:
                excerpt += f"\nAssignee: {ticket.assignee}"
            if ticket.labels:
                excerpt += f"\nLabels: {', '.join(ticket.labels)}"

            # Build URL if we have base_url
            url = None
            if self._config.base_url:
                url = f"{self._config.base_url.rstrip('/')}/browse/{ticket.ticket_id}"

            results.append(
                SearchResult(
                    source_name=self.name,
                    source_type=self.source_type,
                    title=f"[{ticket.ticket_id}] {ticket.title}",
                    excerpt=excerpt,
                    url=url,
                    metadata={
                        "ticket_id": ticket.ticket_id,
                        "status": ticket.status,
                        "assignee": ticket.assignee,
                    },
                )
            )

        return results

    async def fetch_context(self, task_id: str) -> list[ContextData]:
        """Fetch context from a Jira issue (legacy Adapter interface).

        This method is kept for backward compatibility with the old Adapter
        interface. New code should use fetch_task_context() instead.

        Args:
            task_id: The Jira ticket ID.

        Returns:
            List of ContextData items.
        """
        source_context = await self.fetch_task_context(task_id)

        if source_context.is_empty():
            return []

        context = source_context.data
        if not isinstance(context, JiraContext):
            return []

        return [
            ContextData(
                source=f"jira:{task_id}",
                source_type=self.source_type,
                title=f"[{task_id}] {context.ticket.title}",
                content=source_context.raw_text,
                metadata=dict(source_context.metadata),
            )
        ]

    async def health_check(self) -> bool:
        """Check if Jira is configured and accessible."""
        if not self._config.enabled:
            return True

        if not (self._config.base_url and self._config.email and self._config.api_token):
            logger.warning("Jira adapter missing required configuration")
            return False

        try:
            client = self._get_client()
            response = await client.get(f"{JIRA_API_BASE_PATH}/myself")
            healthy = response.status_code == 200

            if healthy:
                logger.info("Jira health check passed")
            else:
                logger.warning(
                    "Jira health check failed",
                    extra={"status_code": response.status_code},
                )

            return healthy

        except Exception as e:
            logger.exception("Jira health check error", extra={"error": str(e)})
            return False
