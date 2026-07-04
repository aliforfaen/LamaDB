"""Tests for GET /api/users/me (LAMA-19).

Verifies the /me shortcut resolves to the bearer key's user profile,
returns 401 on missing/invalid bearer, and is registered before the
parameterized /users/{user_id} route.
"""
import httpx
import pytest
import pytest_asyncio

from tests.conftest import container_required


ADMIN_HEADERS = {"Authorization": "Bearer lamadb_test_key_2026"}
BASE_URL = "http://localhost:8000"


@pytest_asyncio.fixture(scope="function")
async def client():
    """Async httpx client pointing at the running container."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as ac:
        yield ac


@container_required
@pytest.mark.asyncio
async def test_users_me_returns_profile_with_admin_key(client):
    """GET /api/users/me with the admin bearer returns the admin profile."""
    resp = await client.get("/api/users/me", headers=ADMIN_HEADERS)
    assert resp.status_code == 200
    body = resp.json()

    # Shape mirrors GET /api/users/{user_id}: id, name, type, status,
    # masked api_key, task counts, created_at.
    assert "id" in body
    assert "name" in body
    assert body["type"] in ("human", "agent")
    assert body["status"] == "active"
    assert "api_key_masked" in body
    assert "open_tasks" in body and isinstance(body["open_tasks"], int)
    assert "completed_tasks" in body and isinstance(body["completed_tasks"], int)


@container_required
@pytest.mark.asyncio
async def test_users_me_returns_401_without_bearer(client):
    """No Authorization header → 401 (not 403, not 500)."""
    resp = await client.get("/api/users/me")
    assert resp.status_code == 401


@container_required
@pytest.mark.asyncio
async def test_users_me_returns_401_with_invalid_bearer(client):
    """Unknown bearer → 401."""
    resp = await client.get(
        "/api/users/me",
        headers={"Authorization": "Bearer not-a-real-key"},
    )
    assert resp.status_code == 401


@container_required
@pytest.mark.asyncio
async def test_users_me_registered_before_param_route(client):
    """`/users/me` must match before the parameterized `/users/{user_id}`
    route — otherwise FastAPI would try to parse "me" as a UUID and 500."""
    resp = await client.get("/api/users/me", headers=ADMIN_HEADERS)
    # If the param route shadowed `/users/me`, this would be a 422
    # ("Input should be a valid UUID") or a 500 from `user_id=str`. 200/401
    # both prove the literal route won.
    assert resp.status_code in (200, 401)