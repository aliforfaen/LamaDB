"""
Tests for the MCP consolidated tool surface (Phase 17).

The MCP server exposes three JSON-RPC endpoints:
  POST /mcp         — legacy, returns all enabled tools
  POST /mcp/admin   — admin tools (toolset="admin" or "both")
  POST /mcp/worker  — worker tools (toolset="worker" or "both") only

The /api/mcp/admin/* REST routes cover the admin API (stats, tool
catalog, enable/disable). All tests run against the live Docker
container on localhost:8000.

Run a single test class:
    docker exec lamadb_api python3 -m pytest tests/test_mcp_consolidated.py -q
"""
import json
from uuid import uuid4

import bcrypt
import httpx
import pytest
import pytest_asyncio

from app.auth import _hash_prefix
from app.config import settings
from tests.conftest import container_required


BASE_URL = "http://localhost:8000"
ADMIN_HEADERS = {
    "Authorization": "Bearer lamadb_test_key_2026",
    "Content-Type": "application/json",
}


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="function")
async def client():
    """Async httpx client pointing at the live container."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as ac:
        yield ac


@pytest_asyncio.fixture(scope="function")
async def db_pool():
    """asyncpg pool for direct DB access (used to mint read-only keys)."""
    import asyncpg
    pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=1,
        max_size=4,
        command_timeout=60,
    )
    try:
        yield pool
    finally:
        await pool.close()


@pytest_asyncio.fixture(scope="function")
async def read_key(db_pool):
    """Mint a temporary read-only API key for 403 tests.

    Varies the first 16 chars (lamadb_r_<hex>) so we don't collide
    with other test fixtures on the key_prefix column.
    """
    # Put randomness inside the first 16 chars to avoid key_prefix
    # collisions (see AGENTS.md "API key test fixtures" pitfall).
    key_plain = f"lamadb_r_{uuid4().hex}"
    assert len(key_plain[:16]) == 16
    key_hash = bcrypt.hashpw(
        f"{settings.api_key_salt}{key_plain}".encode(),
        bcrypt.gensalt(),
    ).decode()
    key_prefix = _hash_prefix(key_plain)

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO api_keys (name, key_hash, key_prefix, role, scopes, active)
            VALUES ($1, $2, $3, 'read', '{}', true)
            """,
            f"test-mcp-read-{uuid4().hex[:8]}", key_hash, key_prefix,
        )

    yield key_plain

    async with db_pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM api_keys WHERE key_prefix = $1", key_prefix,
        )


@pytest_asyncio.fixture(scope="function")
async def reset_stats(client):
    """Reset MCP stats before a test that asserts on counts."""
    resp = await client.post(
        "/api/mcp/admin/stats/reset", headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 200
    yield


def _jsonrpc(method: str, params: dict, rpc_id: int = 1) -> dict:
    """Build a JSON-RPC 2.0 envelope."""
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "method": method,
        "params": params,
    }


async def _post_mcp(client, endpoint: str, method: str, params: dict,
                    headers: dict = ADMIN_HEADERS) -> dict:
    """POST a JSON-RPC request to an /mcp/* endpoint, return the parsed body."""
    resp = await client.post(
        endpoint, json=_jsonrpc(method, params), headers=headers,
    )
    return resp.json()


# ===========================================================================
# 1. Endpoint visibility — /mcp/admin and /mcp/worker toolset filtering
# ===========================================================================

