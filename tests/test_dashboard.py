"""
Tests for the Dashboard Management API (Phase 5A).

Uses httpx ASGITransport to test the FastAPI app directly.
Tests use the real database (migrations already run on startup via docker compose).
"""
import pytest
import pytest_asyncio
import bcrypt
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from app.config import settings


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    """
    Create a temporary admin API key for testing.
    Yields the plain-text key.
    """
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
            "test-admin",
            key_hash,
            "admin",
            []
        )

    yield key_plain

    # Cleanup
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM api_keys WHERE name = $1", "test-admin")


@pytest_asyncio.fixture(scope="function")
async def non_admin_key(db_pool):
    """
    Create a temporary read-only API key for testing 403 responses.
    Yields the plain-text key.
    """
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
            "test-readonly",
            key_hash,
            "read",
            []
        )

    yield key_plain

    # Cleanup
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM api_keys WHERE name = $1", "test-readonly")


@pytest_asyncio.fixture(scope="function")
async def sample_documents(db_pool):
    """Create sample documents for overview testing."""
    doc_ids = []
    async with db_pool.acquire() as conn:
        for i in range(3):
            row = await conn.fetchrow(
                """
                INSERT INTO documents (source_type, title, content, tags)
                VALUES ($1, $2, $3, $4)
                RETURNING id
                """,
                "test",
                f"Test Document {i}",
                f"Content for test document {i}",
                ["test"]
            )
            doc_ids.append(row["id"])

    yield doc_ids

    # Cleanup
    async with db_pool.acquire() as conn:
        for doc_id in doc_ids:
            await conn.execute("DELETE FROM documents WHERE id = $1", doc_id)


