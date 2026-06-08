"""In-memory caching layer for dashboard and module endpoints."""
import time
import functools
import asyncio
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class CacheEntry:
    """A single cache entry with expiry and tags."""

    __slots__ = ("key", "value", "expires_at", "tags")

    def __init__(self, key: str, value: Any, ttl: float = 60, tags: list[str] | None = None):
        self.key = key
        self.value = value
        self.expires_at = time.monotonic() + ttl
        self.tags = tags or []

    def is_expired(self) -> bool:
        return time.monotonic() > self.expires_at


class CacheManager:
    """Singleton in-memory cache with TTL and tag-based invalidation."""

    def __init__(self):
        self._store: dict[str, CacheEntry] = {}
        self._hits: int = 0
        self._misses: int = 0
        self._expired: int = 0

    def get(self, key: str) -> Any | None:
        """Get a cached value. Returns None if missing or expired."""
        entry = self._store.get(key)
        if entry is None:
            self._misses += 1
            return None
        if entry.is_expired():
            del self._store[key]
            self._expired += 1
            self._misses += 1
            return None
        self._hits += 1
        return entry.value

    def set(self, key: str, value: Any, ttl: float = 60, tags: list[str] | None = None) -> None:
        """Set a cache entry with TTL and optional invalidation tags."""
        self._store[key] = CacheEntry(key=key, value=value, ttl=ttl, tags=tags)

    def invalidate(self, tag: str) -> int:
        """Invalidate all entries matching the tag. Returns count removed."""
        removed = 0
        for key in list(self._store.keys()):
            entry = self._store.get(key)
            if entry and tag in entry.tags:
                del self._store[key]
                removed += 1
        if removed:
            logger.info(f"Cache invalidated tag='{tag}': {removed} entries cleared")
        return removed

    def stats(self) -> dict:
        """Return hit/miss/expired counts and current entry count."""
        self._clean_expired()
        return {
            "hits": self._hits,
            "misses": self._misses,
            "expired": self._expired,
            "entries": len(self._store),
        }

    def _clean_expired(self) -> None:
        """Remove all expired entries."""
        for key in list(self._store.keys()):
            entry = self._store.get(key)
            if entry and entry.is_expired():
                del self._store[key]
                self._expired += 1


# Global singleton
cache_manager = CacheManager()


def cached(
    ttl_seconds: float = 60,
    invalidate_tags: list[str] | None = None,
    key_prefix: str = "",
):
    """
    Decorator for async FastAPI route handlers that caches responses.

    The cache key is derived from the route path + query params.
    Only GET requests are cached.

    Usage:
        @router.get("/overview")
        @cached(ttl_seconds=60, invalidate_tags=["events", "documents"])
        async def overview(user: AuthUser = Depends(require_admin)):
            ...
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            cache_key = _build_cache_key(key_prefix or func.__name__, kwargs)
            cached_value = cache_manager.get(cache_key)
            if cached_value is not None:
                return cached_value

            result = await func(*args, **kwargs)
            cache_manager.set(cache_key, result, ttl=ttl_seconds, tags=invalidate_tags)
            return result
        return wrapper
    return decorator


def _build_cache_key(prefix: str, kwargs: dict) -> str:
    """Build a deterministic cache key from prefix and query params."""
    request = kwargs.get("request")
    if request is not None:
        path = request.url.path
        qs = str(sorted(request.query_params.items()))
        return f"{prefix}:{path}:{qs}"
    return f"{prefix}:no-request"
