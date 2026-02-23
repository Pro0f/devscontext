"""Pydantic models for DevsContext.

This module contains all data models used throughout DevsContext.
All models use Pydantic BaseModel with Field() descriptions for
documentation and validation.

Models are organized by domain:
- Context models (ContextData, TaskContext)
- Jira models (JiraUser, JiraTicket, etc.)
- Fireflies models (Transcript, TranscriptExcerpt, etc.)
- Config models (moved to config.py for separation)
"""

from typing import Any

from pydantic import BaseModel, Field

# =============================================================================
# CONTEXT MODELS
# =============================================================================


class ContextData(BaseModel):
    """Structured context data from an adapter.

    This is the standard format that all adapters return. It represents
    a single piece of context (a ticket, a meeting excerpt, a doc section).
    """

    source: str = Field(
        ...,
        description="Source identifier (e.g., 'jira:PROJ-123', 'fireflies:meeting-id')",
    )
    source_type: str = Field(
        ...,
        description="Type of source (e.g., 'issue_tracker', 'meeting', 'documentation')",
    )
    title: str = Field(
        ...,
        description="Human-readable title for this context item",
    )
    content: str = Field(
        ...,
        description="The actual content/text of this context item",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata specific to the source type",
    )
    relevance_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Relevance score from 0.0 to 1.0 (1.0 = most relevant)",
    )


class TaskContextResult(BaseModel):
    """Result of fetching context for a task.

    Returned by ContextOrchestrator.get_task_context().
    """

    task_id: str = Field(
        ...,
        description="The task identifier that was queried",
    )
    context: str = Field(
        ...,
        description="Formatted context string ready for LLM consumption",
    )
    sources: list[str] = Field(
        default_factory=list,
        description="List of source identifiers that contributed to this context",
    )
    item_count: int = Field(
        default=0,
        ge=0,
        description="Number of context items found",
    )
    cached: bool = Field(
        default=False,
        description="Whether this result was served from cache",
    )


class SearchContextResult(BaseModel):
    """Result of searching across all sources.

    Returned by ContextOrchestrator.search_context().
    """

    query: str = Field(
        ...,
        description="The search query that was executed",
    )
    results: str = Field(
        ...,
        description="Formatted search results",
    )
    sources: list[str] = Field(
        default_factory=list,
        description="List of sources that were searched",
    )
    result_count: int = Field(
        default=0,
        ge=0,
        description="Number of results found",
    )


class StandardsResult(BaseModel):
    """Result of fetching coding standards.

    Returned by ContextOrchestrator.get_standards().
    """

    area: str | None = Field(
        default=None,
        description="The area filter that was applied (if any)",
    )
    content: str = Field(
        ...,
        description="The standards content",
    )


# =============================================================================
# JIRA MODELS
# =============================================================================


class JiraUser(BaseModel):
    """Jira user information."""

    display_name: str = Field(
        default="Unknown",
        description="User's display name",
    )
    email: str | None = Field(
        default=None,
        description="User's email address (may be hidden due to privacy settings)",
    )


class JiraComment(BaseModel):
    """A comment on a Jira ticket."""

    id: str = Field(
        ...,
        description="Unique comment ID",
    )
    author: JiraUser = Field(
        ...,
        description="User who wrote the comment",
    )
    body: str = Field(
        ...,
        description="Comment text content",
    )
    created: str = Field(
        ...,
        description="ISO timestamp when the comment was created",
    )


class JiraLinkedIssue(BaseModel):
    """A linked issue reference from a Jira ticket."""

    key: str = Field(
        ...,
        description="Issue key (e.g., 'PROJ-456')",
    )
    summary: str = Field(
        ...,
        description="Issue summary/title",
    )
    status: str = Field(
        ...,
        description="Current status of the linked issue",
    )
    link_type: str = Field(
        ...,
        description="Type of link (e.g., 'blocks', 'is blocked by', 'relates to')",
    )


class JiraTicket(BaseModel):
    """A Jira ticket with its core fields."""

    key: str = Field(
        ...,
        description="Issue key (e.g., 'PROJ-123')",
    )
    summary: str = Field(
        ...,
        description="Issue summary/title",
    )
    description: str | None = Field(
        default=None,
        description="Issue description (may be in ADF format, converted to plain text)",
    )
    status: str = Field(
        ...,
        description="Current status (e.g., 'To Do', 'In Progress', 'Done')",
    )
    priority: str | None = Field(
        default=None,
        description="Priority level (e.g., 'High', 'Medium', 'Low')",
    )
    assignee: JiraUser | None = Field(
        default=None,
        description="User assigned to this issue",
    )
    reporter: JiraUser | None = Field(
        default=None,
        description="User who reported this issue",
    )
    labels: list[str] = Field(
        default_factory=list,
        description="Labels attached to this issue",
    )
    issue_type: str = Field(
        default="Task",
        description="Issue type (e.g., 'Story', 'Bug', 'Task', 'Epic')",
    )
    created: str | None = Field(
        default=None,
        description="ISO timestamp when the issue was created",
    )
    updated: str | None = Field(
        default=None,
        description="ISO timestamp when the issue was last updated",
    )


class JiraTicketContext(BaseModel):
    """Full Jira ticket context including comments and linked issues.

    This is the complete context package for a single Jira ticket,
    assembled from multiple API calls.
    """

    ticket: JiraTicket = Field(
        ...,
        description="The main ticket details",
    )
    comments: list[JiraComment] = Field(
        default_factory=list,
        description="Comments on the ticket (most recent first)",
    )
    linked_issues: list[JiraLinkedIssue] = Field(
        default_factory=list,
        description="Issues linked to this ticket",
    )


# =============================================================================
# FIREFLIES MODELS
# =============================================================================


class TranscriptSpeaker(BaseModel):
    """A speaker in a Fireflies transcript."""

    name: str = Field(
        ...,
        description="Speaker's name as identified by Fireflies",
    )


class TranscriptExcerpt(BaseModel):
    """An excerpt from a Fireflies transcript relevant to a search."""

    text: str = Field(
        ...,
        description="The excerpt text",
    )
    speaker: str | None = Field(
        default=None,
        description="Speaker name if identified",
    )
    timestamp: str | None = Field(
        default=None,
        description="Timestamp within the meeting",
    )


class FirefliesTranscript(BaseModel):
    """A Fireflies meeting transcript."""

    id: str = Field(
        ...,
        description="Unique transcript ID",
    )
    title: str = Field(
        ...,
        description="Meeting title",
    )
    date: str = Field(
        ...,
        description="Meeting date (ISO format)",
    )
    duration_minutes: int | None = Field(
        default=None,
        ge=0,
        description="Meeting duration in minutes",
    )
    participants: list[str] = Field(
        default_factory=list,
        description="List of participant names",
    )
    summary: str | None = Field(
        default=None,
        description="AI-generated meeting summary",
    )
    action_items: list[str] = Field(
        default_factory=list,
        description="Action items extracted from the meeting",
    )
    excerpts: list[TranscriptExcerpt] = Field(
        default_factory=list,
        description="Relevant excerpts from the transcript",
    )


# =============================================================================
# LOCAL DOCS MODELS
# =============================================================================


class LocalDocument(BaseModel):
    """A local documentation file."""

    path: str = Field(
        ...,
        description="Relative path to the document",
    )
    title: str = Field(
        ...,
        description="Document title (from filename or H1)",
    )
    content: str = Field(
        ...,
        description="Document content",
    )
    last_modified: str | None = Field(
        default=None,
        description="ISO timestamp of last modification",
    )
