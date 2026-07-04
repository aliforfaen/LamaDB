"""Dashboard management API routes."""
import asyncio
import importlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.auth import AuthUser, get_current_user, verify_api_key, _hash_prefix
from app.cache import cache_manager, cached
from app.config import settings
from app.db import get_pool
from app.sse import sse_manager

router = APIRouter(tags=["dashboard"])

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
            # Offload file I/O to thread; this runs in a loop over all modules
            raw = await asyncio.to_thread(state_file.read_text)
            state = json.loads(raw)
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
# GET /api/dashboard/maintenance/status
# ---------------------------------------------------------------------------

@router.get("/maintenance/status")
async def maintenance_status(
    user: AuthUser = Depends(require_admin),
):
    """Get the last maintenance run info."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT ts, body, metadata
               FROM events
               WHERE source = 'lamadb' AND type = 'maintenance'
               ORDER BY ts DESC LIMIT 1"""
        )

    if not row:
        return {"last_run": None, "message": "No maintenance runs yet"}

    meta = row["metadata"]
    if isinstance(meta, str):
        import json
        meta = json.loads(meta)

    return {
        "last_run": row["ts"].isoformat() if row["ts"] else None,
        "message": row["body"],
        "stats": meta,
    }


# ---------------------------------------------------------------------------
# POST /api/dashboard/maintenance/run
# ---------------------------------------------------------------------------

