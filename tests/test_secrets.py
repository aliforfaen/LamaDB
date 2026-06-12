"""
Tests for the secrets module.

Tests run against the live Docker container on localhost:8000.
Uses the pre-existing admin key for authentication.

Covers:
- CRUD: create / list / get / update / delete
- Encryption: value is never returned in list/detail; reveal endpoint
  decrypts correctly; PATCH re-encrypts new value
- Access control: secrets are metadata-only by default; reveal works for owner
- Access requests: submit, approve (creates grant), reject
- Filtering: by service, tag, priority
- last_revealed_at tracking

Run a single test:
    docker exec lamadb_api python3 -m pytest tests/test_secrets.py -q
"""
import pytest
import pytest_asyncio
from tests.conftest import container_required

BASE_URL = "http://localhost:8000"
AUTH_HEADERS = {"Authorization": "Bearer lamadb_test_key_2026"}

pytestmark = container_required


SECRET_PAYLOAD = {
    "name": "Test API Key",
    "service": "openai",
    "description": "Test key for CI",
    "secret_type": "api_key",
    "value": "sk-test-key-12345",
    "priority": "primary",
    "tags": ["test", "ci"],
}


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
async def test_secret(client):
    """Create a test secret and clean up after the test runs."""
    resp = await client.post(
        "/api/secrets", json=SECRET_PAYLOAD, headers=AUTH_HEADERS
    )
    assert resp.status_code == 201
    data = resp.json()
    try:
        yield data
    finally:
        await client.delete(
            f"/api/secrets/{data['id']}", headers=AUTH_HEADERS
        )


# ---------------------------------------------------------------------------
# Test 1: create_secret_api_key — value must NOT be in response
# ---------------------------------------------------------------------------


async def test_create_secret_api_key(client, test_secret):
    """api_key secret created; value is never returned in response."""
    assert test_secret["name"] == "Test API Key"
    assert test_secret["service"] == "openai"
    assert test_secret["secret_type"] == "api_key"
    assert test_secret["priority"] == "primary"
    assert "value" not in test_secret
    assert "encrypted_value" not in test_secret


# ---------------------------------------------------------------------------
# Test 2: create_secret_oauth — extra fields supported
# ---------------------------------------------------------------------------


