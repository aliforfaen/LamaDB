#!/usr/bin/env python3
"""Debug script to understand ticker event creation."""
import asyncio
import asyncpg


async def debug():
    pool = await asyncpg.create_pool(
        'postgresql://lamadb:lamadb_secret@postgres:5432/lamadb',
        min_size=1, max_size=1
    )
    async with pool.acquire() as conn:
        # Clean up first
        await conn.execute("DELETE FROM monitor_status WHERE monitor_id = '999'")
        await conn.execute("DELETE FROM events WHERE metadata->>'monitor_id' = '999'")

        # Insert UP first
        await conn.execute(
            """
            INSERT INTO monitor_status (monitor_id, monitor_name, monitor_url, status, msg, duration_ms)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            '999', 'Debug Monitor', 'http://test.example.com', 1, 'OK', 100
        )

        previous = await conn.fetchval(
            "SELECT status FROM monitor_status WHERE monitor_id = $1 ORDER BY received_at DESC LIMIT 1",
            '999'
        )
        print(f"After UP insert, previous status: {previous}")

        # Insert DOWN
        await conn.execute(
            """
            INSERT INTO monitor_status (monitor_id, monitor_name, monitor_url, status, msg, duration_ms)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            '999', 'Debug Monitor', 'http://test.example.com', 0, 'DOWN', 100
        )

        # Check what the query sees as previous
        previous2 = await conn.fetchval(
            "SELECT status FROM monitor_status WHERE monitor_id = $1 ORDER BY received_at DESC LIMIT 1",
            '999'
        )
        print(f"After DOWN insert, query result (should be 0): {previous2}")

        # Check all monitor_status rows
        rows = await conn.fetch(
            "SELECT id, status, received_at FROM monitor_status WHERE monitor_id = '999' ORDER BY received_at"
        )
        print(f"All monitor_status rows: {rows}")

        # Check ticker events
        ticker = await conn.fetch(
            "SELECT id, ticker, tags, title FROM events WHERE metadata->>'monitor_id' = '999' AND ticker = true"
        )
        print(f"Ticker events found: {len(ticker)}")
        for t in ticker:
            print(f"  - {dict(t)}")

        # Check ALL events
        all_events = await conn.fetch(
            "SELECT id, ticker, type, title FROM events WHERE metadata->>'monitor_id' = '999' ORDER BY ts"
        )
        print(f"All events found: {len(all_events)}")
        for e in all_events:
            print(f"  - {dict(e)}")

        # Clean up
        await conn.execute("DELETE FROM monitor_status WHERE monitor_id = '999'")
        await conn.execute("DELETE FROM events WHERE metadata->>'monitor_id' = '999'")

    await pool.close()
    print("Done!")


if __name__ == "__main__":
    asyncio.run(debug())