@router.post("/maintenance/run")
async def trigger_maintenance(
    user: AuthUser = Depends(require_admin),
):
    """Manually trigger a maintenance run."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("SELECT run_maintenance()")

    return {"status": "ok", "message": "Maintenance run completed"}


# ---------------------------------------------------------------------------
# GET /api/dashboard/module-health
# ---------------------------------------------------------------------------

@router.get("/module-health")
@cached(ttl_seconds=60, invalidate_tags=["events", "documents", "modules"], key_prefix="dashboard_module_health")
async def module_health(user: AuthUser = Depends(require_admin)):
    """Return health status for each module: freshness, doc/event counts, recent errors.

    Status logic (driven by error state, not just staleness):
      - disabled                              -> grey
      - has error in last 1h                  -> red     (something is broken right now)
      - last activity in last 12h             -> green   (collector alive, no recent errors)
      - last activity 12-48h ago              -> yellow  (slow or quiet but reachable)
      - last activity > 48h OR no activity    -> red     (stale)
      - never emitted, no errors              -> yellow  (just hasn't run, or only emits on input)

    Passive modules (ntfy, freshrss, wiki) only emit events on external input, so a
    quiet period is normal — not a sign of breakage. The old 1h/2h freshness threshold
    incorrectly flagged these as red.

    Optimized: 2 batched queries (stats rollup + per-source error counts) regardless
    of module count.
    """
    modules_dir = Path(__file__).parent.parent.parent / "modules"
    pool = get_pool()
    result = []

    # Collect module names first (still iterates the directory, but no per-module SQL)
    module_names: list[str] = []
    enabled_map: dict[str, bool] = {}
    for item in sorted(modules_dir.iterdir()):
        if not item.is_dir() or not (item / "__init__.py").exists():
            continue
        try:
            mod = importlib.import_module(f"modules.{item.name}")
            enabled_map[item.name] = getattr(mod, "ENABLED", False)
        except Exception:
            enabled_map[item.name] = False
        module_names.append(item.name)

    async with pool.acquire() as conn:
        # ── Batched stats: counts + latest event timestamp in one roundtrip ──
        stats_rows = await conn.fetch(
            """
            SELECT
                s.source,
                COALESCE(d.doc_count, 0) AS doc_count,
                COALESCE(e.event_count, 0) AS event_count,
                e.latest_ts AS latest_event
            FROM unnest($1::text[]) AS s(source)
            LEFT JOIN (
                SELECT source_type, count(*) AS doc_count
                FROM documents
                WHERE source_type = ANY($1)
                GROUP BY source_type
            ) d ON d.source_type = s.source
            LEFT JOIN (
                SELECT source, count(*) AS event_count, max(ts) AS latest_ts
                FROM events
                WHERE source = ANY($1)
                GROUP BY source
            ) e ON e.source = s.source
            """,
            module_names,
        )
        stats_by_source = {r["source"]: r for r in stats_rows}

        # ── Batched latest error per module (one error per source, not five) ──
        error_rows = await conn.fetch(
            """
            SELECT DISTINCT ON (source) source, id, ts, title, body
            FROM events
            WHERE source = ANY($1) AND severity = 'error'
            ORDER BY source, ts DESC
            """,
            module_names,
        )
        errors_by_source: dict[str, list[dict]] = {name: [] for name in module_names}
        for r in error_rows:
            errors_by_source[r["source"]].append({
                "id": r["id"],
                "ts": r["ts"].isoformat(),
                "title": r["title"],
                "body": (r["body"] or "")[:200],
            })

        # ── Batched latest error timestamp per source (for status derivation) ──
        latest_error_rows = await conn.fetch(
            """
            SELECT source, max(ts) AS latest_error_ts
            FROM events
            WHERE source = ANY($1) AND severity = 'error'
            GROUP BY source
            """,
            module_names,
        )
        latest_error_by_source: dict[str, object] = {r["source"]: r["latest_error_ts"] for r in latest_error_rows}

    # Thresholds (seconds)
    RECENT_ERROR_WINDOW = 3600        # 1h — anything newer = red
    GREEN_FRESHNESS = 12 * 3600       # 12h — recent enough for green
    YELLOW_FRESHNESS = 48 * 3600      # 48h — older = red (stale)

    # Assemble response from the batched lookups
    now = datetime.now(timezone.utc)
    for name in module_names:
        stats = stats_by_source.get(name)
        doc_count = stats["doc_count"] if stats else 0
        event_count = stats["event_count"] if stats else 0
        latest_event_ts = stats["latest_event"] if stats else None
        latest_error_ts = latest_error_by_source.get(name)

        enabled = enabled_map.get(name, False)
        status_color = "grey"  # disabled
        if enabled:
            recent_error_age = None
            if latest_error_ts is not None:
                recent_error_age = (now - latest_error_ts).total_seconds()

            # Recent error in the last hour -> red regardless of freshness
            if recent_error_age is not None and recent_error_age < RECENT_ERROR_WINDOW:
                status_color = "red"
            elif latest_event_ts is not None:
                age = (now - latest_event_ts).total_seconds()
                if age < GREEN_FRESHNESS:
                    status_color = "green"
                elif age < YELLOW_FRESHNESS:
                    status_color = "yellow"
                else:
                    status_color = "red"
            else:
                # Enabled but never emitted an event — could be passive (waits for input)
                # or could be misconfigured. Yellow is the safe neutral state.
                status_color = "yellow"

        result.append({
            "name": name,
            "enabled": enabled,
            "status": status_color,
            "documents": doc_count,
            "events": event_count,
            "last_event": latest_event_ts.isoformat() if latest_event_ts else None,
            "recent_errors": errors_by_source.get(name, []),
        })

    return {"modules": result}


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
            SELECT id, name, role, scopes, active, created_at, last_used_at
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
            "last_used_at": row["last_used_at"].isoformat() if row["last_used_at"] else None,
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
    key_prefix = _hash_prefix(raw_key)

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO api_keys (name, key_hash, key_prefix, role, scopes)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, created_at
            """,
            body["name"],
            key_hash,
            key_prefix,
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
        key_prefix = _hash_prefix(raw_key)

        await conn.execute(
            "UPDATE api_keys SET key_hash = $1, key_prefix = $2 WHERE id = $3",
            key_hash,
            key_prefix,
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


def _get_valid_scopes() -> set[str]:
    """Return the set of valid scope names from the module registry."""
    valid = {"documents", "events", "search", "dashboard"}
    modules_dir = Path(__file__).parent.parent.parent / "modules"
    if modules_dir.exists():
        for item in sorted(modules_dir.iterdir()):
            if item.is_dir() and (item / "__init__.py").exists():
                valid.add(item.name)
    return valid


# ---------------------------------------------------------------------------
# PATCH /api/dashboard/api-keys/{key_id}
# ---------------------------------------------------------------------------

@router.patch("/api-keys/{key_id}")
async def update_api_key(
    key_id: str,
    body: dict,
    user: AuthUser = Depends(require_admin),
):
    """Update an API key's name, role, scopes, or active status."""
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

        if "scopes" in body:
            scopes = body["scopes"]
            valid_scopes = _get_valid_scopes()
            invalid = [s for s in scopes if s not in valid_scopes]
            if invalid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid scopes: {', '.join(invalid)}. Valid: {', '.join(sorted(valid_scopes))}",
                )

        updates = []
        params = []
        idx = 1
        for field in ("name", "role", "scopes", "active"):
            if field in body:
                updates.append(f"{field} = ${idx}")
                params.append(body[field])
                idx += 1
        if not updates:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields to update",
            )
        params.append(key_id)
        set_clause = ", ".join(updates)

        row = await conn.fetchrow(
            f"""
            UPDATE api_keys SET {set_clause}
            WHERE id = ${idx}
            RETURNING id, name, role, scopes, active, created_at, last_used_at
            """,
            *params,
        )
        return {
            "id": str(row["id"]),
            "name": row["name"],
            "role": row["role"],
            "scopes": list(row["scopes"]) if row["scopes"] else [],
            "active": row["active"],
            "created_at": row["created_at"].isoformat(),
            "last_used_at": row["last_used_at"].isoformat() if row["last_used_at"] else None,
        }


