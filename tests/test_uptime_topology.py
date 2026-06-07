"""
Tests for the Uptime Kuma topology API.

Topology now merges monitor_registry (tags) with monitor_status (heartbeats).
Tests seed both tables to reflect the real data flow.
"""
import pytest
import pytest_asyncio

from httpx import ASGITransport, AsyncClient


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
async def db_pool(client):
    """Get the database pool for direct DB queries in tests."""
    from app.db import get_pool
    return get_pool()


async def _clear_all(db_pool):
    """Clear both registry and status tables before each test."""
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM monitor_status")
        await conn.execute("DELETE FROM monitor_registry")


async def _seed_registry(conn, monitor_id, name, url, tags, monitor_type="http"):
    """Insert a row into monitor_registry."""
    await conn.execute(
        """
        INSERT INTO monitor_registry (monitor_id, monitor_name, monitor_url, monitor_type, tags, active, last_seen)
        VALUES ($1, $2, $3, $4, $5, true, now())
        ON CONFLICT (monitor_id) DO UPDATE SET
            monitor_name = EXCLUDED.monitor_name,
            monitor_url = EXCLUDED.monitor_url,
            monitor_type = EXCLUDED.monitor_type,
            tags = EXCLUDED.tags,
            active = EXCLUDED.active,
            last_seen = now()
        """,
        monitor_id, name, url, monitor_type, tags,
    )


async def _seed_heartbeat(conn, monitor_id, name, url, status, msg=""):
    """Insert a heartbeat row into monitor_status."""
    await conn.execute(
        """
        INSERT INTO monitor_status (monitor_id, monitor_name, monitor_url, status, msg, tags, received_at)
        VALUES ($1, $2, $3, $4, $5, $6, now())
        """,
        monitor_id, name, url, status, msg, [],
    )


# ---------------------------------------------------------------------------
# Test 1: topology_hosts_and_services
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_topology_hosts_and_services(client, db_pool):
    """Monitors with matching host-key tags are grouped under the host."""
    await _clear_all(db_pool)
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            # Host monitor (tagged "host") — in registry
            await _seed_registry(conn, "host_probook", "ProBook", "http://probook.local", ["host"])
            await _seed_heartbeat(conn, "host_probook", "ProBook", "http://probook.local", 1, "OK - 2ms")

            # Service belonging to ProBook — in registry
            await _seed_registry(conn, "svc_lamadb", "LamaDB API", "http://probook:8000", ["docker", "probook", "lamadb"])
            await _seed_heartbeat(conn, "svc_lamadb", "LamaDB API", "http://probook:8000", 1, "OK")

            # Another service for ProBook — in registry
            await _seed_registry(conn, "svc_plex", "Plex Media", "http://probook:32400", ["plex", "probook"])
            await _seed_heartbeat(conn, "svc_plex", "Plex Media", "http://probook:32400", 0, "Connection refused")

    response = await client.get(
        "/api/uptime/topology",
        headers={"Authorization": "Bearer test-agent-key"}
    )
    assert response.status_code == 200
    data = response.json()

    assert data["summary"]["total_hosts"] == 1
    assert data["summary"]["total_services"] == 2
    assert data["summary"]["hosts_up"] == 1
    assert data["summary"]["services_up"] == 1
    assert data["summary"]["orphans"] == 0

    host = data["hosts"][0]
    assert host["name"] == "ProBook"
    assert host["host_key"] == "probook"
    assert host["status"] == 1
    assert host["status_label"] == "UP"
    assert host["total_services"] == 2
    assert host["up_count"] == 1
    assert len(host["services"]) == 2

    svc_names = {s["name"] for s in host["services"]}
    assert "LamaDB API" in svc_names
    assert "Plex Media" in svc_names


# ---------------------------------------------------------------------------
# Test 2: topology_orphans
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_topology_orphans(client, db_pool):
    """Monitors with unrecognized tags are returned as orphans."""
    await _clear_all(db_pool)
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await _seed_registry(conn, "orphan_1", "Mystery Monitor", "http://mystery.local", ["mystery", "orphan"])
            await _seed_heartbeat(conn, "orphan_1", "Mystery Monitor", "http://mystery.local", 0, "DOWN")
            await _seed_registry(conn, "orphan_2", "Another Mystery", None, ["unknown"])
            await _seed_heartbeat(conn, "orphan_2", "Another Mystery", None, 1, "OK")

    response = await client.get(
        "/api/uptime/topology",
        headers={"Authorization": "Bearer test-agent-key"}
    )
    assert response.status_code == 200
    data = response.json()

    assert data["summary"]["total_hosts"] == 0
    assert data["summary"]["orphans"] == 2
    assert len(data["orphans"]) == 2

    orphan_names = {o["name"] for o in data["orphans"]}
    assert "Mystery Monitor" in orphan_names
    assert "Another Mystery" in orphan_names


