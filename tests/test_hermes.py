"""
Tests for /api/hermes/* — Hermes Agent integration endpoints.

These are INTEGRATION tests — the routes make real HTTP calls to the
Hermes API at http://dev-vm:9119. The Hermes service must be running.
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
            "test-hermes-admin", key_hash, "admin", []
        )
    yield key_plain
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM api_keys WHERE name = $1", "test-hermes-admin")


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
            "test-hermes-read", key_hash, "read", []
        )
    yield key_plain
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM api_keys WHERE name = $1", "test-hermes-read")


@pytest_asyncio.fixture(scope="function")
async def hermes_reachable():
    """Skip the test if the Hermes service is unreachable.

    The /api/hermes/* routes make real HTTP calls to the Hermes Agent
    service (default http://dev-vm:9119). When that service is down,
    the upstream calls fail and tests cannot meaningfully exercise
    the integration.
    """
    hermes_url = os.environ.get("HERMES_URL", "http://dev-vm:9119")
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"{hermes_url}/health")
            if r.status_code >= 500:
                pytest.skip(f"Hermes service unhealthy: {r.status_code}")
    except Exception as e:
        pytest.skip(f"Hermes service unreachable at {hermes_url}: {type(e).__name__}")


# ---------------------------------------------------------------------------
# Test: health reachable
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_hermes_health_reachable(client, admin_key, hermes_reachable):
    """GET /api/hermes/health with admin key → 200, reachable=true."""
    response = await client.get(
        "/api/hermes/health",
        headers={"Authorization": "Bearer " + admin_key}
    )
    assert response.status_code == 200
    data = response.json()
    assert "reachable" in data
    assert data["reachable"] is True


# ---------------------------------------------------------------------------
# Test: health no auth
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_hermes_health_no_auth(client):
    """GET /api/hermes/health without key → 401."""
    response = await client.get("/api/hermes/health")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Test: status
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_hermes_status(client, admin_key, hermes_reachable):
    """GET /api/hermes/status with admin key → 200, contains version/gateway_state."""
    response = await client.get(
        "/api/hermes/status",
        headers={"Authorization": "Bearer " + admin_key}
    )
    assert response.status_code == 200
    data = response.json()
    assert "version" in data
    assert "gateway_state" in data


# ---------------------------------------------------------------------------
# Test: sessions stats
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_hermes_sessions_stats(client, admin_key, hermes_reachable):
    """GET /api/hermes/sessions/stats with admin key → 200, contains total/messages."""
    response = await client.get(
        "/api/hermes/sessions/stats",
        headers={"Authorization": "Bearer " + admin_key}
    )
    assert response.status_code == 200
    data = response.json()
    assert "total" in data
    assert "messages" in data


# ---------------------------------------------------------------------------
# Test: system stats
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_hermes_system(client, admin_key, hermes_reachable):
    """GET /api/hermes/system with admin key → 200, contains hostname/cpu_percent/memory."""
    response = await client.get(
        "/api/hermes/system",
        headers={"Authorization": "Bearer " + admin_key}
    )
    assert response.status_code == 200
    data = response.json()
    assert "hostname" in data
    assert "cpu_percent" in data
    assert "memory" in data


# ---------------------------------------------------------------------------
# Test: model info
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_hermes_model(client, admin_key, hermes_reachable):
    """GET /api/hermes/model with admin key → 200, contains model/provider."""
    response = await client.get(
        "/api/hermes/model",
        headers={"Authorization": "Bearer " + admin_key}
    )
    assert response.status_code == 200
    data = response.json()
    assert "model" in data
    assert "provider" in data


# ---------------------------------------------------------------------------
# Test: synced sessions
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_hermes_synced(client, admin_key, hermes_reachable):
    """GET /api/hermes/synced with admin key → 200, has sessions/count."""
    response = await client.get(
        "/api/hermes/synced",
        headers={"Authorization": "Bearer " + admin_key}
    )
    assert response.status_code == 200
    data = response.json()
    assert "sessions" in data
    assert "count" in data
    assert isinstance(data["sessions"], list)


# ---------------------------------------------------------------------------
# Test: sync trigger
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_hermes_sync_trigger(client, admin_key, hermes_reachable):
    """POST /api/hermes/sync with admin key → 200, status in result."""
    response = await client.post(
        "/api/hermes/sync",
        headers={"Authorization": "Bearer " + admin_key}
    )
    assert response.status_code == 200
    data = response.json()
    assert "status" in data


# ---------------------------------------------------------------------------
# Test: read role allowed on health
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_hermes_read_role_allowed(client, read_key):
    """GET /api/hermes/health with read key → 200."""
    response = await client.get(
        "/api/hermes/health",
        headers={"Authorization": "Bearer " + read_key}
    )
    assert response.status_code == 200, "read role should be allowed"


# ---------------------------------------------------------------------------
# Test: no auth on status
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_hermes_no_auth(client):
    """GET /api/hermes/status without key → 401."""
    response = await client.get("/api/hermes/status")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Test: models list
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_hermes_models(client, admin_key, hermes_reachable):
    """GET /api/hermes/models with admin key → 200."""
    response = await client.get(
        "/api/hermes/models",
        headers={"Authorization": "Bearer " + admin_key}
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Test: credentials pool
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_hermes_credentials(client, admin_key, hermes_reachable):
    """GET /api/hermes/credentials with admin key → 200."""
    response = await client.get(
        "/api/hermes/credentials",
        headers={"Authorization": "Bearer " + admin_key}
    )
    assert response.status_code == 200
