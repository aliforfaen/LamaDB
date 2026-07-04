"""MCP tools for the Dashboard module — command-center header data.

Mirrors `GET /api/dashboard/header` (the public, no-auth dashboard
"header" readout: services LED, notifications LED, dozzle LED,
agents LED, and ticker). Reimplemented here against the same tables
so MCP callers can pull the same payload without an extra HTTP hop.
"""
from app.db import get_pool


# Severity → icon char used in ticker items. Matches the mapping in
# `app/core/dashboard.py` so dashboard MCP output stays symmetric
# with the public endpoint.
_SEV_ICON = {"critical": "✗", "warn": "⚠", "info": "✓"}

# Source name → frontend icon identifier. Kept inline so this module
# stays self-contained; if the global SOURCE_ICONS grows, import from
# `app.core.dashboard` instead.
_SOURCE_ICONS = {
    "uptime_kuma": "uptime-kuma",
    "freshrss": "freshrss",
    "rss": "freshrss",
    "agent": "hermes",
    "system": "lamadb",
    "test": "lamadb",
    "dozzle": "dozzle",
    "ntfy": "ntfy",
    "github": "github",
    "hermes": "hermes",
}


async def dashboard_header() -> dict:
    """Return the dashboard command-center header payload.

    Shape matches `GET /api/dashboard/header`:
      - `status_bar`: {hostname, services, notifications, dozzle, agents}
      - `ticker`: list of up to 20 ticker events, breaking first

    No auth required (mirrors the public header endpoint).
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        # Services: latest distinct monitor statuses
        monitor_rows = await conn.fetch(
            """
            SELECT status, count(*) AS cnt FROM (
                SELECT DISTINCT ON (monitor_id) status
                FROM monitor_status
                ORDER BY monitor_id, received_at DESC
            ) AS latest
            GROUP BY status
            """
        )
        svc_total = sum(r["cnt"] for r in monitor_rows)
        svc_up = sum(r["cnt"] for r in monitor_rows if r["status"] == 1)
        svc_down = sum(r["cnt"] for r in monitor_rows if r["status"] == 0)

        # Notifications: critical events in last 24h
        notif_count = await conn.fetchval(
            """
            SELECT count(*) FROM events
            WHERE severity = 'critical'
              AND ts > now() - interval '24 hours'
            """
        ) or 0

        # Dozzle: error/warn in last 30min
        dozzle_rows = await conn.fetch(
            """
            SELECT severity, count(*) AS cnt
            FROM events
            WHERE source = 'dozzle'
              AND severity IN ('error', 'warn')
              AND ts > now() - interval '30 minutes'
            GROUP BY severity
            """
        )
        dozzle_errors = next((r["cnt"] for r in dozzle_rows if r["severity"] == "error"), 0)
        dozzle_warnings = next((r["cnt"] for r in dozzle_rows if r["severity"] == "warn"), 0)

        # Agents: unprocessed agent events pending
        agents_pending = await conn.fetchval(
            """
            SELECT count(*) FROM events
            WHERE source = 'agent' AND processed = false
            """
        ) or 0

        # Ticker events (breaking first, then most recent)
        ticker_rows = await conn.fetch(
            """
            SELECT id, ts, source, severity, title, body, tags, metadata
            FROM events
            WHERE ticker = true
            ORDER BY
                CASE WHEN 'breaking' = ANY(tags) THEN 0 ELSE 1 END,
                ts DESC
            LIMIT 20
            """
        )

    ticker = []
    for row in ticker_rows:
        tags = list(row["tags"]) if row["tags"] else []
        is_breaking = "breaking" in tags
        source = row["source"]
        ticker.append({
            "id": row["id"],
            "ts": row["ts"].isoformat() if row["ts"] else None,
            "source": source,
            "source_icon": _SOURCE_ICONS.get(source),
            "severity": row["severity"],
            "title": row["title"],
            "body": row["body"],
            "tags": tags,
            "icon": "🔴" if is_breaking else _SEV_ICON.get(row["severity"], "✓"),
        })

    return {
        "status_bar": {
            "hostname": "LamaDB",
            "services": {
                "total": svc_total,
                "up": svc_up,
                "down": svc_down,
            },
            "notifications": {
                "count": int(notif_count),
                "has_high_priority": int(notif_count) > 0,
            },
            "dozzle": {
                "errors": int(dozzle_errors),
                "warnings": int(dozzle_warnings),
            },
            "agents": {
                "pending": int(agents_pending),
            },
        },
        "ticker": ticker,
    }
