"""Tests for SSE infrastructure (app/sse.py + /api/dashboard/stream endpoint).

SSE streaming bodies (infinite async generators) cannot be consumed via
httpx ASGITransport because it buffers the full response body. We test:
- Auth rejection (regular GET, no body to read)
- SSEManager subscribe/broadcast/unsubscribe lifecycle (pure unit)
- SSEManager queue-full behavior (pure unit)
- SSE session mgmt via manager: subscribe -> unsubscribe -> cleanup
"""
import pytest
import pytest_asyncio
import bcrypt
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from app.config import settings


@pytest_asyncio.fixture(scope="function")
async def client():
    """Create an async test client with lifespan context (initializes DB pool)."""
    from app.main import make_app
    app = make_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(scope="function")
async def db_pool():
    """Get the database pool for direct DB queries."""
    from app.db import get_pool
    return get_pool()


@pytest_asyncio.fixture(scope="function")
async def admin_key(db_pool):
    """Create a temporary admin API key for SSE test."""
    key_plain = "test-sse-" + uuid4().hex[:8]
    key_hash = bcrypt.hashpw(
        (settings.api_key_salt + key_plain).encode(),
        bcrypt.gensalt()
    ).decode()
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO api_keys (name, key_hash, role, scopes) VALUES ($1, $2, $3, $4)",
            "test-sse", key_hash, "admin", ["dashboard"],
        )
    yield key_plain
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM api_keys WHERE name = $1", "test-sse")


@pytest.mark.asyncio
async def test_sse_endpoint_rejects_unauthenticated(client):
    """Bogus API key returns 401; absent key returns 422 validation error."""
    # Absent key -> 422 (FastAPI rejects missing required Query param)
    response = await client.get("/api/dashboard/stream")
    assert response.status_code == 422

    # Bogus key -> 401
    response = await client.get("/api/dashboard/stream?key=nonexistent-key")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_sse_manager_broadcast():
    """SSEManager subscribe/broadcast/unsubscribe lifecycle works."""
    from app.sse import SSEManager

    manager = SSEManager()
    assert manager.client_count == 0

    q1 = manager.subscribe()
    assert manager.client_count == 1

    q2 = manager.subscribe()
    assert manager.client_count == 2

    # Broadcast and verify both queues receive the data
    msg = {"test": True, "seq": 1}
    await manager.broadcast(msg)

    assert q1.get_nowait() == msg
    assert q2.get_nowait() == msg

    # Unsubscribe and verify
    manager.unsubscribe(q1)
    assert manager.client_count == 1

    # Second unsubscribe is a no-op
    manager.unsubscribe(q1)
    assert manager.client_count == 1

    # Remove the last one
    manager.unsubscribe(q2)
    assert manager.client_count == 0

    # Empty broadcast does not raise
    await manager.broadcast({"final": True})


@pytest.mark.asyncio
async def test_sse_manager_queue_full_does_not_block():
    """Broadcast to a full queue silently drops instead of blocking."""
    from app.sse import SSEManager

    manager = SSEManager()
    q = manager.subscribe()
    # Fill the queue (maxsize=64)
    for i in range(64):
        q.put_nowait({"i": i})

    # This should not raise nor block
    await manager.broadcast({"overflow": True})
    assert q.qsize() == 64  # Original entries still present


@pytest.mark.asyncio
async def test_sse_manager_client_count_after_unsubscribe():
    """Unsubscribing a queue that was already removed is idempotent."""
    from app.sse import SSEManager

    manager = SSEManager()
    q = manager.subscribe()
    assert manager.client_count == 1

    manager.unsubscribe(q)
    assert manager.client_count == 0

    # Unsubscribe again with the same queue — should not raise
    manager.unsubscribe(q)
    assert manager.client_count == 0

    # Unsubscribe with a queue that was never subscribed
    import asyncio
    orphan = asyncio.Queue()
    manager.unsubscribe(orphan)  # Should not raise
    assert manager.client_count == 0
