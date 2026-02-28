"""Context synthesis - LLM-based synthesis of context from multiple sources.

This module provides the LLMSynthesisPlugin class that uses an LLM to combine
raw data from adapters into a structured, concise context block suitable
for AI coding assistants.

Supported providers:
- anthropic: Claude models via the Anthropic SDK
- openai: GPT models via the OpenAI SDK
- ollama: Local models via Ollama HTTP API

This module implements the SynthesisPlugin interface for the plugin system.

Example:
    config = SynthesisConfig(provider="anthropic", model="claude-haiku-4-5")
    plugin = LLMSynthesisPlugin(config)
    result = await plugin.synthesize(
        task_id="PROJ-123",
        source_contexts={"jira": jira_ctx, "fireflies": meeting_ctx, "local_docs": docs_ctx},
    )
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar

import httpx

from devscontext.constants import DEFAULT_HTTP_TIMEOUT_SECONDS
from devscontext.logging import get_logger
from devscontext.models import SynthesisConfig
from devscontext.plugins.base import SourceContext, SynthesisPlugin

if TYPE_CHECKING:
    from devscontext.models import (
        DocsContext,
        GitHubContext,
        GmailContext,
        JiraContext,
        MeetingContext,
        SlackContext,
    )

logger = get_logger(__name__)

# =============================================================================
# SYNTHESIS PROMPT
# =============================================================================

SYNTHESIS_PROMPT = """
You are a senior engineer preparing context for a colleague about to start
working on a task with an AI coding assistant.

Your job: combine the raw data below into a concise, structured context block
that gives the AI agent everything it needs to write correct, well-integrated code.

Rules:
- Target 2000-3000 tokens. Be concise but don't omit important details.
- Use these sections (skip any section with no relevant data):
  ## Task: {task_id} — {title}
  ### Requirements
  ### Key Decisions
  ### Team Discussions
  ### External Context
  ### Architecture Context
  ### Coding Standards
  ### Related Work
- For each fact, note the source in [brackets] at the end of the paragraph.
- If sources conflict, note the conflict explicitly.
- Extract acceptance criteria clearly as a checklist if available.
- For decisions from meetings, include WHO decided and WHEN.
- Do NOT include generic advice. Only include specific, actionable context.

Section-specific guidance:

### Requirements
- Extract from Jira ticket description and acceptance criteria
- Present as numbered list or checklist
- Include any constraints mentioned in comments

### Key Decisions
- Extract from meeting transcripts and formal decision records
- Include WHO made the decision, WHEN, and WHY
- Focus on technical decisions that affect implementation
- Distinguish from informal team discussions

### Team Discussions
- Extract from Slack threads and informal communications
- Focus on clarifications, feedback, and informal agreements
- Note any concerns or open questions raised
- Include action items assigned to team members
- Mark as [Slack] to distinguish from formal decisions

### External Context
- Extract from email threads with stakeholders or customers
- Focus on requirements clarifications from product/business
- Include customer feedback or constraints
- Note any deadlines or commitments mentioned
- Mark as [Email] to distinguish from internal discussions

### Architecture Context
- Focus on ACTIONABLE details from architecture docs:
  - Exact file paths where code should be added/modified
  - Data flow and integration points
  - Database tables and schemas involved
  - Queue names, API endpoints, external services
- Do NOT include general architectural overview

### Coding Standards
- Extract SPECIFIC rules that apply to this task:
  - Error handling patterns (e.g., "use Result<T,E>, don't throw")
  - Naming conventions for this codebase
  - Testing requirements (what needs tests, mocking strategy)
  - Async patterns to follow
- Do NOT include generic advice like "write clean code"

