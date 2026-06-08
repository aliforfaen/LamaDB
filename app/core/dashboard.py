"""Dashboard management API routes."""
import asyncio
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.auth import AuthUser, get_current_user, verify_api_key
from app.cache import cache_manager, cached
from app.config import settings
from app.db import get_pool
from app.sse import sse_manager

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

SOURCE_ICONS = {
    "uptime_kuma": "uptime-kuma",
    "freshrss": "freshrss",
    "rss": "freshrss",
    "agent": "hermes",
    "system": "lamadb",
    "test": "lamadb",
    "dozzle": "dozzle",
    "ntfy": "ntfy",
    "github": "github",
}


def _sev_icon(severity: str) -> str:
    """Map severity to icon character."""
    return {"critical": "✗", "warn": "⚠", "info": "✓"}.get(severity, "✓")


# ---------------------------------------------------------------------------
# GET /api/dashboard/header — PUBLIC, no auth required
# ---------------------------------------------------------------------------

@router.get("/header")
async def dashboard_header():
    """
    Return aggregated header data for the dashboard command center:
    - status_bar: services, notifications, dozzle, agents led values
    - ticker: up to 20 ticker events sorted with breaking first

    This endpoint is publicly readable (no auth required).
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        # ── Services: count from monitor_status ──
        monitor_rows = await conn.fetch("""
            SELECT status, count(*) as cnt FROM (
                SELECT DISTINCT ON (monitor_id) status
                FROM monitor_status
                ORDER BY monitor_id, received_at DESC
            ) AS latest
            GROUP BY status
        """)
        svc_total = sum(r["cnt"] for r in monitor_rows)
        svc_up = sum(r["cnt"] for r in monitor_rows if r["status"] == 1)
        svc_down = sum(r["cnt"] for r in monitor_rows if r["status"] == 0)

        # ── Notifications: critical events in last 24h ──
        notif_row = await conn.fetchrow("""
            SELECT count(*) as cnt
            FROM events
            WHERE severity = 'critical'
              AND ts > now() - interval '24 hours'
        """)
        notif_count = notif_row["cnt"] if notif_row else 0
        has_high_priority = notif_count > 0

        # ── Dozzle: error/warn from dozzle source in last 30min ──
        dozzle_rows = await conn.fetch("""
            SELECT severity, count(*) as cnt
            FROM events
            WHERE source = 'dozzle'
              AND severity IN ('error', 'warn')
              AND ts > now() - interval '30 minutes'
            GROUP BY severity
        """)
        dozzle_errors = next((r["cnt"] for r in dozzle_rows if r["severity"] == "error"), 0)
        dozzle_warnings = next((r["cnt"] for r in dozzle_rows if r["severity"] == "warn"), 0)

        # ── Agents: unprocessed agent events ──
        agents_row = await conn.fetchrow("""
            SELECT count(*) as cnt
            FROM events
            WHERE source = 'agent'
              AND processed = false
        """)
        agents_pending = agents_row["cnt"] if agents_row else 0

        # ── Ticker: ticker=true events, breaking first, limit 20 ──
        ticker_rows = await conn.fetch("""
            SELECT id, ts, source, severity, title, body, tags, metadata
            FROM events
            WHERE ticker = true
            ORDER BY
                CASE WHEN 'breaking' = ANY(tags) THEN 0 ELSE 1 END,
                ts DESC
            LIMIT 20
        """)

        ticker_items = []
        for row in ticker_rows:
            tags = list(row["tags"]) if row["tags"] else []
            is_breaking = "breaking" in tags
            icon = "🔴" if is_breaking else _sev_icon(row["severity"])
            source = row["source"]
            ticker_items.append({
                "id": row["id"],
                "ts": row["ts"].isoformat() if row["ts"] else None,
                "source": source,
                "source_icon": SOURCE_ICONS.get(source),
                "severity": row["severity"],
                "title": row["title"],
                "body": row["body"],
                "tags": tags,
                "icon": icon,
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
                "count": notif_count,
                "has_high_priority": has_high_priority,
            },
            "dozzle": {
                "errors": dozzle_errors,
                "warnings": dozzle_warnings,
            },
            "agents": {
                "pending": agents_pending,
            },
        },
        "ticker": ticker_items,
    }


async def require_admin(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    """Require admin role for dashboard access."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return user


