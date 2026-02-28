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

from datetime import UTC, datetime
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
    primary: bool = Field(
        default=True,
        description="Primary sources are fetched first, context shared with secondary sources",
    )


class FirefliesConfig(BaseModel):
    """Fireflies.ai adapter configuration."""

    api_key: str = Field(default="", description="Fireflies.ai API key (from env)")
    enabled: bool = Field(default=False, description="Whether adapter is enabled")
    primary: bool = Field(default=False, description="Whether this is a primary source")


class RagConfig(BaseModel):
    """RAG configuration for embedding-based doc search.

    When enabled, the LocalDocsAdapter uses semantic similarity (embeddings)
    instead of keyword matching for finding relevant documentation sections.

    Requires: pip install devscontext[rag]
    """

    enabled: bool = Field(default=False, description="Enable RAG for doc matching")
    embedding_provider: Literal["local", "openai", "ollama"] = Field(
        default="local",
        description="Embedding provider (local=sentence-transformers, openai, ollama)",
    )
    embedding_model: str = Field(
        default="all-MiniLM-L6-v2",
        description="Model for generating embeddings",
    )
    index_path: str = Field(
        default=".devscontext/doc_index.json",
        description="Path to the embedding index file",
    )
    top_k: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Number of similar sections to retrieve",
    )
    similarity_threshold: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score (0-1) for results",
    )


class DocsConfig(BaseModel):
    """Local documentation adapter configuration."""

    paths: list[str] = Field(
        default_factory=lambda: ["./docs/"],
        description="Paths to documentation directories",
    )
    standards_path: str | None = Field(default=None, description="Path to coding standards docs")
    architecture_path: str | None = Field(default=None, description="Path to architecture docs")
    enabled: bool = Field(default=True, description="Whether adapter is enabled")
    primary: bool = Field(default=False, description="Whether this is a primary source")
    rag: RagConfig | None = Field(default=None, description="Optional RAG configuration")


class SlackConfig(BaseModel):
    """Slack adapter configuration."""

    bot_token: str = Field(default="", description="Slack bot token (from env)")
    channels: list[str] = Field(
        default_factory=list,
        description="Channel names to search (e.g., ['engineering', 'payments-team'])",
    )
    include_threads: bool = Field(default=True, description="Fetch full threads for matches")
    max_messages: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Max messages to return per search",
    )
    lookback_days: int = Field(
        default=30,
        ge=1,
        le=90,
        description="Days to look back when searching",
    )
    enabled: bool = Field(default=False, description="Whether adapter is enabled")
    primary: bool = Field(default=False, description="Whether this is a primary source")


class GmailConfig(BaseModel):
    """Gmail adapter configuration."""

    credentials_path: str = Field(
        default="",
        description="Path to OAuth2 credentials JSON (from env)",
    )
    token_path: str = Field(
        default=".devscontext/gmail_token.json",
        description="Path to store OAuth2 refresh token",
    )
    search_scope: str = Field(
        default="newer_than:30d",
        description="Gmail search scope filter",
    )
    max_results: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Max emails to return",
    )
    labels: list[str] = Field(
        default_factory=lambda: ["INBOX"],
        description="Labels to search within",
    )
    enabled: bool = Field(default=False, description="Whether adapter is enabled")
    primary: bool = Field(default=False, description="Whether this is a primary source")


class GitHubConfig(BaseModel):
    """GitHub adapter configuration."""

    token: str = Field(default="", description="GitHub Personal Access Token (from env)")
    repos: list[str] = Field(
        default_factory=list,
        description="Repositories to search (e.g., ['org/repo-name'])",
    )
    recent_pr_days: int = Field(
        default=14,
        ge=1,
        le=90,
        description="Days to look back for recent PRs",
    )
    max_prs: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum PRs to return",
    )
    enabled: bool = Field(default=False, description="Whether adapter is enabled")
    primary: bool = Field(default=False, description="Whether this is a primary source")


