"""Fireflies adapter for fetching meeting transcript context."""

from devscontext.adapters.base import Adapter, ContextData
from devscontext.config import FirefliesConfig


class FirefliesAdapter(Adapter):
    """Adapter for fetching context from Fireflies meeting transcripts."""

    def __init__(self, config: FirefliesConfig) -> None:
        """Initialize the Fireflies adapter.

        Args:
            config: Fireflies configuration.
        """
        self._config = config

    @property
    def name(self) -> str:
        return "fireflies"

    @property
    def source_type(self) -> str:
        return "meeting"

    async def fetch_context(self, task_id: str) -> list[ContextData]:
        """Fetch context from Fireflies meeting transcripts.

        Args:
            task_id: The task identifier to search for in transcripts.

        Returns:
            List of relevant meeting excerpts.
        """
        # TODO: Implement real Fireflies API calls
        # For now, return hardcoded stub data
        if not self._config.enabled:
            return []

        return [
            ContextData(
                source="fireflies:meeting-2024-01-15",
                source_type=self.source_type,
                title="Sprint Planning - Auth Implementation Discussion",
                content="""## Meeting Notes (relevant excerpt)

**Sarah (Tech Lead):** For the auth flow, we decided to use Google OAuth as the primary provider. We might add GitHub later but let's start simple.

**Mike (Security):** Make sure we're using PKCE for the OAuth flow. Also, the JWT secret should come from the vault, not environment variables.

**Sarah:** Good point. And remember, the payments service needs to validate tokens from the auth service, so we need to expose a token validation endpoint.

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
        """Check if Fireflies is configured and accessible."""
        if not self._config.enabled:
            return True

        # TODO: Actually ping Fireflies API
        return bool(self._config.api_key)
