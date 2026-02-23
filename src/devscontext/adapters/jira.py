"""Jira adapter for fetching issue context."""

import asyncio
import logging
from typing import Any

import httpx
from pydantic import BaseModel

from devscontext.adapters.base import Adapter, ContextData
from devscontext.config import JiraConfig

logger = logging.getLogger(__name__)


class JiraUser(BaseModel):
    """Jira user model."""

    display_name: str = "Unknown"
    email: str | None = None


class JiraComment(BaseModel):
    """Jira comment model."""

    id: str
    author: JiraUser
    body: str
    created: str


class JiraLinkedIssue(BaseModel):
    """Jira linked issue model."""

    key: str
    summary: str
    status: str
    link_type: str


class JiraTicket(BaseModel):
    """Jira ticket model."""

    key: str
    summary: str
    description: str | None = None
    status: str
    priority: str | None = None
    assignee: JiraUser | None = None
    reporter: JiraUser | None = None
    labels: list[str] = []
    issue_type: str = "Task"
    created: str | None = None
    updated: str | None = None


class JiraTicketContext(BaseModel):
    """Full Jira ticket context including comments and linked issues."""

    ticket: JiraTicket
    comments: list[JiraComment] = []
    linked_issues: list[JiraLinkedIssue] = []


class JiraAdapter(Adapter):
    """Adapter for fetching context from Jira issues."""

    def __init__(self, config: JiraConfig) -> None:
        """Initialize the Jira adapter.

        Args:
            config: Jira configuration.
        """
        self._config = config
        self._client: httpx.AsyncClient | None = None

    @property
    def name(self) -> str:
        return "jira"

    @property
    def source_type(self) -> str:
        return "issue_tracker"

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._config.base_url.rstrip("/"),
                auth=(self._config.email, self._config.api_token),
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    async def _close_client(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get_ticket(self, ticket_id: str) -> JiraTicket | None:
        """Fetch ticket details from Jira.

        Args:
            ticket_id: The Jira issue key (e.g., PROJ-123).

        Returns:
            JiraTicket or None if not found/error.
        """
        try:
            client = self._get_client()
            response = await client.get(
                f"/rest/api/3/issue/{ticket_id}",
                params={
                    "fields": "summary,description,status,priority,assignee,reporter,labels,issuetype,created,updated"
                },
            )
            response.raise_for_status()
            data = response.json()

            fields = data.get("fields", {})

            # Extract assignee
            assignee = None
            if fields.get("assignee"):
                assignee = JiraUser(
                    display_name=fields["assignee"].get("displayName", "Unknown"),
                    email=fields["assignee"].get("emailAddress"),
                )

            # Extract reporter
            reporter = None
            if fields.get("reporter"):
                reporter = JiraUser(
                    display_name=fields["reporter"].get("displayName", "Unknown"),
                    email=fields["reporter"].get("emailAddress"),
                )

            # Extract description (handle Atlassian Document Format)
            description = self._extract_text_from_adf(fields.get("description"))

            return JiraTicket(
                key=data["key"],
                summary=fields.get("summary", ""),
                description=description,
                status=fields.get("status", {}).get("name", "Unknown"),
                priority=fields.get("priority", {}).get("name") if fields.get("priority") else None,
                assignee=assignee,
                reporter=reporter,
                labels=fields.get("labels", []),
                issue_type=fields.get("issuetype", {}).get("name", "Task"),
                created=fields.get("created"),
                updated=fields.get("updated"),
            )

        except httpx.HTTPStatusError as e:
            logger.warning(f"Failed to fetch ticket {ticket_id}: {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"Error fetching ticket {ticket_id}: {e}")
            return None

    async def get_comments(self, ticket_id: str) -> list[JiraComment]:
        """Fetch comments for a Jira ticket.

        Args:
            ticket_id: The Jira issue key.

        Returns:
            List of comments.
        """
        try:
            client = self._get_client()
            response = await client.get(
                f"/rest/api/3/issue/{ticket_id}/comment",
                params={"maxResults": 50, "orderBy": "-created"},
            )
            response.raise_for_status()
            data = response.json()

            comments = []
            for comment_data in data.get("comments", []):
                author = comment_data.get("author", {})
                body = self._extract_text_from_adf(comment_data.get("body"))

                comments.append(
                    JiraComment(
                        id=comment_data["id"],
                        author=JiraUser(
                            display_name=author.get("displayName", "Unknown"),
                            email=author.get("emailAddress"),
                        ),
                        body=body or "",
                        created=comment_data.get("created", ""),
                    )
                )

            return comments

        except httpx.HTTPStatusError as e:
            logger.warning(f"Failed to fetch comments for {ticket_id}: {e.response.status_code}")
            return []
        except Exception as e:
            logger.error(f"Error fetching comments for {ticket_id}: {e}")
            return []

    async def get_linked_issues(self, ticket_id: str) -> list[JiraLinkedIssue]:
        """Fetch linked issues for a Jira ticket.

        Args:
            ticket_id: The Jira issue key.

        Returns:
            List of linked issues with summary and status.
        """
        try:
            client = self._get_client()
            response = await client.get(
                f"/rest/api/3/issue/{ticket_id}",
                params={"fields": "issuelinks"},
            )
            response.raise_for_status()
            data = response.json()

            linked_issues = []
            for link in data.get("fields", {}).get("issuelinks", []):
                link_type = link.get("type", {}).get("name", "Related")

                # Handle both inward and outward links
                if "outwardIssue" in link:
                    issue = link["outwardIssue"]
                    link_direction = link.get("type", {}).get("outward", link_type)
                elif "inwardIssue" in link:
                    issue = link["inwardIssue"]
                    link_direction = link.get("type", {}).get("inward", link_type)
                else:
                    continue

                linked_issues.append(
                    JiraLinkedIssue(
                        key=issue["key"],
                        summary=issue.get("fields", {}).get("summary", ""),
                        status=issue.get("fields", {}).get("status", {}).get("name", "Unknown"),
                        link_type=link_direction,
                    )
                )

            return linked_issues

        except httpx.HTTPStatusError as e:
            logger.warning(f"Failed to fetch linked issues for {ticket_id}: {e.response.status_code}")
            return []
        except Exception as e:
            logger.error(f"Error fetching linked issues for {ticket_id}: {e}")
            return []

    async def get_ticket_full_context(self, ticket_id: str) -> JiraTicketContext | None:
        """Fetch full context for a Jira ticket including comments and linked issues.

        All requests are made in parallel using asyncio.gather.

        Args:
            ticket_id: The Jira issue key.

        Returns:
            Full ticket context or None if ticket not found.
        """
        # Fetch all data in parallel
        ticket, comments, linked_issues = await asyncio.gather(
            self.get_ticket(ticket_id),
            self.get_comments(ticket_id),
            self.get_linked_issues(ticket_id),
            return_exceptions=True,
        )

        # Handle exceptions from gather
        if isinstance(ticket, Exception):
            logger.error(f"Error fetching ticket: {ticket}")
            ticket = None
        if isinstance(comments, Exception):
            logger.error(f"Error fetching comments: {comments}")
            comments = []
        if isinstance(linked_issues, Exception):
            logger.error(f"Error fetching linked issues: {linked_issues}")
            linked_issues = []

        if ticket is None:
            return None

        return JiraTicketContext(
            ticket=ticket,
            comments=comments,  # type: ignore
            linked_issues=linked_issues,  # type: ignore
        )

    def _extract_text_from_adf(self, adf: dict[str, Any] | None) -> str | None:
        """Extract plain text from Atlassian Document Format.

        Args:
            adf: The ADF document.

        Returns:
            Extracted text or None.
        """
        if adf is None:
            return None

        if isinstance(adf, str):
            return adf

        def extract_from_node(node: dict[str, Any]) -> str:
            """Recursively extract text from an ADF node."""
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
            return None

    async def fetch_context(self, task_id: str) -> list[ContextData]:
        """Fetch context from a Jira issue.

        Args:
            task_id: The Jira issue key (e.g., PROJ-123).

        Returns:
            List of context data from the issue.
        """
        if not self._config.enabled:
            return []

        context = await self.get_ticket_full_context(task_id)

        if context is None:
            return []

        # Format the context as markdown
        content_parts = []

        # Ticket details
        content_parts.append(f"## Description\n{context.ticket.description or 'No description'}")

        content_parts.append(f"\n## Details")
        content_parts.append(f"- **Status:** {context.ticket.status}")
        content_parts.append(f"- **Type:** {context.ticket.issue_type}")
        if context.ticket.priority:
            content_parts.append(f"- **Priority:** {context.ticket.priority}")
        if context.ticket.assignee:
            content_parts.append(f"- **Assignee:** {context.ticket.assignee.display_name}")
        if context.ticket.labels:
            content_parts.append(f"- **Labels:** {', '.join(context.ticket.labels)}")

        # Comments
        if context.comments:
            content_parts.append(f"\n## Comments ({len(context.comments)})")
            for comment in context.comments[:10]:  # Limit to 10 most recent
                content_parts.append(f"\n**{comment.author.display_name}** ({comment.created[:10]}):")
                content_parts.append(comment.body)

        # Linked issues
        if context.linked_issues:
            content_parts.append(f"\n## Linked Issues ({len(context.linked_issues)})")
            for linked in context.linked_issues:
                content_parts.append(f"- [{linked.key}] {linked.summary} ({linked.status}) - {linked.link_type}")

        return [
            ContextData(
                source=f"jira:{task_id}",
                source_type=self.source_type,
                title=f"[{task_id}] {context.ticket.summary}",
                content="\n".join(content_parts),
                metadata={
                    "status": context.ticket.status,
                    "assignee": context.ticket.assignee.display_name if context.ticket.assignee else None,
                    "priority": context.ticket.priority,
                    "labels": context.ticket.labels,
                    "comment_count": len(context.comments),
                    "linked_issue_count": len(context.linked_issues),
                },
            )
        ]

    async def health_check(self) -> bool:
        """Check if Jira is configured and accessible."""
        if not self._config.enabled:
            return True  # Not enabled is fine

        if not (self._config.base_url and self._config.email and self._config.api_token):
            return False

        try:
            client = self._get_client()
            response = await client.get("/rest/api/3/myself")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Jira health check failed: {e}")
            return False
