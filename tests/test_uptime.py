"""
Tests for the Uptime Kuma webhook module.

Uses httpx ASGITransport to test the FastAPI app directly.
Tests use the real database (migrations already run on startup via docker compose).
"""
import pytest
import pytest_asyncio

import httpx
import os

from tests.conftest import container_required

BASE_URL = os.environ.get("LAMADB_TEST_URL", "http://localhost:8000")
AUTH_HEADERS = {"Authorization": "Bearer lamadb_test_key_2026"}


VALID_PAYLOAD = {
    "heartbeat": {
        "status": 0,
        "msg": "connect ECONNREFUSED",
        "duration": 1523,
        "time": "2026-05-29T14:30:00+02:00"
    },
    "monitor": {
        "id": 42,
        "name": "Plex - Media Server",
        "url": "https://plex.notflix.no"
    }
}

VALID_PAYLOAD_UP = {
    "heartbeat": {
        "status": 1,
        "msg": "OK",
        "duration": 120,
        "time": "2026-05-29T14:35:00+02:00"
    },
    "monitor": {
        "id": 42,
        "name": "Plex - Media Server",
        "url": "https://plex.notflix.no"
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
# Test 1: webhook_creates_monitor_status
# ---------------------------------------------------------------------------
@container_required
@pytest.mark.asyncio
async def test_webhook_creates_monitor_status(client, db_pool):
    """POST valid payload creates a row in monitor_status."""
    response = await client.post("/api/uptime/webhook", json=VALID_PAYLOAD)
    assert response.status_code == 201
    data = response.json()
    assert data.get("received") is True

    # Verify the row was inserted
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT monitor_id, monitor_name, status, msg, duration_ms "
            "FROM monitor_status WHERE monitor_id = $1",
            "42"
        )
        assert row is not None
        assert row["monitor_name"] == "Plex - Media Server"
        assert row["status"] == 0
        assert row["msg"] == "connect ECONNREFUSED"
        assert row["duration_ms"] == 1523


# ---------------------------------------------------------------------------
# Test 2: webhook_creates_event
# ---------------------------------------------------------------------------
@container_required
@pytest.mark.asyncio
async def test_webhook_creates_event(client, db_pool):
    """POST valid payload also creates an event in the events table."""
    response = await client.post("/api/uptime/webhook", json=VALID_PAYLOAD)
    assert response.status_code == 201

    # Find the event that was created
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT source, type, severity, title, metadata "
            "FROM events WHERE source = 'uptime_kuma' ORDER BY ts DESC LIMIT 1"
        )
        assert row is not None
        assert row["source"] == "uptime_kuma"
        assert row["type"] == "monitor_status"
        assert row["title"] == "Plex - Media Server is DOWN"


# ---------------------------------------------------------------------------
# Test 3: webhook_down_status_critical_severity
# ---------------------------------------------------------------------------
@container_required
@pytest.mark.asyncio
async def test_webhook_down_status_critical_severity(client, db_pool):
    """status=0 (DOWN) maps to severity='critical' on the event."""
    response = await client.post("/api/uptime/webhook", json=VALID_PAYLOAD)
    assert response.status_code == 201

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT severity FROM events WHERE source = 'uptime_kuma' ORDER BY ts DESC LIMIT 1"
        )
        assert row["severity"] == "critical"


# ---------------------------------------------------------------------------
# Test 4: webhook_up_status_info_severity
# ---------------------------------------------------------------------------
@container_required
@pytest.mark.asyncio
async def test_webhook_up_status_info_severity(client, db_pool):
    """status=1 (UP) maps to severity='info' on the event."""
    response = await client.post("/api/uptime/webhook", json=VALID_PAYLOAD_UP)
    assert response.status_code == 201

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT severity FROM events WHERE source = 'uptime_kuma' ORDER BY ts DESC LIMIT 1"
        )
        assert row["severity"] == "info"


# ---------------------------------------------------------------------------
# Test 5: get_status_returns_latest_per_monitor
# ---------------------------------------------------------------------------
@container_required
@pytest.mark.asyncio
async def test_get_status_returns_latest_per_monitor(client, db_pool):
    """Insert 2 statuses for same monitor, GET /status returns only 1 (latest)."""
    async with db_pool.acquire() as conn:
        # Seed registry so the monitor exists in the merge
        await conn.execute(
            """
            INSERT INTO monitor_registry (monitor_id, monitor_name, monitor_url, monitor_type, tags, active, last_seen)
            VALUES ($1, $2, $3, $4, $5, true, now())
            ON CONFLICT (monitor_id) DO NOTHING
            """,
            "99", "Test Monitor", "http://test.com", "http", [],
        )
        # Insert two statuses
        await conn.execute(
            """
            INSERT INTO monitor_status (monitor_id, monitor_name, monitor_url, status, msg, duration_ms)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            "99", "Test Monitor", "http://test.com", 1, "OK", 100
        )
        # Insert second (later) status
        await conn.execute(
            """
            INSERT INTO monitor_status (monitor_id, monitor_name, monitor_url, status, msg, duration_ms)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            "99", "Test Monitor", "http://test.com", 0, "DOWN", 0
        )

    # GET /status should return 1 row (the latest)
    response = await client.get(
        "/api/uptime/status",
        headers={"Authorization": "Bearer lamadb_test_key_2026"}
    )
    assert response.status_code == 200
    data = response.json()
    # Find monitor 99
    monitor_99 = [m for m in data if m["monitor_id"] == "99"]
    assert len(monitor_99) == 1
    assert monitor_99[0]["status"] == 0  # Latest status


