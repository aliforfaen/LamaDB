"""
Tests for MCP tool toggle persistence (LAMA-17).

The `mcp_tool_config` table stores per-tool enable/disable state so the
registry survives container restarts. The PATCH endpoint upserts the row,
and `load_persisted_state()` (called from app/main.py lifespan) hydrates
the in-memory `_tools` dict from the table on startup.

Run:
    docker exec lamadb_api python3 -m pytest tests/test_mcp_tool_config.py -q
"""
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio

from app.config import settings
from tests.conftest import container_required


BASE_URL = "http://localhost:8000"
ADMIN_HEADERS = {
    "Authorization": "Bearer lamadb_test_key_2026",
    "Content-Type": "application/json",
}


@container_required
class TestMcpToolConfigPersistence:
    """PATCH writes to `mcp_tool_config`; load_persisted_state reads it back."""

    @pytest_asyncio.fixture(scope="function")
    async def client(self):
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as ac:
            yield ac

    @pytest_asyncio.fixture(scope="function")
    async def db_pool(self):
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

    @pytest_asyncio.fixture
    async def restore_tool(self, client):
        """Re-enable the tool we toggle, regardless of test outcome."""
        yield
        await client.patch(
            "/api/mcp/admin/tools/lamadb_docs",
            json={"enabled": True},
            headers=ADMIN_HEADERS,
        )

    @pytest.mark.asyncio
    async def test_patch_writes_row_to_mcp_tool_config(
        self, client, db_pool, restore_tool,
    ):
        """Disabling a tool creates / updates a row with enabled=false."""
        resp = await client.patch(
            "/api/mcp/admin/tools/lamadb_docs",
            json={"enabled": False},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 200, resp.text

        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT enabled FROM mcp_tool_config WHERE name = $1",
                "lamadb_docs",
            )
        assert row is not None, "expected a row in mcp_tool_config"
        assert row["enabled"] is False

    @pytest.mark.asyncio
    async def test_patch_updates_existing_row(
        self, client, db_pool, restore_tool,
    ):
        """Toggling twice updates the same row (UPSERT, not duplicate insert)."""
        # First toggle off, then on.
        await client.patch(
            "/api/mcp/admin/tools/lamadb_docs",
            json={"enabled": False},
            headers=ADMIN_HEADERS,
        )
        await client.patch(
            "/api/mcp/admin/tools/lamadb_docs",
            json={"enabled": True},
            headers=ADMIN_HEADERS,
        )

        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT enabled, updated_at FROM mcp_tool_config WHERE name = $1",
                "lamadb_docs",
            )
        assert len(rows) == 1, f"expected exactly one row, got {len(rows)}"
        assert rows[0]["enabled"] is True

    @pytest.mark.asyncio
    async def test_load_persisted_state_restores_disabled(
        self, client, db_pool, restore_tool,
    ):
        """load_persisted_state() re-applies the DB row to the in-memory registry.

        We exercise the function directly (importing the registry module from
        the test process). Because the registry dict is per-process, we
        instantiate a fresh in-memory state by:
          1. Disable via the API (persists).
          2. Read the row back, sanity-check enabled=false.
          3. Call load_persisted_state() and verify it doesn't crash / returns
             >= 1 for our tool.
        """
        await client.patch(
            "/api/mcp/admin/tools/lamadb_docs",
            json={"enabled": False},
            headers=ADMIN_HEADERS,
        )

        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT enabled FROM mcp_tool_config WHERE name = $1",
                "lamadb_docs",
            )
            assert row is not None and row["enabled"] is False

            # Now load_persisted_state should set _tools["lamadb_docs"]["enabled"]
            # to False in the test process's import of the registry.
            from app.mcp_registry import load_persisted_state, _tools
            # Make sure the registry contains the tool — main.py wires up
            # consolidated + legacy tools at import time.
            assert "lamadb_docs" in _tools, (
                "test process must import a registry that includes lamadb_docs; "
                "if this fails, ensure tests run inside the lamadb_api container "
                "via `docker exec lamadb_api python3 -m pytest ...`"
            )
            restored = await load_persisted_state(conn)
            assert restored >= 1
            assert _tools["lamadb_docs"]["enabled"] is False

    @pytest.mark.asyncio
    async def test_disable_nonexistent_tool_does_not_write_row(
        self, client, db_pool,
    ):
        """PATCH on an unknown tool returns 404 and writes nothing."""
        ghost = f"definitely_not_a_tool_{uuid4().hex[:8]}"
        resp = await client.patch(
            f"/api/mcp/admin/tools/{ghost}",
            json={"enabled": False},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 404

        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM mcp_tool_config WHERE name = $1",
                ghost,
            )
        assert row is None, "404 toggles must not leave a row behind"