### Recent Changes
- Extract from GitHub PRs that touch the same files or service area
- Keep brief — just the relevant PRs, not every recent merge
- Include reviewer comments only if relevant to current task
- Focus on patterns from recent PRs (what conventions to follow)
- Note any files recently changed (avoid merge conflicts)
- Mark as [GitHub PR #N] for source attribution

### Related Work
- Linked tickets and their status
- Similar past implementations to reference

Raw data:
---
{raw_data}
---
"""


# =============================================================================
# LLM PROVIDER INTERFACE
# =============================================================================


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def generate(self, prompt: str, max_tokens: int) -> str:
        """Generate a response from the LLM.

        Args:
            prompt: The prompt to send to the LLM.
            max_tokens: Maximum tokens in the response.

        Returns:
            The generated text.

        Raises:
            Exception: If generation fails.
        """
        ...


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider."""

    def __init__(self, api_key: str, model: str) -> None:
        """Initialize the Anthropic provider."""
        self._api_key = api_key
        self._model = model
        self._client: Any = None

    def _get_client(self) -> Any:
        """Get or create the Anthropic client."""
        if self._client is None:
            try:
                from anthropic import AsyncAnthropic  # type: ignore[import-not-found]
            except ImportError as e:
                raise ImportError(
                    "anthropic package not installed. "
                    "Install with: pip install devscontext[anthropic]"
                ) from e
            self._client = AsyncAnthropic(api_key=self._api_key)
        return self._client

    async def generate(self, prompt: str, max_tokens: int) -> str:
        """Generate using Claude."""
        client = self._get_client()
        response = await client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return str(response.content[0].text)


class OpenAIProvider(LLMProvider):
    """OpenAI GPT provider."""

    def __init__(self, api_key: str, model: str) -> None:
        """Initialize the OpenAI provider."""
        self._api_key = api_key
        self._model = model
        self._client: Any = None

    def _get_client(self) -> Any:
        """Get or create the OpenAI client."""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as e:
                raise ImportError(
                    "openai package not installed. Install with: pip install devscontext[openai]"
                ) from e
            self._client = AsyncOpenAI(api_key=self._api_key)
        return self._client

    async def generate(self, prompt: str, max_tokens: int) -> str:
        """Generate using GPT."""
        client = self._get_client()
        response = await client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content or ""


class OllamaProvider(LLMProvider):
    """Ollama local provider."""

    def __init__(self, model: str, base_url: str = "http://localhost:11434") -> None:
        """Initialize the Ollama provider."""
        self._model = model
        self._base_url = base_url
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=DEFAULT_HTTP_TIMEOUT_SECONDS * 2,  # Ollama can be slower
            )
        return self._client

    async def generate(self, prompt: str, max_tokens: int) -> str:
        """Generate using Ollama."""
        client = self._get_client()
        response = await client.post(
            "/api/generate",
            json={
                "model": self._model,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": max_tokens},
            },
        )
        response.raise_for_status()
        data = response.json()
        return str(data.get("response", ""))


def create_provider(config: SynthesisConfig) -> LLMProvider:
    """Factory function to create the appropriate LLM provider.

    Args:
        config: Synthesis configuration with provider and model settings.

    Returns:
        An LLMProvider instance.

    Raises:
        ValueError: If provider is not supported or API key is missing.
    """
    if config.provider == "anthropic":
        if not config.api_key:
            raise ValueError("Anthropic API key required for synthesis")
        return AnthropicProvider(api_key=config.api_key, model=config.model)

    elif config.provider == "openai":
        if not config.api_key:
            raise ValueError("OpenAI API key required for synthesis")
        return OpenAIProvider(api_key=config.api_key, model=config.model)

    elif config.provider == "ollama":
        return OllamaProvider(model=config.model)

    else:
        raise ValueError(f"Unsupported synthesis provider: {config.provider}")


# =============================================================================
# LLM SYNTHESIS PLUGIN
# =============================================================================


