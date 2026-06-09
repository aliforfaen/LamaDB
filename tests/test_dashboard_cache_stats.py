"""Tests for the Dashboard Cache Stats endpoint (GET /api/dashboard/cache-stats)."""
import pytest
import pytest_asyncio
import bcrypt
from uuid import uuid4

import httpx
import os

from tests.conftest import container_required

BASE_URL = os.environ.get("LAMADB_TEST_URL", "http://localhost:8000")
AUTH_HEADERS = {"Authorization": "Bearer lamadb_test_key_2026"}

from app.config import settings


@pytest_asyncio.fixture(scope="function")
async def client():
    """Create an async httpx client pointing at the running container."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as ac:
        yield ac


@pytest_asyncio.fixture(scope="function")
async def db_pool():
    """Create a fresh asyncpg pool against the running container's Postgres."""
    import asyncpg
    pool = await asyncpg.create_pool(
        dsn=settings.database_url, min_size=1, max_size=4, command_timeout=60,
    )
    try:
        yield pool
    finally:
        await pool.close()


@pytest_asyncio.fixture(scope="function")
async def admin_key(db_pool):
    """Create a temporary admin API key for testing. Yields the plain-text key."""
    key_plain = f"test-admin-{uuid4().hex[:8]}"
    key_hash = bcrypt.hashpw(
        f"{settings.api_key_salt}{key_plain}".encode(),
        bcrypt.gensalt()
    ).decode()

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO api_keys (name, key_hash, role, scopes)
            VALUES ($1, $2, $3, $4)
            """,
            "test-admin-cache",
            key_hash,
            "admin",
            []
        )

    yield key_plain

    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM api_keys WHERE name = $1", "test-admin-cache")


@pytest_asyncio.fixture(scope="function")
async def non_admin_key(db_pool):
    """Create a temporary read-only API key for testing 401 responses."""
    key_plain = f"test-readonly-{uuid4().hex[:8]}"
    key_hash = bcrypt.hashpw(
        f"{settings.api_key_salt}{key_plain}".encode(),
        bcrypt.gensalt()
    ).decode()

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO api_keys (name, key_hash, role, scopes)
            VALUES ($1, $2, $3, $4)
            """,
            "test-readonly-cache",
            key_hash,
            "read",
            []
        )

    yield key_plain

    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM api_keys WHERE name = $1", "test-readonly-cache")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_cache_stats_returns_valid_shape(client, admin_key):
    """GET /api/dashboard/cache-stats returns hits/misses/expired/entries."""
    response = await client.get(
        "/api/dashboard/cache-stats",
        params={"key": admin_key}
    )
    assert response.status_code == 200
    data = response.json()
    assert "hits" in data
    assert "misses" in data
    assert "expired" in data
    assert "entries" in data
    assert isinstance(data["hits"], int)
    assert isinstance(data["misses"], int)
    assert isinstance(data["expired"], int)
    assert isinstance(data["entries"], int)


@container_required
@pytest.mark.asyncio
async def test_cache_stats_reflects_activity(client, admin_key):
    """Cache stats reflect actual cache hits and misses.

    Drives activity through the API (cached endpoints) so the live
    container's cache manager records real hits/misses.
    """
    # First call populates the cache (miss), second call hits it
    headers = {"Authorization": f"Bearer {admin_key}"}
    for _ in range(3):
        r = await client.get("/api/dashboard/overview", headers=headers)
        assert r.status_code == 200

    response = await client.get(
        "/api/dashboard/cache-stats",
        params={"key": admin_key}
    )
    assert response.status_code == 200
    data = response.json()
    # After at least 3 overview calls we expect hits + misses recorded
    assert data["hits"] + data["misses"] >= 1
    assert isinstance(data["entries"], int)


@container_required
@pytest.mark.asyncio
async def test_cache_stats_rejects_bad_key(client):
    """GET /api/dashboard/cache-stats returns 401 for invalid key."""
    response = await client.get(
        "/api/dashboard/cache-stats",
        params={"key": "badkey"}
    )
    assert response.status_code == 401


@container_required
@pytest.mark.asyncio
async def test_cache_stats_rejects_non_admin(client, non_admin_key):
    """GET /api/dashboard/cache-stats returns 401 for non-admin role."""
    response = await client.get(
        "/api/dashboard/cache-stats",
        params={"key": non_admin_key}
    )
    assert response.status_code == 401


@container_required
@pytest.mark.asyncio
async def test_cache_stats_requires_key(client):
    """GET /api/dashboard/cache-stats returns 422 when key param missing."""
    response = await client.get("/api/dashboard/cache-stats")
    assert response.status_code == 422
