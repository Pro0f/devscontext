"""Simple TTL cache for DevsContext.

This module provides a simple in-memory cache with time-to-live (TTL)
expiration. It's used to cache context fetching results to avoid
repeated API calls.

Example:
    cache = SimpleCache(ttl=900, max_size=100)  # 15 min TTL
    cache.set("key", {"data": "value"})
    result = cache.get("key")  # Returns {"data": "value"}
    # After 15 minutes...
    result = cache.get("key")  # Returns None (expired)
"""

from __future__ import annotations

import time
from typing import Any

from devscontext.constants import DEFAULT_CACHE_MAX_SIZE, DEFAULT_CACHE_TTL_SECONDS


class CacheEntry:
    """A cache entry with value and expiration time.

    Attributes:
        value: The cached value.
        expires_at: Monotonic time when this entry expires.
    """

    __slots__ = ("expires_at", "value")

    def __init__(self, value: Any, ttl: float) -> None:
        """Initialize a cache entry.

        Args:
            value: The value to cache.
            ttl: Time-to-live in seconds.
        """
        self.value = value
        self.expires_at = time.monotonic() + ttl

    def is_expired(self) -> bool:
        """Check if this entry has expired.

        Returns:
            True if expired, False otherwise.
        """
        return time.monotonic() > self.expires_at


class SimpleCache:
    """Simple in-memory TTL cache.

    Uses a dict with timestamps for expiration. Evicts expired entries
    lazily on access and when the cache is full.

    Attributes:
        _cache: The underlying cache dictionary.
        _ttl: Time-to-live in seconds for new entries.
        _max_size: Maximum number of entries.
    """

    def __init__(
        self,
        ttl: float = DEFAULT_CACHE_TTL_SECONDS,
        max_size: int = DEFAULT_CACHE_MAX_SIZE,
    ) -> None:
        """Initialize the cache.

        Args:
            ttl: Time-to-live in seconds for cache entries. Default 15 minutes.
            max_size: Maximum number of items in cache. Default 100.
        """
        self._cache: dict[str, CacheEntry] = {}
        self._ttl = ttl
        self._max_size = max_size

    def get(self, key: str) -> Any | None:
        """Get a value from the cache.

        Args:
            key: Cache key.

        Returns:
            Cached value or None if not found/expired.
        """
        entry = self._cache.get(key)

        if entry is None:
            return None

        if entry.is_expired():
            del self._cache[key]
            return None

        return entry.value

    def set(self, key: str, value: Any) -> None:
        """Set a value in the cache.

        Evicts expired entries if cache is full, then evicts the oldest
        entry if still at capacity.

        Args:
            key: Cache key.
            value: Value to cache.
        """
        # Evict expired entries if we're at max size
        if len(self._cache) >= self._max_size and key not in self._cache:
            self._evict_expired()

        # If still at max size, evict oldest entry
        if len(self._cache) >= self._max_size and key not in self._cache:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]

        self._cache[key] = CacheEntry(value, self._ttl)

    def invalidate(self, key: str) -> None:
        """Remove a specific key from the cache.

        Args:
            key: Cache key to remove.
        """
        self._cache.pop(key, None)

    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()

    def _evict_expired(self) -> None:
        """Remove all expired entries from the cache."""
        now = time.monotonic()
        expired_keys = [key for key, entry in self._cache.items() if now > entry.expires_at]
        for key in expired_keys:
            del self._cache[key]

    def __len__(self) -> int:
        """Return the number of entries in the cache.

        Note: This includes potentially expired entries.

        Returns:
            Number of cache entries.
        """
        return len(self._cache)


# Alias for backwards compatibility
ContextCache = SimpleCache
