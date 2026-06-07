"""
Tests for GET /api/dashboard/header — public dashboard command-center endpoint.

The header endpoint is publicly readable (no auth required).
"""
import pytest
import pytest_asyncio

from httpx import ASGITransport, AsyncClient

from app.main import make_app


@pytest_asyncio.fixture(scope="function")
async def client():
    """Create an async test client for the FastAPI app."""
    app = make_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(scope="function")
async def db_pool(client):
    """Get the database pool for direct DB queries in tests.

    Depends on `client` to ensure the app lifespan has initialized the pool.
    """
    from app.db import get_pool
    return get_pool()


# ---------------------------------------------------------------------------
# Tests: GET /api/dashboard/header
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_header_returns_status_bar_and_ticker(client):
    """GET /api/dashboard/header returns both status_bar and ticker keys."""
    response = await client.get("/api/dashboard/header")
    assert response.status_code == 200
    data = response.json()

    assert "status_bar" in data
    assert "ticker" in data
    assert isinstance(data["ticker"], list)


@pytest.mark.asyncio
async def test_header_status_bar_has_all_leds(client):
    """status_bar contains services, notifications, dozzle, and agents leds."""
    response = await client.get("/api/dashboard/header")
    assert response.status_code == 200
    data = response.json()

    sb = data["status_bar"]
    assert "hostname" in sb
    assert "services" in sb
    assert "notifications" in sb
    assert "dozzle" in sb
    assert "agents" in sb

    # Services sub-stats
    assert "total" in sb["services"]
    assert "up" in sb["services"]
    assert "down" in sb["services"]

    # Notifications sub-stats
    assert "count" in sb["notifications"]
    assert "has_high_priority" in sb["notifications"]

    # Dozzle sub-stats
    assert "errors" in sb["dozzle"]
    assert "warnings" in sb["dozzle"]

    # Agents sub-stats
    assert "pending" in sb["agents"]


@pytest.mark.asyncio
async def test_header_ticker_items_have_icon_field(client):
    """Each ticker item must have an icon field computed server-side."""
    response = await client.get("/api/dashboard/header")
    assert response.status_code == 200
    data = response.json()

    for item in data["ticker"]:
        assert "icon" in item
        assert "id" in item
        assert "ts" in item
        assert "source" in item
        assert "severity" in item
        assert "title" in item
        assert "tags" in item


@pytest.mark.asyncio
async def test_header_is_public_no_auth_required(client):
    """The header endpoint must NOT require authentication."""
    response = await client.get("/api/dashboard/header")
    # Must not return 401 or 403
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_header_services_reflects_monitor_status(db_pool, client):
    """Services LED reflects actual monitor_status table data."""
    # Insert a test monitor
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO monitor_status (monitor_id, monitor_name, status)
            VALUES ('test-mon-1', 'Test Monitor', 1)
            ON CONFLICT DO NOTHING
        """)

    response = await client.get("/api/dashboard/header")
    assert response.status_code == 200
    data = response.json()

    # At least one service should be tracked (the one we just added)
    assert data["status_bar"]["services"]["total"] >= 1


@pytest.mark.asyncio
async def test_header_ticker_respects_breaking_tag_order(db_pool, client):
    """Ticker items with 'breaking' tag appear first."""
    # Insert a breaking ticker item
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO events (source, type, severity, title, ticker, tags)
            VALUES ('test', 'test', 'info', 'Breaking test event', true, ARRAY['breaking'])
            ON CONFLICT DO NOTHING
        """)
        await conn.execute("""
            INSERT INTO events (source, type, severity, title, ticker, tags)
            VALUES ('test', 'test', 'info', 'Normal test event', true, ARRAY['normal'])
            ON CONFLICT DO NOTHING
        """)

    response = await client.get("/api/dashboard/header")
    assert response.status_code == 200
    data = response.json()

    ticker = data["ticker"]
    if len(ticker) >= 2:
        # Breaking item should be first
        breaking_idx = next((i for i, t in enumerate(ticker) if 'breaking' in (t.get("tags") or [])), None)
        if breaking_idx is not None and breaking_idx != 0:
            # If there's a breaking item, it must appear before non-breaking items
            assert breaking_idx == 0


@pytest.mark.asyncio
async def test_header_ticker_icon_mapping(db_pool, client):
    """Icon mapping: info→✓, warn→⚠, critical→✗."""
    icons_to_severities = [
        ("info", "✓"),
        ("warn", "⚠"),
        ("critical", "✗"),
    ]
    async with db_pool.acquire() as conn:
        for sev, expected_icon in icons_to_severities:
            await conn.execute("""
                INSERT INTO events (source, type, severity, title, ticker, tags)
                VALUES ($1, $2, $3, $4, true, '{}')
                ON CONFLICT DO NOTHING
            """, f"test-icon-{sev}", "test", sev, f"Test {sev} event")

    response = await client.get("/api/dashboard/header")
    assert response.status_code == 200
    data = response.json()

    ticker_map = {t["title"]: t["icon"] for t in data["ticker"]}
    for sev, expected_icon in icons_to_severities:
        title = f"Test {sev} event"
        if title in ticker_map:
            assert ticker_map[title] == expected_icon, f"For severity {sev}, expected {expected_icon}"
