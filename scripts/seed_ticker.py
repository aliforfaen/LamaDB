#!/usr/bin/env python3
"""
Seed script: populates the events table with sample ticker events.

Run from the project root:
    python scripts/seed_ticker.py

Requires DATABASE_URL env var or .env file.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

# Ensure the project root is in the path
sys.path.insert(0, str(__file__).rsplit("/", 2)[0])

import asyncpg


TICKER_EVENTS = [
    {
        "source": "uptime",
        "type": "heartbeat",
        "severity": "info",
        "title": "All systems operational",
        "body": None,
        "ticker": True,
        "tags": ["status", "operational"],
    },
    {
        "source": "uptime",
        "type": "monitor",
        "severity": "info",
        "title": "Database responding normally — 12ms avg latency",
        "body": None,
        "ticker": True,
        "tags": ["database", "health"],
    },
    {
        "source": "uptime",
        "type": "monitor",
        "severity": "warn",
        "title": "Memory usage at 78% — approaching threshold",
        "body": None,
        "ticker": True,
        "tags": ["memory", "warning"],
    },
    {
        "source": "agent",
        "type": "task",
        "severity": "info",
        "title": "Feed sync completed — 14 documents fetched",
        "body": None,
        "ticker": True,
        "tags": ["agent", "sync"],
    },
    {
        "source": "agent",
        "type": "task",
        "severity": "info",
        "title": "Uptime check completed — all monitors up",
        "body": None,
        "ticker": True,
        "tags": ["agent", "uptime"],
    },
    {
        "source": "system",
        "type": "event",
        "severity": "critical",
        "title": "⚠ CRITICAL: Payment service degraded",
        "body": "Response time > 5s — investigating",
        "ticker": True,
        "tags": ["breaking", "payment", "critical"],
    },
    {
        "source": "uptime",
        "type": "monitor",
        "severity": "warn",
        "title": "Disk I/O elevated on primary volume",
        "body": None,
        "ticker": True,
        "tags": ["disk", "warning"],
    },
    {
        "source": "uptime",
        "type": "heartbeat",
        "severity": "info",
        "title": "API response time nominal — 45ms p95",
        "body": None,
        "ticker": True,
        "tags": ["api", "performance"],
    },
]


async def seed():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        # Try to load from .env
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    k, _, v = line.strip().partition("=")
                    if k == "DATABASE_URL":
                        db_url = v.strip()
                        break

    if not db_url:
        print("ERROR: DATABASE_URL not set. Exiting.")
        sys.exit(1)

    pool = await asyncpg.create_pool(dsn=db_url, min_size=1, max_size=2)

    async with pool.acquire() as conn:
        # First check if ticker events already exist
        existing = await conn.fetchval(
            "SELECT count(*) FROM events WHERE ticker = true"
        )
        if existing > 0:
            print(f"Ticker events already exist ({existing} rows). Skipping seed.")
            print("Run: DELETE FROM events WHERE ticker = true;  to clear first.")
            return

        for ev in TICKER_EVENTS:
            await conn.execute(
                """
                INSERT INTO events (source, type, severity, title, body, ticker, tags)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                ev["source"],
                ev["type"],
                ev["severity"],
                ev["title"],
                ev["body"],
                ev["ticker"],
                ev["tags"],
            )
            print(f"  + {ev['title']}")

    await pool.close()
    print(f"\nSeeded {len(TICKER_EVENTS)} ticker events.")


if __name__ == "__main__":
    asyncio.run(seed())
