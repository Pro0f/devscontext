"""Simple TTL cache for DevsContext."""

from typing import TypeVar

from cachetools import TTLCache

T = TypeVar("T")


class ContextCache:
    """TTL cache for context data."""

    def __init__(self, maxsize: int = 100, ttl: int = 300) -> None:
        """Initialize the cache.

        Args:
            maxsize: Maximum number of items in cache.
            ttl: Time-to-live in seconds for cache entries.
        """
        self._cache: TTLCache[str, object] = TTLCache(maxsize=maxsize, ttl=ttl)

    def get(self, key: str) -> object | None:
        """Get a value from the cache.

        Args:
            key: Cache key.

        Returns:
            Cached value or None if not found/expired.
        """
        return self._cache.get(key)

    def set(self, key: str, value: object) -> None:
        """Set a value in the cache.

        Args:
            key: Cache key.
            value: Value to cache.
        """
        self._cache[key] = value

    def invalidate(self, key: str) -> None:
        """Remove a specific key from the cache.

        Args:
            key: Cache key to remove.
        """
        self._cache.pop(key, None)

    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()