# ---------------------------------------------------------------------------
# GET /api/dashboard/overview
# ---------------------------------------------------------------------------

@router.get("/overview")
@cached(ttl_seconds=60, invalidate_tags=["events", "documents", "monitors"], key_prefix="dashboard_overview")
async def overview(user: AuthUser = Depends(require_admin)):
    """Return aggregated stats for the overview page."""
    pool = get_pool()
    async with pool.acquire() as conn:
        # Total documents + today
        doc_total = await conn.fetchval("SELECT count(*) FROM documents")
        doc_today = await conn.fetchval(
            "SELECT count(*) FROM documents WHERE created_at > now() - interval '1 day'"
        )

        # Total feeds
        feed_total = await conn.fetchval("SELECT count(*) FROM feeds")

        # Monitor status (DISTINCT ON to get latest per monitor)
        monitor_rows = await conn.fetch("""
            SELECT status, count(*) FROM (
                SELECT DISTINCT ON (monitor_id) status
                FROM monitor_status
                ORDER BY monitor_id, received_at DESC
            ) AS latest
            GROUP BY status
        """)
        # status: 0=down, 1=up, 2=pending, 3=unknown
        monitors = {"up": 0, "down": 0, "unknown": 0}
        for row in monitor_rows:
            if row["status"] == 1:
                monitors["up"] = row["count"]
            elif row["status"] == 0:
                monitors["down"] = row["count"]
            else:
                monitors["unknown"] += row["count"]

        # Events today + delta
        event_today = await conn.fetchval(
            "SELECT count(*) FROM events WHERE ts > now() - interval '1 day'"
        )
        event_yesterday = await conn.fetchval(
            "SELECT count(*) FROM events WHERE ts > now() - interval '2 days' AND ts <= now() - interval '1 day'"
        )

        # Agent tasks summary
        task_rows = await conn.fetch(
            "SELECT status, count(*) as cnt FROM agent_tasks GROUP BY status"
        )
        task_counts = {row["status"]: row["cnt"] for row in task_rows}

    return {
        "documents": {"total": doc_total or 0, "today": doc_today or 0},
        "feeds": {"total": feed_total or 0},
        "monitors": monitors,
        "events": {
            "today": event_today or 0,
            "delta_yesterday": (event_today or 0) - (event_yesterday or 0),
        },
        "agent_tasks": task_counts,
    }


# ---------------------------------------------------------------------------
# GET /api/dashboard/modules
# ---------------------------------------------------------------------------

@router.get("/modules")
@cached(ttl_seconds=300, invalidate_tags=["modules"], key_prefix="dashboard_modules")
async def list_modules(user: AuthUser = Depends(require_admin)):
    """List all modules with metadata and runtime state."""
    modules_dir = Path(__file__).parent.parent.parent / "modules"
    modules = []

    for item in sorted(modules_dir.iterdir()):
        if not item.is_dir() or not (item / "__init__.py").exists():
            continue

        mod = __import__(
            f"modules.{item.name}",
            fromlist=["MODULE_NAME", "MODULE_DESCRIPTION", "MODULE_VERSION", "ENABLED"],
        )

        # Check for .state file override
        state_file = item / ".state"
        enabled = getattr(mod, "ENABLED", False)
        if state_file.exists():
            state = json.loads(state_file.read_text())
            enabled = state.get("enabled", enabled)

        modules.append({
            "name": getattr(mod, "MODULE_NAME", item.name),
            "description": getattr(mod, "MODULE_DESCRIPTION", ""),
            "version": getattr(mod, "MODULE_VERSION", "0.0.0"),
            "enabled": enabled,
            "directory": item.name,
        })

    return {"modules": modules}


