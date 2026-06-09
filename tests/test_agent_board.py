"""
Tests for the Agent Board module (Phase 3).

Tests task queue, messaging, claim flow, and LISTEN/NOTIFY.
Uses httpx ASGITransport to test the FastAPI app directly.
"""
import pytest
import pytest_asyncio
import bcrypt
from uuid import uuid4

import httpx
import os

from tests.conftest import container_required

BASE_URL = os.environ.get("LAMADB_TEST_URL", "http://localhost:8000")
AUTH_HEADERS = {"Authorization": "Bearer lamadb_test_key_2026"}

from app.config import settings


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def client():
    """Create an async httpx client pointing at the running container."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as ac:
        yield ac


@pytest_asyncio.fixture(scope="function")
async def db_pool():
    """Create a fresh asyncpg pool against the running container's Postgres."""
    import asyncpg
    pool = await asyncpg.create_pool(
        dsn=settings.database_url, min_size=1, max_size=4, command_timeout=60,
    )
    try:
        yield pool
    finally:
        await pool.close()


@pytest_asyncio.fixture(scope="function")
async def admin_key(db_pool):
    """Create a temporary admin API key for testing."""
    key_plain = f"test-admin-{uuid4().hex[:8]}"
    key_hash = bcrypt.hashpw(
        f"{settings.api_key_salt}{key_plain}".encode(),
        bcrypt.gensalt()
    ).decode()

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO api_keys (name, key_hash, role, scopes)
            VALUES ($1, $2, $3, $4)
            """,
            "test-admin",
            key_hash,
            "admin",
            []
        )

    yield key_plain

    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM api_keys WHERE name = $1", "test-admin")


@pytest_asyncio.fixture(scope="function")
async def agent_key(db_pool):
    """Create a temporary agent API key for testing."""
    key_plain = f"test-agent-{uuid4().hex[:8]}"
    key_hash = bcrypt.hashpw(
        f"{settings.api_key_salt}{key_plain}".encode(),
        bcrypt.gensalt()
    ).decode()

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO api_keys (name, key_hash, role, scopes)
            VALUES ($1, $2, $3, $4)
            """,
            "test-agent",
            key_hash,
            "agent",
            []
        )

    yield key_plain

    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM api_keys WHERE name = $1", "test-agent")