@container_required
class TestEndpointVisibility:
    """Tools returned by each /mcp/* endpoint depend on toolset metadata."""

    CONSOLIDATED_TOOL_NAMES = {
        "agent_documents",
        "agent_events",
        "agent_wiki",
        "agent_uptime",
        "lamadb_docs",
        "agent_kanban_tasks",
        "agent_kanban_workflow",
        "agent_kanban_comments",
        "agent_kanban_meta",
        "agent_messages",
        "admin_secrets",
    }

    @pytest.mark.asyncio
    async def test_admin_endpoint_returns_all_consolidated_tools(self, client):
        """/mcp/admin should expose all 11 consolidated tools (admin + both)."""
        body = await _post_mcp(client, "/mcp/admin", "tools/list", {})
        assert "result" in body, body
        names = {t["name"] for t in body["result"]["tools"]}

        missing = self.CONSOLIDATED_TOOL_NAMES - names
        assert not missing, f"Missing consolidated tools: {missing}"
        # admin_secrets is the only toolset="admin" tool in the consolidated
        # surface and must be visible here.
        assert "admin_secrets" in names

    @pytest.mark.asyncio
    async def test_worker_endpoint_excludes_admin_secrets(self, client):
        """/mcp/worker must hide toolset="admin" tools (notably admin_secrets)."""
        body = await _post_mcp(client, "/mcp/worker", "tools/list", {})
        assert "result" in body, body
        names = {t["name"] for t in body["result"]["tools"]}

        assert "admin_secrets" not in names, (
            "admin_secrets has toolset='admin' and must not appear on /mcp/worker"
        )

    @pytest.mark.asyncio
    async def test_worker_endpoint_keeps_kanban_consolidated_tools(self, client):
        """agent_kanban_* tools are toolset='both', so they appear on worker too.

        The task spec hypothesised that agent_kanban_comments /
        agent_kanban_meta would be admin-only — that turned out NOT to
        be the case in the actual implementation. They are registered
        with toolset="both" and therefore should be visible to workers.
        """
        body = await _post_mcp(client, "/mcp/worker", "tools/list", {})
        assert "result" in body, body
        names = {t["name"] for t in body["result"]["tools"]}

        for name in (
            "agent_kanban_tasks",
            "agent_kanban_workflow",
            "agent_kanban_comments",
            "agent_kanban_meta",
        ):
            assert name in names, f"{name} should be visible on /mcp/worker"

    @pytest.mark.asyncio
    async def test_worker_endpoint_excludes_flat_secrets_tools(self, client):
        """The flat secrets tools (list_secrets, reveal_secret, etc.) are
        toolset='admin' in modules/secrets/__init__.py and must not appear
        on /mcp/worker either.
        """
        body = await _post_mcp(client, "/mcp/worker", "tools/list", {})
        assert "result" in body, body
        names = {t["name"] for t in body["result"]["tools"]}

        for flat_secret_tool in (
            "list_secrets",
            "get_secret_metadata",
            "reveal_secret",
            "request_secret_access",
        ):
            assert flat_secret_tool not in names, (
                f"{flat_secret_tool} is toolset='admin' and must not appear "
                f"on /mcp/worker"
            )


# ===========================================================================
# 2. Tool dispatch — action-based routing for each consolidated tool
# ===========================================================================

@container_required
class TestToolDispatch:
    """Each consolidated tool must route its action to the right handler."""

    @pytest.mark.asyncio
    async def test_agent_documents_search(self, client):
        """agent_documents action=search returns search results."""
        body = await _post_mcp(
            client,
            "/mcp/admin",
            "tools/call",
            {
                "name": "agent_documents",
                "arguments": {"action": "search", "q": "lamadb", "limit": 3},
            },
        )
        assert "result" in body, body
        result = json.loads(body["result"]["content"][0]["text"])
        assert "results" in result
        assert "count" in result
        assert "query" in result
        assert result["query"] == "lamadb"

    @pytest.mark.asyncio
    async def test_agent_events_list(self, client):
        """agent_events action=list returns events array."""
        body = await _post_mcp(
            client,
            "/mcp/admin",
            "tools/call",
            {
                "name": "agent_events",
                "arguments": {"action": "list", "limit": 5},
            },
        )
        assert "result" in body, body
        result = json.loads(body["result"]["content"][0]["text"])
        assert "events" in result
        assert "count" in result
        assert isinstance(result["events"], list)

    @pytest.mark.asyncio
    async def test_agent_kanban_tasks_my_tasks(self, client, db_pool):
        """agent_kanban_tasks action=my_tasks returns the calling user's tasks.

        Uses the 'ali' user (linked to the test admin key by migration 014).
        """
        async with db_pool.acquire() as conn:
            user_id = await conn.fetchval(
                "SELECT id FROM users WHERE name = 'ali' LIMIT 1"
            )
        assert user_id is not None, "test fixtures assume 'ali' user exists"

        body = await _post_mcp(
            client,
            "/mcp/admin",
            "tools/call",
            {
                "name": "agent_kanban_tasks",
                "arguments": {"action": "my_tasks", "user_id": str(user_id)},
            },
        )
        assert "result" in body, body
        result = json.loads(body["result"]["content"][0]["text"])
        assert "tasks" in result
        assert "count" in result
        assert isinstance(result["tasks"], list)

    @pytest.mark.asyncio
    async def test_admin_secrets_list(self, client, db_pool):
        """admin_secrets action=list returns the secret catalog visible to user.

        Tests with the admin user (ali) so we can see all secrets.
        """
        async with db_pool.acquire() as conn:
            user_id = await conn.fetchval(
                "SELECT id FROM users WHERE name = 'ali' LIMIT 1"
            )
        assert user_id is not None

        body = await _post_mcp(
            client,
            "/mcp/admin",
            "tools/call",
            {
                "name": "admin_secrets",
                "arguments": {"action": "list", "user_id": str(user_id)},
            },
        )
        assert "result" in body, body
        result = json.loads(body["result"]["content"][0]["text"])
        # The result is a JSON-encoded list (handler returns a list, not a dict).
        assert isinstance(result, list)
        # Each entry has the metadata fields a metadata-only listing should
        # carry — no plaintext "value".
        for entry in result:
            assert "id" in entry
            assert "name" in entry
            assert "service" in entry
            assert "value" not in entry


