"""Local docs adapter for fetching context from local markdown files.

This adapter searches local documentation directories for relevant content.
It supports markdown, text, and rst files.

Note: This is currently a stub implementation. Real file search will be
added in a future iteration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from devscontext.adapters.base import Adapter
from devscontext.constants import ADAPTER_LOCAL_DOCS, SOURCE_TYPE_DOCUMENTATION
from devscontext.logging import get_logger
from devscontext.models import ContextData

if TYPE_CHECKING:
    from devscontext.config import LocalDocsConfig

logger = get_logger(__name__)


class LocalDocsAdapter(Adapter):
    """Adapter for fetching context from local documentation files.

    This adapter searches configured documentation directories for
    markdown files that contain relevant content.

    Attributes:
        name: Always "local_docs".
        source_type: Always "documentation".
    """

    def __init__(self, config: LocalDocsConfig) -> None:
        """Initialize the local docs adapter.

        Args:
            config: Local docs configuration with paths to search.
        """
        self._config = config

    @property
    def name(self) -> str:
        """Return the adapter name."""
        return ADAPTER_LOCAL_DOCS

    @property
    def source_type(self) -> str:
        """Return the source type."""
        return SOURCE_TYPE_DOCUMENTATION

    async def fetch_context(self, task_id: str) -> list[ContextData]:
        """Fetch context from local documentation files.

        Searches configured documentation directories for relevant content.

        Args:
            task_id: The task identifier to search for in docs.

        Returns:
            List of relevant documentation excerpts, empty if not configured.
        """
        if not self._config.enabled:
            logger.debug("Local docs adapter is disabled")
            return []

        # TODO: Implement real file scanning and search
        # For now, return stub data to demonstrate the interface
        logger.info(
            "Fetching local docs context (stub)",
            extra={"task_id": task_id, "paths": self._config.paths},
        )

        results: list[ContextData] = []

        results.append(
            ContextData(
                source="docs:architecture/payments-service.md",
                source_type=self.source_type,
                title="Payments Service Architecture",
                content="""# Payments Service Architecture

## Authentication

The payments service uses JWT tokens for authentication. All requests must include
a valid Bearer token in the Authorization header.

### Token Validation

Tokens are validated against the auth service using the `/auth/validate` endpoint.
The service caches validation results for 5 minutes to reduce load.

### Required Scopes

- `payments:read` - View payment history
- `payments:write` - Create new payments
- `payments:admin` - Manage payment methods

## Security Considerations

- All payment data is encrypted at rest
- PCI DSS compliance is required
- Audit logs are maintained for all transactions
""",
                metadata={
                    "path": "docs/architecture/payments-service.md",
                    "last_modified": "2024-01-10",
                },
                relevance_score=0.9,
            )
        )

        results.append(
            ContextData(
                source="docs:standards/typescript.md",
                source_type=self.source_type,
                title="TypeScript Coding Standards",
                content="""# TypeScript Coding Standards

## Authentication Patterns

When implementing authentication:

1. Always use the `AuthMiddleware` from `@company/auth`
2. Never store tokens in localStorage - use httpOnly cookies
3. Implement token refresh logic in the API client

```typescript
import { AuthMiddleware } from '@company/auth';

app.use('/api', AuthMiddleware.verify());
```

## Error Handling

Authentication errors should return:
- 401 for invalid/expired tokens
- 403 for insufficient permissions
""",
                metadata={
                    "path": "docs/standards/typescript.md",
                    "last_modified": "2024-01-05",
                },
                relevance_score=0.75,
            )
        )

        return results

    async def health_check(self) -> bool:
        """Check if local docs paths are accessible.

        Returns:
            True if healthy or disabled, False if configured paths don't exist.
        """
        if not self._config.enabled:
            return True

        # TODO: Actually check if paths exist
        healthy = len(self._config.paths) > 0

        if healthy:
            logger.info(
                "Local docs health check passed",
                extra={"path_count": len(self._config.paths)},
            )
        else:
            logger.warning("Local docs adapter has no paths configured")

        return healthy
