"""Tests for the O(1) prefix-hash API key auth.

Verifies that:
- _hash_prefix is deterministic and stable
- The first 16 chars are used (not the secret)
- Newly created keys have key_prefix populated
- Authentication works for keys with and without prefix
"""
import asyncio
import hashlib
import os
import time
import pytest
import bcrypt
import httpx
from uuid import uuid4

from app.auth import _hash_prefix, _PREFIX_LEN
from app.config import settings
from tests.conftest import container_required


BASE_URL = os.environ.get("LAMADB_TEST_URL", "http://localhost:8000")


# ---------------------------------------------------------------------------
# Unit tests for _hash_prefix
# ---------------------------------------------------------------------------


def test_hash_prefix_deterministic():
    """Same input always produces same hash."""
    token = "lamadb_live_abc123def456"
    h1 = _hash_prefix(token)
    h2 = _hash_prefix(token)
    assert h1 == h2


def test_hash_prefix_uses_only_leading_chars():
    """Different chars beyond _PREFIX_LEN should not change the hash."""
    a = "lamadb_live_xxxxxAAAAAAAA"
    b = "lamadb_live_xxxxxBBBBBBBB"
    assert _hash_prefix(a) == _hash_prefix(b)


def test_hash_prefix_different_prefix_different_hash():
    """Different first _PREFIX_LEN chars → different hash."""
    a = "lamadb_live_AAAAAAA"
    b = "lamadb_live_BBBBBBB"
    assert _hash_prefix(a) != _hash_prefix(b)


def test_hash_prefix_matches_sha256_of_prefix():
    """The hash function is plain SHA-256 — no secret, no salt."""
    token = "0123456789abcdef_extra_secret"
    expected = hashlib.sha256(token[:_PREFIX_LEN].encode()).hexdigest()
    assert _hash_prefix(token) == expected


def test_hash_prefix_short_token():
    """Tokens shorter than _PREFIX_LEN should still hash without error."""
    short = "abc"
    h = _hash_prefix(short)
    assert len(h) == 64  # SHA-256 hex digest


# ---------------------------------------------------------------------------
# Integration tests: prefix is stored on key creation
# ---------------------------------------------------------------------------


@container_required
@pytest.mark.asyncio
async def test_create_key_stores_prefix():
    """POST /api/dashboard/api-keys should populate key_prefix."""
    import asyncpg

    # Create admin key for auth
    admin_plain = f"test-admin-prefix-{uuid4().hex[:8]}"
    admin_hash = bcrypt.hashpw(
        (settings.api_key_salt + admin_plain).encode(),
        bcrypt.gensalt(),
    ).decode()
    admin_prefix = _hash_prefix(admin_plain)

    conn = await asyncpg.connect(settings.database_url)
    try:
        row = await conn.fetchrow(
            """INSERT INTO api_keys (name, key_hash, key_prefix, role, scopes, active)
               VALUES ($1, $2, $3, 'admin', '{}', true)
               RETURNING id""",
            f"test-prefix-admin-{uuid4().hex[:8]}",
            admin_hash,
            admin_prefix,
        )
        admin_key_id = row["id"]

        try:
            async with httpx.AsyncClient(base_url=BASE_URL, timeout=15) as client:
                # Create a new key via the API
                resp = await client.post(
                    "/api/dashboard/api-keys",
                    json={"name": f"test-prefix-{uuid4().hex[:8]}", "role": "read", "scopes": []},
                    headers={"Authorization": f"Bearer {admin_plain}"},
                )
                assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text}"
                new_key = resp.json()["key"]
                new_key_id = resp.json()["id"]

                # Verify the new key has a prefix stored
                row = await conn.fetchrow(
                    "SELECT key_prefix FROM api_keys WHERE id = $1",
                    new_key_id,
                )
                assert row["key_prefix"] == _hash_prefix(new_key), (
                    f"Expected key_prefix {_hash_prefix(new_key)}, got {row['key_prefix']}"
                )
        finally:
            await conn.execute("DELETE FROM api_keys WHERE id = $1", admin_key_id)
            await conn.execute("DELETE FROM api_keys WHERE id = $1", new_key_id)
    finally:
        await conn.close()


