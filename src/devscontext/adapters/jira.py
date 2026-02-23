"""Jira adapter for fetching issue context."""

from devscontext.adapters.base import Adapter, ContextData
from devscontext.config import JiraConfig


class JiraAdapter(Adapter):
    """Adapter for fetching context from Jira issues."""

    def __init__(self, config: JiraConfig) -> None:
        """Initialize the Jira adapter.

        Args:
            config: Jira configuration.
        """
        self._config = config

    @property
    def name(self) -> str:
        return "jira"

    @property
    def source_type(self) -> str:
        return "issue_tracker"

    async def fetch_context(self, task_id: str) -> list[ContextData]:
        """Fetch context from a Jira issue.

        Args:
            task_id: The Jira issue key (e.g., PROJ-123).

        Returns:
            List of context data from the issue.
        """
        # TODO: Implement real Jira API calls
        # For now, return hardcoded stub data
        return [
            ContextData(
                source=f"jira:{task_id}",
                source_type=self.source_type,
                title=f"[{task_id}] Implement user authentication flow",
                content="""## Description
Implement OAuth2 authentication flow for the payments service.

## Acceptance Criteria
- Users can log in via Google OAuth
- JWT tokens are issued upon successful authentication
- Tokens expire after 24 hours
- Refresh tokens are supported

## Technical Notes
- Use the existing auth middleware in `src/middleware/auth.ts`
- Follow the patterns in the user-service for token handling
""",
                metadata={
                    "status": "In Progress",
                    "assignee": "developer@example.com",
                    "priority": "High",
                    "labels": ["authentication", "security"],
                    "sprint": "Sprint 42",
                },
            )
        ]

    async def health_check(self) -> bool:
        """Check if Jira is configured and accessible."""
        if not self._config.enabled:
            return True  # Not enabled is fine

        # TODO: Actually ping Jira API
        return bool(
            self._config.base_url and self._config.email and self._config.api_token
        )
