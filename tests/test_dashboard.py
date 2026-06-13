"""
Tests for the Dashboard Management API (Phase 5A).

Uses httpx against the running container. Tests use the real
database (migrations already run on startup via docker compose).
"""
import httpx
import os
import pytest
import pytest_asyncio
import bcrypt
from uuid import uuid4

from tests.conftest import container_required

BASE_URL = os.environ.get("LAMADB_TEST_URL", "http://localhost:8000")
AUTH_HEADERS = {"Authorization": "Bearer lamadb_test_key_2026"}

from app.config import settings


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def client():
    """Create an async httpx client pointing at the running container."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as ac:
        yield ac


@pytest_asyncio.fixture(scope="function")
async def db_pool():
    """Get the database pool for direct DB queries in tests.

    Creates a fresh asyncpg pool against the running container's
    Postgres so tests can seed/clean up alongside the live API.
    """
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

@container_required
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


@container_required
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

@container_required
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


@container_required
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


@container_required
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

@container_required
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

@container_required
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


@container_required
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


@container_required
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


@container_required
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


@container_required
@pytest.mark.asyncio
async def test_revoke_api_key_not_found(client, admin_key):
    """DELETE /api/dashboard/api-keys/{id} returns 404 for nonexistent key."""
    fake_id = str(uuid4())
    response = await client.delete(
        f"/api/dashboard/api-keys/{fake_id}",
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 404


@container_required
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


@container_required
@pytest.mark.asyncio
async def test_rotate_api_key_not_found(client, admin_key):
    """POST /api/dashboard/api-keys/{id}/rotate returns 404 for nonexistent key."""
    fake_id = str(uuid4())
    response = await client.post(
        f"/api/dashboard/api-keys/{fake_id}/rotate",
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Test: PATCH /api/dashboard/api-keys/{key_id}
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_patch_api_key_update_name(client, admin_key, db_pool):
    """PATCH /api/dashboard/api-keys/{id} updates name."""
    # Create a key first
    key_hash = bcrypt.hashpw(
        f"{settings.api_key_salt}test-patch-key".encode(),
        bcrypt.gensalt()
    ).decode()

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO api_keys (name, key_hash, role, scopes)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            "test-patch-original",
            key_hash,
            "read",
            []
        )
        key_id = str(row["id"])

    # Patch the name
    response = await client.patch(
        f"/api/dashboard/api-keys/{key_id}",
        json={"name": "test-patch-updated"},
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "test-patch-updated"
    assert data["id"] == key_id
    assert "last_used_at" in data

    # Cleanup
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM api_keys WHERE id = $1", key_id)


@container_required
@pytest.mark.asyncio
async def test_patch_api_key_update_role(client, admin_key, db_pool):
    """PATCH /api/dashboard/api-keys/{id} updates role."""
    key_hash = bcrypt.hashpw(
        f"{settings.api_key_salt}test-patch-role".encode(),
        bcrypt.gensalt()
    ).decode()

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO api_keys (name, key_hash, role, scopes)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            "test-patch-role",
            key_hash,
            "read",
            []
        )
        key_id = str(row["id"])

    # Patch the role
    response = await client.patch(
        f"/api/dashboard/api-keys/{key_id}",
        json={"role": "admin"},
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "admin"

    # Cleanup
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM api_keys WHERE id = $1", key_id)


@container_required
@pytest.mark.asyncio
async def test_patch_api_key_update_scopes(client, admin_key, db_pool):
    """PATCH /api/dashboard/api-keys/{id} updates scopes."""
    key_hash = bcrypt.hashpw(
        f"{settings.api_key_salt}test-patch-scopes".encode(),
        bcrypt.gensalt()
    ).decode()

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO api_keys (name, key_hash, role, scopes)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            "test-patch-scopes",
            key_hash,
            "agent",
            ["feeds"]
        )
        key_id = str(row["id"])

    # Patch scopes
    response = await client.patch(
        f"/api/dashboard/api-keys/{key_id}",
        json={"scopes": ["feeds", "uptime"]},
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["scopes"] == ["feeds", "uptime"]

    # Cleanup
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM api_keys WHERE id = $1", key_id)


@container_required
@pytest.mark.asyncio
async def test_patch_api_key_invalid_scopes(client, admin_key, db_pool):
    """PATCH /api/dashboard/api-keys/{id} returns 400 for invalid scopes."""
    key_hash = bcrypt.hashpw(
        f"{settings.api_key_salt}test-patch-invalid".encode(),
        bcrypt.gensalt()
    ).decode()

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO api_keys (name, key_hash, role, scopes)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            "test-patch-invalid",
            key_hash,
            "agent",
            []
        )
        key_id = str(row["id"])

    # Patch with invalid scope
    response = await client.patch(
        f"/api/dashboard/api-keys/{key_id}",
        json={"scopes": ["totally_fake_scope_xyz"]},
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 400
    data = response.json()
    assert "Invalid scopes" in data["detail"]
    assert "totally_fake_scope_xyz" in data["detail"]

    # Cleanup
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM api_keys WHERE id = $1", key_id)


@container_required
@pytest.mark.asyncio
async def test_patch_api_key_not_found(client, admin_key):
    """PATCH /api/dashboard/api-keys/{id} returns 404 for nonexistent key."""
    fake_id = str(uuid4())
    response = await client.patch(
        f"/api/dashboard/api-keys/{fake_id}",
        json={"name": "nope"},
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 404


@container_required
@pytest.mark.asyncio
async def test_patch_api_key_empty_body(client, admin_key, db_pool):
    """PATCH /api/dashboard/api-keys/{id} returns 400 when no fields provided."""
    key_hash = bcrypt.hashpw(
        f"{settings.api_key_salt}test-patch-empty".encode(),
        bcrypt.gensalt()
    ).decode()

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO api_keys (name, key_hash, role, scopes)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            "test-patch-empty",
            key_hash,
            "read",
            []
        )
        key_id = str(row["id"])

    # Patch with empty body
    response = await client.patch(
        f"/api/dashboard/api-keys/{key_id}",
        json={},
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 400
    assert "No fields to update" in response.json()["detail"]

    # Cleanup
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM api_keys WHERE id = $1", key_id)


# ---------------------------------------------------------------------------
# Test: GET /api/dashboard/api-keys/stats
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_api_key_stats(client, admin_key, db_pool):
    """GET /api/dashboard/api-keys/stats returns active/inactive/stale counts."""
    # Create some keys for testing
    keys_created = []
    for i in range(3):
        key_hash = bcrypt.hashpw(
            f"{settings.api_key_salt}test-stats-{i}".encode(),
            bcrypt.gensalt()
        ).decode()
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO api_keys (name, key_hash, role, scopes, active)
                VALUES ($1, $2, $3, $4, $5)
                """,
                f"test-stats-{i}",
                key_hash,
                "read",
                [],
                i < 2,  # first 2 active, third inactive
            )
            keys_created.append(f"test-stats-{i}")

    response = await client.get(
        "/api/dashboard/api-keys/stats",
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "active" in data
    assert "inactive" in data
    assert "stale" in data
    assert isinstance(data["active"], int)
    assert isinstance(data["inactive"], int)
    assert isinstance(data["stale"], int)
    assert data["active"] >= 2
    assert data["inactive"] >= 1

    # Cleanup
    async with db_pool.acquire() as conn:
        for name in keys_created:
            await conn.execute("DELETE FROM api_keys WHERE name = $1", name)


@container_required
@pytest.mark.asyncio
async def test_api_key_stats_requires_admin(client, non_admin_key):
    """GET /api/dashboard/api-keys/stats returns 403 for non-admin."""
    response = await client.get(
        "/api/dashboard/api-keys/stats",
        headers={"Authorization": f"Bearer {non_admin_key}"}
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Test: last_used_at in list response
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_list_api_keys_includes_last_used_at(client, admin_key):
    """GET /api/dashboard/api-keys returns last_used_at field."""
    response = await client.get(
        "/api/dashboard/api-keys",
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "keys" in data
    for key in data["keys"]:
        assert "last_used_at" in key


# ---------------------------------------------------------------------------
# Tests: module-health status logic (Phase 12 bugfix)
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_module_health_status_shape(client, admin_key):
    """GET /api/dashboard/module-health returns a list of modules with status info."""
    response = await client.get(
        "/api/dashboard/module-health",
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "modules" in data
    for m in data["modules"]:
        assert "name" in m
        assert "status" in m
        assert m["status"] in ("green", "yellow", "red", "grey")
        assert "enabled" in m
        assert "recent_errors" in m
        assert "last_event" in m


@container_required
@pytest.mark.asyncio
async def test_module_health_passive_module_not_red(
    client, admin_key
):
    """A passive module (no recent input) with no recent errors must NOT be red.

    Reproduces the ntfy bug: ntfy only logs events when notifications arrive.
    A 7h gap with no events is normal — the old 1h/2h threshold incorrectly
    flagged it red.

    We verify the inverse on a real enabled module: 'dashboard' (the management
    UI) typically has no events of its own — if it ever accumulates a recent
    error, status will be red, but without one it should be yellow at worst.
    """
    response = await client.get(
        "/api/dashboard/module-health",
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200
    modules = {m["name"]: m for m in response.json()["modules"]}
    # Every enabled module must be in {green, yellow, grey} — never red —
    # UNLESS it has a recent error. We sanity-check that at least the ntfy/
    # wiki pattern (no recent input, no errors) is not flagged red.
    for name, m in modules.items():
        if m["enabled"] and not m["recent_errors"]:
            assert m["status"] in ("green", "yellow", "grey"), (
                f"Module {name!r} has no recent errors but reports status={m['status']!r} — "
                "the passive-module bug may have regressed"
            )


@container_required
@pytest.mark.asyncio
async def test_module_health_requires_admin(client, non_admin_key):
    """GET /api/dashboard/module-health returns 403 for non-admin users."""
    response = await client.get(
        "/api/dashboard/module-health",
        headers={"Authorization": f"Bearer {non_admin_key}"}
    )
    assert response.status_code == 403
