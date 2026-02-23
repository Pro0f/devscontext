"""Custom exceptions for DevsContext.

This module defines a hierarchy of exceptions used throughout DevsContext.
All exceptions inherit from DevsContextError, making it easy to catch
all DevsContext-related errors in one place.

Exception Hierarchy:
    DevsContextError (base)
    ├── ConfigError - Configuration loading/validation failures
    ├── AdapterError (base for adapter failures)
    │   ├── JiraAdapterError
    │   ├── FirefliesAdapterError
    │   └── LocalDocsAdapterError
    ├── SynthesisError - LLM synthesis failures
    └── CacheError - Cache operation failures
"""

from typing import Any


class DevsContextError(Exception):
    """Base exception for all DevsContext errors.

    Args:
        message: Human-readable error message.
        details: Optional dictionary with additional error context.
    """

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} | Details: {self.details}"
        return self.message


class ConfigError(DevsContextError):
    """Raised when configuration loading or validation fails.

    Examples:
        - Invalid YAML syntax in .devscontext.yaml
        - Missing required configuration values
        - Environment variable not found
    """


class AdapterError(DevsContextError):
    """Base exception for adapter-related errors.

    All adapter-specific exceptions should inherit from this class.
    This allows catching all adapter errors with a single except clause.

    Args:
        message: Human-readable error message.
        adapter_name: Name of the adapter that raised the error.
        details: Optional dictionary with additional error context.
    """

    def __init__(
        self,
        message: str,
        adapter_name: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details)
        self.adapter_name = adapter_name

    def __str__(self) -> str:
        base = f"[{self.adapter_name}] {self.message}"
        if self.details:
            return f"{base} | Details: {self.details}"
        return base


class JiraAdapterError(AdapterError):
    """Raised when Jira API operations fail.

    Examples:
        - Authentication failure (401)
        - Ticket not found (404)
        - Rate limiting (429)
        - Network errors
    """

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, adapter_name="jira", details=details)


class FirefliesAdapterError(AdapterError):
    """Raised when Fireflies API operations fail.

    Examples:
        - Authentication failure
        - GraphQL query errors
        - Rate limiting
        - Network errors
    """

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, adapter_name="fireflies", details=details)


class LocalDocsAdapterError(AdapterError):
    """Raised when local documentation operations fail.

    Examples:
        - Directory not found
        - Permission denied
        - Invalid file encoding
    """

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, adapter_name="local_docs", details=details)


class SynthesisError(DevsContextError):
    """Raised when LLM synthesis operations fail.

    Examples:
        - LLM API rate limiting
        - Invalid response format
        - Context too long
        - LLM not configured
    """


class CacheError(DevsContextError):
    """Raised when cache operations fail.

    Examples:
        - Serialization errors
        - Memory allocation failures
    """