# ---------------------------------------------------------------------------
# Test 3: topology_host_key_matching
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_topology_host_key_matching(client, db_pool):
    """Host key matching is case-insensitive; 'Plex Box' host matches 'plex-box' tag."""
    await _clear_all(db_pool)
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await _seed_registry(conn, "host_plex", "Plex Box", "http://plex.local", ["host"])
            await _seed_heartbeat(conn, "host_plex", "Plex Box", "http://plex.local", 1, "OK")
            await _seed_registry(conn, "svc_plexstream", "Plex Stream", "http://plex:8080", ["plex-box", "media"])
            await _seed_heartbeat(conn, "svc_plexstream", "Plex Stream", "http://plex:8080", 1, "OK")

    response = await client.get(
        "/api/uptime/topology",
        headers={"Authorization": "Bearer test-agent-key"}
    )
    assert response.status_code == 200
    data = response.json()

    assert data["summary"]["total_hosts"] == 1
    assert data["summary"]["orphans"] == 0

    host = data["hosts"][0]
    assert host["host_key"] == "plex-box"
    assert len(host["services"]) == 1
    assert host["services"][0]["name"] == "Plex Stream"


# ---------------------------------------------------------------------------
# Test 4: topology_empty_tags
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_topology_empty_tags(client, db_pool):
    """Monitors with no tags (empty) are treated as orphans."""
    await _clear_all(db_pool)
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await _seed_registry(conn, "null_tag_1", "NULL Tag Monitor", "http://null.local", [])
            await _seed_heartbeat(conn, "null_tag_1", "NULL Tag Monitor", "http://null.local", 1, "OK")
            await _seed_registry(conn, "empty_tag_1", "Empty Tag Monitor", "http://empty.local", [])
            await _seed_heartbeat(conn, "empty_tag_1", "Empty Tag Monitor", "http://empty.local", 0, "DOWN")

    response = await client.get(
        "/api/uptime/topology",
        headers={"Authorization": "Bearer test-agent-key"}
    )
    assert response.status_code == 200
    data = response.json()

    assert data["summary"]["total_hosts"] == 0
    assert data["summary"]["orphans"] == 2
    orphan_names = {o["name"] for o in data["orphans"]}
    assert "NULL Tag Monitor" in orphan_names
    assert "Empty Tag Monitor" in orphan_names


# ---------------------------------------------------------------------------
# Test 5: topology_summary_counts
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_topology_summary_counts(client, db_pool):
    """Summary correctly counts up/down/total for hosts and services."""
    await _clear_all(db_pool)
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            # Host 1: UP
            await _seed_registry(conn, "host_alpha", "Alpha Server", "http://alpha.local", ["host"])
            await _seed_heartbeat(conn, "host_alpha", "Alpha Server", "http://alpha.local", 1, "OK")
            # Host 1 services: 1 UP, 1 DOWN
            await _seed_registry(conn, "svc_alpha_api", "Alpha API", "http://alpha:8000", ["alpha-server"])
            await _seed_heartbeat(conn, "svc_alpha_api", "Alpha API", "http://alpha:8000", 1, "OK")
            await _seed_registry(conn, "svc_alpha_web", "Alpha Web", "http://alpha:80", ["alpha-server"])
            await _seed_heartbeat(conn, "svc_alpha_web", "Alpha Web", "http://alpha:80", 0, "DOWN")

            # Host 2: DOWN
            await _seed_registry(conn, "host_beta", "Beta Server", "http://beta.local", ["host"])
            await _seed_heartbeat(conn, "host_beta", "Beta Server", "http://beta.local", 0, "DOWN")
            # Host 2 services: 1 UP, 1 PENDING (status=2)
            await _seed_registry(conn, "svc_beta_db", "Beta DB", "http://beta:5432", ["beta-server"])
            await _seed_heartbeat(conn, "svc_beta_db", "Beta DB", "http://beta:5432", 1, "OK")
            await _seed_registry(conn, "svc_beta_cache", "Beta Cache", "http://beta:6379", ["beta-server"])
            await _seed_heartbeat(conn, "svc_beta_cache", "Beta Cache", "http://beta:6379", 2, "PENDING")

    response = await client.get(
        "/api/uptime/topology",
        headers={"Authorization": "Bearer test-agent-key"}
    )
    assert response.status_code == 200
    data = response.json()

    assert data["summary"]["total_hosts"] == 2
    assert data["summary"]["hosts_up"] == 1          # Alpha UP, Beta DOWN
    assert data["summary"]["total_services"] == 4    # 2+2
    assert data["summary"]["services_up"] == 2       # Alpha API UP + Beta DB UP
    assert data["summary"]["orphans"] == 0


# ---------------------------------------------------------------------------
# Test 6: topology_no_data
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_topology_no_data(client, db_pool):
    """Empty tables return empty topology with zeroed summary."""
    await _clear_all(db_pool)
    response = await client.get(
        "/api/uptime/topology",
        headers={"Authorization": "Bearer test-agent-key"}
    )
    assert response.status_code == 200
    data = response.json()

    assert data["hosts"] == []
    assert data["orphans"] == []
    assert data["summary"]["total_hosts"] == 0
    assert data["summary"]["hosts_up"] == 0
    assert data["summary"]["total_services"] == 0
    assert data["summary"]["services_up"] == 0
    assert data["summary"]["orphans"] == 0


# ---------------------------------------------------------------------------
# Test 7: topology_endpoint_requires_auth
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_topology_endpoint_requires_auth(client, db_pool):
    """GET /topology without auth returns 401."""
    response = await client.get("/api/uptime/topology")
    assert response.status_code in (401, 403)
