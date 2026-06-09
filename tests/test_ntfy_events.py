"""
Tests for GET /api/ntfy/events — ntfy events cache endpoint.
"""
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
    """Create a temporary admin API key for testing."""
    key_plain = "test-admin-" + uuid4().hex[:8]
    key_hash = bcrypt.hashpw(
        (settings.api_key_salt + key_plain).encode(),
        bcrypt.gensalt()
    ).decode()
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO api_keys (name, key_hash, role, scopes) VALUES ($1, $2, $3, $4)",
            "test-ntfy-admin", key_hash, "admin", []
        )
    yield key_plain
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM api_keys WHERE name = $1", "test-ntfy-admin")


@pytest_asyncio.fixture(scope="function")
async def read_key(db_pool):
    """Create a temporary read-only API key for testing auth."""
    key_plain = "test-read-" + uuid4().hex[:8]
    key_hash = bcrypt.hashpw(
        (settings.api_key_salt + key_plain).encode(),
        bcrypt.gensalt()
    ).decode()
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO api_keys (name, key_hash, role, scopes) VALUES ($1, $2, $3, $4)",
            "test-ntfy-read", key_hash, "read", []
        )
    yield key_plain
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM api_keys WHERE name = $1", "test-ntfy-read")


# ---------------------------------------------------------------------------
# Test: get ntfy events (empty)
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_get_ntfy_events_empty(client, admin_key):
    """GET /api/ntfy/events → 200 with empty list when no events exist."""
    response = await client.get(
        "/api/ntfy/events",
        headers={"Authorization": "Bearer " + admin_key}
    )
    assert response.status_code == 200
    data = response.json()
    assert "messages" in data
    assert "count" in data
    assert isinstance(data["messages"], list)


# ---------------------------------------------------------------------------
# Test: get ntfy events returns events
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_get_ntfy_events_returns_events(client, admin_key, db_pool):
    """Directly insert an ntfy event and verify it appears in the endpoint."""
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO events (source, type, severity, title, body, metadata, tags)
            VALUES ('ntfy', 'test', 'critical', 'Test Event',
                    'Something failed', '{"priority": 5}', ARRAY['failure'])
            """
        )

    response = await client.get(
        "/api/ntfy/events",
        headers={"Authorization": "Bearer " + admin_key}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["count"] >= 1
    titles = [m.get("title") for m in data["messages"]]
    assert "Test Event" in titles


# ---------------------------------------------------------------------------
# Test: filter by priority=critical
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_get_ntfy_events_priority_critical(client, admin_key, db_pool):
    """priority=critical → SQL filters severity=critical."""
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO events (source, type, severity, title, body) VALUES
                ('ntfy', 'a', 'critical', 'Crit Event', 'body'),
                ('ntfy', 'b', 'info', 'Info Event', 'body')
            """
        )

    response = await client.get(
        "/api/ntfy/events?priority=critical",
        headers={"Authorization": "Bearer " + admin_key}
    )
    assert response.status_code == 200
    data = response.json()
    # The endpoint's SQL filters severity=critical, so only Crit Event should appear
    titles = [m["title"] for m in data["messages"]]
    assert "Crit Event" in titles
    # Info Event should not appear (different severity)
    assert "Info Event" not in titles


# ---------------------------------------------------------------------------
# Test: filter by priority=high
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_get_ntfy_events_priority_high(client, admin_key, db_pool):
    """priority=high → SQL filters severity IN (critical, warn)."""
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO events (source, type, severity, title, body) VALUES
                ('ntfy', 'a', 'critical', 'Crit Event', 'body'),
                ('ntfy', 'b', 'warn', 'Warn Event', 'body'),
                ('ntfy', 'c', 'info', 'Info Event', 'body')
            """
        )

    response = await client.get(
        "/api/ntfy/events?priority=high",
        headers={"Authorization": "Bearer " + admin_key}
    )
    assert response.status_code == 200
    data = response.json()
    titles = [m["title"] for m in data["messages"]]
    assert "Crit Event" in titles
    assert "Warn Event" in titles
    assert "Info Event" not in titles


# ---------------------------------------------------------------------------
# Test: since parameter
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_get_ntfy_events_since_param(client, admin_key):
    """since=1h, 6h, 24h all return 200 without error."""
    for since_val in ("1h", "6h", "24h"):
        response = await client.get(
            "/api/ntfy/events?since=" + since_val,
            headers={"Authorization": "Bearer " + admin_key}
        )
        assert response.status_code == 200, "since=" + since_val + " failed"


# ---------------------------------------------------------------------------
# Test: read role is allowed
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_get_ntfy_events_read_role_allowed(client, read_key):
    """Read role is allowed on ntfy/events (no scope restriction)."""
    response = await client.get(
        "/api/ntfy/events",
        headers={"Authorization": "Bearer " + read_key}
    )
    assert response.status_code == 200, "read role should be allowed"


# ---------------------------------------------------------------------------
# Test: no auth header
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_get_ntfy_events_no_auth(client):
    """No auth header → 401."""
    response = await client.get("/api/ntfy/events")
    assert response.status_code == 401
