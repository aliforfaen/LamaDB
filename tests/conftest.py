"""Shared test fixtures for LamaDB tests.

Sets LAMADB_SKIP_POLLERS=1 so the lifespan skips background
poller tasks during test runs. Also seeds a test API key so
auth-required tests have a key to verify against.

Each test file defines its own client, db_pool, and auth fixtures.
"""
import os
import pytest_asyncio

os.environ["LAMADB_SKIP_POLLERS"] = "1"


@pytest_asyncio.fixture(scope="function", autouse=True)
async def seed_test_api_key():
    """Ensure the test API key exists so auth-required tests pass."""
    from app.config import settings
    import asyncpg

    conn = await asyncpg.connect(settings.database_url)
    try:
        await conn.execute(
            """
            INSERT INTO api_keys (name, key_hash, role, scopes, active)
            VALUES ($1, $2, $3, $4, true)
            ON CONFLICT (key_hash) DO NOTHING
            """,
            "test-agent",
            "$2b$12$oEdTQNnKaKXLHg9EkfoYkeOrQnQHYsbC06jjudpYZfmbnLfk90k8i",
            "admin",
            ["feeds", "uptime", "documents", "dashboard", "wiki", "agent_board", "ntfy", "dozzle", "freshrss", "notflix"],
        )
    finally:
        await conn.close()
