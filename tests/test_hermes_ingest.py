"""Tests for the Hermes ingest endpoint (POST /api/hermes/ingest).

Tests verify document creation, upsert, event creation with correct
severity/ticker/metadata, and error handling.
"""
import pytest
import pytest_asyncio
import bcrypt
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from app.config import settings


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
async def db_pool():
    """Get the database pool for direct DB queries."""
    from app.db import get_pool
    return get_pool()


@pytest_asyncio.fixture(scope="function")
async def admin_key(db_pool):
    """Create a temporary admin API key for testing."""
    key_plain = "test-hermes-ingest-" + uuid4().hex[:8]
    key_hash = bcrypt.hashpw(
        (settings.api_key_salt + key_plain).encode(),
        bcrypt.gensalt()
    ).decode()
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO api_keys (name, key_hash, role, scopes) VALUES ($1, $2, $3, $4)",
            "test-hermes-ingest", key_hash, "admin", []
        )
    yield key_plain
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM api_keys WHERE name = $1", "test-hermes-ingest")


# ---------------------------------------------------------------------------
# Test: session_finalize creates document + event
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ingest_session_finalize(client, db_pool, admin_key):
    """POST session_finalize creates a document and info event."""
    session_id = "sess-finalize-" + uuid4().hex[:8]
    payload = {
        "event_type": "session_finalize",
        "timestamp": 1717800000.0,
        "data": {
            "id": session_id,
            "title": "Test Session",
            "preview": "A test conversation",
            "source": "cli",
            "model": "gpt-4",
            "message_count": 5,
            "tool_call_count": 2,
            "input_tokens": 100,
            "output_tokens": 50,
        },
    }

    response = await client.post("/api/hermes/ingest", json=payload,
                                 headers={"Authorization": f"Bearer {admin_key}"})
    data = response.json()

    assert response.status_code == 200
    assert data["accepted"] is True
    assert data["doc_id"] is not None
    assert data["detail"] == "created"

    # Verify document exists in DB
    async with db_pool.acquire() as conn:
        doc = await conn.fetchrow(
            "SELECT id, title, content, source_type "
            "FROM documents WHERE metadata->>'hermes_session_id' = $1",
            session_id,
        )
        assert doc is not None, "Document should exist"
        assert doc["title"] == "Test Session"
        assert doc["source_type"] == "hermes_session"

        # Verify event was created
        event = await conn.fetchrow(
            "SELECT id, source, type, severity, ticker "
            "FROM events WHERE metadata->>'session_id' = $1",
            session_id,
        )
        assert event is not None, "Summary event should exist"
        assert event["type"] == "hermes.session_end"
        assert event["severity"] == "info"
        assert event["ticker"] is True

    # Cleanup
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM document_links WHERE source_id = $1 OR target_id = $1",
                           doc["id"])
        await conn.execute("DELETE FROM documents WHERE metadata->>'hermes_session_id' = $1",
                           session_id)
        await conn.execute("DELETE FROM events WHERE metadata->>'session_id' = $1",
                           session_id)


# ---------------------------------------------------------------------------
# Test: session_finalize upsert (same session ID twice)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ingest_session_upsert(client, db_pool, admin_key):
    """POST same session ID twice updates document, no duplicate."""
    session_id = "sess-upsert-" + uuid4().hex[:8]
    payload = {
        "event_type": "session_finalize",
        "timestamp": 1717800000.0,
        "data": {
            "id": session_id,
            "title": "Original",
            "preview": "First version",
            "source": "cli",
            "model": "gpt-4",
            "message_count": 3,
            "tool_call_count": 1,
            "input_tokens": 50,
            "output_tokens": 25,
        },
    }

    # First POST — create
    r1 = await client.post("/api/hermes/ingest", json=payload,
                           headers={"Authorization": f"Bearer {admin_key}"})
    d1 = r1.json()
    assert d1["accepted"] is True
    assert d1["detail"] == "created"
    doc_id_1 = d1["doc_id"]

    # Second POST with updated title — upsert
    payload["data"]["title"] = "Updated"
    r2 = await client.post("/api/hermes/ingest", json=payload,
                           headers={"Authorization": f"Bearer {admin_key}"})
    d2 = r2.json()
    assert d2["accepted"] is True
    assert d2["detail"] == "updated"
    assert d2["doc_id"] == doc_id_1, "Should return same doc_id"

    # Verify only one document exists for this session
    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM documents WHERE metadata->>'hermes_session_id' = $1",
            session_id,
        )
        assert count == 1, "Should not duplicate document"

        # Verify title was updated
        title = await conn.fetchval(
            "SELECT title FROM documents WHERE metadata->>'hermes_session_id' = $1",
            session_id,
        )
        assert title == "Updated", "Title should reflect second POST"

    # Cleanup
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM events WHERE metadata->>'session_id' = $1",
                           session_id)
        await conn.execute("DELETE FROM document_links WHERE target_id = $1",
                           doc_id_1)
        await conn.execute("DELETE FROM documents WHERE id = $1", doc_id_1)


