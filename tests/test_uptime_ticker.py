"""
Tests for Uptime Kuma ticker event creation on status changes.

Tests verify that:
- Status UP→DOWN creates a ticker event with 'breaking' tag
- Status DOWN→UP creates a ticker event with 'recovered' tag
- Same-status heartbeat does NOT create a ticker event
- First heartbeat (no previous) does NOT create a ticker event

Uses httpx ASGITransport to test the FastAPI app directly.
Tests use the real database (migrations already run on startup via docker compose).
"""
import pytest
import pytest_asyncio

from httpx import ASGITransport, AsyncClient


# Payload with status DOWN (0)
PAYLOAD_DOWN = {
    "heartbeat": {
        "status": 0,
        "msg": "Connection refused",
        "duration": 1523,
        "time": "2026-05-29T14:30:00+02:00"
    },
    "monitor": {
        "id": 100,
        "name": "Test Monitor",
        "url": "https://test.example.com"
    }
}

# Payload with status UP (1)
PAYLOAD_UP = {
    "heartbeat": {
        "status": 1,
        "msg": "OK",
        "duration": 120,
        "time": "2026-05-29T14:35:00+02:00"
    },
    "monitor": {
        "id": 100,
        "name": "Test Monitor",
        "url": "https://test.example.com"
    }
}


@pytest_asyncio.fixture(scope="function")
async def client():
    """
    Create an async test client for the FastAPI app.
    The lifespan context is entered explicitly to ensure the DB pool
    is initialized before any test runs.
    """
    from app.main import make_app

    app = make_app()

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(scope="function")
async def db_pool():
    """
    Get the database pool for direct DB queries in tests.
    """
    from app.db import get_pool
    return get_pool()


@pytest_asyncio.fixture(scope="function")
async def clean_monitor_100(db_pool):
    """Clean up any existing data for monitor 100 before and after test."""
    async with db_pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM monitor_status WHERE monitor_id = $1",
            "100"
        )
        await conn.execute(
            "DELETE FROM events WHERE metadata->>'monitor_id' = $1",
            "100"
        )
    yield
    async with db_pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM monitor_status WHERE monitor_id = $1",
            "100"
        )
        await conn.execute(
            "DELETE FROM events WHERE metadata->>'monitor_id' = $1",
            "100"
        )


# ---------------------------------------------------------------------------
# Test 1: first heartbeat does NOT create ticker event
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_first_heartbeat_no_ticker(client, db_pool, clean_monitor_100):
    """First heartbeat ever for a monitor should NOT create a ticker event."""
    response = await client.post("/api/uptime/webhook", json=PAYLOAD_DOWN)
    assert response.status_code == 201

    async with db_pool.acquire() as conn:
        # Find ticker events for this monitor
        ticker_rows = await conn.fetch(
            """
            SELECT id, ticker, tags
            FROM events
            WHERE ticker = true
              AND metadata->>'monitor_id' = '100'
            ORDER BY ts DESC
            """
        )
        assert len(ticker_rows) == 0, "First heartbeat should NOT create ticker event"


# ---------------------------------------------------------------------------
# Test 2: same status does NOT create ticker event
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_same_status_no_ticker(client, db_pool, clean_monitor_100):
    """Two heartbeats with the same status should NOT create a ticker event."""
    # First: send DOWN
    response = await client.post("/api/uptime/webhook", json=PAYLOAD_DOWN)
    assert response.status_code == 201

    # Second: send DOWN again (same status)
    response = await client.post("/api/uptime/webhook", json=PAYLOAD_DOWN)
    assert response.status_code == 201

    async with db_pool.acquire() as conn:
        # Find ticker events for this monitor
        ticker_rows = await conn.fetch(
            """
            SELECT id, ticker, tags
            FROM events
            WHERE ticker = true
              AND metadata->>'monitor_id' = '100'
            ORDER BY ts DESC
            """
        )
        assert len(ticker_rows) == 0, "Same-status heartbeat should NOT create ticker event"