# ---------------------------------------------------------------------------
# POST /api/dashboard/modules/{name}/toggle
# ---------------------------------------------------------------------------

@router.post("/modules/{name}/toggle")
async def toggle_module(
    name: str,
    body: dict,
    user: AuthUser = Depends(require_admin),
):
    """Toggle a module's enabled state via .state file."""
    modules_dir = Path(__file__).parent.parent.parent / "modules"
    module_dir = modules_dir / name

    if not module_dir.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Module '{name}' not found",
        )

    state_file = module_dir / ".state"
    state_file.write_text(json.dumps({"enabled": body["enabled"]}))

    cache_manager.invalidate("modules")

    return {
        "name": name,
        "enabled": body["enabled"],
        "restart_required": True,
    }


# ---------------------------------------------------------------------------
# GET /api/dashboard/health
# ---------------------------------------------------------------------------

@router.get("/health")
@cached(ttl_seconds=120, invalidate_tags=["system"], key_prefix="dashboard_health")
async def health_detail(user: AuthUser = Depends(require_admin)):
    """Return detailed system health information."""
    pool = get_pool()

    async with pool.acquire() as conn:
        # PG version
        version = await conn.fetchval("SELECT version()")

        # Extensions (exclude plpgsql which is always installed)
        ext_rows = await conn.fetch(
            "SELECT extname, extversion FROM pg_extension WHERE extname != 'plpgsql'"
        )
        extensions = {
            row["extname"]: {"installed": True, "version": row["extversion"]}
            for row in ext_rows
        }

        # Table stats
        tables = {}
        for table in [
            "documents",
            "document_links",
            "events",
            "api_keys",
            "feeds",
            "monitor_status",
        ]:
            count = await conn.fetchval(f"SELECT count(*) FROM {table}")
            size = await conn.fetchval(
                f"SELECT pg_size_pretty(pg_total_relation_size('{table}'))"
            )
            tables[table] = {"rows": count, "size": size}

    # Pool stats
    pool_stats = {
        "active": pool.get_size() - pool.get_idle_size(),
        "idle": pool.get_idle_size(),
        "max": pool.get_max_size(),
    }

    return {
        "status": "healthy",
        "database": {
            "connected": True,
            "version": version,
            "extensions": extensions,
            "tables": tables,
        },
        "pool": pool_stats,
    }


# ---------------------------------------------------------------------------
# GET /api/dashboard/api-keys
# ---------------------------------------------------------------------------

@router.get("/api-keys")
async def list_api_keys(user: AuthUser = Depends(require_admin)):
    """List all API keys (hashes never returned)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, role, scopes, active, created_at
            FROM api_keys
            ORDER BY created_at DESC
            """
        )

    keys = []
    for row in rows:
        keys.append({
            "id": str(row["id"]),
            "name": row["name"],
            "role": row["role"],
            "scopes": list(row["scopes"]) if row["scopes"] else [],
            "active": row["active"],
            "created_at": row["created_at"].isoformat(),
        })

    return {"keys": keys}


# ---------------------------------------------------------------------------
# POST /api/dashboard/api-keys
# ---------------------------------------------------------------------------

@router.post("/api-keys")
async def create_api_key(
    body: dict,
    user: AuthUser = Depends(require_admin),
):
    """Create a new API key. Returns the raw key ONCE."""
    raw_key = f"lamadb_live_{secrets.token_urlsafe(32)}"
    key_hash = bcrypt.hashpw(
        f"{settings.api_key_salt}{raw_key}".encode(),
        bcrypt.gensalt(),
    ).decode()

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO api_keys (name, key_hash, role, scopes)
            VALUES ($1, $2, $3, $4)
            RETURNING id, created_at
            """,
            body["name"],
            key_hash,
            body.get("role", "read"),
            body.get("scopes", []),
        )

    cache_manager.invalidate("modules")

    return {
        "id": str(row["id"]),
        "name": body["name"],
        "role": body.get("role", "read"),
        "scopes": body.get("scopes", []),
        "key": raw_key,
        "message": "Save this key — it will not be shown again",
        "created_at": row["created_at"].isoformat(),
    }


# ---------------------------------------------------------------------------
# DELETE /api/dashboard/api-keys/{key_id}
# ---------------------------------------------------------------------------

@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: str,
    user: AuthUser = Depends(require_admin),
):
    """Revoke an API key (set active=false)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE api_keys SET active = false WHERE id = $1",
            key_id,
        )
        if result == "UPDATE 0":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="API key not found",
            )

    cache_manager.invalidate("modules")

    return {"id": key_id, "active": False}


