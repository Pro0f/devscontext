"""Simple TTL cache for DevsContext."""

import time
from typing import Any


class CacheEntry:
    """A cache entry with value and expiration time."""

    __slots__ = ("value", "expires_at")

    def __init__(self, value: Any, ttl: float) -> None:
        self.value = value
        self.expires_at = time.monotonic() + ttl

    def is_expired(self) -> bool:
        return time.monotonic() > self.expires_at


class SimpleCache:
    """Simple in-memory TTL cache.

    Uses a dict with timestamps for expiration.
    Default TTL is 15 minutes (900 seconds).
    """

    def __init__(self, ttl: float = 900, max_size: int = 100) -> None:
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

        Evicts expired entries if cache is full.

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
        expired_keys = [
            key for key, entry in self._cache.items()
            if now > entry.expires_at
        ]
        for key in expired_keys:
            del self._cache[key]

    def __len__(self) -> int:
        """Return the number of entries in the cache (including expired)."""
        return len(self._cache)


# Alias for backwards compatibility
ContextCache = SimpleCache