# ---------------------------------------------------------------------------
# GET /api/dashboard/api-keys/stats
# ---------------------------------------------------------------------------

@router.get("/api-keys/stats")
async def api_key_stats(user: AuthUser = Depends(require_admin)):
    """Return API key statistics: active, inactive, stale counts."""
    pool = get_pool()
    async with pool.acquire() as conn:
        active = await conn.fetchval(
            "SELECT count(*) FROM api_keys WHERE active = true"
        )
        inactive = await conn.fetchval(
            "SELECT count(*) FROM api_keys WHERE active = false"
        )
        stale = await conn.fetchval(
            "SELECT count(*) FROM api_keys WHERE active = true "
            "AND (last_used_at IS NULL OR last_used_at < now() - interval '30 days')"
        )
    return {"active": active or 0, "inactive": inactive or 0, "stale": stale or 0}


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
# POST /api/dashboard/poll/{module_name} — generic force-poll
# ---------------------------------------------------------------------------

FORCE_POLL_REGISTRY: dict[str, tuple[str, str]] = {
    "freshrss": ("modules.freshrss.collector", "collect"),
    "hermes":   ("modules.hermes.collector",   "collect"),
    "ntfy":     ("modules.ntfy.collector",     "collect"),
    "dozzle":   ("modules.dozzle.collector",   "collect"),
    "notflix":  ("modules.notflix.collector",  "collect"),
    "youtube":  ("modules.youtube.collector",  "collect"),
    "uptime":   ("modules.uptime.poller",      "poll_kuma_registry"),
}


@router.post("/poll/{module_name}")
async def force_poll_module(
    module_name: str,
    user: AuthUser = Depends(require_admin),
):
    """Manually trigger a module's data collector immediately.

    Supports: freshrss, hermes, ntfy, dozzle, notflix, youtube, uptime.
    Returns collector stats or 404 if the module has no poller.
    """
    entry = FORCE_POLL_REGISTRY.get(module_name)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No force-poll available for module '{module_name}'. Supported: {', '.join(sorted(FORCE_POLL_REGISTRY.keys()))}",
        )

    mod_path, fn_name = entry
    try:
        mod = importlib.import_module(mod_path)
        fn = getattr(mod, fn_name)
        stats = await fn()
        # Collectors may return non-dicts; wrap raw values to avoid serialization errors
        return {
            "success": True,
            "module": module_name,
            "stats": stats if isinstance(stats, dict) else {"raw": str(stats)},
            "message": f"Polled {module_name} successfully",
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Poll failed for {module_name}: {str(e)}",
        )


