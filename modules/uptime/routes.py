"""
Uptime Kuma webhook API routes.

Endpoints:
  - POST /api/uptime/webhook  — receive Kuma webhook (no auth)
  - GET  /api/uptime/status   — current status of all monitors (auth required)
  - GET  /api/uptime/history  — recent status changes (auth required)
  - GET  /api/uptime/history/{monitor_id} — history for specific monitor (auth required)
"""
import json
import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger("uptime.webhook")

from app.auth import AuthUser, get_current_user
from app.cache import cache_manager, cached
from app.db import get_pool

from .models import (
    CurrentStatus,
    MonitorStatus,
    TopologyResponse,
    UptimeWebhookPayload,
    WebhookResponse,
)
from .topology import get_topology
from .webhook import process_webhook

router = APIRouter(tags=["uptime"])


class ConsolidatedMonitorStatus(BaseModel):
    """Monitor status with a duplicate count for the last 1h (consolidation view)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    monitor_id: str
    monitor_name: str
    monitor_url: str | None = None
    status: int
    msg: str | None = None
    duration_ms: int | None = None
    received_at: str  # ISO string from asyncpg
    count: int = 1


@router.post("/webhook-debug")
async def receive_webhook_debug(request: Request):
    """Debug endpoint that logs raw body."""
    body = await request.body()
    logger.info(f"RAW WEBHOOK BODY: {body.decode('utf-8', errors='replace')[:2000]}")
    return {"received": True, "body_length": len(body)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _monitor_status_from_row(row) -> MonitorStatus:
    """Convert an asyncpg row to a MonitorStatus model."""
    d = dict(row)
    return MonitorStatus(**d)


def _consolidated_from_row(row) -> ConsolidatedMonitorStatus:
    """Convert an asyncpg row (with `count` column) to a ConsolidatedMonitorStatus."""
    d = dict(row)
    if hasattr(d.get("received_at"), "isoformat"):
        d["received_at"] = d["received_at"].isoformat()
    return ConsolidatedMonitorStatus(**d)


# ---------------------------------------------------------------------------
# POST /api/uptime/webhook — public, no auth
# ---------------------------------------------------------------------------

@router.post(
    "/webhook",
    response_model=WebhookResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["uptime"],
)
async def receive_webhook(payload: UptimeWebhookPayload) -> WebhookResponse:
    """
    Receive a Uptime Kuma webhook payload.

    This endpoint is public (no authentication) because Uptime Kuma
    cannot send API keys with its webhook requests.

    Uptime Kuma test notifications send null heartbeat/monitor —
    we return success for those without processing.

    Returns:
        WebhookResponse with received=True on success.
    """
    # Debug logging
    logger.info(f"Webhook received: heartbeat={payload.heartbeat is not None}, monitor={payload.monitor is not None}")
    if payload.heartbeat:
        logger.info(f"  Heartbeat: status={payload.heartbeat.status}, msg={payload.heartbeat.msg[:100] if payload.heartbeat.msg else 'None'}")
    if payload.monitor:
        logger.info(f"  Monitor: id={payload.monitor.id}, name={payload.monitor.name}, tags={payload.monitor.tags}")

    # Test notifications from Uptime Kuma have null heartbeat/monitor
    if payload.heartbeat is None or payload.monitor is None:
        logger.info("  → Test notification (null heartbeat/monitor), returning success")
        return WebhookResponse(received=True)

    logger.info(f"  → Processing real heartbeat for monitor '{payload.monitor.name}'")
    await process_webhook(payload)
    cache_manager.invalidate("monitor_status")
    return WebhookResponse(received=True)


# ---------------------------------------------------------------------------
# GET /api/uptime/status — auth required
# ---------------------------------------------------------------------------

@router.get(
    "/status",
    response_model=list[CurrentStatus],
    tags=["uptime"],
)
@cached(ttl_seconds=30, invalidate_tags=["monitor_status"], key_prefix="uptime_status")
async def get_current_status(
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> list[CurrentStatus]:
    """
    Get the current (latest) status of all monitors.

    Merges monitor_registry (all monitors) with monitor_status (heartbeat data).
    Monitors without heartbeats show as PENDING (status=2).

    Returns:
        List of CurrentStatus, one per unique monitor.
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

        # Merge registry with heartbeat data
        results = []
        for reg in registry_rows:
            monitor_id = reg["monitor_id"]
            hb = heartbeat_map.get(monitor_id)

            results.append(
                CurrentStatus(
                    monitor_id=monitor_id,
                    monitor_name=reg["monitor_name"],
                    monitor_url=reg["monitor_url"],
                    status=hb["status"] if hb else 2,  # 2 = PENDING
                    msg=hb["msg"] if hb else None,
                    duration_ms=hb["duration_ms"] if hb else None,
                    received_at=hb["received_at"] if hb else None,
                )
            )

        return results