@pytest_asyncio.fixture(scope="function")
async def read_key(db_pool):
    """Create a temporary read-only API key for testing 403 responses."""
    key_plain = f"test-read-{uuid4().hex[:8]}"
    key_hash = bcrypt.hashpw(
        f"{settings.api_key_salt}{key_plain}".encode(),
        bcrypt.gensalt()
    ).decode()

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO api_keys (name, key_hash, role, scopes)
            VALUES ($1, $2, $3, $4)
            """,
            "test-read",
            key_hash,
            "read",
            []
        )

    yield key_plain

    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM api_keys WHERE name = $1", "test-read")


@pytest_asyncio.fixture(scope="function")
async def sample_task(client, admin_key):
    """Create a sample task for testing."""
    response = await client.post(
        "/api/agent_board/tasks",
        json={
            "title": "Test Task",
            "description": "A test task",
            "task_type": "general",
            "priority": "normal",
        },
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 201
    task = response.json()
    yield task
    # Cleanup not needed as tasks table is cleaned per-test


# ---------------------------------------------------------------------------
# Test: create task
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_create_task(client, admin_key):
    """POST /api/agent_board/tasks → 201, task in response."""
    response = await client.post(
        "/api/agent_board/tasks",
        json={
            "title": "Build something",
            "description": "Important work",
            "task_type": "development",
            "priority": "high",
        },
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Build something"
    assert data["description"] == "Important work"
    assert data["task_type"] == "development"
    assert data["priority"] == "high"
    assert data["status"] == "pending"
    assert "id" in data
    assert "created_at" in data


# ---------------------------------------------------------------------------
# Test: list tasks
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_list_tasks(client, admin_key, sample_task):
    """GET /api/agent_board/tasks → returns array."""
    response = await client.get(
        "/api/agent_board/tasks",
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1


# ---------------------------------------------------------------------------
# Test: filter tasks by status
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_filter_tasks_by_status(client, admin_key):
    """GET ?status=pending → only pending tasks."""
    # Create a pending task
    await client.post(
        "/api/agent_board/tasks",
        json={"title": "Pending Task", "priority": "normal"},
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    # Create and claim a task
    resp = await client.post(
        "/api/agent_board/tasks",
        json={"title": "Claimed Task", "priority": "high"},
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    task_id = resp.json()["id"]
    await client.post(
        f"/api/agent_board/tasks/{task_id}/claim",
        json={"claimed_by": "worker-1"},
        headers={"Authorization": f"Bearer {admin_key}"}
    )

    # Filter by pending
    response = await client.get(
        "/api/agent_board/tasks?status=pending",
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200
    data = response.json()
    for task in data:
        assert task["status"] == "pending"


# ---------------------------------------------------------------------------
# Test: filter tasks by priority
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_filter_tasks_by_priority(client, admin_key):
    """GET ?priority=high → only high priority tasks."""
    await client.post(
        "/api/agent_board/tasks",
        json={"title": "Low Task", "priority": "low"},
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    await client.post(
        "/api/agent_board/tasks",
        json={"title": "High Task", "priority": "high"},
        headers={"Authorization": f"Bearer {admin_key}"}
    )

    response = await client.get(
        "/api/agent_board/tasks?priority=high",
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200
    data = response.json()
    for task in data:
        assert task["priority"] == "high"


# ---------------------------------------------------------------------------
# Test: claim task
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_claim_task(client, admin_key):
    """POST /tasks/{id}/claim → status='claimed', claimed_by set."""
    # Create a task
    resp = await client.post(
        "/api/agent_board/tasks",
        json={"title": "Claimable Task"},
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    task_id = resp.json()["id"]

    # Claim it
    response = await client.post(
        f"/api/agent_board/tasks/{task_id}/claim",
        json={"claimed_by": "muninn"},
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "claimed"
    assert data["claimed_by"] == "muninn"
    assert data["claimed_at"] is not None


# ---------------------------------------------------------------------------
# Test: claim already claimed task
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_claim_already_claimed_task(client, admin_key):
    """Claim claimed task → 409 Conflict."""
    # Create and claim a task
    resp = await client.post(
        "/api/agent_board/tasks",
        json={"title": "Double Claim Test"},
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    task_id = resp.json()["id"]
    await client.post(
        f"/api/agent_board/tasks/{task_id}/claim",
        json={"claimed_by": "worker-1"},
        headers={"Authorization": f"Bearer {admin_key}"}
    )

    # Try to claim again
    response = await client.post(
        f"/api/agent_board/tasks/{task_id}/claim",
        json={"claimed_by": "worker-2"},
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# Test: complete task
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_complete_task(client, admin_key):
    """POST /tasks/{id}/complete → status='completed', result set."""
    # Create, claim, then complete
    resp = await client.post(
        "/api/agent_board/tasks",
        json={"title": "Completable Task"},
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    task_id = resp.json()["id"]
    await client.post(
        f"/api/agent_board/tasks/{task_id}/claim",
        json={"claimed_by": "muninn"},
        headers={"Authorization": f"Bearer {admin_key}"}
    )

    response = await client.post(
        f"/api/agent_board/tasks/{task_id}/complete",
        json={"result": {"output": "done", "items": 42}},
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["result"]["output"] == "done"
    assert data["completed_at"] is not None


# ---------------------------------------------------------------------------
# Test: fail task
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_fail_task(client, admin_key):
    """POST /tasks/{id}/fail → status='failed', error set."""
    # Create, claim, then fail
    resp = await client.post(
        "/api/agent_board/tasks",
        json={"title": "Failable Task"},
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    task_id = resp.json()["id"]
    await client.post(
        f"/api/agent_board/tasks/{task_id}/claim",
        json={"claimed_by": "muninn"},
        headers={"Authorization": f"Bearer {admin_key}"}
    )

    response = await client.post(
        f"/api/agent_board/tasks/{task_id}/fail",
        json={"error": "Something went wrong"},
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["error"] == "Something went wrong"
# ---------------------------------------------------------------------------
# Test: unclaim task
# ---------------------------------------------------------------------------
@container_required
@pytest.mark.asyncio
async def test_unclaim_task(client, admin_key):
    """POST /tasks/{id}/unclaim → status='pending', claimed_by cleared."""
    # Create and claim a task
    resp = await client.post(
        "/api/agent_board/tasks",
        json={"title": "Unclaimable Task"},
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    task_id = resp.json()["id"]
    await client.post(
        f"/api/agent_board/tasks/{task_id}/claim",
        json={"claimed_by": "worker-1"},
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    # Unclaim it
    response = await client.post(
        f"/api/agent_board/tasks/{task_id}/unclaim",
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending"
    assert data["claimed_by"] is None
    assert data["claimed_at"] is None
# ---------------------------------------------------------------------------
# Test: unclaim non-claimed task fails
# ---------------------------------------------------------------------------
@container_required
@pytest.mark.asyncio
async def test_unclaim_non_claimed_task(client, admin_key):
    """Unclaim a pending task → 400."""
    resp = await client.post(
        "/api/agent_board/tasks",
        json={"title": "Never Claimed"},
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    task_id = resp.json()["id"]
    response = await client.post(
        f"/api/agent_board/tasks/{task_id}/unclaim",
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 400
# ---------------------------------------------------------------------------
# Test: unclaim not found
# ---------------------------------------------------------------------------
@container_required
@pytest.mark.asyncio
async def test_unclaim_not_found(client, admin_key):
    """Unclaim a fake task → 404."""
    fake_id = str(uuid4())
    response = await client.post(
        f"/api/agent_board/tasks/{fake_id}/unclaim",
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 404
# ---------------------------------------------------------------------------
# Test: read role cannot unclaim
# ---------------------------------------------------------------------------
@container_required
@pytest.mark.asyncio
async def test_unclaim_forbidden_for_read_role(client, read_key):
    """Read role → 403 on unclaim."""
    # Create and claim a task first (needs admin)
    resp = await client.post(
        "/api/agent_board/tasks",
        json={"title": "Restricted Unclaim"},
        headers={"Authorization": f"Bearer {read_key}"}
    )
    # read_key can't even create; use admin to set up
    # Just test the 403 directly on a fake id
    response = await client.post(
        f"/api/agent_board/tasks/{str(uuid4())}/unclaim",
        headers={"Authorization": f"Bearer {read_key}"}
    )
    assert response.status_code == 403
# ---------------------------------------------------------------------------
# Test: mark message read
# ---------------------------------------------------------------------------
@container_required
@pytest.mark.asyncio
async def test_mark_message_read(client, admin_key):
    """POST /messages/{id}/read → read=true."""
    # Send a message
    resp = await client.post(
        "/api/agent_board/messages",
        json={"to_agent": "muninn", "subject": "Read me"},
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    msg_id = resp.json()["id"]
    # Mark as read
    response = await client.patch(
        f"/api/agent_board/messages/{msg_id}/read",
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["read"] is True
# ---------------------------------------------------------------------------
# Test: mark message read not found
# ---------------------------------------------------------------------------
@container_required
@pytest.mark.asyncio
async def test_mark_message_read_not_found(client, admin_key):
    """Mark a fake message → 404."""
    response = await client.patch(
        "/api/agent_board/messages/999999/read",
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 404

# ---------------------------------------------------------------------------
# Test: complete unclaimed task
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_complete_unclaimed_task(client, admin_key):
    """Complete without claim → 400."""
    # Create a task but don't claim it
    resp = await client.post(
        "/api/agent_board/tasks",
        json={"title": "Unclaimed Task"},
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    task_id = resp.json()["id"]

    response = await client.post(
        f"/api/agent_board/tasks/{task_id}/complete",
        json={"result": {"output": "oops"}},
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Test: send message
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_send_message(client, admin_key):
    """POST /api/agent_board/messages → 201."""
    response = await client.post(
        "/api/agent_board/messages",
        json={
            "to_agent": "muninn",
            "subject": "Help needed",
            "body": "Can you check the database?",
            "message_type": "question",
        },
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["subject"] == "Help needed"
    assert data["to_agent"] == "muninn"
    assert data["message_type"] == "question"
    assert "id" in data
    assert "created_at" in data


# ---------------------------------------------------------------------------
# Test: list messages filtered
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_list_messages_filtered(client, admin_key):
    """GET ?to_agent=muninn&unread=true → filtered."""
    # Send two messages
    await client.post(
        "/api/agent_board/messages",
        json={"to_agent": "muninn", "subject": "Msg for Muninn"},
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    await client.post(
        "/api/agent_board/messages",
        json={"to_agent": "rommie", "subject": "Msg for Rommie"},
        headers={"Authorization": f"Bearer {admin_key}"}
    )

    # Filter
    response = await client.get(
        "/api/agent_board/messages?to_agent=muninn",
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200
    data = response.json()
    for msg in data:
        assert msg["to_agent"] == "muninn"


# ---------------------------------------------------------------------------
# Test: unauthorized create
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_unauthorized_create(client, read_key):
    """Read role → 403 on POST."""
    response = await client.post(
        "/api/agent_board/tasks",
        json={"title": "Should fail"},
        headers={"Authorization": f"Bearer {read_key}"}
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Test: create task with metadata
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_create_task_with_metadata(client, admin_key):
    """JSONB round-trips correctly."""
    response = await client.post(
        "/api/agent_board/tasks",
        json={
            "title": "Task with Metadata",
            "metadata": {"key": "value", "nested": {"a": 1}},
        },
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["metadata"]["key"] == "value"
    assert data["metadata"]["nested"]["a"] == 1


# ---------------------------------------------------------------------------
# Test: get task by ID
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_get_task_by_id(client, admin_key, sample_task):
    """GET /api/agent_board/tasks/{id} → returns task."""
    task_id = sample_task["id"]
    response = await client.get(
        f"/api/agent_board/tasks/{task_id}",
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == task_id
    assert data["title"] == sample_task["title"]


# ---------------------------------------------------------------------------
# Test: get task not found
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_get_task_not_found(client, admin_key):
    """GET /api/agent_board/tasks/{fake_id} → 404."""
    fake_id = str(uuid4())
    response = await client.get(
        f"/api/agent_board/tasks/{fake_id}",
        headers={"Authorization": f"Bearer {admin_key}"}
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Test: agent role can create tasks
# ---------------------------------------------------------------------------

@container_required
@pytest.mark.asyncio
async def test_agent_can_create_task(client, agent_key):
    """Agent role (not admin) can create tasks."""
    response = await client.post(
        "/api/agent_board/tasks",
        json={"title": "Agent created"},
        headers={"Authorization": f"Bearer {agent_key}"}
    )
    assert response.status_code == 201