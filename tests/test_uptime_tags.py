"""
Tests for the Uptime Kuma tags integration.

Verifies:
1. MonitorPayload accepts tags
2. Webhook handler stores tags in the DB
3. Migration adds the column successfully
"""
import pytest
import pytest_asyncio

import httpx
import os

from tests.conftest import container_required

BASE_URL = os.environ.get("LAMADB_TEST_URL", "http://localhost:8000")
AUTH_HEADERS = {"Authorization": "Bearer lamadb_test_key_2026"}

# Payload with tags included
VALID_PAYLOAD_WITH_TAGS = {
    "heartbeat": {
        "status": 1,
        "msg": "OK",
        "duration": 120,
        "time": "2026-05-30T10:00:00+02:00"
    },
    "monitor": {
        "id": 100,
        "name": "Test Monitor with Tags",
        "url": "https://test.example.com",
        "tags": ["production", "critical", "api"]
    }
}

# Payload with no tags
VALID_PAYLOAD_NO_TAGS = {
    "heartbeat": {
        "status": 0,
        "msg": "Connection refused",
        "duration": 500,
        "time": "2026-05-30T10:01:00+02:00"
    },
    "monitor": {
        "id": 101,
        "name": "Test Monitor No Tags",
        "url": "https://test2.example.com"
    }
}


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


# ---------------------------------------------------------------------------
# Test 1: MonitorPayload accepts tags
# ---------------------------------------------------------------------------
@container_required
@pytest.mark.asyncio
async def test_monitor_payload_accepts_tags():
    """MonitorPayload model accepts and stores tags field."""
    from modules.uptime.models import MonitorPayload

    payload = MonitorPayload(
        id=1,
        name="Test Monitor",
        url="https://test.com",
        tags=["production", "critical"]
    )
    assert [t.name for t in payload.tags] == ["production", "critical"]


@container_required
@pytest.mark.asyncio
async def test_monitor_payload_tags_default_to_empty_list():
    """MonitorPayload tags defaults to empty list when not provided."""
    from modules.uptime.models import MonitorPayload

    payload = MonitorPayload(
        id=1,
        name="Test Monitor",
        url="https://test.com"
    )
    assert [t.name for t in payload.tags] == []


# ---------------------------------------------------------------------------
# Test 2: Webhook handler stores tags in the DB
# ---------------------------------------------------------------------------
@container_required
@pytest.mark.asyncio
async def test_webhook_stores_tags_in_db(client, db_pool):
    """POST payload with tags stores them correctly in monitor_status."""
    response = await client.post("/api/uptime/webhook", json=VALID_PAYLOAD_WITH_TAGS)
    assert response.status_code == 201
    data = response.json()
    assert data.get("received") is True

    # Verify tags were stored in the database
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT monitor_id, monitor_name, status, tags "
            "FROM monitor_status WHERE monitor_id = $1",
            "100"
        )
        assert row is not None
        assert row["monitor_name"] == "Test Monitor with Tags"
        assert row["status"] == 1
        # Verify tags were stored as an array
        assert row["tags"] == ["production", "critical", "api"]


@container_required
@pytest.mark.asyncio
async def test_webhook_stores_empty_tags_for_monitor_without_tags(client, db_pool):
    """POST payload without tags stores empty array in monitor_status."""
    response = await client.post("/api/uptime/webhook", json=VALID_PAYLOAD_NO_TAGS)
    assert response.status_code == 201

    # Verify empty tags array was stored
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT monitor_id, monitor_name, tags "
            "FROM monitor_status WHERE monitor_id = $1",
            "101"
        )
        assert row is not None
        assert row["monitor_name"] == "Test Monitor No Tags"
        # Tags should be an empty array (default)
        assert row["tags"] == []


# ---------------------------------------------------------------------------
# Test 3: Migration adds the column successfully
# ---------------------------------------------------------------------------
@container_required
@pytest.mark.asyncio
async def test_migration_adds_tags_column(client, db_pool):
    """The tags column exists on monitor_status with correct type and default."""
    async with db_pool.acquire() as conn:
        # Check column exists
        col_exists = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'monitor_status' AND column_name = 'tags'
            )
            """
        )
        assert col_exists is True, "tags column should exist on monitor_status"

        # Check column type is TEXT[]
        col_type = await conn.fetchval(
            """
            SELECT data_type FROM information_schema.columns
            WHERE table_name = 'monitor_status' AND column_name = 'tags'
            """
        )
        assert col_type == "ARRAY", f"tags column should be ARRAY type, got {col_type}"

        # Check the default is '{}'
        default = await conn.fetchval(
            """
            SELECT column_default FROM information_schema.columns
            WHERE table_name = 'monitor_status' AND column_name = 'tags'
            """
        )
        assert default == "'{}'::text[]", f"tags column default should be '{{}}'::text[], got {default}"
