"""Context synthesis - LLM-based synthesis of context from multiple sources.

This module provides the SynthesisEngine class that uses an LLM to combine
raw data from adapters into a structured, concise context block suitable
for AI coding assistants.

Supported providers:
- anthropic: Claude models via the Anthropic SDK
- openai: GPT models via the OpenAI SDK
- ollama: Local models via Ollama HTTP API

Example:
    config = SynthesisConfig(provider="anthropic", model="claude-haiku-4-5")
    engine = SynthesisEngine(config)
    result = await engine.synthesize(
        task_id="PROJ-123",
        jira_context=jira_ctx,
        meeting_context=meeting_ctx,
        docs_context=docs_ctx,
    )
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import httpx

from devscontext.constants import DEFAULT_HTTP_TIMEOUT_SECONDS
from devscontext.logging import get_logger

if TYPE_CHECKING:
    from devscontext.models import (
        DocsContext,
        JiraContext,
        MeetingContext,
        SynthesisConfig,
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
  ### Architecture Context
  ### Coding Standards
  ### Related Work
- For each fact, note the source in [brackets] at the end of the paragraph.
- If sources conflict, note the conflict explicitly.
- Extract acceptance criteria clearly as a checklist if available.
- For decisions from meetings, include WHO decided and WHEN.
- For architecture, focus on file paths, patterns, and integration points.
- Do NOT include generic advice. Only include specific, actionable context.

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
                from anthropic import AsyncAnthropic
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
        return response.content[0].text


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
                    "openai package not installed. "
                    "Install with: pip install devscontext[openai]"
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
        return data.get("response", "")


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
# SYNTHESIS ENGINE
# =============================================================================


class SynthesisEngine:
    """Engine for synthesizing context from multiple sources using an LLM.

    The engine takes raw context from Jira, meetings, and documentation,
    formats it into a prompt, and uses an LLM to produce a structured
    context block for AI coding assistants.
    """

    def __init__(self, config: SynthesisConfig) -> None:
        """Initialize the synthesis engine.

        Args:
            config: Synthesis configuration.
        """
        self._config = config
        self._provider: LLMProvider | None = None

    def _get_provider(self) -> LLMProvider:
        """Get or create the LLM provider (lazy initialization)."""
        if self._provider is None:
            self._provider = create_provider(self._config)
        return self._provider

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
                    f"- [{linked.ticket_id}] {linked.title} "
                    f"({linked.status}) - {linked.link_type}"
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

    def _format_docs_context(self, ctx: DocsContext) -> str:
        """Format documentation context as raw data for the prompt."""
        if not ctx.sections:
            return ""

        parts = ["## LOCAL DOCUMENTATION"]

        for section in ctx.sections:
            title = section.section_title or section.file_path
            parts.append(f"\n### {title}")
            parts.append(f"**Source:** {section.file_path} ({section.doc_type})")
            parts.append(f"\n{section.content}")

        return "\n".join(parts)

    def _build_raw_data(
        self,
        jira_context: JiraContext | None,
        meeting_context: MeetingContext | None,
        docs_context: DocsContext | None,
    ) -> str:
        """Build the raw data section for the synthesis prompt.

        Args:
            jira_context: Jira ticket context (if available).
            meeting_context: Meeting transcripts context (if available).
            docs_context: Documentation context (if available).

        Returns:
            Formatted raw data string.
        """
        sections: list[str] = []

        if jira_context and jira_context.ticket:
            sections.append(self._format_jira_context(jira_context))

        if meeting_context and meeting_context.meetings:
            sections.append(self._format_meeting_context(meeting_context))

        if docs_context and docs_context.sections:
            sections.append(self._format_docs_context(docs_context))

        if not sections:
            return "No context data available."

        return "\n\n---\n\n".join(sections)

    def _format_fallback(
        self,
        task_id: str,
        jira_context: JiraContext | None,
        meeting_context: MeetingContext | None,
        docs_context: DocsContext | None,
    ) -> str:
        """Format context as plain markdown when LLM synthesis fails.

        This provides a fallback that's still useful even without LLM processing.

        Args:
            task_id: The task identifier.
            jira_context: Jira ticket context (if available).
            meeting_context: Meeting transcripts context (if available).
            docs_context: Documentation context (if available).

        Returns:
            Plain markdown formatted context.
        """
        parts = [f"## Task: {task_id}"]
        parts.append("\n*Note: LLM synthesis unavailable, showing raw context.*\n")

        raw_data = self._build_raw_data(jira_context, meeting_context, docs_context)
        parts.append(raw_data)

        return "\n".join(parts)

    async def synthesize(
        self,
        task_id: str,
        jira_context: JiraContext | None,
        meeting_context: MeetingContext | None,
        docs_context: DocsContext | None,
    ) -> str:
        """Synthesize context from multiple sources using LLM.

        Takes raw data from adapters and produces a structured context block
        suitable for AI coding assistants.

        Args:
            task_id: The task identifier.
            jira_context: Jira ticket context (if available).
            meeting_context: Meeting transcripts context (if available).
            docs_context: Documentation context (if available).

        Returns:
            Synthesized markdown context, or fallback raw format on error.
        """
        # Build raw data
        raw_data = self._build_raw_data(jira_context, meeting_context, docs_context)

        if raw_data == "No context data available.":
            return f"## Task: {task_id}\n\nNo context found for this task."

        # Get title from Jira if available
        title = ""
        if jira_context and jira_context.ticket:
            title = jira_context.ticket.title

        # Build the prompt
        prompt = SYNTHESIS_PROMPT.format(
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
                task_id, jira_context, meeting_context, docs_context
            )

        except ValueError as e:
            logger.warning(
                "LLM configuration error, using fallback",
                extra={"error": str(e), "provider": self._config.provider},
            )
            return self._format_fallback(
                task_id, jira_context, meeting_context, docs_context
            )

        except Exception as e:
            logger.warning(
                "LLM synthesis failed, using fallback",
                extra={"error": str(e), "provider": self._config.provider},
            )
            return self._format_fallback(
                task_id, jira_context, meeting_context, docs_context
            )
