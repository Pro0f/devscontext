"""Local docs adapter for fetching context from local markdown files."""

from pathlib import Path

from devscontext.adapters.base import Adapter, ContextData
from devscontext.config import LocalDocsConfig


class LocalDocsAdapter(Adapter):
    """Adapter for fetching context from local documentation files."""

    def __init__(self, config: LocalDocsConfig) -> None:
        """Initialize the local docs adapter.

        Args:
            config: Local docs configuration.
        """
        self._config = config

    @property
    def name(self) -> str:
        return "local_docs"

    @property
    def source_type(self) -> str:
        return "documentation"

    async def fetch_context(self, task_id: str) -> list[ContextData]:
        """Fetch context from local documentation files.

        Args:
            task_id: The task identifier to search for in docs.

        Returns:
            List of relevant documentation excerpts.
        """
        # TODO: Implement real file scanning and search
        # For now, return hardcoded stub data
        if not self._config.enabled:
            return []

        results: list[ContextData] = []

        # Stub: Return example documentation
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
        """Check if local docs paths are accessible."""
        if not self._config.enabled:
            return True

        for path_str in self._config.paths:
            path = Path(path_str)
            if not path.exists():
                return False

        return True