# ---------------------------------------------------------------------------
# Test: overview endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_overview_returns_stats(client, admin_key, db_pool, sample_documents):
    """GET /api/dashboard/overview returns all four stat categories."""
    response = await client.get(
        "/api/dashboard/overview",
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200
    data = response.json()

    # Must have all four stat categories
    assert "documents" in data
    assert "feeds" in data
    assert "monitors" in data
    assert "events" in data

    # Documents sub-stats
    assert "total" in data["documents"]
    assert "today" in data["documents"]
    assert isinstance(data["documents"]["total"], int)
    assert isinstance(data["documents"]["today"], int)

    # Feeds sub-stats
    assert "total" in data["feeds"]

    # Monitors sub-stats
    assert "up" in data["monitors"]
    assert "down" in data["monitors"]
    assert "unknown" in data["monitors"]

    # Events sub-stats
    assert "today" in data["events"]
    assert "delta_yesterday" in data["events"]


@pytest.mark.asyncio
async def test_overview_requires_admin(client, non_admin_key):
    """GET /api/dashboard/overview returns 403 for non-admin users."""
    response = await client.get(
        "/api/dashboard/overview",
        headers={"Authorization": f"Bearer {non_admin_key}"}
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Test: modules endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_modules(client, admin_key):
    """GET /api/dashboard/modules returns module list with metadata."""
    response = await client.get(
        "/api/dashboard/modules",
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200
    data = response.json()

    assert "modules" in data
    assert isinstance(data["modules"], list)

    # Each module should have name, description, version, enabled, directory
    for mod in data["modules"]:
        assert "name" in mod
        assert "description" in mod
        assert "version" in mod
        assert "enabled" in mod
        assert "directory" in mod


@pytest.mark.asyncio
async def test_toggle_module(client, admin_key):
    """POST /api/dashboard/modules/{name}/toggle writes .state file."""
    # Toggle feeds module (it should exist)
    response = await client.post(
        "/api/dashboard/modules/feeds/toggle",
        json={"enabled": False},
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "feeds"
    assert data["enabled"] is False
    assert data["restart_required"] is True

    # Verify .state file was written
    from pathlib import Path
    state_file = Path(__file__).parent.parent / "modules" / "feeds" / ".state"
    assert state_file.exists()

    import json
    state = json.loads(state_file.read_text())
    assert state["enabled"] is False

    # Toggle back
    response = await client.post(
        "/api/dashboard/modules/feeds/toggle",
        json={"enabled": True},
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_toggle_module_not_found(client, admin_key):
    """POST /api/dashboard/modules/{name}/toggle returns 404 for nonexistent module."""
    response = await client.post(
        "/api/dashboard/modules/nonexistent-module-xyz/toggle",
        json={"enabled": False},
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Test: health endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_detail(client, admin_key):
    """GET /api/dashboard/health returns DB version, extensions, tables."""
    response = await client.get(
        "/api/dashboard/health",
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "healthy"
    assert "database" in data
    assert data["database"]["connected"] is True
    assert "version" in data["database"]
    assert "extensions" in data["database"]
    assert "tables" in data["database"]
    assert "pool" in data

    # Pool stats
    assert "active" in data["pool"]
    assert "idle" in data["pool"]
    assert "max" in data["pool"]


# ---------------------------------------------------------------------------
# Test: API keys endpoints
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_api_keys(client, admin_key):
    """GET /api/dashboard/api-keys returns keys without hashes."""
    response = await client.get(
        "/api/dashboard/api-keys",
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200
    data = response.json()

    assert "keys" in data
    assert isinstance(data["keys"], list)

    # No key_hash should ever be returned
    for key in data["keys"]:
        assert "key_hash" not in key
        assert "id" in key
        assert "name" in key
        assert "role" in key


@pytest.mark.asyncio
async def test_create_api_key(client, admin_key, db_pool):
    """POST /api/dashboard/api-keys returns raw key once."""
    response = await client.post(
        "/api/dashboard/api-keys",
        json={
            "name": "Test Create Key",
            "role": "agent",
            "scopes": ["feeds"]
        },
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200
    data = response.json()

    assert "key" in data
    assert data["key"].startswith("lamadb_live_")
    assert data["name"] == "Test Create Key"
    assert data["role"] == "agent"
    assert data["scopes"] == ["feeds"]
    assert "message" in data
    assert "id" in data

    # Verify key was actually stored
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, role, scopes FROM api_keys WHERE name = $1",
            "Test Create Key"
        )
        assert row is not None

    # Cleanup
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM api_keys WHERE name = $1", "Test Create Key")


@pytest.mark.asyncio
async def test_create_api_key_returns_key(client, admin_key):
    """POST /api/dashboard/api-keys response must include 'key' field."""
    response = await client.post(
        "/api/dashboard/api-keys",
        json={"name": "Key Field Test", "role": "read"},
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "key" in data
    assert len(data["key"]) > 0


@pytest.mark.asyncio
async def test_revoke_api_key(client, admin_key, db_pool):
    """DELETE /api/dashboard/api-keys/{id} sets active=false."""
    # Create a key first
    key_plain = f"test-revoke-{uuid4().hex[:8]}"
    key_hash = bcrypt.hashpw(
        f"{settings.api_key_salt}{key_plain}".encode(),
        bcrypt.gensalt()
    ).decode()

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO api_keys (name, key_hash, role, scopes)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            "test-revoke",
            key_hash,
            "read",
            []
        )
        key_id = str(row["id"])

    # Revoke it
    response = await client.delete(
        f"/api/dashboard/api-keys/{key_id}",
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["active"] is False
    assert data["id"] == key_id

    # Verify it's actually inactive in DB
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT active FROM api_keys WHERE id = $1",
            key_id
        )
        assert row["active"] is False


@pytest.mark.asyncio
async def test_revoke_api_key_not_found(client, admin_key):
    """DELETE /api/dashboard/api-keys/{id} returns 404 for nonexistent key."""
    fake_id = str(uuid4())
    response = await client.delete(
        f"/api/dashboard/api-keys/{fake_id}",
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_rotate_api_key(client, admin_key, db_pool):
    """POST /api/dashboard/api-keys/{id}/rotate returns new key."""
    # Create a key first
    key_plain = f"test-rotate-{uuid4().hex[:8]}"
    key_hash = bcrypt.hashpw(
        f"{settings.api_key_salt}{key_plain}".encode(),
        bcrypt.gensalt()
    ).decode()

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO api_keys (name, key_hash, role, scopes)
            VALUES ($1, $2, $3, $4)
            RETURNING id, name, role, scopes
            """,
            "test-rotate",
            key_hash,
            "agent",
            ["feeds"]
        )
        key_id = str(row["id"])

    # Rotate it
    response = await client.post(
        f"/api/dashboard/api-keys/{key_id}/rotate",
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200
    data = response.json()

    assert "key" in data
    assert data["key"].startswith("lamadb_live_")
    assert data["name"] == "test-rotate"
    assert data["role"] == "agent"
    assert data["scopes"] == ["feeds"]
    assert "message" in data

    # Cleanup
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM api_keys WHERE name = $1", "test-rotate")


@pytest.mark.asyncio
async def test_rotate_api_key_not_found(client, admin_key):
    """POST /api/dashboard/api-keys/{id}/rotate returns 404 for nonexistent key."""
    fake_id = str(uuid4())
    response = await client.post(
        f"/api/dashboard/api-keys/{fake_id}/rotate",
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 404
