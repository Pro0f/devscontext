"""Fireflies adapter for fetching meeting transcript context.

This adapter connects to the Fireflies.ai GraphQL API to fetch meeting
transcripts and search for relevant discussions related to a task.

Note: This is currently a stub implementation. The real implementation
will be added in Day 2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from devscontext.adapters.base import Adapter
from devscontext.constants import ADAPTER_FIREFLIES, SOURCE_TYPE_MEETING
from devscontext.logging import get_logger
from devscontext.models import ContextData

if TYPE_CHECKING:
    from devscontext.config import FirefliesConfig

logger = get_logger(__name__)


class FirefliesAdapter(Adapter):
    """Adapter for fetching context from Fireflies meeting transcripts.

    This adapter connects to Fireflies.ai to search for meeting transcripts
    that mention a specific task ID or keywords.

    Attributes:
        name: Always "fireflies".
        source_type: Always "meeting".
    """

    def __init__(self, config: FirefliesConfig) -> None:
        """Initialize the Fireflies adapter.

        Args:
            config: Fireflies configuration with api_key.
        """
        self._config = config

    @property
    def name(self) -> str:
        """Return the adapter name."""
        return ADAPTER_FIREFLIES

    @property
    def source_type(self) -> str:
        """Return the source type."""
        return SOURCE_TYPE_MEETING

    async def fetch_context(self, task_id: str) -> list[ContextData]:
        """Fetch context from Fireflies meeting transcripts.

        Searches for meeting transcripts that mention the given task ID.

        Args:
            task_id: The task identifier to search for in transcripts.

        Returns:
            List of relevant meeting excerpts, empty if not configured or no matches.
        """
        if not self._config.enabled:
            logger.debug("Fireflies adapter is disabled")
            return []

        # TODO: Implement real Fireflies API calls in Day 2
        # For now, return stub data to demonstrate the interface
        logger.info(
            "Fetching Fireflies context (stub)",
            extra={"task_id": task_id},
        )

        return [
            ContextData(
                source="fireflies:meeting-2024-01-15",
                source_type=self.source_type,
                title="Sprint Planning - Auth Implementation Discussion",
                content="""## Meeting Notes (relevant excerpt)

**Sarah (Tech Lead):** For the auth flow, we decided to use Google OAuth as the primary provider.
We might add GitHub later but let's start simple.

**Mike (Security):** Make sure we're using PKCE for the OAuth flow.
Also, the JWT secret should come from the vault, not environment variables.

**Sarah:** Good point. And remember, the payments service needs to validate tokens
from the auth service, so we need to expose a token validation endpoint.

**Action Items:**
- Implement PKCE flow for OAuth
- Set up vault integration for JWT secrets
- Create /auth/validate endpoint for service-to-service token validation
""",
                metadata={
                    "date": "2024-01-15",
                    "participants": ["Sarah", "Mike", "Developer"],
                    "duration_minutes": 45,
                },
                relevance_score=0.85,
            )
        ]

    async def health_check(self) -> bool:
        """Check if Fireflies is configured and accessible.

        Returns:
            True if healthy or disabled, False if there's an issue.
        """
        if not self._config.enabled:
            return True

        # TODO: Actually ping Fireflies API
        healthy = bool(self._config.api_key)

        if healthy:
            logger.info("Fireflies health check passed (stub)")
        else:
            logger.warning("Fireflies adapter missing API key")

        return healthy