# ---------------------------------------------------------------------------
# Test: llm_call creates event
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ingest_llm_call(client, db_pool, admin_key):
    """POST llm_call creates an info event with token data."""
    payload = {
        "event_type": "llm_call",
        "timestamp": 1717800001.0,
        "data": {
            "session_id": "s1",
            "model": "gpt-4",
            "input_tokens": 10,
            "output_tokens": 20,
            "latency_ms": 1500,
        },
    }

    response = await client.post("/api/hermes/ingest", json=payload,
                                 headers={"Authorization": f"Bearer {admin_key}"})
    data = response.json()

    assert response.status_code == 200
    assert data["accepted"] is True
    assert data["event_id"] is not None

    # Verify event in DB
    async with db_pool.acquire() as conn:
        event = await conn.fetchrow(
            "SELECT id, source, type, severity, ticker, metadata "
            "FROM events WHERE id = $1",
            data["event_id"],
        )
        assert event is not None
        assert event["source"] == "hermes"
        assert event["type"] == "hermes.llm_call"
        assert event["severity"] == "info"
        assert event["ticker"] is False or event["ticker"] is None
        import json
        meta = json.loads(event["metadata"]) if isinstance(event["metadata"], str) else event["metadata"]
        assert meta["session_id"] == "s1"
        assert meta["model"] == "gpt-4"
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM events WHERE id = $1", data["event_id"])


# ---------------------------------------------------------------------------
# Test: credential_error creates error event with ticker
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ingest_credential_error(client, db_pool, admin_key):
    """POST credential_error creates error-severity event with ticker=true."""
    payload = {
        "event_type": "credential_error",
        "timestamp": 1717800002.0,
        "data": {
            "provider": "openai",
            "error": "invalid_api_key",
        },
    }

    response = await client.post("/api/hermes/ingest", json=payload,
                                 headers={"Authorization": f"Bearer {admin_key}"})
    data = response.json()

    assert response.status_code == 200
    assert data["accepted"] is True
    assert data["event_id"] is not None

    # Verify event in DB
    async with db_pool.acquire() as conn:
        event = await conn.fetchrow(
            "SELECT id, source, type, severity, ticker, title, body, tags "
            "FROM events WHERE id = $1",
            data["event_id"],
        )
        assert event is not None
        assert event["source"] == "hermes"
        assert event["type"] == "hermes.credential_error"
        assert event["severity"] == "error"
        assert event["ticker"] is True
        assert "openai" in event["title"]
        assert "invalid_api_key" in event["body"]
        assert "credential" in event["tags"]

    # Cleanup
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM events WHERE id = $1", data["event_id"])


# ---------------------------------------------------------------------------
# Test: gateway_status severity depends on state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ingest_gateway_status(client, db_pool, admin_key):
    """POST gateway_status with state=running → info, state=crashed → error."""
    event_ids = []

    # State: running → info severity
    payload_running = {
        "event_type": "gateway_status",
        "timestamp": 1717800003.0,
        "data": {"state": "running", "platforms": {"openai": "ok"}},
    }
    r1 = await client.post("/api/hermes/ingest", json=payload_running,
                           headers={"Authorization": f"Bearer {admin_key}"})
    d1 = r1.json()
    assert d1["accepted"] is True
    event_ids.append(d1["event_id"])

    # State: crashed → error severity, ticker=true
    payload_crashed = {
        "event_type": "gateway_status",
        "timestamp": 1717800004.0,
        "data": {"state": "crashed", "platforms": {}},
    }
    r2 = await client.post("/api/hermes/ingest", json=payload_crashed,
                           headers={"Authorization": f"Bearer {admin_key}"})
    d2 = r2.json()
    assert d2["accepted"] is True
    event_ids.append(d2["event_id"])

    # Verify in DB
    async with db_pool.acquire() as conn:
        events = await conn.fetch(
            "SELECT id, severity, ticker FROM events WHERE id = ANY($1) ORDER BY id",
            event_ids,
        )
        assert len(events) == 2
        assert events[0]["severity"] == "info"
        assert events[0]["ticker"] is False or events[0]["ticker"] is None
        assert events[1]["severity"] == "error"
        assert events[1]["ticker"] is True

    # Cleanup
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM events WHERE id = ANY($1)", event_ids)


# ---------------------------------------------------------------------------
# Test: unknown event_type returns 400
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ingest_unknown_type(client, admin_key):
    """POST with unknown event_type returns 400."""
    payload = {
        "event_type": "nonexistent",
        "timestamp": 1717800005.0,
        "data": {},
    }

    response = await client.post("/api/hermes/ingest", json=payload,
                                 headers={"Authorization": f"Bearer {admin_key}"})
    assert response.status_code == 400
    assert "Unknown event_type" in response.text