async def test_create_secret_oauth(client):
    """Create oauth type secret; extra fields are accepted and persisted."""
    resp = await client.post(
        "/api/secrets",
        json={
            "name": "OAuth App",
            "service": "github",
            "secret_type": "oauth",
            "value": "gh_secret_abc",
            "extra_1": "gh_client_id_123",
        },
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["secret_type"] == "oauth"
    assert data["service"] == "github"
    assert "value" not in data

    # Cleanup
    await client.delete(
        f"/api/secrets/{data['id']}", headers=AUTH_HEADERS
    )


# ---------------------------------------------------------------------------
# Test 3: list_secrets_metadata_only
# ---------------------------------------------------------------------------


async def test_list_secrets_metadata_only(client, test_secret):
    """GET /api/secrets never returns encrypted or plaintext value fields."""
    resp = await client.get("/api/secrets", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    secrets = resp.json()
    assert isinstance(secrets, list)
    for s in secrets:
        assert "value" not in s
        assert "encrypted_value" not in s


# ---------------------------------------------------------------------------
# Test 4: reveal_secret_as_owner
# ---------------------------------------------------------------------------


async def test_reveal_secret_as_owner(client, test_secret):
    """Owner can call /reveal and get the plaintext value back."""
    resp = await client.get(
        f"/api/secrets/{test_secret['id']}/reveal", headers=AUTH_HEADERS
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["value"] == "sk-test-key-12345"
    assert data["secret_type"] == "api_key"


# ---------------------------------------------------------------------------
# Test 5: list_secrets_filter_service
# ---------------------------------------------------------------------------


async def test_list_secrets_filter_service(client, test_secret):
    """GET /api/secrets?service=openai returns only openai secrets."""
    resp = await client.get(
        "/api/secrets?service=openai", headers=AUTH_HEADERS
    )
    assert resp.status_code == 200
    secrets = resp.json()
    assert all(s["service"] == "openai" for s in secrets)


# ---------------------------------------------------------------------------
# Test 6: list_secrets_filter_tags
# ---------------------------------------------------------------------------


async def test_list_secrets_filter_tags(client, test_secret):
    """GET /api/secrets?tag=test returns only secrets with that tag."""
    resp = await client.get(
        "/api/secrets?tag=test", headers=AUTH_HEADERS
    )
    assert resp.status_code == 200
    secrets = resp.json()
    assert all("test" in s["tags"] for s in secrets)


# ---------------------------------------------------------------------------
# Test 7: update_secret (metadata only)
# ---------------------------------------------------------------------------


async def test_update_secret(client, test_secret):
    """PATCH /api/secrets/{id} updates metadata fields."""
    resp = await client.patch(
        f"/api/secrets/{test_secret['id']}",
        json={
            "name": "Updated Key Name",
            "priority": "secondary",
        },
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Updated Key Name"
    assert data["priority"] == "secondary"


# ---------------------------------------------------------------------------
# Test 8: update_secret_re_encrypt
# ---------------------------------------------------------------------------


async def test_update_secret_re_encrypt(client, test_secret):
    """Updating value re-encrypts; reveal returns the new value."""
    patch_resp = await client.patch(
        f"/api/secrets/{test_secret['id']}",
        json={"value": "new-secret-value-xyz"},
        headers=AUTH_HEADERS,
    )
    assert patch_resp.status_code == 200

    reveal = await client.get(
        f"/api/secrets/{test_secret['id']}/reveal", headers=AUTH_HEADERS
    )
    assert reveal.status_code == 200
    assert reveal.json()["value"] == "new-secret-value-xyz"


# ---------------------------------------------------------------------------
# Test 9: delete_secret_cascade
# ---------------------------------------------------------------------------


async def test_delete_secret_cascade(client):
    """DELETE returns 204; subsequent GET returns 404."""
    create = await client.post(
        "/api/secrets", json=SECRET_PAYLOAD, headers=AUTH_HEADERS
    )
    assert create.status_code == 201
    secret_id = create.json()["id"]

    resp = await client.delete(
        f"/api/secrets/{secret_id}", headers=AUTH_HEADERS
    )
    assert resp.status_code == 204

    r2 = await client.get(
        f"/api/secrets/{secret_id}", headers=AUTH_HEADERS
    )
    assert r2.status_code == 404


# ---------------------------------------------------------------------------
# Test 10: access_request_submit
# ---------------------------------------------------------------------------


async def test_access_request_submit(client, test_secret):
    """Submit an access request for a secret; status starts as 'pending'."""
    resp = await client.post(
        f"/api/secrets/{test_secret['id']}/request",
        json={"reason": "Need this for building features"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "pending"
    assert "id" in data


# ---------------------------------------------------------------------------
# Test 11: access_request_approve
# ---------------------------------------------------------------------------


async def test_access_request_approve(client, test_secret):
    """Approving a request creates a grant visible in /access."""
    # Submit
    req = await client.post(
        f"/api/secrets/{test_secret['id']}/request",
        json={"reason": "Need access"},
        headers=AUTH_HEADERS,
    )
    assert req.status_code == 201
    req_id = req.json()["id"]

    # Approve
    resp = await client.patch(
        f"/api/secrets/requests/{req_id}",
        json={"status": "approved"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200

    # Verify grant created
    grants = await client.get(
        f"/api/secrets/{test_secret['id']}/access", headers=AUTH_HEADERS
    )
    assert grants.status_code == 200
    assert len(grants.json()) >= 1


# ---------------------------------------------------------------------------
# Test 12: access_request_reject
# ---------------------------------------------------------------------------


async def test_access_request_reject(client, test_secret):
    """Rejecting a request sets status to 'rejected'."""
    req = await client.post(
        f"/api/secrets/{test_secret['id']}/request",
        json={"reason": "Need access"},
        headers=AUTH_HEADERS,
    )
    assert req.status_code == 201
    req_id = req.json()["id"]

    resp = await client.patch(
        f"/api/secrets/requests/{req_id}",
        json={"status": "rejected"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


# ---------------------------------------------------------------------------
# Test 13: priority_filtering
# ---------------------------------------------------------------------------


async def test_priority_filtering(client, test_secret):
    """GET /api/secrets?priority=primary returns only primary secrets."""
    resp = await client.get(
        "/api/secrets?priority=primary", headers=AUTH_HEADERS
    )
    assert resp.status_code == 200
    secrets = resp.json()
    assert all(s["priority"] == "primary" for s in secrets)


# ---------------------------------------------------------------------------
# Test 14: last_revealed_updated
# ---------------------------------------------------------------------------


async def test_last_revealed_updated(client, test_secret):
    """last_revealed_at is null before reveal, set after reveal."""
    # Pre-reveal state
    detail = await client.get(
        f"/api/secrets/{test_secret['id']}", headers=AUTH_HEADERS
    )
    assert detail.status_code == 200
    assert detail.json()["last_revealed_at"] is None

    # Reveal
    reveal = await client.get(
        f"/api/secrets/{test_secret['id']}/reveal", headers=AUTH_HEADERS
    )
    assert reveal.status_code == 200

    # Post-reveal state
    detail2 = await client.get(
        f"/api/secrets/{test_secret['id']}", headers=AUTH_HEADERS
    )
    assert detail2.status_code == 200
    assert detail2.json()["last_revealed_at"] is not None