# ---------------------------------------------------------------------------
# GET /api/dashboard/module-settings
# ---------------------------------------------------------------------------

@router.get("/module-settings")
async def get_module_settings(user: AuthUser = Depends(require_admin)):
    """Return all modules with their config schemas and resolved values."""
    from app.config import discover_module_configs
    return {"modules": await discover_module_configs()}


# ---------------------------------------------------------------------------
# PUT /api/dashboard/module-settings/{module_name}
# ---------------------------------------------------------------------------

@router.put("/module-settings/{module_name}")
async def update_module_settings(
    module_name: str,
    body: dict,
    user: AuthUser = Depends(require_admin),
):
    """Update settings for a module. Writes to settings.json overlay."""
    from app.config import save_settings, discover_module_configs

    available = await discover_module_configs()
    if module_name not in available:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Module '{module_name}' not found or has no config schema")

    try:
        restart_needed = await save_settings(module_name, body)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    from app.cache import cache_manager
    cache_manager.invalidate("modules")

    return {
        "module": module_name,
        "saved": True,
        "restart_required": restart_needed,
        "message": "Settings saved." + (" Restart required for changes to take effect." if restart_needed else ""),
    }


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


# ---------------------------------------------------------------------------
# GET /api/dashboard/user-layout — saved module card order
# ---------------------------------------------------------------------------

DEFAULT_MODULE_ORDER = ["uptime", "hermes", "freshrss", "ntfy", "dozzle",
                        "notflix", "youtube", "wiki", "feeds", "notifications"]


@router.get("/user-layout")
async def get_user_layout(
    page: str = Query("overview"),
    user: AuthUser = Depends(get_current_user),
):
    """
    Return saved module card order for the overview page.
    Returns default order if no layout saved.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT layout FROM user_layouts WHERE user_id = $1 AND page = $2",
            user.name, page,
        )
        if row:
            layout = json.loads(row["layout"]) if isinstance(row["layout"], str) else row["layout"]
            return {"user_id": user.name, "page": page, "layout": layout}

        default = {"module_order": DEFAULT_MODULE_ORDER}
        return {"user_id": user.name, "page": page, "layout": default}


@router.put("/user-layout")
async def save_user_layout(
    body: dict,
    page: str = Query("overview"),
    user: AuthUser = Depends(get_current_user),
):
    """
    Save module card order for the overview page.
    The frontend sends module names in desired order.

    Body: {"module_order": ["uptime", "freshrss", "hermes", ...]}
    """
    module_order = body.get("module_order", [])
    if not isinstance(module_order, list):
        raise HTTPException(status_code=400, detail="'module_order' must be a list")

    layout = json.dumps({"module_order": module_order})
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_layouts (user_id, page, layout, updated_at)
            VALUES ($1, $2, $3, now())
            ON CONFLICT (user_id, page) DO UPDATE SET
                layout = EXCLUDED.layout,
                updated_at = now()
            """,
            user.name, page, layout,
        )

    return {"user_id": user.name, "page": page, "layout": {"module_order": module_order}}



# ---------------------------------------------------------------------------
# GET /api/dashboard/migrations — migration history
# ---------------------------------------------------------------------------

@router.get("/migrations")
async def list_migrations(user: AuthUser = Depends(require_admin)):
    """Return full migration history."""
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT filename, applied_at, checksum, execution_ms FROM migration_history ORDER BY applied_at DESC"
    )
    return {"migrations": [dict(r) for r in rows]}


# ---------------------------------------------------------------------------
# GET /api/dashboard/migrations/status — applied vs pending
# ---------------------------------------------------------------------------


@router.get("/migrations/status")
async def migration_status(user: AuthUser = Depends(require_admin)):
    """Return applied count and list of pending migration files."""
    MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"
    all_files = sorted(f.name for f in MIGRATIONS_DIR.glob("*.sql"))
    pool = get_pool()
    rows = await pool.fetch("SELECT filename FROM migration_history")
    applied = {row["filename"] for row in rows}
    return {
        "total": len(all_files),
        "applied": len(applied),
        "pending": [f for f in all_files if f not in applied],
        "files": all_files
    }