class LLMSynthesisPlugin(SynthesisPlugin):
    """LLM-based synthesis plugin for combining context from multiple sources.

    Implements the SynthesisPlugin interface for the plugin system.
    Uses an LLM to combine raw data from adapters into a structured,
    concise context block suitable for AI coding assistants.

    Supports custom prompt templates via config.prompt_template path.

    Class Attributes:
        name: Plugin identifier ("llm").
        config_schema: Configuration model (SynthesisConfig).
    """

    # SynthesisPlugin class attributes
    name: ClassVar[str] = "llm"
    config_schema: ClassVar[type[SynthesisConfig]] = SynthesisConfig

    def __init__(self, config: SynthesisConfig) -> None:
        """Initialize the synthesis plugin.

        Args:
            config: Synthesis configuration.
        """
        self._config = config
        self._provider: LLMProvider | None = None
        self._custom_prompt: str | None = None

    def _get_provider(self) -> LLMProvider:
        """Get or create the LLM provider (lazy initialization)."""
        if self._provider is None:
            self._provider = create_provider(self._config)
        return self._provider

    def _get_prompt_template(self) -> str:
        """Get the prompt template (custom or default).

        If config.prompt_template is set, loads from that file.
        Otherwise uses the default SYNTHESIS_PROMPT.

        Returns:
            The prompt template string.
        """
        if self._custom_prompt is not None:
            return self._custom_prompt

        if self._config.prompt_template:
            from pathlib import Path

            template_path = Path(self._config.prompt_template)
            if template_path.exists():
                self._custom_prompt = template_path.read_text()
                logger.info(f"Loaded custom prompt template from: {template_path}")
                return self._custom_prompt
            else:
                logger.warning(f"Custom prompt template not found: {template_path}, using default")

        return SYNTHESIS_PROMPT

    def _format_jira_context(self, ctx: JiraContext) -> str:
        """Format Jira context as raw data for the prompt."""
        parts = ["## JIRA TICKET"]
        ticket = ctx.ticket

        parts.append(f"**ID:** {ticket.ticket_id}")
        parts.append(f"**Title:** {ticket.title}")
        parts.append(f"**Status:** {ticket.status}")

        if ticket.assignee:
            parts.append(f"**Assignee:** {ticket.assignee}")
        if ticket.labels:
            parts.append(f"**Labels:** {', '.join(ticket.labels)}")
        if ticket.components:
            parts.append(f"**Components:** {', '.join(ticket.components)}")
        if ticket.sprint:
            parts.append(f"**Sprint:** {ticket.sprint}")

        if ticket.description:
            parts.append(f"\n**Description:**\n{ticket.description}")

        if ticket.acceptance_criteria:
            parts.append(f"\n**Acceptance Criteria:**\n{ticket.acceptance_criteria}")

        # Comments
        if ctx.comments:
            parts.append(f"\n### Comments ({len(ctx.comments)})")
            for comment in ctx.comments[:10]:
                date_str = comment.created.strftime("%Y-%m-%d")
                parts.append(f"\n**{comment.author}** ({date_str}):\n{comment.body}")

        # Linked issues
        if ctx.linked_issues:
            parts.append(f"\n### Linked Issues ({len(ctx.linked_issues)})")
            for linked in ctx.linked_issues:
                parts.append(
                    f"- [{linked.ticket_id}] {linked.title} ({linked.status}) - {linked.link_type}"
                )

        return "\n".join(parts)

    def _format_meeting_context(self, ctx: MeetingContext) -> str:
        """Format meeting context as raw data for the prompt."""
        if not ctx.meetings:
            return ""

        parts = ["## MEETING TRANSCRIPTS"]

        for meeting in ctx.meetings:
            date_str = meeting.meeting_date.strftime("%Y-%m-%d")
            parts.append(f"\n### {meeting.meeting_title} ({date_str})")

            if meeting.participants:
                parts.append(f"**Participants:** {', '.join(meeting.participants)}")

            parts.append(f"\n**Relevant Excerpt:**\n{meeting.excerpt}")

            if meeting.action_items:
                parts.append("\n**Action Items:**")
                for item in meeting.action_items:
                    parts.append(f"- {item}")

            if meeting.decisions:
                parts.append("\n**Decisions:**")
                for decision in meeting.decisions:
                    parts.append(f"- {decision}")

        return "\n".join(parts)

    def _format_architecture_docs(self, ctx: DocsContext) -> str:
        """Format architecture documentation as raw data for the prompt."""
        arch_sections = [s for s in ctx.sections if s.doc_type == "architecture"]
        if not arch_sections:
            return ""

        parts = ["## ARCHITECTURE DOCS"]
        parts.append("*Focus on file paths, data flow, integration points, and infrastructure.*\n")

        for section in arch_sections:
            title = section.section_title or section.file_path
            parts.append(f"\n### {title}")
            parts.append(f"**Source:** {section.file_path}")
            parts.append(f"\n{section.content}")

        return "\n".join(parts)

    def _format_coding_standards(self, ctx: DocsContext) -> str:
        """Format coding standards as raw data for the prompt."""
        standards_sections = [s for s in ctx.sections if s.doc_type == "standards"]
        if not standards_sections:
            return ""

        parts = ["## CODING STANDARDS"]
        parts.append("*Specific rules and patterns to follow in this codebase.*\n")

        for section in standards_sections:
            title = section.section_title or section.file_path
            parts.append(f"\n### {title}")
            parts.append(f"**Source:** {section.file_path}")
            parts.append(f"\n{section.content}")

        return "\n".join(parts)

    def _format_other_docs(self, ctx: DocsContext) -> str:
        """Format ADRs and other documentation as raw data for the prompt."""
        other_sections = [s for s in ctx.sections if s.doc_type in ("adr", "other")]
        if not other_sections:
            return ""

        parts = ["## OTHER DOCUMENTATION"]

        for section in other_sections:
            doc_type_label = "ADR" if section.doc_type == "adr" else "Doc"
            title = section.section_title or section.file_path
            parts.append(f"\n### [{doc_type_label}] {title}")
            parts.append(f"**Source:** {section.file_path}")
            parts.append(f"\n{section.content}")

        return "\n".join(parts)

    def _format_slack_context(self, ctx: SlackContext) -> str:
        """Format Slack context as raw data for the prompt."""
        if not ctx.threads and not ctx.standalone_messages:
            return ""

        parts = ["## SLACK DISCUSSIONS"]
        parts.append("*Informal team communications and discussions.*\n")

        for thread in ctx.threads:
            date_str = thread.parent_message.timestamp.strftime("%Y-%m-%d")
            parts.append(f"\n### Thread in #{thread.parent_message.channel_name} ({date_str})")
            parts.append(f"**Participants:** {', '.join(thread.participant_names)}")

            parts.append(f"\n**{thread.parent_message.user_name}:** {thread.parent_message.text}")

            for reply in thread.replies[:5]:
                parts.append(f"**{reply.user_name}:** {reply.text}")

            if thread.decisions:
                parts.append("\n**Informal Decisions:**")
                for d in thread.decisions:
                    parts.append(f"- {d}")

            if thread.action_items:
                parts.append("\n**Action Items:**")
                for a in thread.action_items:
                    parts.append(f"- {a}")

        for msg in ctx.standalone_messages[:5]:
            date_str = msg.timestamp.strftime("%Y-%m-%d")
            parts.append(f"\n**#{msg.channel_name}** ({date_str})")
            parts.append(f"**{msg.user_name}:** {msg.text}")

        return "\n".join(parts)

    def _format_gmail_context(self, ctx: GmailContext) -> str:
        """Format Gmail context as raw data for the prompt."""
        if not ctx.threads:
            return ""

        parts = ["## EMAIL CONTEXT"]
        parts.append("*External communications with stakeholders, customers, etc.*\n")

        for thread in ctx.threads:
            parts.append(f"\n### Email Thread: {thread.subject}")
            parts.append(f"**Participants:** {', '.join(thread.participants[:5])}")
            parts.append(f"**Latest:** {thread.latest_date.strftime('%Y-%m-%d')}")

            for msg in thread.messages[:3]:
                sender = msg.sender_name or msg.sender
                date_str = msg.date.strftime("%Y-%m-%d")
                parts.append(f"\n**{sender}** ({date_str}):")
                body = msg.body_text or msg.snippet
                if len(body) > 500:
                    body = body[:500] + "..."
                parts.append(body)

        return "\n".join(parts)

    def _format_github_context(self, ctx: GitHubContext) -> str:
        """Format GitHub context as raw data for the prompt."""
        if not ctx.related_prs and not ctx.recent_prs and not ctx.related_issues:
            return ""

        from datetime import UTC, datetime

        parts = ["## GITHUB CONTEXT"]
        parts.append("*Recent PRs and changes in the same service area.*\n")

        # Related PRs (mention ticket or same files)
        if ctx.related_prs:
            parts.append("### Related PRs")
            for pr in ctx.related_prs:
                status = "merged" if pr.merged_at else pr.state
                parts.append(f"\n**PR #{pr.number}**: {pr.title} ({status})")
                parts.append(f"Author: @{pr.author}")
                if pr.changed_files:
                    files_str = ", ".join(pr.changed_files[:5])
                    if len(pr.changed_files) > 5:
                        files_str += f" (+{len(pr.changed_files) - 5} more)"
                    parts.append(f"Changed: {files_str}")
                for comment in pr.review_comments[:3]:
                    body = comment.body[:200]
                    if len(comment.body) > 200:
                        body += "..."
                    parts.append(f"Review (@{comment.author}): {body}")

        # Recent PRs in same area
        if ctx.recent_prs:
            parts.append("\n### Recent PRs in Service Area")
            for pr in ctx.recent_prs[:5]:
                merge_date = pr.merged_at or pr.created_at
                days_ago = (datetime.now(UTC) - merge_date).days
                parts.append(f"- PR #{pr.number}: {pr.title} ({days_ago}d ago)")

        # Related issues
        if ctx.related_issues:
            parts.append("\n### Related Issues")
            for issue in ctx.related_issues:
                labels_str = f" [{', '.join(issue.labels)}]" if issue.labels else ""
                parts.append(f"- #{issue.number}: {issue.title} ({issue.state}){labels_str}")

        return "\n".join(parts)

    def _build_raw_data(
        self,
        jira_context: JiraContext | None,
        meeting_context: MeetingContext | None,
        docs_context: DocsContext | None,
        slack_context: SlackContext | None = None,
        gmail_context: GmailContext | None = None,
        github_context: GitHubContext | None = None,
    ) -> str:
        """Build the raw data section for the synthesis prompt.

        Args:
            jira_context: Jira ticket context (if available).
            meeting_context: Meeting transcripts context (if available).
            docs_context: Documentation context (if available).
            slack_context: Slack discussions context (if available).
            gmail_context: Gmail email context (if available).
            github_context: GitHub PRs and issues context (if available).

        Returns:
            Formatted raw data string.
        """
        sections: list[str] = []

        # Jira ticket data
        if jira_context and jira_context.ticket:
            sections.append(self._format_jira_context(jira_context))

        # Meeting transcripts (formal decisions)
        if meeting_context and meeting_context.meetings:
            sections.append(self._format_meeting_context(meeting_context))

        # Slack discussions (informal team communications)
        if slack_context and (slack_context.threads or slack_context.standalone_messages):
            sections.append(self._format_slack_context(slack_context))

        # Email context (external communications)
        if gmail_context and gmail_context.threads:
            sections.append(self._format_gmail_context(gmail_context))

        # GitHub context (PRs, issues, recent changes)
        if github_context and (
            github_context.related_prs
            or github_context.recent_prs
            or github_context.related_issues
        ):
            sections.append(self._format_github_context(github_context))

        # Documentation - split by type for better synthesis
        if docs_context and docs_context.sections:
            # Architecture docs (file paths, data flow, infrastructure)
            arch_docs = self._format_architecture_docs(docs_context)
            if arch_docs:
                sections.append(arch_docs)

            # Coding standards (patterns, rules, conventions)
            standards = self._format_coding_standards(docs_context)
            if standards:
                sections.append(standards)

            # ADRs and other docs
            other_docs = self._format_other_docs(docs_context)
            if other_docs:
                sections.append(other_docs)

        if not sections:
            return "No context data available."

        return "\n\n---\n\n".join(sections)

    def _format_fallback(
        self,
        task_id: str,
        jira_context: JiraContext | None,
        meeting_context: MeetingContext | None,
        docs_context: DocsContext | None,
        slack_context: SlackContext | None = None,
        gmail_context: GmailContext | None = None,
        github_context: GitHubContext | None = None,
    ) -> str:
        """Format context as plain markdown when LLM synthesis fails.

        This provides a fallback that's still useful even without LLM processing.

        Args:
            task_id: The task identifier.
            jira_context: Jira ticket context (if available).
            meeting_context: Meeting transcripts context (if available).
            docs_context: Documentation context (if available).
            slack_context: Slack discussions context (if available).
            gmail_context: Gmail email context (if available).
            github_context: GitHub PRs and issues context (if available).

        Returns:
            Plain markdown formatted context.
        """
        parts = [f"## Task: {task_id}"]
        parts.append("\n*Note: LLM synthesis unavailable, showing raw context.*\n")

        raw_data = self._build_raw_data(
            jira_context,
            meeting_context,
            docs_context,
            slack_context,
            gmail_context,
            github_context,
        )
        parts.append(raw_data)

        return "\n".join(parts)

    async def synthesize(
        self,
        task_id: str,
        source_contexts: dict[str, SourceContext],
    ) -> str:
        """Synthesize context from multiple sources using LLM.

        Implements the SynthesisPlugin interface. Takes context data from
        all enabled adapters and combines it into a structured markdown
        document suitable for AI coding assistants.

        Args:
            task_id: The task identifier.
            source_contexts: Dict mapping adapter names to their SourceContext.

        Returns:
            Synthesized markdown context, or fallback raw format on error.
        """
        # Extract typed contexts from source_contexts
        from devscontext.models import (
            DocsContext,
            GitHubContext,
            GmailContext,
            JiraContext,
            MeetingContext,
            SlackContext,
        )

        jira_context: JiraContext | None = None
        meeting_context: MeetingContext | None = None
        docs_context: DocsContext | None = None
        slack_context: SlackContext | None = None
        gmail_context: GmailContext | None = None
        github_context: GitHubContext | None = None

        for _name, ctx in source_contexts.items():
            if ctx.is_empty():
                continue

            if isinstance(ctx.data, JiraContext):
                jira_context = ctx.data
            elif isinstance(ctx.data, MeetingContext):
                meeting_context = ctx.data
            elif isinstance(ctx.data, DocsContext):
                docs_context = ctx.data
            elif isinstance(ctx.data, SlackContext):
                slack_context = ctx.data
            elif isinstance(ctx.data, GmailContext):
                gmail_context = ctx.data
            elif isinstance(ctx.data, GitHubContext):
                github_context = ctx.data

        # Build raw data
        raw_data = self._build_raw_data(
            jira_context,
            meeting_context,
            docs_context,
            slack_context,
            gmail_context,
            github_context,
        )

        if raw_data == "No context data available.":
            return f"## Task: {task_id}\n\nNo context found for this task."

        # Get title from Jira if available
        title = ""
        if jira_context and jira_context.ticket:
            title = jira_context.ticket.title

        # Build the prompt using custom or default template
        prompt_template = self._get_prompt_template()
        prompt = prompt_template.format(
            task_id=task_id,
            title=title,
            raw_data=raw_data,
        )

        # Try LLM synthesis
        try:
            provider = self._get_provider()
            result = await provider.generate(
                prompt=prompt,
                max_tokens=self._config.max_output_tokens,
            )
            logger.info(
                "Synthesis completed",
                extra={"task_id": task_id, "provider": self._config.provider},
            )
            return result

        except ImportError as e:
            logger.warning(
                "LLM provider not available, using fallback",
                extra={"error": str(e), "provider": self._config.provider},
            )
            return self._format_fallback(
                task_id,
                jira_context,
                meeting_context,
                docs_context,
                slack_context,
                gmail_context,
                github_context,
            )

        except ValueError as e:
            logger.warning(
                "LLM configuration error, using fallback",
                extra={"error": str(e), "provider": self._config.provider},
            )
            return self._format_fallback(
                task_id,
                jira_context,
                meeting_context,
                docs_context,
                slack_context,
                gmail_context,
                github_context,
            )

        except Exception as e:
            logger.warning(
                "LLM synthesis failed, using fallback",
                extra={"error": str(e), "provider": self._config.provider},
            )
            return self._format_fallback(
                task_id,
                jira_context,
                meeting_context,
                docs_context,
                slack_context,
                gmail_context,
                github_context,
            )


