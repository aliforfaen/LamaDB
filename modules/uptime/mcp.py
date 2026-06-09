"""MCP tools for the Uptime module."""
import json
from app.db import get_pool


async def get_uptime_status() -> dict:
    """Get the current status of all monitors.

    Returns a list of monitors with their latest heartbeat status.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        # Get all active monitors from registry
        registry_rows = await conn.fetch(
            """
            SELECT monitor_id, monitor_name, monitor_url, tags
            FROM monitor_registry
            WHERE active = true
            ORDER BY monitor_name
            """
        )

        # Get latest heartbeat for each monitor
        heartbeat_rows = await conn.fetch(
            """
            SELECT DISTINCT ON (monitor_id)
                monitor_id, status, msg, duration_ms, received_at
            FROM monitor_status
            ORDER BY monitor_id, received_at DESC
            """
        )
        heartbeat_map = {str(r["monitor_id"]): r for r in heartbeat_rows}

        monitors = []
        for reg in registry_rows:
            monitor_id = reg["monitor_id"]
            hb = heartbeat_map.get(monitor_id)

            monitors.append({
                "monitor_id": monitor_id,
                "monitor_name": reg["monitor_name"],
                "monitor_url": reg["monitor_url"],
                "status": hb["status"] if hb else 2,  # 2 = PENDING
                "msg": hb["msg"] if hb else None,
                "duration_ms": hb["duration_ms"] if hb else None,
                "received_at": hb["received_at"].isoformat() if hb and hb["received_at"] else None,
            })

    up = sum(1 for m in monitors if m["status"] == 1)
    down = sum(1 for m in monitors if m["status"] == 0)
    pending = sum(1 for m in monitors if m["status"] == 2)

    return {
        "monitors": monitors,
        "summary": {"total": len(monitors), "up": up, "down": down, "pending": pending},
    }


async def get_uptime_history(monitor_id: str = None, limit: int = 50) -> dict:
    """Get recent status history across all monitors or for a specific monitor."""
    pool = get_pool()
    async with pool.acquire() as conn:
        if monitor_id is not None:
            rows = await conn.fetch(
                """
                SELECT id, monitor_id, monitor_name, monitor_url, status, msg, duration_ms, received_at
                FROM monitor_status
                WHERE monitor_id = $1
                ORDER BY received_at DESC
                LIMIT $2
                """,
                monitor_id,
                limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, monitor_id, monitor_name, monitor_url, status, msg, duration_ms, received_at
                FROM monitor_status
                ORDER BY received_at DESC
                LIMIT $1
                """,
                limit,
            )

    entries = []
    for row in rows:
        entries.append({
            "id": row["id"],
            "monitor_id": row["monitor_id"],
            "monitor_name": row["monitor_name"],
            "status": row["status"],
            "msg": row["msg"],
            "duration_ms": row["duration_ms"],
            "received_at": row["received_at"].isoformat() if row["received_at"] else None,
        })

    return {"entries": entries, "count": len(entries)}
