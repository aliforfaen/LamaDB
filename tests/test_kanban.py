"""
Tests for the Kanban module (Phase 10).

Covers boards, columns, tasks, subtasks, dependencies, comments, agent logs,
cache invalidation, and MCP tools. Tests run against the live Docker
container on localhost:8000.

Run a single test class:
    docker exec lamadb_api python3 -m pytest tests/test_kanban.py -q
"""
import os
import json
import time
from uuid import uuid4

import pytest
import pytest_asyncio
import bcrypt
import httpx

from tests.conftest import container_required
from app.config import settings


BASE_URL = os.environ.get("LAMADB_TEST_URL", "http://localhost:8000")
# Permanent admin key (pre-existing in DB; linked to user 'ali')
ADMIN_HEADERS = {"Authorization": "Bearer lamadb_test_key_2026"}


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="function")
async def client():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as ac:
        yield ac


@pytest_asyncio.fixture(scope="function")
async def db_pool():
    import asyncpg
    pool = await asyncpg.create_pool(
        dsn=settings.database_url, min_size=1, max_size=4, command_timeout=60,
    )
    try:
        yield pool
    finally:
        await pool.close()


@pytest_asyncio.fixture(scope="function")
async def read_key(db_pool):
    """Temporary read-only API key for 403 tests."""
    key_plain = f"test-kanban-read-{uuid4().hex[:8]}"
    key_hash = bcrypt.hashpw(
        f"{settings.api_key_salt}{key_plain}".encode(),
        bcrypt.gensalt(),
    ).decode()
    from app.auth import _hash_prefix
    key_prefix = _hash_prefix(key_plain)

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO api_keys (name, key_hash, key_prefix, role, scopes, active)
            VALUES ($1, $2, $3, 'read', '{}', true)
            """,
            "test-kanban-read", key_hash, key_prefix,
        )

    yield key_plain

    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM api_keys WHERE name = $1", "test-kanban-read")


@pytest_asyncio.fixture(scope="function")
async def test_board(client, db_pool):
    """Create a fresh agentic test board. Cleans up after itself.

    Teardown removes agent logs by both board_id AND task_id (in this
    board) because some log actions set task_id without a board_id, and
    `kanban_agent_logs.task_id` lacks ON DELETE CASCADE.
    """
    name = f"Test Board {uuid4().hex[:8]}"
    response = await client.post(
        "/api/kanban/boards",
        json={"name": name, "type": "agentic"},
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 201, response.text
    board = response.json()
    board_id = board["id"]

    # Fetch the default columns
    detail = await client.get(
        f"/api/kanban/boards/{board_id}", headers=ADMIN_HEADERS,
    )
    assert detail.status_code == 200
    columns = {c["status"]: c for c in detail.json()["columns"]}

    yield {"id": board_id, "name": name, "columns": columns}

    # Teardown: clean agent logs (both by board_id and by task_id in this
    # board, since task_id FK has no CASCADE), then drop the board which
    # cascades to columns, tasks, subtasks, dependencies, comments.
    async with db_pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM kanban_agent_logs WHERE board_id = $1",
            board_id,
        )
        await conn.execute(
            "DELETE FROM kanban_agent_logs WHERE task_id IN "
            "(SELECT id FROM kanban_tasks WHERE board_id = $1)",
            board_id,
        )
        await conn.execute("DELETE FROM kanban_boards WHERE id = $1", board_id)


# ---------------------------------------------------------------------------
# 1. User/Identity
# ---------------------------------------------------------------------------

@container_required
class TestAgentConnect:
    """GET /api/kanban/me — agent first-connect payload."""

    @pytest.mark.asyncio
    async def test_me_returns_profile_and_boards(self, client):
        response = await client.get("/api/kanban/me", headers=ADMIN_HEADERS)
        assert response.status_code == 200
        data = response.json()

        # Profile
        assert "user" in data
        assert data["user"]["name"] == "ali"
        assert data["user"]["type"] == "human"
        assert "id" in data["user"]

        # Masked key + endpoints
        assert data["api_key_masked"]
        assert data["endpoints"]["mcp"] == "/mcp"
        assert data["endpoints"]["api"] == "/api/kanban"

        # active_boards is a list (may be empty or have the QA board)
        assert isinstance(data["active_boards"], list)
        for b in data["active_boards"]:
            assert "id" in b and "name" in b
            assert "task_count" in b and "column_count" in b

        # my_open_tasks is a list (admin user likely has none)
        assert isinstance(data["my_open_tasks"], list)

    @pytest.mark.asyncio
    async def test_me_requires_auth(self, client):
        response = await client.get("/api/kanban/me")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# 2. Board CRUD
# ---------------------------------------------------------------------------

@container_required
class TestBoards:
    """Board list, create (agentic + personal), get, update, delete, auth."""

    @pytest.mark.asyncio
    async def test_list_boards_includes_existing(self, client, test_board):
        response = await client.get("/api/kanban/boards", headers=ADMIN_HEADERS)
        assert response.status_code == 200
        boards = response.json()
        assert isinstance(boards, list)
        names = [b["name"] for b in boards]
        assert test_board["name"] in names

    @pytest.mark.asyncio
    async def test_create_agentic_board_creates_default_columns(self, client, db_pool):
        name = f"Agentic Board {uuid4().hex[:8]}"
        response = await client.post(
            "/api/kanban/boards",
            json={"name": name, "type": "agentic"},
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 201
        board = response.json()
        assert board["name"] == name
        assert board["columns"] == 4

        # Verify the columns that were created
        detail = await client.get(
            f"/api/kanban/boards/{board['id']}", headers=ADMIN_HEADERS,
        )
        cols = {c["status"]: c for c in detail.json()["columns"]}
        assert set(cols.keys()) == {"backlog", "in_progress", "review", "done"}
        assert cols["backlog"]["name"] == "Backlog"
        assert cols["done"]["name"] == "Done"

        # Cleanup
        async with db_pool.acquire() as conn:
            await conn.execute("DELETE FROM kanban_agent_logs WHERE board_id = $1", board["id"])
            await conn.execute("DELETE FROM kanban_boards WHERE id = $1", board["id"])

    @pytest.mark.asyncio
    async def test_create_personal_board_uses_inbox(self, client, db_pool):
        name = f"Personal Board {uuid4().hex[:8]}"
        response = await client.post(
            "/api/kanban/boards",
            json={"name": name, "type": "personal"},
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 201
        board_id = response.json()["id"]

        detail = await client.get(
            f"/api/kanban/boards/{board_id}", headers=ADMIN_HEADERS,
        )
        cols = {c["status"]: c for c in detail.json()["columns"]}
        # Personal boards use "Inbox" instead of "Backlog" but same status code
        assert cols["backlog"]["name"] == "Inbox"
        assert set(cols.keys()) == {"backlog", "in_progress", "review", "done"}

        async with db_pool.acquire() as conn:
            await conn.execute("DELETE FROM kanban_agent_logs WHERE board_id = $1", board_id)
            await conn.execute("DELETE FROM kanban_boards WHERE id = $1", board_id)

    @pytest.mark.asyncio
    async def test_get_board_returns_columns_with_task_counts(
        self, client, test_board,
    ):
        response = await client.get(
            f"/api/kanban/boards/{test_board['id']}", headers=ADMIN_HEADERS,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == test_board["name"]
        assert len(data["columns"]) == 4
        for c in data["columns"]:
            assert "task_count" in c
            assert c["task_count"] == 0  # fresh board

    @pytest.mark.asyncio
    async def test_get_board_not_found(self, client):
        fake = str(uuid4())
        response = await client.get(f"/api/kanban/boards/{fake}", headers=ADMIN_HEADERS)
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_board(self, client, test_board):
        new_name = f"Renamed {uuid4().hex[:6]}"
        response = await client.patch(
            f"/api/kanban/boards/{test_board['id']}",
            json={"name": new_name, "instructions": "Updated instructions"},
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 200

        # Verify the change persisted
        detail = await client.get(
            f"/api/kanban/boards/{test_board['id']}", headers=ADMIN_HEADERS,
        )
        assert detail.json()["name"] == new_name
        assert detail.json()["instructions"] == "Updated instructions"

    @pytest.mark.asyncio
    async def test_update_board_not_found(self, client):
        fake = str(uuid4())
        response = await client.patch(
            f"/api/kanban/boards/{fake}",
            json={"name": "nope"},
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_board_then_404(self, client, db_pool):
        # Create a throwaway board
        name = f"Delete Me {uuid4().hex[:8]}"
        create = await client.post(
            "/api/kanban/boards",
            json={"name": name, "type": "agentic"},
            headers=ADMIN_HEADERS,
        )
        board_id = create.json()["id"]

        # Delete it
        response = await client.delete(
            f"/api/kanban/boards/{board_id}", headers=ADMIN_HEADERS,
        )
        assert response.status_code == 200
        assert response.json()["status"] == "deleted"

        # Confirm 404
        response = await client.get(
            f"/api/kanban/boards/{board_id}", headers=ADMIN_HEADERS,
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_read_key_can_list_but_not_create(self, client, read_key):
        headers = {"Authorization": f"Bearer {read_key}"}

        # Read OK
        response = await client.get("/api/kanban/boards", headers=headers)
        assert response.status_code == 200

        # Create rejected (403 from _require_admin_or_agent)
        response = await client.post(
            "/api/kanban/boards",
            json={"name": "Should fail", "type": "agentic"},
            headers=headers,
        )
        assert response.status_code == 403

        # Update rejected
        response = await client.patch(
            f"/api/kanban/boards/{uuid4()}",
            json={"name": "x"},
            headers=headers,
        )
        assert response.status_code == 403

        # Delete rejected
        response = await client.delete(
            f"/api/kanban/boards/{uuid4()}", headers=headers,
        )
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# 3. Column CRUD
# ---------------------------------------------------------------------------

@container_required
class TestColumns:
    """Add, rename, and delete columns. Verify task migration on delete."""

    @pytest.mark.asyncio
    async def test_add_column(self, client, test_board):
        response = await client.post(
            f"/api/kanban/boards/{test_board['id']}/columns",
            json={"name": "QA", "status": "review", "position": 5, "wip_limit": 3},
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 201
        col = response.json()
        assert col["name"] == "QA"
        assert col["status"] == "review"

    @pytest.mark.asyncio
    async def test_rename_column(self, client, test_board):
        col_id = test_board["columns"]["review"]["id"]
        response = await client.patch(
            f"/api/kanban/columns/{col_id}",
            json={"name": "Code Review", "wip_limit": 5},
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 200

        # Verify
        detail = await client.get(
            f"/api/kanban/boards/{test_board['id']}", headers=ADMIN_HEADERS,
        )
        cols = {c["id"]: c for c in detail.json()["columns"]}
        assert cols[col_id]["name"] == "Code Review"
        assert cols[col_id]["wip_limit"] == 5

    @pytest.mark.asyncio
    async def test_delete_column_moves_tasks_to_first(self, client, test_board):
        # Add a task to the Review column, then delete it
        review_col = test_board["columns"]["review"]["id"]
        backlog_col = test_board["columns"]["backlog"]["id"]

        create_resp = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "In review", "column_id": review_col},
            headers=ADMIN_HEADERS,
        )
        assert create_resp.status_code == 201
        task_id = create_resp.json()["id"]

        # Delete the Review column
        response = await client.delete(
            f"/api/kanban/columns/{review_col}", headers=ADMIN_HEADERS,
        )
        assert response.status_code == 200

        # Task should now be in Backlog (the first column by position)
        get_resp = await client.get(
            f"/api/kanban/tasks/{task_id}", headers=ADMIN_HEADERS,
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["column_id"] == backlog_col

    @pytest.mark.asyncio
    async def test_delete_column_not_found(self, client):
        fake = str(uuid4())
        response = await client.delete(
            f"/api/kanban/columns/{fake}", headers=ADMIN_HEADERS,
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_read_key_cannot_add_column(self, client, test_board, read_key):
        response = await client.post(
            f"/api/kanban/boards/{test_board['id']}/columns",
            json={"name": "x", "status": "review"},
            headers={"Authorization": f"Bearer {read_key}"},
        )
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# 4. Task lifecycle
# ---------------------------------------------------------------------------

@container_required
class TestTaskLifecycle:
    """Create, list, get, update, move, claim, complete, and task_number."""

    @pytest.mark.asyncio
    async def test_create_task(self, client, test_board):
        response = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={
                "title": "First task",
                "description": "Initial description",
                "priority": "high",
            },
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 201
        task = response.json()
        assert task["title"] == "First task"
        assert "id" in task
        assert task["task_number"] == 1  # first on a fresh board

    @pytest.mark.asyncio
    async def test_task_number_auto_increments(self, client, test_board):
        # Create 3 tasks in a row
        numbers = []
        for i in range(3):
            response = await client.post(
                f"/api/kanban/boards/{test_board['id']}/tasks",
                json={"title": f"Task {i}"},
                headers=ADMIN_HEADERS,
            )
            assert response.status_code == 201
            numbers.append(response.json()["task_number"])

        assert numbers == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_list_tasks_filter_by_column(self, client, test_board):
        # Create one task in backlog (default) and one in in_progress
        await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "Backlog task"},
            headers=ADMIN_HEADERS,
        )
        in_progress_col = test_board["columns"]["in_progress"]["id"]
        await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={
                "title": "Active task",
                "column_id": in_progress_col,
            },
            headers=ADMIN_HEADERS,
        )

        # Filter by column
        response = await client.get(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            params={"column_id": in_progress_col},
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 200
        tasks = response.json()
        assert len(tasks) == 1
        assert tasks[0]["title"] == "Active task"
        assert tasks[0]["column_id"] == in_progress_col

    @pytest.mark.asyncio
    async def test_get_task_includes_subtasks_deps_comments(self, client, test_board):
        # Create a task
        create = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "Detailed task"},
            headers=ADMIN_HEADERS,
        )
        task_id = create.json()["id"]

        # Add a subtask, a comment
        await client.post(
            f"/api/kanban/tasks/{task_id}/subtasks",
            json={"title": "Sub 1"},
            headers=ADMIN_HEADERS,
        )
        await client.post(
            f"/api/kanban/tasks/{task_id}/comments",
            json={"body": "Hello"},
            headers=ADMIN_HEADERS,
        )

        # Fetch full detail
        response = await client.get(
            f"/api/kanban/tasks/{task_id}", headers=ADMIN_HEADERS,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == task_id
        assert data["subtask_count"] == 1
        assert len(data["subtasks"]) == 1
        assert data["subtasks"][0]["title"] == "Sub 1"
        assert len(data["comments"]) == 1
        assert data["comments"][0]["body"] == "Hello"
        assert data["dependencies"] == []

    @pytest.mark.asyncio
    async def test_get_task_not_found(self, client):
        fake = str(uuid4())
        response = await client.get(
            f"/api/kanban/tasks/{fake}", headers=ADMIN_HEADERS,
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_task(self, client, test_board):
        create = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "Original"},
            headers=ADMIN_HEADERS,
        )
        task_id = create.json()["id"]

        response = await client.patch(
            f"/api/kanban/tasks/{task_id}",
            json={"title": "Updated", "priority": "critical"},
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 200

        # Verify
        get_resp = await client.get(
            f"/api/kanban/tasks/{task_id}", headers=ADMIN_HEADERS,
        )
        data = get_resp.json()
        assert data["title"] == "Updated"
        assert data["priority"] == "critical"

    @pytest.mark.asyncio
    async def test_update_task_not_found(self, client):
        fake = str(uuid4())
        response = await client.patch(
            f"/api/kanban/tasks/{fake}",
            json={"title": "x"},
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_move_task(self, client, test_board):
        create = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "Moveable"},
            headers=ADMIN_HEADERS,
        )
        task_id = create.json()["id"]
        review_col = test_board["columns"]["review"]["id"]

        response = await client.patch(
            f"/api/kanban/tasks/{task_id}/move",
            json={"column_id": review_col, "position": 2},
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 200
        assert response.json()["status"] == "moved"

        # Verify
        get_resp = await client.get(
            f"/api/kanban/tasks/{task_id}", headers=ADMIN_HEADERS,
        )
        assert get_resp.json()["column_id"] == review_col
        assert get_resp.json()["position"] == 2

    @pytest.mark.asyncio
    async def test_claim_task_sets_assignee(self, client, test_board):
        create = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "Claimable"},
            headers=ADMIN_HEADERS,
        )
        task_id = create.json()["id"]

        response = await client.post(
            f"/api/kanban/tasks/{task_id}/claim", headers=ADMIN_HEADERS,
        )
        assert response.status_code == 200
        assert response.json()["status"] == "claimed"

        # Verify assignee + column move
        get_resp = await client.get(
            f"/api/kanban/tasks/{task_id}", headers=ADMIN_HEADERS,
        )
        data = get_resp.json()
        assert data["assignee_id"] is not None
        # Should now be in in_progress column
        assert data["column_id"] == test_board["columns"]["in_progress"]["id"]

    @pytest.mark.asyncio
    async def test_claim_task_not_found(self, client):
        fake = str(uuid4())
        response = await client.post(
            f"/api/kanban/tasks/{fake}/claim", headers=ADMIN_HEADERS,
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_complete_task_moves_to_done(self, client, test_board):
        create = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "Completable"},
            headers=ADMIN_HEADERS,
        )
        task_id = create.json()["id"]

        response = await client.post(
            f"/api/kanban/tasks/{task_id}/complete",
            json={"summary": "All done"},
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 200
        assert response.json()["status"] == "completed"

        # Verify it landed in the Done column
        get_resp = await client.get(
            f"/api/kanban/tasks/{task_id}", headers=ADMIN_HEADERS,
        )
        data = get_resp.json()
        assert data["completed_at"] is not None
        assert data["column_id"] == test_board["columns"]["done"]["id"]

    @pytest.mark.asyncio
    async def test_complete_task_not_found(self, client):
        fake = str(uuid4())
        response = await client.post(
            f"/api/kanban/tasks/{fake}/complete",
            json={"summary": "x"},
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_create_task_rejects_invalid_priority(self, client, test_board):
        # Pydantic pattern check on the body — should 422
        response = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "x", "priority": "bogus"},
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_task_on_board_with_no_columns_fails(
        self, client, db_pool,
    ):
        # Make a board with NO columns (insert directly, bypass the API)
        name = f"Empty Board {uuid4().hex[:8]}"
        async with db_pool.acquire() as conn:
            board_id = await conn.fetchval(
                "INSERT INTO kanban_boards (name, type) VALUES ($1, 'agentic') RETURNING id",
                name,
            )

        try:
            response = await client.post(
                f"/api/kanban/boards/{board_id}/tasks",
                json={"title": "No column"},
                headers=ADMIN_HEADERS,
            )
            assert response.status_code == 400
        finally:
            async with db_pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM kanban_boards WHERE id = $1", board_id,
                )

    @pytest.mark.asyncio
    async def test_read_key_cannot_create_task(self, client, test_board, read_key):
        response = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "nope"},
            headers={"Authorization": f"Bearer {read_key}"},
        )
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# 5. Subtasks
# ---------------------------------------------------------------------------

@container_required
class TestSubtasks:
    """Add and toggle subtasks."""

    @pytest.mark.asyncio
    async def test_add_and_toggle_subtask(self, client, test_board):
        create = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "Parent"},
            headers=ADMIN_HEADERS,
        )
        task_id = create.json()["id"]

        sub_resp = await client.post(
            f"/api/kanban/tasks/{task_id}/subtasks",
            json={"title": "Sub A"},
            headers=ADMIN_HEADERS,
        )
        assert sub_resp.status_code == 201
        sub_id = sub_resp.json()["id"]

        # Initially incomplete
        detail = await client.get(
            f"/api/kanban/tasks/{task_id}", headers=ADMIN_HEADERS,
        )
        assert detail.json()["subtasks"][0]["completed"] is False

        # Toggle to completed
        toggle = await client.patch(
            f"/api/kanban/subtasks/{sub_id}",
            json={"completed": True},
            headers=ADMIN_HEADERS,
        )
        assert toggle.status_code == 200

        # Verify
        detail = await client.get(
            f"/api/kanban/tasks/{task_id}", headers=ADMIN_HEADERS,
        )
        assert detail.json()["subtasks"][0]["completed"] is True
        assert detail.json()["subtask_done"] == 1

        # Toggle back
        await client.patch(
            f"/api/kanban/subtasks/{sub_id}",
            json={"completed": False},
            headers=ADMIN_HEADERS,
        )
        detail = await client.get(
            f"/api/kanban/tasks/{task_id}", headers=ADMIN_HEADERS,
        )
        assert detail.json()["subtasks"][0]["completed"] is False


# ---------------------------------------------------------------------------
# 6. Dependencies
# ---------------------------------------------------------------------------

@container_required
class TestDependencies:
    """Add/remove dependencies and verify auto-start on completion."""

    @pytest.mark.asyncio
    async def test_add_and_remove_dependency(self, client, test_board):
        a = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "A (blocker)"},
            headers=ADMIN_HEADERS,
        )
        b = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "B (depends on A)"},
            headers=ADMIN_HEADERS,
        )
        a_id = a.json()["id"]
        b_id = b.json()["id"]

        # B depends on A
        add = await client.post(
            f"/api/kanban/tasks/{b_id}/dependencies",
            json={"depends_on_id": a_id},
            headers=ADMIN_HEADERS,
        )
        assert add.status_code == 201
        assert add.json()["status"] == "linked"

        # Verify B shows the dependency
        detail = await client.get(
            f"/api/kanban/tasks/{b_id}", headers=ADMIN_HEADERS,
        )
        deps = detail.json()["dependencies"]
        assert len(deps) == 1
        assert deps[0]["depends_on_id"] == a_id
        assert deps[0]["depends_on_completed"] is False

        # Remove the dependency
        remove = await client.delete(
            f"/api/kanban/tasks/{b_id}/dependencies/{a_id}",
            headers=ADMIN_HEADERS,
        )
        assert remove.status_code == 200
        assert remove.json()["status"] == "unlinked"

        # Verify gone
        detail = await client.get(
            f"/api/kanban/tasks/{b_id}", headers=ADMIN_HEADERS,
        )
        assert detail.json()["dependencies"] == []

    @pytest.mark.asyncio
    async def test_duplicate_dependency_is_idempotent(self, client, test_board):
        a = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "A"},
            headers=ADMIN_HEADERS,
        )
        b = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "B"},
            headers=ADMIN_HEADERS,
        )
        a_id, b_id = a.json()["id"], b.json()["id"]

        # Add the same dep twice — second should be a no-op (ON CONFLICT DO NOTHING)
        await client.post(
            f"/api/kanban/tasks/{b_id}/dependencies",
            json={"depends_on_id": a_id},
            headers=ADMIN_HEADERS,
        )
        second = await client.post(
            f"/api/kanban/tasks/{b_id}/dependencies",
            json={"depends_on_id": a_id},
            headers=ADMIN_HEADERS,
        )
        assert second.status_code == 201

        # Only one row
        detail = await client.get(
            f"/api/kanban/tasks/{b_id}", headers=ADMIN_HEADERS,
        )
        assert len(detail.json()["dependencies"]) == 1

    @pytest.mark.asyncio
    async def test_completing_task_auto_starts_dependent(
        self, client, test_board,
    ):
        # Two tasks. B depends on A. A is in Backlog, B is in Backlog.
        a = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "A"},
            headers=ADMIN_HEADERS,
        )
        b = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "B"},
            headers=ADMIN_HEADERS,
        )
        a_id, b_id = a.json()["id"], b.json()["id"]

        await client.post(
            f"/api/kanban/tasks/{b_id}/dependencies",
            json={"depends_on_id": a_id},
            headers=ADMIN_HEADERS,
        )

        in_progress_col = test_board["columns"]["in_progress"]["id"]
        backlog_col = test_board["columns"]["backlog"]["id"]

        # B should start in Backlog
        b_detail = await client.get(
            f"/api/kanban/tasks/{b_id}", headers=ADMIN_HEADERS,
        )
        assert b_detail.json()["column_id"] == backlog_col

        # Complete A
        await client.post(
            f"/api/kanban/tasks/{a_id}/complete",
            json={"summary": "x"},
            headers=ADMIN_HEADERS,
        )

        # B should now be in In Progress
        b_detail = await client.get(
            f"/api/kanban/tasks/{b_id}", headers=ADMIN_HEADERS,
        )
        assert b_detail.json()["column_id"] == in_progress_col


# ---------------------------------------------------------------------------
# 7. Comments
# ---------------------------------------------------------------------------

@container_required
class TestComments:
    """Add and list comments."""

    @pytest.mark.asyncio
    async def test_add_and_list_comments(self, client, test_board):
        create = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "Discussable"},
            headers=ADMIN_HEADERS,
        )
        task_id = create.json()["id"]

        # Add two comments
        for body in ["First", "Second"]:
            resp = await client.post(
                f"/api/kanban/tasks/{task_id}/comments",
                json={"body": body},
                headers=ADMIN_HEADERS,
            )
            assert resp.status_code == 201

        # List comments
        response = await client.get(
            f"/api/kanban/tasks/{task_id}/comments", headers=ADMIN_HEADERS,
        )
        assert response.status_code == 200
        comments = response.json()
        assert len(comments) == 2
        # Ordered by created_at
        assert comments[0]["body"] == "First"
        assert comments[1]["body"] == "Second"
        # Should be attributed to a user
        assert comments[0]["user_name"] == "ali"

    @pytest.mark.asyncio
    async def test_comment_rejects_empty(self, client, test_board):
        create = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "Discussable"},
            headers=ADMIN_HEADERS,
        )
        task_id = create.json()["id"]

        # Pydantic min_length=1 on body
        response = await client.post(
            f"/api/kanban/tasks/{task_id}/comments",
            json={"body": ""},
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# 8. Agent Logs
# ---------------------------------------------------------------------------

@container_required
class TestAgentLogs:
    """GET /api/kanban/boards/{id}/logs — audit trail."""

    @pytest.mark.asyncio
    async def test_logs_record_claim_and_complete(self, client, test_board):
        # Create + claim + complete a task — should generate log entries
        create = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "Logged"},
            headers=ADMIN_HEADERS,
        )
        task_id = create.json()["id"]
        await client.post(
            f"/api/kanban/tasks/{task_id}/claim", headers=ADMIN_HEADERS,
        )
        await client.post(
            f"/api/kanban/tasks/{task_id}/complete",
            json={"summary": "log me"},
            headers=ADMIN_HEADERS,
        )

        response = await client.get(
            f"/api/kanban/boards/{test_board['id']}/logs",
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 200
        logs = response.json()
        actions = {log["action"] for log in logs}
        assert "task_claimed" in actions
        assert "task_completed" in actions

    @pytest.mark.asyncio
    async def test_logs_respect_limit(self, client, test_board):
        response = await client.get(
            f"/api/kanban/boards/{test_board['id']}/logs",
            params={"limit": 1},
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 200
        assert len(response.json()) <= 1


# ---------------------------------------------------------------------------
# 9. Cache invalidation
# ---------------------------------------------------------------------------

@container_required
class TestCacheInvalidation:
    """Verify mutations invalidate the kanban_tasks and kanban caches.

    Uses timing-based verification: the cached endpoints have TTLs of
    30-60s, so a fast second call after a mutation should return FRESH
    data (i.e. not the cached pre-mutation state).
    """

    @pytest_asyncio.fixture
    async def board_with_task(self, client, test_board):
        create = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "Cache test", "priority": "low"},
            headers=ADMIN_HEADERS,
        )
        return create.json()["id"], test_board

    @pytest.mark.asyncio
    async def test_create_task_invalidates_cache(self, client, test_board):
        # Prime the cache
        await client.get(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            headers=ADMIN_HEADERS,
        )
        # Create a new task — should invalidate
        await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "Cache buster"},
            headers=ADMIN_HEADERS,
        )
        # Next list should reflect the new task
        response = await client.get(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            headers=ADMIN_HEADERS,
        )
        titles = [t["title"] for t in response.json()]
        assert "Cache buster" in titles

    @pytest.mark.asyncio
    async def test_move_task_invalidates_cache(self, client, board_with_task):
        task_id, board = board_with_task
        # Prime
        await client.get(
            f"/api/kanban/boards/{board['id']}/tasks", headers=ADMIN_HEADERS,
        )
        # Move
        review_col = board["columns"]["review"]["id"]
        await client.patch(
            f"/api/kanban/tasks/{task_id}/move",
            json={"column_id": review_col, "position": 0},
            headers=ADMIN_HEADERS,
        )
        # Verify next list reflects the move
        response = await client.get(
            f"/api/kanban/boards/{board['id']}/tasks",
            params={"column_id": review_col},
            headers=ADMIN_HEADERS,
        )
        ids = [t["id"] for t in response.json()]
        assert task_id in ids

    @pytest.mark.asyncio
    async def test_comment_invalidates_cache(self, client, board_with_task):
        task_id, board = board_with_task
        # Prime
        await client.get(
            f"/api/kanban/boards/{board['id']}/tasks", headers=ADMIN_HEADERS,
        )
        # Add a comment
        await client.post(
            f"/api/kanban/tasks/{task_id}/comments",
            json={"body": "fresh comment"},
            headers=ADMIN_HEADERS,
        )
        # The task detail endpoint should now show the comment
        detail = await client.get(
            f"/api/kanban/tasks/{task_id}", headers=ADMIN_HEADERS,
        )
        bodies = [c["body"] for c in detail.json()["comments"]]
        assert "fresh comment" in bodies

    @pytest.mark.asyncio
    async def test_add_dependency_invalidates_cache(
        self, client, test_board,
    ):
        a = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "A"},
            headers=ADMIN_HEADERS,
        )
        b = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "B"},
            headers=ADMIN_HEADERS,
        )
        a_id, b_id = a.json()["id"], b.json()["id"]

        # Prime B's detail cache
        await client.get(
            f"/api/kanban/tasks/{b_id}", headers=ADMIN_HEADERS,
        )

        # Add dep
        await client.post(
            f"/api/kanban/tasks/{b_id}/dependencies",
            json={"depends_on_id": a_id},
            headers=ADMIN_HEADERS,
        )

        # Detail should now show the dep
        detail = await client.get(
            f"/api/kanban/tasks/{b_id}", headers=ADMIN_HEADERS,
        )
        deps = detail.json()["dependencies"]
        assert len(deps) == 1
        assert deps[0]["depends_on_id"] == a_id

    @pytest.mark.asyncio
    async def test_remove_dependency_invalidates_cache(
        self, client, test_board,
    ):
        a = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "A"},
            headers=ADMIN_HEADERS,
        )
        b = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "B"},
            headers=ADMIN_HEADERS,
        )
        a_id, b_id = a.json()["id"], b.json()["id"]

        # Create dep
        await client.post(
            f"/api/kanban/tasks/{b_id}/dependencies",
            json={"depends_on_id": a_id},
            headers=ADMIN_HEADERS,
        )

        # Prime
        await client.get(
            f"/api/kanban/tasks/{b_id}", headers=ADMIN_HEADERS,
        )

        # Remove
        await client.delete(
            f"/api/kanban/tasks/{b_id}/dependencies/{a_id}",
            headers=ADMIN_HEADERS,
        )

        # Verify gone
        detail = await client.get(
            f"/api/kanban/tasks/{b_id}", headers=ADMIN_HEADERS,
        )
        assert detail.json()["dependencies"] == []


# ---------------------------------------------------------------------------
# 10. MCP tools (JSON-RPC at /mcp)
# ---------------------------------------------------------------------------

@container_required
class TestMCPTools:
    """MCP tools/list + tools/call for kanban_* tools.

    The MCP handler uses JSON-RPC 2.0 over POST /mcp. Auth is via the
    Authorization header (NOT the request body).
    """

    KANBAN_TOOL_NAMES = {
        "kanban_my_tasks",
        "kanban_find_work",
        "kanban_claim_task",
        "kanban_start_task",
        "kanban_complete_task",
        "kanban_create_task",
        "kanban_update_task",
        "kanban_add_comment",
        "kanban_get_task",
        "kanban_help_wanted",
        "kanban_my_instructions",
    }

    @pytest_asyncio.fixture
    async def mcp_user_id(self, db_pool):
        """Get the user_id linked to the test admin key.

        The 'ali' human user is linked to the admin test key in the DB
        (see migration 014).
        """
        async with db_pool.acquire() as conn:
            user_id = await conn.fetchval(
                "SELECT id FROM users WHERE name = 'ali' LIMIT 1"
            )
        assert user_id is not None
        return str(user_id)

    @pytest.mark.asyncio
    async def test_tools_list_includes_all_kanban_tools(self, client):
        """tools/list must expose all 11 kanban_* tools."""
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0", "id": 1,
                "method": "tools/list", "params": {},
            },
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["jsonrpc"] == "2.0"
        tools = body["result"]["tools"]
        names = {t["name"] for t in tools}
        missing = self.KANBAN_TOOL_NAMES - names
        assert not missing, f"Missing kanban tools: {missing}"

    @pytest.mark.asyncio
    async def test_tools_list_requires_auth(self, client):
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0", "id": 1,
                "method": "tools/list", "params": {},
            },
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_tools_call_unknown_tool_returns_error(self, client):
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0", "id": 1,
                "method": "tools/call",
                "params": {"name": "kanban_does_not_exist", "arguments": {}},
            },
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 200
        body = response.json()
        assert "error" in body
        assert body["error"]["code"] == -32601  # method not found

    @pytest.mark.asyncio
    async def test_kanban_my_tasks(self, client, mcp_user_id, test_board):
        # Create a task and assign it to the user
        create = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "MCP mine"},
            headers=ADMIN_HEADERS,
        )
        task_id = create.json()["id"]
        await client.post(
            f"/api/kanban/tasks/{task_id}/claim", headers=ADMIN_HEADERS,
        )

        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0", "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "kanban_my_tasks",
                    "arguments": {"user_id": mcp_user_id},
                },
            },
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 200
        body = response.json()
        result = json.loads(body["result"]["content"][0]["text"])
        assert "tasks" in result
        assert "count" in result
        ids = [t["id"] for t in result["tasks"]]
        assert task_id in ids

    @pytest.mark.asyncio
    async def test_kanban_find_work(self, client, mcp_user_id, test_board):
        # Create an unassigned task in Backlog
        create = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "Findable work"},
            headers=ADMIN_HEADERS,
        )
        task_id = create.json()["id"]

        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0", "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "kanban_find_work",
                    "arguments": {"user_id": mcp_user_id},
                },
            },
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 200
        body = response.json()
        result = json.loads(body["result"]["content"][0]["text"])
        assert "tasks" in result
        ids = [t["id"] for t in result["tasks"]]
        assert task_id in ids

    @pytest.mark.asyncio
    async def test_kanban_claim_task_moves_to_in_progress(
        self, client, mcp_user_id, test_board,
    ):
        create = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "Claimable via MCP"},
            headers=ADMIN_HEADERS,
        )
        task_id = create.json()["id"]

        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0", "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "kanban_claim_task",
                    "arguments": {
                        "user_id": mcp_user_id, "task_id": task_id,
                    },
                },
            },
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 200
        body = response.json()
        result = json.loads(body["result"]["content"][0]["text"])
        assert result["status"] == "claimed"

        # Verify column moved to in_progress
        detail = await client.get(
            f"/api/kanban/tasks/{task_id}", headers=ADMIN_HEADERS,
        )
        assert detail.json()["column_id"] == test_board["columns"]["in_progress"]["id"]

    @pytest.mark.asyncio
    async def test_kanban_complete_task_moves_to_done(
        self, client, mcp_user_id, test_board,
    ):
        create = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "MCP completable"},
            headers=ADMIN_HEADERS,
        )
        task_id = create.json()["id"]

        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0", "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "kanban_complete_task",
                    "arguments": {
                        "user_id": mcp_user_id,
                        "task_id": task_id,
                        "summary": "MCP finished it",
                    },
                },
            },
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 200
        body = response.json()
        result = json.loads(body["result"]["content"][0]["text"])
        assert result["status"] == "completed"

        # Verify column moved to Done
        detail = await client.get(
            f"/api/kanban/tasks/{task_id}", headers=ADMIN_HEADERS,
        )
        assert detail.json()["column_id"] == test_board["columns"]["done"]["id"]
        assert detail.json()["completed_at"] is not None

    @pytest.mark.asyncio
    async def test_kanban_create_task(self, client, mcp_user_id, test_board):
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0", "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "kanban_create_task",
                    "arguments": {
                        "user_id": mcp_user_id,
                        "board_id": test_board["id"],
                        "title": "MCP created",
                        "description": "via tools/call",
                        "priority": "high",
                    },
                },
            },
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 200
        body = response.json()
        result = json.loads(body["result"]["content"][0]["text"])
        assert result["status"] == "created"
        assert "task_id" in result
        assert "task_number" in result

    @pytest.mark.asyncio
    async def test_kanban_get_task(self, client, mcp_user_id, test_board):
        create = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "Getable", "description": "details here"},
            headers=ADMIN_HEADERS,
        )
        task_id = create.json()["id"]

        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0", "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "kanban_get_task",
                    "arguments": {
                        "user_id": mcp_user_id, "task_id": task_id,
                    },
                },
            },
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 200
        body = response.json()
        result = json.loads(body["result"]["content"][0]["text"])
        assert "task" in result
        assert result["task"]["title"] == "Getable"
        assert result["task"]["description"] == "details here"

    @pytest.mark.asyncio
    async def test_kanban_get_task_not_found(self, client, mcp_user_id):
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0", "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "kanban_get_task",
                    "arguments": {
                        "user_id": mcp_user_id,
                        "task_id": str(uuid4()),
                    },
                },
            },
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 200
        body = response.json()
        result = json.loads(body["result"]["content"][0]["text"])
        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_kanban_help_wanted(self, client, mcp_user_id, test_board):
        create = await client.post(
            f"/api/kanban/boards/{test_board['id']}/tasks",
            json={"title": "Need help"},
            headers=ADMIN_HEADERS,
        )
        task_id = create.json()["id"]

        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0", "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "kanban_help_wanted",
                    "arguments": {
                        "user_id": mcp_user_id,
                        "task_id": task_id,
                        "message": "Stuck on edge case",
                    },
                },
            },
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 200
        body = response.json()
        result = json.loads(body["result"]["content"][0]["text"])
        assert result["status"] == "flagged"

        # Verify
        detail = await client.get(
            f"/api/kanban/tasks/{task_id}", headers=ADMIN_HEADERS,
        )
        assert detail.json()["help_wanted"] is True
        assert detail.json()["help_wanted_message"] == "Stuck on edge case"

    @pytest.mark.asyncio
    async def test_mcp_invalid_key_returns_401(self, client, mcp_user_id):
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0", "id": 1,
                "method": "tools/list", "params": {},
            },
            headers={"Authorization": "Bearer definitely-not-a-real-key"},
        )
        assert response.status_code == 401