# =============================================================================
# TEMPLATE SYNTHESIS PLUGIN
# =============================================================================


class TemplateSynthesisPlugin(SynthesisPlugin):
    """Template-based synthesis plugin using Jinja2 templates.

    Combines context data using a Jinja2 template file, providing
    customizable output without LLM costs. Good for teams that want
    consistent, deterministic output format.

    Class Attributes:
        name: Plugin identifier ("template").
        config_schema: Configuration model (SynthesisConfig).
    """

    name: ClassVar[str] = "template"
    config_schema: ClassVar[type[SynthesisConfig]] = SynthesisConfig

    def __init__(self, config: SynthesisConfig) -> None:
        """Initialize the template synthesis plugin.

        Args:
            config: Synthesis configuration with template_path.
        """
        self._config = config
        self._template: Any = None

    def _get_template(self) -> Any:
        """Get or create the Jinja2 template (lazy initialization)."""
        if self._template is None:
            try:
                from jinja2 import Environment, FileSystemLoader
            except ImportError as e:
                raise ImportError(
                    "jinja2 package not installed. Install with: pip install jinja2"
                ) from e

            template_path = self._config.template_path
            if not template_path:
                raise ValueError("template_path is required for template synthesis plugin")

            from pathlib import Path

            template_file = Path(template_path)
            if not template_file.exists():
                raise ValueError(f"Template file not found: {template_path}")

            env = Environment(
                loader=FileSystemLoader(str(template_file.parent)),
                autoescape=False,
            )
            self._template = env.get_template(template_file.name)

        return self._template

    async def synthesize(
        self,
        task_id: str,
        source_contexts: dict[str, SourceContext],
    ) -> str:
        """Synthesize context using Jinja2 template.

        The template receives:
        - task_id: The task identifier
        - contexts: Dict of source contexts
        - jira: JiraContext if available
        - meetings: MeetingContext if available
        - docs: DocsContext if available
        - slack: SlackContext if available
        - gmail: GmailContext if available
        - github: GitHubContext if available

        Args:
            task_id: The task identifier.
            source_contexts: Dict mapping adapter names to their SourceContext.

        Returns:
            Rendered template output.
        """
        from devscontext.models import (
            DocsContext,
            GitHubContext,
            GmailContext,
            JiraContext,
            MeetingContext,
            SlackContext,
        )

        # Extract typed contexts
        jira_context: JiraContext | None = None
        meeting_context: MeetingContext | None = None
        docs_context: DocsContext | None = None
        slack_context: SlackContext | None = None
        gmail_context: GmailContext | None = None
        github_context: GitHubContext | None = None

        for _name, ctx in source_contexts.items():
            if ctx.is_empty():
                continue
            if isinstance(ctx.data, JiraContext):
                jira_context = ctx.data
            elif isinstance(ctx.data, MeetingContext):
                meeting_context = ctx.data
            elif isinstance(ctx.data, DocsContext):
                docs_context = ctx.data
            elif isinstance(ctx.data, SlackContext):
                slack_context = ctx.data
            elif isinstance(ctx.data, GmailContext):
                gmail_context = ctx.data
            elif isinstance(ctx.data, GitHubContext):
                github_context = ctx.data

        try:
            template = self._get_template()
            return str(
                template.render(
                    task_id=task_id,
                    contexts=source_contexts,
                    jira=jira_context,
                    meetings=meeting_context,
                    docs=docs_context,
                    github=github_context,
                    slack=slack_context,
                    gmail=gmail_context,
                )
            )
        except Exception as e:
            logger.warning(f"Template synthesis failed: {e}")
            return f"## Task: {task_id}\n\nTemplate synthesis error: {e}"


