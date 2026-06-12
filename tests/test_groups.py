"""
Tests for the groups module.

Tests run against the live Docker container on localhost:8000.
Uses the pre-existing admin key for authentication.

Run a single test:
    docker exec lamadb_api python3 -m pytest tests/test_groups.py -q
"""
import pytest
import pytest_asyncio
from tests.conftest import container_required

BASE_URL = "http://localhost:8000"
AUTH_HEADERS = {"Authorization": "Bearer lamadb_test_key_2026"}

pytestmark = container_required


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def client():
    """Create an async httpx client pointing at the running container."""
    import httpx
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as ac:
        yield ac


@pytest_asyncio.fixture(scope="function")
async def test_group(client):
    """Create a test group and clean up after the test runs."""
    resp = await client.post(
        "/api/groups",
        json={
            "name": "pytest-group-test",
            "description": "Auto-created test group",
        },
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 201
    data = resp.json()
    try:
        yield data
    finally:
        await client.delete(
            f"/api/groups/{data['id']}", headers=AUTH_HEADERS
        )


# ---------------------------------------------------------------------------
# Test 1: create_group
# ---------------------------------------------------------------------------


async def test_create_group(client):
    """Admin can create a group; member_count starts at 0."""
    resp = await client.post(
        "/api/groups",
        json={
            "name": "test-create-group",
            "description": "A test group",
        },
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "test-create-group"
    assert data["member_count"] == 0
    assert "id" in data

    # Cleanup
    await client.delete(f"/api/groups/{data['id']}", headers=AUTH_HEADERS)


# ---------------------------------------------------------------------------
# Test 2: list_groups
# ---------------------------------------------------------------------------


async def test_list_groups(client, test_group):
    """List groups returns the created test group."""
    resp = await client.get("/api/groups", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    groups = resp.json()
    assert isinstance(groups, list)
    assert any(g["name"] == "pytest-group-test" for g in groups)


# ---------------------------------------------------------------------------
# Test 3: get_group_detail
# ---------------------------------------------------------------------------


async def test_get_group_detail(client, test_group):
    """GET /api/groups/{id} returns the group detail."""
    resp = await client.get(
        f"/api/groups/{test_group['id']}", headers=AUTH_HEADERS
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "pytest-group-test"
    assert data["id"] == test_group["id"]


# ---------------------------------------------------------------------------
# Test 4: add_member
# ---------------------------------------------------------------------------


async def test_add_member(client, test_group):
    """Add a member to a group using the seeded admin user 'ali'."""
    # Locate 'ali' user
    users_resp = await client.get("/api/users", headers=AUTH_HEADERS)
    assert users_resp.status_code == 200
    users = users_resp.json()
    ali = next((u for u in users if u["name"] == "ali"), None)
    assert ali is not None, "User 'ali' not found — is the DB seeded?"

    # Add as member
    resp = await client.post(
        f"/api/groups/{test_group['id']}/members",
        json={"user_id": ali["id"], "role": "member"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 201

    # Verify membership
    detail = await client.get(
        f"/api/groups/{test_group['id']}", headers=AUTH_HEADERS
    )
    assert detail.status_code == 200
    members = detail.json()["members"]
    assert len(members) == 1
    assert members[0]["user_id"] == ali["id"]


# ---------------------------------------------------------------------------
# Test 5: remove_member
# ---------------------------------------------------------------------------


async def test_remove_member(client, test_group):
    """Remove a member from a group."""
    users_resp = await client.get("/api/users", headers=AUTH_HEADERS)
    assert users_resp.status_code == 200
    ali = next(
        (u for u in users_resp.json() if u["name"] == "ali"), None
    )
    assert ali is not None, "User 'ali' not found — is the DB seeded?"

    # Add member first
    add_resp = await client.post(
        f"/api/groups/{test_group['id']}/members",
        json={"user_id": ali["id"], "role": "member"},
        headers=AUTH_HEADERS,
    )
    assert add_resp.status_code == 201

    # Remove member
    resp = await client.delete(
        f"/api/groups/{test_group['id']}/members/{ali['id']}",
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 204

    # Verify gone
    detail = await client.get(
        f"/api/groups/{test_group['id']}", headers=AUTH_HEADERS
    )
    assert detail.status_code == 200
    assert len(detail.json()["members"]) == 0


# ---------------------------------------------------------------------------
# Test 6: delete_group
# ---------------------------------------------------------------------------


async def test_delete_group(client):
    """Delete a group; subsequent GET returns 404."""
    create_resp = await client.post(
        "/api/groups",
        json={"name": "test-delete-group"},
        headers=AUTH_HEADERS,
    )
    assert create_resp.status_code == 201
    group_id = create_resp.json()["id"]

    resp = await client.delete(
        f"/api/groups/{group_id}", headers=AUTH_HEADERS
    )
    assert resp.status_code == 204

    # Verify gone
    r2 = await client.get(
        f"/api/groups/{group_id}", headers=AUTH_HEADERS
    )
    assert r2.status_code == 404