class SynthesisConfig(BaseModel):
    """Synthesis configuration supporting multiple synthesis plugins."""

    plugin: Literal["llm", "template", "passthrough"] = Field(
        default="llm",
        description="Synthesis plugin to use (llm, template, passthrough)",
    )
    provider: Literal["anthropic", "openai", "ollama"] = Field(
        default="anthropic",
        description="LLM provider for synthesis (only used when plugin=llm)",
    )
    model: str = Field(default="claude-haiku-4-5", description="Model name/ID to use")
    api_key: str | None = Field(default=None, description="API key for the provider (from env)")
    max_output_tokens: int = Field(
        default=3000,
        ge=100,
        le=10000,
        description="Maximum tokens in synthesized output",
    )
    temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="Temperature for LLM generation",
    )
    prompt_template: str | None = Field(
        default=None,
        description="Path to custom prompt template file (optional)",
    )
    template_path: str | None = Field(
        default=None,
        description="Path to Jinja2 template (only used when plugin=template)",
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


class AgentTriggerConfig(BaseModel):
    """Configuration for how the pre-processing agent is triggered."""

    type: Literal["polling"] = Field(
        default="polling",
        description="Trigger type (polling or webhook in future)",
    )
    poll_interval_minutes: int = Field(
        default=5,
        ge=1,
        le=60,
        description="How often to poll Jira for ready tickets",
    )


class PreprocessorConfig(BaseModel):
    """Configuration for the pre-processing agent."""

    enabled: bool = Field(default=False, description="Whether agent is enabled")
    trigger: AgentTriggerConfig = Field(default_factory=AgentTriggerConfig)
    jira_status: str = Field(
        default="Ready for Development",
        description="Jira status that triggers pre-processing",
    )
    jira_project: str | list[str] = Field(
        default="",
        description="Project key(s) to watch (e.g., 'PROJ' or ['PROJ', 'TEAM'])",
    )
    context_ttl_hours: int = Field(
        default=24,
        ge=1,
        le=168,
        description="How long pre-built context is valid",
    )


class AgentsConfig(BaseModel):
    """Configuration for background agents."""

    preprocessor: PreprocessorConfig = Field(default_factory=PreprocessorConfig)


class StorageConfig(BaseModel):
    """Configuration for persistent storage."""

    path: str = Field(
        default=".devscontext/cache.db",
        description="Path to SQLite database for pre-built context",
    )


class SourcesConfig(BaseModel):
    """Configuration for all data sources."""

    jira: JiraConfig = Field(default_factory=JiraConfig)
    fireflies: FirefliesConfig = Field(default_factory=FirefliesConfig)
    docs: DocsConfig = Field(default_factory=DocsConfig)
    slack: SlackConfig = Field(default_factory=SlackConfig)
    gmail: GmailConfig = Field(default_factory=GmailConfig)
    github: GitHubConfig = Field(default_factory=GitHubConfig)


class DevsContextConfig(BaseModel):
    """Root configuration for DevsContext."""

    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    synthesis: SynthesisConfig = Field(default_factory=SynthesisConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)


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
# SLACK DATA MODELS
# =============================================================================


class SlackMessage(BaseModel):
    """A single Slack message."""

    message_id: str = Field(..., description="Slack message timestamp (ts)")
    channel_id: str = Field(..., description="Channel ID where message was posted")
    channel_name: str = Field(..., description="Channel name (human readable)")
    user_id: str = Field(..., description="User ID who sent the message")
    user_name: str = Field(..., description="User display name")
    text: str = Field(..., description="Message text content")
    timestamp: datetime = Field(..., description="When message was sent (UTC)")
    thread_ts: str | None = Field(default=None, description="Parent thread timestamp if reply")
    permalink: str | None = Field(default=None, description="Permalink to the message")
    reactions: list[str] = Field(default_factory=list, description="Reaction emojis on message")


class SlackThread(BaseModel):
    """A Slack thread with parent message and replies."""

    parent_message: SlackMessage = Field(..., description="The thread's parent message")
    replies: list[SlackMessage] = Field(default_factory=list, description="Reply messages")
    participant_names: list[str] = Field(default_factory=list, description="Unique participants")
    decisions: list[str] = Field(default_factory=list, description="Decisions identified in thread")
    action_items: list[str] = Field(default_factory=list, description="Action items from thread")


class SlackContext(BaseModel):
    """All Slack context found for a task."""

    threads: list[SlackThread] = Field(default_factory=list, description="Relevant threads")
    standalone_messages: list[SlackMessage] = Field(
        default_factory=list,
        description="Relevant messages not in threads",
    )


# =============================================================================
# GMAIL DATA MODELS
# =============================================================================


class GmailMessage(BaseModel):
    """A single Gmail message."""

    message_id: str = Field(..., description="Gmail message ID")
    thread_id: str = Field(..., description="Gmail thread/conversation ID")
    subject: str = Field(..., description="Email subject line")
    sender: str = Field(..., description="Sender email address")
    sender_name: str | None = Field(default=None, description="Sender display name")
    recipients: list[str] = Field(default_factory=list, description="To recipients")
    cc: list[str] = Field(default_factory=list, description="CC recipients")
    date: datetime = Field(..., description="When email was sent (UTC)")
    snippet: str = Field(default="", description="Short preview of email body")
    body_text: str = Field(default="", description="Plain text body content")
    labels: list[str] = Field(default_factory=list, description="Gmail labels")


class GmailThread(BaseModel):
    """A Gmail conversation thread."""

    thread_id: str = Field(..., description="Gmail thread ID")
    subject: str = Field(..., description="Thread subject (from first message)")
    messages: list[GmailMessage] = Field(default_factory=list, description="Messages in thread")
    participants: list[str] = Field(default_factory=list, description="All participants")
    latest_date: datetime = Field(..., description="Most recent message date")


class GmailContext(BaseModel):
    """All Gmail context found for a task."""

    threads: list[GmailThread] = Field(default_factory=list, description="Relevant email threads")


# =============================================================================
# GITHUB DATA MODELS
# =============================================================================


class GitHubReviewComment(BaseModel):
    """A review comment on a GitHub PR."""

    author: str = Field(..., description="Comment author's GitHub username")
    body: str = Field(..., description="Comment text content")
    path: str | None = Field(default=None, description="File path the comment is on")
    created_at: datetime = Field(..., description="When comment was created (UTC)")


class GitHubPR(BaseModel):
    """A GitHub Pull Request."""

    number: int = Field(..., description="PR number")
    title: str = Field(..., description="PR title")
    author: str = Field(..., description="PR author's GitHub username")
    state: str = Field(..., description="PR state (open, closed, merged)")
    url: str = Field(..., description="URL to the PR")
    created_at: datetime = Field(..., description="When PR was created (UTC)")
    merged_at: datetime | None = Field(default=None, description="When PR was merged (UTC)")
    changed_files: list[str] = Field(default_factory=list, description="List of changed file paths")
    review_comments: list[GitHubReviewComment] = Field(
        default_factory=list, description="Review comments on the PR"
    )
    body: str | None = Field(default=None, description="PR description")


class GitHubIssue(BaseModel):
    """A GitHub Issue."""

    number: int = Field(..., description="Issue number")
    title: str = Field(..., description="Issue title")
    author: str = Field(..., description="Issue author's GitHub username")
    state: str = Field(..., description="Issue state (open, closed)")
    url: str = Field(..., description="URL to the issue")
    created_at: datetime = Field(..., description="When issue was created (UTC)")
    labels: list[str] = Field(default_factory=list, description="Labels on the issue")
    body: str | None = Field(default=None, description="Issue description")


class GitHubContext(BaseModel):
    """All GitHub context found for a task."""

    related_prs: list[GitHubPR] = Field(
        default_factory=list, description="PRs that mention the ticket or touch same files"
    )
    recent_prs: list[GitHubPR] = Field(
        default_factory=list, description="Recent merged PRs in the same service area"
    )
    related_issues: list[GitHubIssue] = Field(
        default_factory=list, description="Issues that mention the ticket"
    )


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
    cached: bool = Field(default=False, description="Whether served from in-memory cache")
    prebuilt: bool = Field(default=False, description="Whether served from pre-built storage")


class PrebuiltContext(BaseModel):
    """Pre-built context stored in SQLite for instant retrieval."""

    task_id: str = Field(..., description="Task identifier (e.g., 'PROJ-123')")
    synthesized: str = Field(..., description="Synthesized markdown context")
    sources_used: list[str] = Field(default_factory=list, description="Sources that contributed")
    context_quality_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Quality score based on context completeness (0-1)",
    )
    gaps: list[str] = Field(
        default_factory=list,
        description="Identified gaps (e.g., 'No acceptance criteria')",
    )
    built_at: datetime = Field(..., description="When context was built (UTC)")
    expires_at: datetime = Field(..., description="When context expires (UTC)")
    source_data_hash: str = Field(
        ...,
        description="Hash of Jira ticket.updated for staleness detection",
    )

    def is_expired(self) -> bool:
        """Check if this pre-built context has expired."""
        return datetime.now(UTC) > self.expires_at


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
