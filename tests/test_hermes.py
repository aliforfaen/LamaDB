"""
Tests for /api/hermes/* — Hermes Agent integration endpoints.

These are INTEGRATION tests — the routes make real HTTP calls to the
Hermes API at http://dev-vm:9119. The Hermes service must be running.
"""
import pytest
import pytest_asyncio
import bcrypt
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from app.config import settings


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
    """Get the database pool for direct DB queries."""
    from app.db import get_pool
    return get_pool()


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


# ---------------------------------------------------------------------------
# Test: health reachable
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hermes_health_reachable(client, admin_key):
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

@pytest.mark.asyncio
async def test_hermes_health_no_auth(client):
    """GET /api/hermes/health without key → 401."""
    response = await client.get("/api/hermes/health")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Test: status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hermes_status(client, admin_key):
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

@pytest.mark.asyncio
async def test_hermes_sessions_stats(client, admin_key):
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

@pytest.mark.asyncio
async def test_hermes_system(client, admin_key):
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

@pytest.mark.asyncio
async def test_hermes_model(client, admin_key):
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

@pytest.mark.asyncio
async def test_hermes_synced(client, admin_key):
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

@pytest.mark.asyncio
async def test_hermes_sync_trigger(client, admin_key):
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

@pytest.mark.asyncio
async def test_hermes_no_auth(client):
    """GET /api/hermes/status without key → 401."""
    response = await client.get("/api/hermes/status")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Test: models list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hermes_models(client, admin_key):
    """GET /api/hermes/models with admin key → 200."""
    response = await client.get(
        "/api/hermes/models",
        headers={"Authorization": "Bearer " + admin_key}
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Test: credentials pool
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hermes_credentials(client, admin_key):
    """GET /api/hermes/credentials with admin key → 200."""
    response = await client.get(
        "/api/hermes/credentials",
        headers={"Authorization": "Bearer " + admin_key}
    )
    assert response.status_code == 200