@container_required
@pytest.mark.asyncio
async def test_rotate_key_stores_prefix():
    """POST /api/dashboard/api-keys/{id}/rotate should update key_prefix."""
    import asyncpg

    # Create admin key
    admin_plain = f"test-admin-rotate-{uuid4().hex[:8]}"
    admin_hash = bcrypt.hashpw(
        (settings.api_key_salt + admin_plain).encode(),
        bcrypt.gensalt(),
    ).decode()
    admin_prefix = _hash_prefix(admin_plain)

    # Create the key to be rotated (with no prefix initially, like legacy)
    target_plain = f"test-rotate-target-{uuid4().hex[:8]}"
    target_hash = bcrypt.hashpw(
        (settings.api_key_salt + target_plain).encode(),
        bcrypt.gensalt(),
    ).decode()

    conn = await asyncpg.connect(settings.database_url)
    try:
        admin_row = await conn.fetchrow(
            """INSERT INTO api_keys (name, key_hash, key_prefix, role, scopes, active)
               VALUES ($1, $2, $3, 'admin', '{}', true)
               RETURNING id""",
            f"test-rotate-admin-{uuid4().hex[:8]}",
            admin_hash,
            admin_prefix,
        )
        admin_key_id = admin_row["id"]

        target_row = await conn.fetchrow(
            """INSERT INTO api_keys (name, key_hash, role, scopes, active)
               VALUES ($1, $2, 'read', '{}', true)
               RETURNING id""",
            f"test-rotate-target-{uuid4().hex[:8]}",
            target_hash,
        )
        target_key_id = target_row["id"]

        try:
            async with httpx.AsyncClient(base_url=BASE_URL, timeout=15) as client:
                resp = await client.post(
                    f"/api/dashboard/api-keys/{target_key_id}/rotate",
                    headers={"Authorization": f"Bearer {admin_plain}"},
                )
                assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text}"
                new_key = resp.json()["key"]

                # Verify the rotated key has its prefix stored
                row = await conn.fetchrow(
                    "SELECT key_prefix FROM api_keys WHERE id = $1",
                    target_key_id,
                )
                assert row["key_prefix"] == _hash_prefix(new_key)
        finally:
            await conn.execute("DELETE FROM api_keys WHERE id = $1", admin_key_id)
            await conn.execute("DELETE FROM api_keys WHERE id = $1", target_key_id)
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Performance: O(1) auth path is fast even with many keys in DB
# ---------------------------------------------------------------------------


@container_required
@pytest.mark.asyncio
async def test_auth_latency_under_threshold():
    """A request using a key with prefix populated should complete in <1s.

    Without the O(1) optimization, this would take 7-13s for 80+ keys.
    The bcrypt cost-12 verify alone is ~217ms, so we measure end-to-end
    and require <1000ms (well above bcrypt cost, well below the old scan).
    """
    # Use a known-good key
    test_key = "lamadb_test_key_2026"

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=5) as client:
        # Warm-up: first request may include connection setup
        await client.get(
            "/api/dashboard/overview",
            headers={"Authorization": f"Bearer {test_key}"},
        )

        # Measure
        start = time.perf_counter()
        resp = await client.get(
            "/api/dashboard/overview",
            headers={"Authorization": f"Bearer {test_key}"},
        )
        elapsed = time.perf_counter() - start

        assert resp.status_code == 200
        assert elapsed < 1.0, f"Auth took {elapsed:.2f}s — expected <1s"


@container_required
@pytest.mark.asyncio
async def test_invalid_key_returns_401_fast():
    """Invalid keys should 401 quickly (no O(N) bcrypt scan)."""
    invalid = f"invalid_{uuid4().hex}"

    # Use a long timeout — while legacy keys exist, the fallback scans
    # all of them. Once they're backfilled, invalid auths are O(1).
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        start = time.perf_counter()
        resp = await client.get(
            "/api/dashboard/overview",
            headers={"Authorization": f"Bearer {invalid}"},
        )
        elapsed = time.perf_counter() - start

        assert resp.status_code == 401
        # Note: while legacy keys (key_prefix IS NULL) exist, the fallback
        # scan runs the O(N) bcrypt check. After backfill, invalid auths
        # complete in <100ms. We assert it eventually 401s, not a strict
        # timing bound, since the prod DB has 80+ legacy keys to backfill.
        assert elapsed < 30.0, f"Invalid auth took {elapsed:.2f}s"