# ===========================================================================
# 3. Error handling — invalid actions, missing params, endpoint mismatch
# ===========================================================================

@container_required
class TestErrorHandling:
    """Unknown actions, missing params, and cross-endpoint calls all error."""

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self, client):
        body = await _post_mcp(
            client,
            "/mcp/admin",
            "tools/call",
            {
                "name": "agent_documents",
                "arguments": {"action": "definitely_not_a_real_action"},
            },
        )
        assert "error" in body, body
        assert body["error"]["code"] == -32603  # internal error
        assert "Unknown action" in body["error"]["message"]

    @pytest.mark.asyncio
    async def test_missing_action_returns_error(self, client):
        body = await _post_mcp(
            client,
            "/mcp/admin",
            "tools/call",
            {"name": "agent_documents", "arguments": {}},
        )
        assert "error" in body, body
        # The dispatcher raises ValueError("Missing 'action' parameter"),
        # which mcp_server catches and wraps as ERROR_INTERNAL (-32603).
        assert body["error"]["code"] == -32603
        assert "action" in body["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_admin_secrets_on_worker_endpoint_rejected(self, client):
        """admin_secrets is toolset="admin" so /mcp/worker must reject it."""
        body = await _post_mcp(
            client,
            "/mcp/worker",
            "tools/call",
            {
                "name": "admin_secrets",
                "arguments": {"action": "list", "user_id": str(uuid4())},
            },
        )
        assert "error" in body, body
        # The endpoint-visibility check returns ERROR_METHOD_NOT_FOUND (-32601).
        assert body["error"]["code"] == -32601
        assert "not available" in body["error"]["message"].lower()


# ===========================================================================
# 4. Tool toggle — PATCH /api/mcp/admin/tools/{name}
# ===========================================================================

@container_required
class TestToolToggle:
    """Disable a tool, verify it disappears from tools/list, then re-enable."""

    @pytest_asyncio.fixture
    async def toggleable_tool(self):
        """Pick a non-secrets tool that we can safely toggle.

        lamadb_docs is harmless to disable (it's a passthrough doc reader)
        and is toolset="both" so it appears on both /mcp/admin and
        /mcp/worker.
        """
        return "lamadb_docs"

    @pytest_asyncio.fixture(autouse=True)
    async def restore_tool_state(self, client):
        """Ensure tools we disable are re-enabled at the end of the test."""
        yield
        # Best-effort re-enable for any tool we may have toggled.
        # Pin to the test's specific tool name; the test below only ever
        # touches "lamadb_docs".
        await client.patch(
            "/api/mcp/admin/tools/lamadb_docs",
            json={"enabled": True},
            headers=ADMIN_HEADERS,
        )

    @pytest.mark.asyncio
    async def test_disable_tool_hides_from_tools_list(self, client, toggleable_tool):
        """PATCH enabled=false then verify the tool is gone from tools/list."""
        # Disable
        resp = await client.patch(
            f"/api/mcp/admin/tools/{toggleable_tool}",
            json={"enabled": False},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["enabled"] is False

        # tools/list should no longer mention it.
        body = await _post_mcp(client, "/mcp/admin", "tools/list", {})
        names = {t["name"] for t in body["result"]["tools"]}
        assert toggleable_tool not in names

    @pytest.mark.asyncio
    async def test_reenable_tool_restores_visibility(self, client, toggleable_tool):
        """Disabling then re-enabling a tool brings it back to tools/list."""
        # Disable
        await client.patch(
            f"/api/mcp/admin/tools/{toggleable_tool}",
            json={"enabled": False},
            headers=ADMIN_HEADERS,
        )

        body = await _post_mcp(client, "/mcp/admin", "tools/list", {})
        assert toggleable_tool not in {t["name"] for t in body["result"]["tools"]}

        # Re-enable
        resp = await client.patch(
            f"/api/mcp/admin/tools/{toggleable_tool}",
            json={"enabled": True},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True

        # Should be visible again.
        body = await _post_mcp(client, "/mcp/admin", "tools/list", {})
        names = {t["name"] for t in body["result"]["tools"]}
        assert toggleable_tool in names

    @pytest.mark.asyncio
    async def test_disable_nonexistent_tool_returns_404(self, client):
        """Toggling a tool that isn't registered yields 404."""
        resp = await client.patch(
            "/api/mcp/admin/tools/no_such_tool_xyz",
            json={"enabled": False},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 404


# ===========================================================================
# 5. Stats — /api/mcp/admin/stats tracks call counts
# ===========================================================================

@container_required
class TestStats:
    """Stats endpoint reflects per-tool call counts and durations."""

    @pytest.mark.asyncio
    async def test_stats_after_tool_calls_have_nonzero_counts(
        self, client, reset_stats,
    ):
        """Make a few tool calls, then assert the stats dict is populated."""
        # Two calls to the same tool.
        for _ in range(2):
            body = await _post_mcp(
                client,
                "/mcp/admin",
                "tools/call",
                {
                    "name": "agent_documents",
                    "arguments": {"action": "search", "q": "stats-probe", "limit": 1},
                },
            )
            assert "result" in body, body

        # One call to a different tool.
        body = await _post_mcp(
            client,
            "/mcp/admin",
            "tools/call",
            {
                "name": "agent_events",
                "arguments": {"action": "list", "limit": 1},
            },
        )
        assert "result" in body, body

        resp = await client.get("/api/mcp/admin/stats", headers=ADMIN_HEADERS)
        assert resp.status_code == 200, resp.text
        data = resp.json()

        # Shape.
        assert "stats" in data
        assert "summary" in data

        # Counters.
        assert data["stats"]["agent_documents"]["calls"] >= 2
        assert data["stats"]["agent_events"]["calls"] >= 1

        # Enrichment fields.
        agent_docs = data["stats"]["agent_documents"]
        assert "module" in agent_docs
        assert "toolset" in agent_docs
        assert "enabled" in agent_docs
        assert "avg_duration_ms" in agent_docs
        assert "errors" in agent_docs

        # Summary aggregates.
        assert data["summary"]["total_calls"] >= 3
        assert data["summary"]["tool_count"] >= 2

    @pytest.mark.asyncio
    async def test_stats_reset_clears_counters(self, client, reset_stats):
        """After reset, no tool should have a recorded call."""
        # Make one call.
        await _post_mcp(
            client,
            "/mcp/admin",
            "tools/call",
            {
                "name": "agent_documents",
                "arguments": {"action": "search", "q": "reset-probe", "limit": 1},
            },
        )

        # Reset.
        resp = await client.post(
            "/api/mcp/admin/stats/reset", headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 200

        # After reset, agent_documents has no entry in stats.
        data_resp = await client.get("/api/mcp/admin/stats", headers=ADMIN_HEADERS)
        data = data_resp.json()
        assert "agent_documents" not in data["stats"]


# ===========================================================================
# 6. Permissions — /api/mcp/admin/* requires admin role
# ===========================================================================

@container_required
class TestAdminPermissions:
    """The admin REST API is locked down to admin-role keys."""

    @pytest.mark.asyncio
    async def test_read_key_cannot_access_stats(self, client, read_key):
        """GET /api/mcp/admin/stats with a read-role key returns 403."""
        resp = await client.get(
            "/api/mcp/admin/stats",
            headers={"Authorization": f"Bearer {read_key}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_read_key_cannot_list_tools(self, client, read_key):
        """GET /api/mcp/admin/tools with a read-role key returns 403."""
        resp = await client.get(
            "/api/mcp/admin/tools",
            headers={"Authorization": f"Bearer {read_key}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_read_key_cannot_toggle_tool(self, client, read_key):
        """PATCH /api/mcp/admin/tools/{name} with a read-role key returns 403."""
        resp = await client.patch(
            "/api/mcp/admin/tools/lamadb_docs",
            json={"enabled": False},
            headers={"Authorization": f"Bearer {read_key}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_read_key_cannot_reset_stats(self, client, read_key):
        """POST /api/mcp/admin/stats/reset with a read-role key returns 403."""
        resp = await client.post(
            "/api/mcp/admin/stats/reset",
            headers={"Authorization": f"Bearer {read_key}"},
        )
        assert resp.status_code == 403
