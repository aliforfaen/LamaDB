"""Tests for the Dashboard Cache Stats endpoint (GET /api/dashboard/cache-stats)."""
import pytest
import pytest_asyncio
import bcrypt
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.cache import cache_manager


@pytest_asyncio.fixture(scope="function")
async def client():
    """Create an async test client for the FastAPI app."""
    from app.main import make_app

    app = make_app()

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(scope="function")
async def db_pool():
    """Get the database pool for direct DB queries in tests."""
    from app.db import get_pool
    return get_pool()


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


@pytest.mark.asyncio
async def test_cache_stats_reflects_activity(client, admin_key):
    """Cache stats reflect actual cache hits and misses."""
    # Seed some cache activity
    cache_manager._store.clear()
    cache_manager._hits = 0
    cache_manager._misses = 0
    cache_manager._expired = 0

    cache_manager.set("test-key", "value1")
    cache_manager.get("test-key")  # hit
    cache_manager.get("nonexistent")  # miss

    response = await client.get(
        "/api/dashboard/cache-stats",
        params={"key": admin_key}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["hits"] >= 1
    assert data["misses"] >= 1
    assert data["entries"] >= 1


@pytest.mark.asyncio
async def test_cache_stats_rejects_bad_key(client):
    """GET /api/dashboard/cache-stats returns 401 for invalid key."""
    response = await client.get(
        "/api/dashboard/cache-stats",
        params={"key": "badkey"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_cache_stats_rejects_non_admin(client, non_admin_key):
    """GET /api/dashboard/cache-stats returns 401 for non-admin role."""
    response = await client.get(
        "/api/dashboard/cache-stats",
        params={"key": non_admin_key}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_cache_stats_requires_key(client):
    """GET /api/dashboard/cache-stats returns 422 when key param missing."""
    response = await client.get("/api/dashboard/cache-stats")
    assert response.status_code == 422
