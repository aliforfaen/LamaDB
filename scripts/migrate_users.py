#!/usr/bin/env python3
"""One-time: backfill users table from existing api_keys.

For every distinct name in api_keys that has no linked user, create a
'human' user and attach all of that name's unlinked keys to it.

Idempotent: re-running after a successful run is a no-op.

Usage:
    docker exec lamadb_api python3 scripts/migrate_users.py
"""
from __future__ import annotations

import asyncio
import os

import asyncpg


async def main() -> None:
    dsn = os.environ.get(
        "DATABASE_URL",
        "postgresql://lamadb:lamadb_secret@postgres:5432/lamadb",
    )
    conn = await asyncpg.connect(dsn)

    try:
        # Create users for api_keys that don't have one (distinct by name).
        rows = await conn.fetch("""
            INSERT INTO users (name, type, status)
            SELECT DISTINCT k.name, 'human', 'active'
            FROM api_keys k
            WHERE k.user_id IS NULL
              AND NOT EXISTS (SELECT 1 FROM users u WHERE u.name = k.name)
            RETURNING id, name
        """)
        for r in rows:
            print(f"Created user: {r['name']} ({r['id']})")
            await conn.execute(
                "UPDATE api_keys SET user_id = $1 WHERE name = $2 AND user_id IS NULL",
                r["id"], r["name"],
            )

        remaining = await conn.fetchval(
            "SELECT count(*) FROM api_keys WHERE user_id IS NULL"
        )
        user_count = await conn.fetchval("SELECT count(*) FROM users")

        print(
            f"\nResults: {len(rows)} users created, "
            f"{remaining} api_keys without user, "
            f"{user_count} total users"
        )
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