# =============================================================================
# PASSTHROUGH SYNTHESIS PLUGIN
# =============================================================================


class PassthroughSynthesisPlugin(SynthesisPlugin):
    """Passthrough synthesis plugin that returns raw formatted data.

    No LLM processing - just formats the raw context data as markdown.
    Useful for debugging, testing, or when you want to see exactly
    what data is being collected.

    Class Attributes:
        name: Plugin identifier ("passthrough").
        config_schema: Configuration model (SynthesisConfig).
    """

    name: ClassVar[str] = "passthrough"
    config_schema: ClassVar[type[SynthesisConfig]] = SynthesisConfig

    def __init__(self, config: SynthesisConfig) -> None:
        """Initialize the passthrough synthesis plugin.

        Args:
            config: Synthesis configuration (mostly unused for passthrough).
        """
        self._config = config

    async def synthesize(
        self,
        task_id: str,
        source_contexts: dict[str, SourceContext],
    ) -> str:
        """Return raw formatted context without LLM processing.

        Args:
            task_id: The task identifier.
            source_contexts: Dict mapping adapter names to their SourceContext.

        Returns:
            Raw markdown formatted context.
        """
        from devscontext.models import (
            DocsContext,
            GitHubContext,
            GmailContext,
            JiraContext,
            MeetingContext,
            SlackContext,
        )

        parts = [f"## Task: {task_id}", ""]

        if not source_contexts:
            parts.append("No context data available.")
            return "\n".join(parts)

        for name, ctx in source_contexts.items():
            if ctx.is_empty():
                continue

            parts.append(f"### Source: {name} ({ctx.source_type})")
            parts.append(f"*Fetched at: {ctx.fetched_at.isoformat()}*")
            parts.append("")

            # Format based on data type
            if isinstance(ctx.data, JiraContext):
                parts.append(self._format_jira(ctx.data))
            elif isinstance(ctx.data, MeetingContext):
                parts.append(self._format_meetings(ctx.data))
            elif isinstance(ctx.data, DocsContext):
                parts.append(self._format_docs(ctx.data))
            elif isinstance(ctx.data, SlackContext):
                parts.append(self._format_slack(ctx.data))
            elif isinstance(ctx.data, GmailContext):
                parts.append(self._format_gmail(ctx.data))
            elif isinstance(ctx.data, GitHubContext):
                parts.append(self._format_github(ctx.data))
            elif ctx.raw_text:
                parts.append(ctx.raw_text)
            else:
                parts.append(f"*Data type: {type(ctx.data).__name__}*")

            parts.append("")

        return "\n".join(parts)

    def _format_jira(self, ctx: JiraContext) -> str:
        """Format Jira context as markdown."""
        lines = []
        ticket = ctx.ticket

        lines.append(f"**{ticket.ticket_id}**: {ticket.title}")
        lines.append(f"- Status: {ticket.status}")
        if ticket.assignee:
            lines.append(f"- Assignee: {ticket.assignee}")
        if ticket.labels:
            lines.append(f"- Labels: {', '.join(ticket.labels)}")
        if ticket.components:
            lines.append(f"- Components: {', '.join(ticket.components)}")
        if ticket.description:
            lines.append(f"\n**Description:**\n{ticket.description}")
        if ticket.acceptance_criteria:
            lines.append(f"\n**Acceptance Criteria:**\n{ticket.acceptance_criteria}")

        if ctx.comments:
            lines.append(f"\n**Comments ({len(ctx.comments)}):**")
            for c in ctx.comments[:5]:
                lines.append(f"- {c.author}: {c.body[:200]}...")

        if ctx.linked_issues:
            lines.append(f"\n**Linked Issues ({len(ctx.linked_issues)}):**")
            for li in ctx.linked_issues:
                lines.append(f"- {li.ticket_id}: {li.title} ({li.link_type})")

        return "\n".join(lines)

    def _format_meetings(self, ctx: MeetingContext) -> str:
        """Format meeting context as markdown."""
        if not ctx.meetings:
            return "*No meetings found*"

        lines = []
        for m in ctx.meetings:
            date_str = m.meeting_date.strftime("%Y-%m-%d")
            lines.append(f"**{m.meeting_title}** ({date_str})")
            if m.participants:
                lines.append(f"Participants: {', '.join(m.participants)}")
            lines.append(f"\n{m.excerpt[:500]}...")
            if m.decisions:
                lines.append("\nDecisions:")
                for d in m.decisions:
                    lines.append(f"- {d}")
            if m.action_items:
                lines.append("\nAction Items:")
                for a in m.action_items:
                    lines.append(f"- {a}")
            lines.append("")

        return "\n".join(lines)

    def _format_docs(self, ctx: DocsContext) -> str:
        """Format docs context as markdown."""
        if not ctx.sections:
            return "*No documentation found*"

        lines = []
        for s in ctx.sections:
            title = s.section_title or s.file_path
            lines.append(f"**{title}** [{s.doc_type}]")
            lines.append(f"*Source: {s.file_path}*")
            lines.append(f"\n{s.content[:500]}...")
            lines.append("")

        return "\n".join(lines)

    def _format_slack(self, ctx: SlackContext) -> str:
        """Format Slack context as markdown."""
        if not ctx.threads and not ctx.standalone_messages:
            return "*No Slack discussions found*"

        lines = []
        for thread in ctx.threads:
            date_str = thread.parent_message.timestamp.strftime("%Y-%m-%d")
            lines.append(f"**#{thread.parent_message.channel_name}** ({date_str})")
            lines.append(f"Participants: {', '.join(thread.participant_names)}")
            user = thread.parent_message.user_name
            text = thread.parent_message.text[:200]
            lines.append(f"\n{user}: {text}...")
            if thread.decisions:
                lines.append("\nDecisions:")
                for d in thread.decisions[:3]:
                    lines.append(f"- {d}")
            if thread.action_items:
                lines.append("\nAction Items:")
                for a in thread.action_items[:3]:
                    lines.append(f"- {a}")
            lines.append("")

        for msg in ctx.standalone_messages[:5]:
            date_str = msg.timestamp.strftime("%Y-%m-%d")
            lines.append(f"**#{msg.channel_name}** ({date_str}): {msg.text[:200]}...")

        return "\n".join(lines)

    def _format_gmail(self, ctx: GmailContext) -> str:
        """Format Gmail context as markdown."""
        if not ctx.threads:
            return "*No email threads found*"

        lines = []
        for thread in ctx.threads:
            lines.append(f"**{thread.subject}**")
            lines.append(f"Participants: {', '.join(thread.participants[:5])}")
            lines.append(f"Latest: {thread.latest_date.strftime('%Y-%m-%d')}")
            for msg in thread.messages[:2]:
                sender = msg.sender_name or msg.sender
                lines.append(f"\n{sender}: {msg.snippet[:200]}...")
            lines.append("")

        return "\n".join(lines)

    def _format_github(self, ctx: GitHubContext) -> str:
        """Format GitHub context as markdown."""
        if not ctx.related_prs and not ctx.recent_prs and not ctx.related_issues:
            return "*No GitHub context found*"

        lines = []

        if ctx.related_prs:
            lines.append("**Related PRs:**")
            for pr in ctx.related_prs:
                status = "merged" if pr.merged_at else pr.state
                lines.append(f"- PR #{pr.number}: {pr.title} ({status})")
            lines.append("")

        if ctx.recent_prs:
            lines.append("**Recent PRs:**")
            for pr in ctx.recent_prs[:5]:
                lines.append(f"- PR #{pr.number}: {pr.title}")
            lines.append("")

        if ctx.related_issues:
            lines.append("**Related Issues:**")
            for issue in ctx.related_issues:
                lines.append(f"- #{issue.number}: {issue.title} ({issue.state})")
            lines.append("")

        return "\n".join(lines)


# Keep old name as alias for backward compatibility
SynthesisEngine = LLMSynthesisPlugin