# ---------------------------------------------------------------------------
# POST /api/dashboard/api-keys/{key_id}/rotate
# ---------------------------------------------------------------------------

@router.post("/api-keys/{key_id}/rotate")
async def rotate_api_key(
    key_id: str,
    user: AuthUser = Depends(require_admin),
):
    """Rotate an API key — generate new key, invalidate old one."""
    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id, name, role, scopes FROM api_keys WHERE id = $1",
            key_id,
        )
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="API key not found",
            )

        raw_key = f"lamadb_live_{secrets.token_urlsafe(32)}"
        key_hash = bcrypt.hashpw(
            f"{settings.api_key_salt}{raw_key}".encode(),
            bcrypt.gensalt(),
        ).decode()

        await conn.execute(
            "UPDATE api_keys SET key_hash = $1 WHERE id = $2",
            key_hash,
            key_id,
        )

    cache_manager.invalidate("modules")

    return {
        "id": str(existing["id"]),
        "name": existing["name"],
        "role": existing["role"],
        "scopes": list(existing["scopes"]) if existing["scopes"] else [],
        "key": raw_key,
        "message": "Save this key — it will not be shown again",
    }


# ---------------------------------------------------------------------------
# POST /api/dashboard/poll-uptime — trigger Uptime Kuma poll manually
# ---------------------------------------------------------------------------

@router.post("/poll-uptime")
async def poll_uptime_kuma(
    user: AuthUser = Depends(require_admin),
):
    """Manually trigger Uptime Kuma monitor registry poll.

    Returns sync stats: added, updated, deleted, total, heartbeats.
    """
    from modules.uptime.poller import poll_kuma_registry

    try:
        stats = await poll_kuma_registry()
        return {
            "success": True,
            "stats": stats,
            "message": f"Polled {stats['total']} monitors: +{stats['added']} new, ~{stats['updated']} updated, -{stats['deleted']} removed, {stats['heartbeats']} heartbeats synced",
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Poll failed: {str(e)}",
        )


# ---------------------------------------------------------------------------
# GET /api/dashboard/stream — SSE real-time event stream
# ---------------------------------------------------------------------------

@router.get("/stream")
async def dashboard_stream(key: str = Query(..., description="API key for auth")):
    """
    Server-Sent Events stream for real-time dashboard updates.

    Auth via query parameter (EventSource cannot set custom headers).
    Pushes events when new database events are created or tasks are updated.
    Heartbeat every 15s to keep the connection alive.
    """
    # Authenticate via query param
    from app.auth import verify_api_key
    user = await verify_api_key(key)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    queue = sse_manager.subscribe()

    async def event_generator():
        try:
            yield "event: connected\ndata: {}\n\n"
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=15.0)
                    channel = data.get("channel", "unknown")
                    payload = json.dumps(data.get("data", {}))
                    yield f"event: {channel}\ndata: {payload}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            sse_manager.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# GET /api/dashboard/cache-stats — cache performance stats
# ---------------------------------------------------------------------------

@router.get("/cache-stats")
async def cache_stats(key: str = Query(..., description="API key for query-param auth")):
    """
    Return cache hit/miss/expired counts and current entries.
    Auth via query param (matches SSE pattern — used from dashboard JavaScript).
    """
    user = await verify_api_key(key)
    if user is None or user.role != "admin":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or insufficient API key")

    return cache_manager.stats()
