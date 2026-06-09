"""Tests for the in-memory caching layer (pure unit tests, no container needed)."""
import time
import json
import pytest
from app.cache import CacheManager, cache_manager


class TestCacheManager:
    """Unit tests for the CacheManager singleton."""

    def test_set_and_get(self):
        """Basic set/get with no TTL."""
        c = CacheManager()
        c._store.clear()
        c.set("test_key", {"value": 42})
        assert c.get("test_key") == {"value": 42}

    def test_miss_returns_none(self):
        """Getting an unset key returns None."""
        c = CacheManager()
        c._store.clear()
        assert c.get("nonexistent") is None

    def test_ttl_expiry(self):
        """Value expires after TTL."""
        c = CacheManager()
        c._store.clear()
        c.set("temp", "data", ttl=0.01)  # 10ms TTL
        assert c.get("temp") == "data"
        time.sleep(0.02)
        assert c.get("temp") is None

    def test_invalidate_by_tag(self):
        """Invalidating a tag removes all matching entries."""
        c = CacheManager()
        c._store.clear()
        c.set("a", 1, tags=["events"])
        c.set("b", 2, tags=["monitors"])
        c.set("c", 3, tags=["events", "documents"])
        c.invalidate("events")
        assert c.get("a") is None
        assert c.get("b") == 2  # not tagged events
        assert c.get("c") is None  # tagged events AND documents

    def test_invalidate_nonexistent_tag(self):
        """Invalidating a tag with no entries should not raise."""
        c = CacheManager()
        c._store.clear()
        c.invalidate("nonexistent")  # no error

    def test_stats(self):
        """stats() returns hit/miss/expired/entry counts."""
        c = CacheManager()
        c._store.clear()
        c.get("miss1")  # miss
        c.get("miss2")  # miss
        c.set("hit", "value")
        c.get("hit")  # hit
        c.get("hit")  # hit
        c.set("exp", "val", ttl=0.01)
        time.sleep(0.02)
        c.get("exp")  # expired
        stats = c.stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 3  # miss1 + miss2 + expired get
        assert stats["expired"] == 1
        assert stats["entries"] >= 0