# ---------------------------------------------------------------------------
# Test 6: get_status_multiple_monitors
# ---------------------------------------------------------------------------
@container_required
@pytest.mark.asyncio
async def test_get_status_multiple_monitors(client, db_pool):
    """Insert 2 monitors, GET /status returns 2 rows."""
    async with db_pool.acquire() as conn:
        # Seed registry for both monitors
        await conn.execute(
            """INSERT INTO monitor_registry (monitor_id, monitor_name, monitor_url, monitor_type, tags, active, last_seen) VALUES ($1, $2, $3, $4, $5, true, now()) ON CONFLICT (monitor_id) DO NOTHING""",
            "m1", "Monitor One", "http://one.com", "http", [],
        )
        await conn.execute(
            """INSERT INTO monitor_registry (monitor_id, monitor_name, monitor_url, monitor_type, tags, active, last_seen) VALUES ($1, $2, $3, $4, $5, true, now()) ON CONFLICT (monitor_id) DO NOTHING""",
            "m2", "Monitor Two", "http://two.com", "http", [],
        )
        await conn.execute(
            """
            INSERT INTO monitor_status (monitor_id, monitor_name, monitor_url, status, msg, duration_ms)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            "m1", "Monitor One", "http://one.com", 1, "OK", 50
        )
        await conn.execute(
            """
            INSERT INTO monitor_status (monitor_id, monitor_name, monitor_url, status, msg, duration_ms)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            "m2", "Monitor Two", "http://two.com", 0, "DOWN", 0
        )

    response = await client.get(
        "/api/uptime/status",
        headers={"Authorization": "Bearer lamadb_test_key_2026"}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 2


# ---------------------------------------------------------------------------
# Test 7: get_history_filters_by_monitor_id
# ---------------------------------------------------------------------------
@container_required
@pytest.mark.asyncio
async def test_get_history_filters_by_monitor_id(client, db_pool):
    """GET /history?monitor_id=X returns only that monitor's entries."""
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO monitor_status (monitor_id, monitor_name, monitor_url, status, msg, duration_ms)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            "filter_x", "Filter X", "http://x.com", 1, "OK", 10
        )
        await conn.execute(
            """
            INSERT INTO monitor_status (monitor_id, monitor_name, monitor_url, status, msg, duration_ms)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            "filter_y", "Filter Y", "http://y.com", 0, "DOWN", 0
        )

    response = await client.get(
        "/api/uptime/history?monitor_id=filter_x",
        headers={"Authorization": "Bearer lamadb_test_key_2026"}
    )
    assert response.status_code == 200
    data = response.json()
    for entry in data:
        assert entry["monitor_id"] == "filter_x"


# ---------------------------------------------------------------------------
# Test 8: get_history_pagination
# ---------------------------------------------------------------------------
@container_required
@pytest.mark.asyncio
async def test_get_history_pagination(client, db_pool):
    """Insert 5 records, GET /history?limit=3 returns 3."""
    async with db_pool.acquire() as conn:
        for i in range(5):
            await conn.execute(
                """
                INSERT INTO monitor_status (monitor_id, monitor_name, monitor_url, status, msg, duration_ms)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                f"pag_{i}", f"Pag Monitor {i}", f"http://pag{i}.com", 1, "OK", i * 10
            )

    response = await client.get(
        "/api/uptime/history?limit=3",
        headers={"Authorization": "Bearer lamadb_test_key_2026"}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3


# ---------------------------------------------------------------------------
# Test 9: webhook_no_auth_required
# ---------------------------------------------------------------------------
@container_required
@pytest.mark.asyncio
async def test_webhook_no_auth_required(client, db_pool):
    """POST /webhook without auth header succeeds (201)."""
    response = await client.post("/api/uptime/webhook", json=VALID_PAYLOAD)
    assert response.status_code == 201


# ---------------------------------------------------------------------------
# Test 10: status_endpoint_requires_auth
# ---------------------------------------------------------------------------
@container_required
@pytest.mark.asyncio
async def test_status_endpoint_requires_auth(client, db_pool):
    """GET /status without auth returns 401."""
    response = await client.get("/api/uptime/status")
    assert response.status_code in (401, 403)