# ---------------------------------------------------------------------------
# Test 3: UP → DOWN creates ticker with breaking tag
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_up_to_down_creates_ticker_with_breaking_tag(client, db_pool, clean_monitor_100):
    """Transition from UP to DOWN should create a ticker event with 'breaking' tag."""
    # First: send UP (monitor comes online)
    response = await client.post("/api/uptime/webhook", json=PAYLOAD_UP)
    assert response.status_code == 201

    # Second: send DOWN (monitor goes down - this should create ticker)
    response = await client.post("/api/uptime/webhook", json=PAYLOAD_DOWN)
    assert response.status_code == 201

    async with db_pool.acquire() as conn:
        # Find ticker events for this monitor
        ticker_rows = await conn.fetch(
            """
            SELECT id, ticker, tags, title
            FROM events
            WHERE ticker = true
              AND metadata->>'monitor_id' = '100'
            ORDER BY ts DESC
            """
        )
        assert len(ticker_rows) == 1, "UP→DOWN transition should create exactly 1 ticker event"
        assert ticker_rows[0]["ticker"] is True
        tags = list(ticker_rows[0]["tags"]) if ticker_rows[0]["tags"] else []
        assert "breaking" in tags, "Ticker event should have 'breaking' tag"
        assert "uptime" in tags, "Ticker event should have 'uptime' tag"
        assert "down" in tags, "Ticker event should have 'down' tag"
        assert "recovered" not in tags, "Ticker event should NOT have 'recovered' tag"
        assert "Test Monitor is DOWN" in ticker_rows[0]["title"]


# ---------------------------------------------------------------------------
# Test 4: DOWN → UP creates ticker with recovered tag
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_down_to_up_creates_ticker_with_recovered_tag(client, db_pool, clean_monitor_100):
    """Transition from DOWN to UP should create a ticker event with 'recovered' tag."""
    # First: send DOWN (monitor goes down)
    response = await client.post("/api/uptime/webhook", json=PAYLOAD_DOWN)
    assert response.status_code == 201

    # Second: send UP (monitor comes back - this should create ticker)
    response = await client.post("/api/uptime/webhook", json=PAYLOAD_UP)
    assert response.status_code == 201

    async with db_pool.acquire() as conn:
        # Find ticker events for this monitor
        ticker_rows = await conn.fetch(
            """
            SELECT id, ticker, tags, title
            FROM events
            WHERE ticker = true
              AND metadata->>'monitor_id' = '100'
            ORDER BY ts DESC
            """
        )
        assert len(ticker_rows) == 1, "DOWN→UP transition should create exactly 1 ticker event"
        assert ticker_rows[0]["ticker"] is True
        tags = list(ticker_rows[0]["tags"]) if ticker_rows[0]["tags"] else []
        assert "recovered" in tags, "Ticker event should have 'recovered' tag"
        assert "uptime" in tags, "Ticker event should have 'uptime' tag"
        assert "status" in tags, "Ticker event should have 'status' tag"
        assert "breaking" not in tags, "Ticker event should NOT have 'breaking' tag"
        assert "Test Monitor recovered" in ticker_rows[0]["title"]


# ---------------------------------------------------------------------------
# Test 5: regular event still created for every heartbeat
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_regular_event_still_created_every_heartbeat(client, db_pool, clean_monitor_100):
    """Every heartbeat should still create a regular (non-ticker) event."""
    # First heartbeat
    response = await client.post("/api/uptime/webhook", json=PAYLOAD_DOWN)
    assert response.status_code == 201

    # Second heartbeat (same status)
    response = await client.post("/api/uptime/webhook", json=PAYLOAD_DOWN)
    assert response.status_code == 201

    async with db_pool.acquire() as conn:
        # Find ALL events for this monitor (including non-ticker)
        all_rows = await conn.fetch(
            """
            SELECT id, ticker, type, title
            FROM events
            WHERE metadata->>'monitor_id' = '100'
            ORDER BY ts DESC
            """
        )
        # Should have 2 events total (one for each heartbeat)
        assert len(all_rows) == 2, "Every heartbeat creates a regular event"
        # Neither should be ticker
        assert all_rows[0]["ticker"] is False
        assert all_rows[1]["ticker"] is False


# ---------------------------------------------------------------------------
# Test 6: ticker event has correct source and type
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ticker_event_source_and_type(client, db_pool, clean_monitor_100):
    """Ticker event should have source='uptime_kuma' and type='status_change'."""
    # First: UP
    response = await client.post("/api/uptime/webhook", json=PAYLOAD_UP)
    assert response.status_code == 201

    # Then: DOWN
    response = await client.post("/api/uptime/webhook", json=PAYLOAD_DOWN)
    assert response.status_code == 201

    async with db_pool.acquire() as conn:
        ticker_row = await conn.fetchrow(
            """
            SELECT source, type, ticker, title
            FROM events
            WHERE ticker = true
              AND metadata->>'monitor_id' = '100'
            """
        )
        assert ticker_row is not None
        assert ticker_row["source"] == "uptime_kuma"
        assert ticker_row["type"] == "status_change"
        assert ticker_row["ticker"] is True
