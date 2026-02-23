"""Pydantic models for DevsContext.

This module contains all data models used throughout DevsContext.
All models use Pydantic BaseModel with Field() descriptions for
documentation and validation.

Models are organized by domain:
- Config models (JiraConfig, FirefliesConfig, DocsConfig, etc.)
- Jira data models (JiraTicket, JiraComment, LinkedIssue, JiraContext)
- Meeting data models (MeetingExcerpt, MeetingContext)
- Documentation models (DocSection, DocsContext)
- Result models (TaskContext, ContextData)

All datetime fields use timezone-aware UTC datetimes.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - Required at runtime for Pydantic
from typing import Any, Literal

from pydantic import BaseModel, Field

# =============================================================================
# CONFIG MODELS
# =============================================================================


class JiraConfig(BaseModel):
    """Jira adapter configuration."""

    base_url: str = Field(default="", description="Jira instance URL")
    email: str = Field(default="", description="Jira authentication email")
    api_token: str = Field(default="", description="Jira API token (from env)")
    project: str = Field(default="", description="Default Jira project key")
    enabled: bool = Field(default=False, description="Whether adapter is enabled")


class FirefliesConfig(BaseModel):
    """Fireflies.ai adapter configuration."""

    api_key: str = Field(default="", description="Fireflies.ai API key (from env)")
    enabled: bool = Field(default=False, description="Whether adapter is enabled")


class DocsConfig(BaseModel):
    """Local documentation adapter configuration."""

    paths: list[str] = Field(
        default_factory=lambda: ["./docs/"],
        description="Paths to documentation directories",
    )
    standards_path: str | None = Field(default=None, description="Path to coding standards docs")
    architecture_path: str | None = Field(default=None, description="Path to architecture docs")
    enabled: bool = Field(default=True, description="Whether adapter is enabled")


class SynthesisConfig(BaseModel):
    """LLM synthesis configuration."""

    provider: Literal["anthropic", "openai", "ollama"] = Field(
        default="anthropic",
        description="LLM provider for synthesis",
    )
    model: str = Field(default="claude-haiku-4-5", description="Model name/ID to use")
    api_key: str | None = Field(default=None, description="API key for the provider (from env)")
    max_output_tokens: int = Field(
        default=3000,
        ge=100,
        le=10000,
        description="Maximum tokens in synthesized output",
    )


class CacheConfig(BaseModel):
    """Cache configuration."""

    enabled: bool = Field(default=True, description="Whether caching is enabled")
    ttl_minutes: int = Field(default=15, ge=1, le=1440, description="Cache entry TTL in minutes")
    max_size: int = Field(default=100, ge=1, description="Maximum cache entries")

    @property
    def ttl_seconds(self) -> int:
        """Return TTL in seconds for compatibility."""
        return self.ttl_minutes * 60


class SourcesConfig(BaseModel):
    """Configuration for all data sources."""

    jira: JiraConfig = Field(default_factory=JiraConfig)
    fireflies: FirefliesConfig = Field(default_factory=FirefliesConfig)
    docs: DocsConfig = Field(default_factory=DocsConfig)


class DevsContextConfig(BaseModel):
    """Root configuration for DevsContext."""

    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    synthesis: SynthesisConfig = Field(default_factory=SynthesisConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)


# =============================================================================
# JIRA DATA MODELS
# =============================================================================


class JiraTicket(BaseModel):
    """A Jira ticket with its core fields."""

    ticket_id: str = Field(..., description="Issue key (e.g., 'PROJ-123')")
    title: str = Field(..., description="Issue summary/title")
    description: str | None = Field(default=None, description="Issue description text")
    status: str = Field(..., description="Current status (e.g., 'In Progress')")
    assignee: str | None = Field(default=None, description="Assigned user's display name")
    labels: list[str] = Field(default_factory=list, description="Labels on this issue")
    components: list[str] = Field(default_factory=list, description="Components")
    acceptance_criteria: str | None = Field(default=None, description="Acceptance criteria")
    story_points: float | None = Field(default=None, ge=0, description="Story points estimate")
    sprint: str | None = Field(default=None, description="Current sprint name")
    created: datetime = Field(..., description="When issue was created (UTC)")
    updated: datetime = Field(..., description="When issue was last updated (UTC)")


class JiraComment(BaseModel):
    """A comment on a Jira ticket."""

    author: str = Field(..., description="Comment author's display name")
    body: str = Field(..., description="Comment text content")
    created: datetime = Field(..., description="When comment was created (UTC)")


class LinkedIssue(BaseModel):
    """A linked issue reference from a Jira ticket."""

    ticket_id: str = Field(..., description="Issue key (e.g., 'PROJ-456')")
    title: str = Field(..., description="Issue summary/title")
    status: str = Field(..., description="Current status of linked issue")
    link_type: str = Field(
        ...,
        description="Link type (e.g., 'blocks', 'is blocked by', 'relates to')",
    )


class JiraContext(BaseModel):
    """Complete Jira context for a ticket."""

    ticket: JiraTicket = Field(..., description="The main ticket details")
    comments: list[JiraComment] = Field(default_factory=list, description="Comments")
    linked_issues: list[LinkedIssue] = Field(default_factory=list, description="Linked issues")


# =============================================================================
# MEETING DATA MODELS
# =============================================================================


class MeetingExcerpt(BaseModel):
    """Relevant excerpt from a meeting transcript."""

    meeting_title: str = Field(..., description="Title of the meeting")
    meeting_date: datetime = Field(..., description="When the meeting occurred (UTC)")
    participants: list[str] = Field(default_factory=list, description="Participant names")
    excerpt: str = Field(..., description="Relevant portion of transcript")
    action_items: list[str] = Field(default_factory=list, description="Action items extracted")
    decisions: list[str] = Field(default_factory=list, description="Decisions made")


class MeetingContext(BaseModel):
    """All meeting context found for a task."""

    meetings: list[MeetingExcerpt] = Field(default_factory=list, description="Meeting excerpts")


# =============================================================================
# DOCUMENTATION MODELS
# =============================================================================


class DocSection(BaseModel):
    """A relevant section from a local document."""

    file_path: str = Field(..., description="Path to the document file")
    section_title: str | None = Field(default=None, description="Section title if identifiable")
    content: str = Field(..., description="The section content")
    doc_type: Literal["architecture", "standards", "adr", "other"] = Field(
        default="other",
        description="Type of documentation",
    )


class DocsContext(BaseModel):
    """All relevant documentation found for a task."""

    sections: list[DocSection] = Field(default_factory=list, description="Document sections")


# =============================================================================
# RESULT MODELS
# =============================================================================


class TaskContext(BaseModel):
    """The final synthesized context returned to the AI agent."""

    task_id: str = Field(..., description="The task identifier that was queried")
    synthesized: str = Field(..., description="LLM-generated structured markdown synthesis")
    sources_used: list[str] = Field(default_factory=list, description="Sources that contributed")
    fetch_duration_ms: int = Field(..., ge=0, description="How long the fetch took (ms)")
    synthesized_at: datetime = Field(..., description="When context was synthesized (UTC)")
    cached: bool = Field(default=False, description="Whether served from cache")


class ContextData(BaseModel):
    """Structured context data from an adapter."""

    source: str = Field(..., description="Source identifier (e.g., 'jira:PROJ-123')")
    source_type: str = Field(..., description="Type of source (e.g., 'issue_tracker')")
    title: str = Field(..., description="Human-readable title for this context item")
    content: str = Field(..., description="The actual content/text of this context item")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    relevance_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Relevance score from 0.0 to 1.0",
    )
