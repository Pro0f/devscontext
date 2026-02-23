"""Jira adapter for fetching issue context.

This adapter connects to the Jira REST API (v3) to fetch ticket details,
comments, and linked issues. It handles Atlassian Document Format (ADF)
conversion and assembles all data into a structured context block.

The adapter requires configuration with:
    - base_url: Your Jira instance URL (e.g., https://company.atlassian.net)
    - email: Your Atlassian account email
    - api_token: An API token from https://id.atlassian.com/manage-profile/security/api-tokens

Example:
    config = JiraConfig(
        base_url="https://company.atlassian.net",
        email="user@company.com",
        api_token="your-api-token",
        enabled=True,
    )
    adapter = JiraAdapter(config)
    context = await adapter.fetch_context("PROJ-123")
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import httpx

from devscontext.adapters.base import Adapter
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
    JiraLinkedIssue,
    JiraTicket,
    JiraTicketContext,
    JiraUser,
)

if TYPE_CHECKING:
    from devscontext.config import JiraConfig

logger = get_logger(__name__)


class JiraAdapter(Adapter):
    """Adapter for fetching context from Jira issues.

    This adapter connects to the Jira REST API to fetch:
        - Ticket details (summary, description, status, etc.)
        - Comments (most recent first)
        - Linked issues (with summary and status)

    All data is fetched in parallel using asyncio.gather for performance.

    Attributes:
        name: Always "jira".
        source_type: Always "issue_tracker".
    """

    def __init__(self, config: JiraConfig) -> None:
        """Initialize the Jira adapter.

        Args:
            config: Jira configuration with base_url, email, and api_token.
        """
        self._config = config
        self._client: httpx.AsyncClient | None = None

    @property
    def name(self) -> str:
        """Return the adapter name."""
        return ADAPTER_JIRA

    @property
    def source_type(self) -> str:
        """Return the source type."""
        return SOURCE_TYPE_ISSUE_TRACKER

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client.

        The client is created lazily and reused for all requests.

        Returns:
            An httpx AsyncClient configured for Jira API calls.
        """
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._config.base_url.rstrip("/"),
                auth=(self._config.email, self._config.api_token),
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client.

        Should be called when the adapter is no longer needed to
        release resources.
        """
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get_ticket(self, ticket_id: str) -> JiraTicket | None:
        """Fetch ticket details from Jira.

        Args:
            ticket_id: The Jira issue key (e.g., 'PROJ-123').

        Returns:
            JiraTicket if found, None if not found or on error.

        Raises:
            JiraAdapterError: Only for unexpected errors (not 404s).
        """
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

            fields = data.get("fields", {})
            return self._parse_ticket(data["key"], fields)

        except httpx.HTTPStatusError as e:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            if e.response.status_code == 404:
                logger.warning(
                    "Jira ticket not found",
                    extra={"ticket_id": ticket_id, "duration_ms": duration_ms},
                )
                return None
            logger.error(
                "Jira API error",
                extra={
                    "ticket_id": ticket_id,
                    "status_code": e.response.status_code,
                    "duration_ms": duration_ms,
                },
            )
            return None

        except httpx.RequestError as e:
            logger.exception(
                "Network error fetching Jira ticket",
                extra={"ticket_id": ticket_id, "error": str(e)},
            )
            return None

    async def get_comments(self, ticket_id: str) -> list[JiraComment]:
        """Fetch comments for a Jira ticket.

        Args:
            ticket_id: The Jira issue key.

        Returns:
            List of JiraComment objects, empty list on error.
        """
        start_time = time.monotonic()
        client = self._get_client()

        try:
            response = await client.get(
                f"{JIRA_API_BASE_PATH}/issue/{ticket_id}/comment",
                params={"maxResults": JIRA_MAX_COMMENTS, "orderBy": "-created"},
            )
            response.raise_for_status()
            data = response.json()

            duration_ms = int((time.monotonic() - start_time) * 1000)
            comment_count = len(data.get("comments", []))
            logger.info(
                "Fetched Jira comments",
                extra={
                    "ticket_id": ticket_id,
                    "count": comment_count,
                    "duration_ms": duration_ms,
                },
            )

            return [self._parse_comment(comment_data) for comment_data in data.get("comments", [])]

        except httpx.HTTPStatusError as e:
            logger.warning(
                "Failed to fetch Jira comments",
                extra={"ticket_id": ticket_id, "status_code": e.response.status_code},
            )
            return []

        except httpx.RequestError as e:
            logger.exception(
                "Network error fetching Jira comments",
                extra={"ticket_id": ticket_id, "error": str(e)},
            )
            return []

    async def get_linked_issues(self, ticket_id: str) -> list[JiraLinkedIssue]:
        """Fetch linked issues for a Jira ticket.

        Args:
            ticket_id: The Jira issue key.

        Returns:
            List of JiraLinkedIssue objects, empty list on error.
        """
        start_time = time.monotonic()
        client = self._get_client()

        try:
            response = await client.get(
                f"{JIRA_API_BASE_PATH}/issue/{ticket_id}",
                params={"fields": "issuelinks"},
            )
            response.raise_for_status()
            data = response.json()

            duration_ms = int((time.monotonic() - start_time) * 1000)
            links = data.get("fields", {}).get("issuelinks", [])
            logger.info(
                "Fetched Jira linked issues",
                extra={
                    "ticket_id": ticket_id,
                    "count": len(links),
                    "duration_ms": duration_ms,
                },
            )

            return [
                linked for link in links if (linked := self._parse_linked_issue(link)) is not None
            ]

        except httpx.HTTPStatusError as e:
            logger.warning(
                "Failed to fetch linked issues",
                extra={"ticket_id": ticket_id, "status_code": e.response.status_code},
            )
            return []

        except httpx.RequestError as e:
            logger.exception(
                "Network error fetching linked issues",
                extra={"ticket_id": ticket_id, "error": str(e)},
            )
            return []

    async def get_ticket_full_context(self, ticket_id: str) -> JiraTicketContext | None:
        """Fetch full context for a Jira ticket.

        Fetches ticket details, comments, and linked issues in parallel.

        Args:
            ticket_id: The Jira issue key.

        Returns:
            JiraTicketContext if ticket found, None otherwise.
        """
        start_time = time.monotonic()

        # Fetch all data in parallel
        results = await asyncio.gather(
            self.get_ticket(ticket_id),
            self.get_comments(ticket_id),
            self.get_linked_issues(ticket_id),
            return_exceptions=True,
        )

        # Unpack results, handling exceptions
        ticket = results[0] if not isinstance(results[0], Exception) else None
        comments = results[1] if not isinstance(results[1], Exception) else []
        linked_issues = results[2] if not isinstance(results[2], Exception) else []

        # Log any exceptions
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "Exception in parallel fetch",
                    extra={
                        "ticket_id": ticket_id,
                        "fetch_index": i,
                        "error": str(result),
                    },
                )

        duration_ms = int((time.monotonic() - start_time) * 1000)

        if ticket is None:
            logger.warning(
                "Ticket not found, returning None",
                extra={"ticket_id": ticket_id, "duration_ms": duration_ms},
            )
            return None

        logger.info(
            "Assembled full ticket context",
            extra={
                "ticket_id": ticket_id,
                "comment_count": len(comments) if isinstance(comments, list) else 0,
                "linked_count": len(linked_issues) if isinstance(linked_issues, list) else 0,
                "duration_ms": duration_ms,
            },
        )

        return JiraTicketContext(
            ticket=ticket,
            comments=comments if isinstance(comments, list) else [],
            linked_issues=linked_issues if isinstance(linked_issues, list) else [],
        )

    def _parse_ticket(self, key: str, fields: dict[str, Any]) -> JiraTicket:
        """Parse ticket data from Jira API response.

        Args:
            key: The issue key.
            fields: The fields dict from the API response.

        Returns:
            A JiraTicket model.
        """
        assignee = None
        if fields.get("assignee"):
            assignee = JiraUser(
                display_name=fields["assignee"].get("displayName", "Unknown"),
                email=fields["assignee"].get("emailAddress"),
            )

        reporter = None
        if fields.get("reporter"):
            reporter = JiraUser(
                display_name=fields["reporter"].get("displayName", "Unknown"),
                email=fields["reporter"].get("emailAddress"),
            )

        description = self._extract_text_from_adf(fields.get("description"))

        return JiraTicket(
            key=key,
            summary=fields.get("summary", ""),
            description=description,
            status=fields.get("status", {}).get("name", "Unknown"),
            priority=(fields.get("priority", {}).get("name") if fields.get("priority") else None),
            assignee=assignee,
            reporter=reporter,
            labels=fields.get("labels", []),
            issue_type=fields.get("issuetype", {}).get("name", "Task"),
            created=fields.get("created"),
            updated=fields.get("updated"),
        )

    def _parse_comment(self, comment_data: dict[str, Any]) -> JiraComment:
        """Parse comment data from Jira API response.

        Args:
            comment_data: A comment object from the API response.

        Returns:
            A JiraComment model.
        """
        author_data = comment_data.get("author", {})
        body = self._extract_text_from_adf(comment_data.get("body")) or ""

        return JiraComment(
            id=comment_data["id"],
            author=JiraUser(
                display_name=author_data.get("displayName", "Unknown"),
                email=author_data.get("emailAddress"),
            ),
            body=body,
            created=comment_data.get("created", ""),
        )

    def _parse_linked_issue(self, link: dict[str, Any]) -> JiraLinkedIssue | None:
        """Parse linked issue data from Jira API response.

        Args:
            link: An issue link object from the API response.

        Returns:
            A JiraLinkedIssue model, or None if the link is malformed.
        """
        link_type = link.get("type", {}).get("name", "Related")

        if "outwardIssue" in link:
            issue = link["outwardIssue"]
            link_direction = link.get("type", {}).get("outward", link_type)
        elif "inwardIssue" in link:
            issue = link["inwardIssue"]
            link_direction = link.get("type", {}).get("inward", link_type)
        else:
            return None

        return JiraLinkedIssue(
            key=issue["key"],
            summary=issue.get("fields", {}).get("summary", ""),
            status=issue.get("fields", {}).get("status", {}).get("name", "Unknown"),
            link_type=link_direction,
        )

    def _extract_text_from_adf(self, adf: dict[str, Any] | str | None) -> str | None:
        """Extract plain text from Atlassian Document Format.

        Jira v3 API returns descriptions and comments in ADF, a rich text format.
        This method recursively extracts the plain text content.

        Args:
            adf: The ADF document, a plain string, or None.

        Returns:
            Extracted text, or None if input is None.
        """
        if adf is None:
            return None

        if isinstance(adf, str):
            return adf

        def extract_from_node(node: dict[str, Any]) -> str:
            if node.get("type") == "text":
                return node.get("text", "")

            content = node.get("content", [])
            texts = [extract_from_node(child) for child in content]

            # Add newlines for block elements
            if node.get("type") in ("paragraph", "heading", "listItem"):
                return "".join(texts) + "\n"

            return "".join(texts)

        try:
            return extract_from_node(adf).strip()
        except Exception:
            logger.warning("Failed to parse ADF document")
            return None

    def _format_context_content(self, context: JiraTicketContext) -> str:
        """Format ticket context as markdown.

        Args:
            context: The full ticket context.

        Returns:
            A formatted markdown string.
        """
        parts: list[str] = []

        # Description
        parts.append(f"## Description\n{context.ticket.description or 'No description'}")

        # Details
        parts.append("\n## Details")
        parts.append(f"- **Status:** {context.ticket.status}")
        parts.append(f"- **Type:** {context.ticket.issue_type}")
        if context.ticket.priority:
            parts.append(f"- **Priority:** {context.ticket.priority}")
        if context.ticket.assignee:
            parts.append(f"- **Assignee:** {context.ticket.assignee.display_name}")
        if context.ticket.labels:
            parts.append(f"- **Labels:** {', '.join(context.ticket.labels)}")

        # Comments
        if context.comments:
            parts.append(f"\n## Comments ({len(context.comments)})")
            for comment in context.comments[:10]:  # Limit to 10
                date_str = comment.created[:10] if comment.created else "Unknown"
                parts.append(f"\n**{comment.author.display_name}** ({date_str}):")
                parts.append(comment.body)

        # Linked issues
        if context.linked_issues:
            parts.append(f"\n## Linked Issues ({len(context.linked_issues)})")
            for linked in context.linked_issues:
                parts.append(
                    f"- [{linked.key}] {linked.summary} ({linked.status}) - {linked.link_type}"
                )

        return "\n".join(parts)

    async def fetch_context(self, task_id: str) -> list[ContextData]:
        """Fetch context from a Jira issue.

        This is the main entry point for the adapter, implementing the
        Adapter interface.

        Args:
            task_id: The Jira issue key (e.g., 'PROJ-123').

        Returns:
            A list containing one ContextData item if found, empty list otherwise.
        """
        if not self._config.enabled:
            logger.debug("Jira adapter is disabled")
            return []

        context = await self.get_ticket_full_context(task_id)

        if context is None:
            return []

        content = self._format_context_content(context)

        return [
            ContextData(
                source=f"jira:{task_id}",
                source_type=self.source_type,
                title=f"[{task_id}] {context.ticket.summary}",
                content=content,
                metadata={
                    "status": context.ticket.status,
                    "assignee": (
                        context.ticket.assignee.display_name if context.ticket.assignee else None
                    ),
                    "priority": context.ticket.priority,
                    "labels": context.ticket.labels,
                    "comment_count": len(context.comments),
                    "linked_issue_count": len(context.linked_issues),
                },
            )
        ]

    async def health_check(self) -> bool:
        """Check if Jira is configured and accessible.

        Returns:
            True if healthy or disabled, False if there's an issue.
        """
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