# ---------------------------------------------------------------------------
# GET /api/uptime/history — auth required
# ---------------------------------------------------------------------------

@router.get(
    "/history",
    response_model=list[MonitorStatus] | list[ConsolidatedMonitorStatus],
    tags=["uptime"],
)
async def get_history(
    user: Annotated[AuthUser, Depends(get_current_user)],
    monitor_id: str | None = Query(default=None, description="Filter by monitor ID"),
    consolidate: bool = Query(
        default=False,
        description="Group by monitor_id, return latest per monitor + count of recent entries (last 1h).",
    ),
    limit: int = Query(default=50, ge=1, le=500, description="Max results"),
    offset: int = Query(default=0, ge=0, description="Skip first N results"),
) -> list:
    """
    Get recent status changes across all monitors.

    Supports filtering by monitor_id and pagination via limit/offset.

    When `consolidate=true`, returns the most recent status row per `monitor_id`
    plus a `count` of how many status rows for that monitor exist in the last
    hour. Useful for collapsing a flapping monitor into a single row.

    Args:
        monitor_id: Optional monitor ID to filter results.
        consolidate: Group by monitor_id and return a count of recent entries.
        limit: Maximum number of results to return (default 50, max 500).
        offset: Number of results to skip (for pagination).

    Returns:
        List of MonitorStatus (or ConsolidatedMonitorStatus) entries ordered by received_at DESC.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        if consolidate:
            # Group by monitor_id, latest row per monitor, with count from last 1h
            base_where = "received_at > now() - interval '1 hour'"
            if monitor_id is not None:
                base_where += f" AND monitor_id = ${1}"
                rows = await conn.fetch(
                    f"""
                    SELECT DISTINCT ON (monitor_id)
                        id, monitor_id, monitor_name, monitor_url, status, msg, duration_ms, received_at,
                        COUNT(*) OVER (PARTITION BY monitor_id) AS count
                    FROM monitor_status
                    WHERE {base_where}
                    ORDER BY monitor_id, received_at DESC
                    """,
                    monitor_id,
                )
            else:
                rows = await conn.fetch(
                    f"""
                    SELECT DISTINCT ON (monitor_id)
                        id, monitor_id, monitor_name, monitor_url, status, msg, duration_ms, received_at,
                        COUNT(*) OVER (PARTITION BY monitor_id) AS count
                    FROM monitor_status
                    WHERE {base_where}
                    ORDER BY monitor_id, received_at DESC
                    """
                )
            return [_consolidated_from_row(row) for row in rows]

        if monitor_id is not None:
            rows = await conn.fetch(
                """
                SELECT id, monitor_id, monitor_name, monitor_url, status, msg, duration_ms, received_at
                FROM monitor_status
                WHERE monitor_id = $1
                ORDER BY received_at DESC
                LIMIT $2 OFFSET $3
                """,
                monitor_id,
                limit,
                offset,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, monitor_id, monitor_name, monitor_url, status, msg, duration_ms, received_at
                FROM monitor_status
                ORDER BY received_at DESC
                LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
            )
        return [_monitor_status_from_row(row) for row in rows]


# ---------------------------------------------------------------------------
# GET /api/uptime/history/{monitor_id} — auth required
# ---------------------------------------------------------------------------

@router.get(
    "/history/{monitor_id}",
    response_model=list[MonitorStatus] | list[ConsolidatedMonitorStatus],
    tags=["uptime"],
)
async def get_monitor_history(
    monitor_id: str,
    user: Annotated[AuthUser, Depends(get_current_user)],
    consolidate: bool = Query(
        default=False,
        description="Group by monitor_id, return latest row + count of recent entries (last 1h).",
    ),
    limit: int = Query(default=50, ge=1, le=500, description="Max results"),
    offset: int = Query(default=0, ge=0, description="Skip first N results"),
) -> list:
    """
    Get status history for a specific monitor.

    When `consolidate=true`, returns the most recent row for this monitor plus
    a `count` of how many rows for it exist in the last hour.

    Args:
        monitor_id: The Uptime Kuma monitor ID.
        consolidate: If true, return only the latest row + a count.
        limit: Maximum number of results to return.
        offset: Number of results to skip.

    Returns:
        List of MonitorStatus (or ConsolidatedMonitorStatus) entries for the specified monitor.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        if consolidate:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (monitor_id)
                    id, monitor_id, monitor_name, monitor_url, status, msg, duration_ms, received_at,
                    COUNT(*) OVER (PARTITION BY monitor_id) AS count
                FROM monitor_status
                WHERE monitor_id = $1
                  AND received_at > now() - interval '1 hour'
                ORDER BY monitor_id, received_at DESC
                """,
                monitor_id,
            )
            return [_consolidated_from_row(row) for row in rows]

        rows = await conn.fetch(
            """
            SELECT id, monitor_id, monitor_name, monitor_url, status, msg, duration_ms, received_at
            FROM monitor_status
            WHERE monitor_id = $1
            ORDER BY received_at DESC
            LIMIT $2 OFFSET $3
            """,
            monitor_id,
            limit,
            offset,
        )
        return [_monitor_status_from_row(row) for row in rows]



# ---------------------------------------------------------------------------
# GET /api/uptime/history/recent — batch recent history for all monitors
# ---------------------------------------------------------------------------

@router.get(
    "/history/recent",
    tags=["uptime"],
)
@cached(ttl_seconds=30, invalidate_tags=["monitor_status"], key_prefix="uptime_history_recent")
async def get_recent_history(
    user: Annotated[AuthUser, Depends(get_current_user)],
    limit: int = Query(default=30, ge=1, le=100, description="Max entries per monitor"),
):
    """
    Get recent status history grouped by monitor.

    Returns the last N entries for each monitor in a single query.
    This avoids N+1 fetch calls for sparkline rendering on the dashboard.

    Returns:
        {"monitors": {monitor_id: [{"received_at": "...", "status": 0}, ...], ...}}
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT monitor_id, received_at, status
            FROM monitor_status
            WHERE id IN (
                SELECT id FROM (
                    SELECT id,
                        ROW_NUMBER() OVER (PARTITION BY monitor_id ORDER BY received_at DESC) AS rn
                    FROM monitor_status
                ) sub
                WHERE rn <= $1
            )
            ORDER BY monitor_id, received_at
            """,
            limit,
        )
        monitors = {}
        for row in rows:
            mid = row["monitor_id"]
            if mid not in monitors:
                monitors[mid] = []
            monitors[mid].append({
                "received_at": row["received_at"].isoformat(),
                "status": row["status"],
            })
        return {"monitors": monitors}

# ---------------------------------------------------------------------------
# GET /api/uptime/topology — auth required
# ---------------------------------------------------------------------------

@router.get(
    "/topology",
    response_model=TopologyResponse,
    tags=["uptime"],
)
async def topology(
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> TopologyResponse:
    """
    Get the monitor topology as a tree of hosts and their services.

    Hosts are monitors tagged with "host". Services are monitors whose tags
    include the host's key (derived from the host name). Any monitor that
    does not match a host is returned as an orphan.

    Returns:
        TopologyResponse with hosts, orphans, and summary counts.
    """
    return await get_topology()
