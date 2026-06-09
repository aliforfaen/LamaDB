"""Tests for user layout persistence endpoints."""
import os
import pytest
import pytest_asyncio
import httpx
from tests.conftest import container_required

BASE_URL = os.environ.get("LAMADB_TEST_URL", "http://localhost:8000")
AUTH_HEADERS = {"Authorization": "Bearer lamadb_test_key_2026"}


@pytest_asyncio.fixture
async def client():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as ac:
        yield ac


@pytest.mark.asyncio
@container_required
async def test_get_default_layout(client):
    """GET should return default module order when nothing saved."""
    resp = await client.get("/api/dashboard/user-layout?page=overview", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["page"] == "overview"
    assert "uptime" in data["layout"]["module_order"]


@pytest.mark.asyncio
@container_required
async def test_save_and_retrieve_layout(client):
    """PUT should save module order, GET should return it."""
    custom = {"module_order": ["uptime", "freshrss", "hermes", "ntfy", "dozzle", "notflix", "wiki", "feeds", "notifications"]}
    resp = await client.put("/api/dashboard/user-layout?page=overview", json=custom, headers=AUTH_HEADERS)
    assert resp.status_code == 200

    resp2 = await client.get("/api/dashboard/user-layout?page=overview", headers=AUTH_HEADERS)
    assert resp2.json()["layout"]["module_order"] == custom["module_order"]


@pytest.mark.asyncio
@container_required
async def test_requires_auth(client):
    """Endpoints should reject unauthenticated requests."""
    resp = await client.get("/api/dashboard/user-layout")
    assert resp.status_code in (401, 403)
