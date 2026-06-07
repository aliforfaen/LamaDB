"""ntfy notification routes."""
import json
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, status
import httpx
from app.auth import AuthUser, get_current_user
from app.config import settings
from app.db import get_pool
from .models import NtfyMessage, NtfyHealth

router = APIRouter(tags=["ntfy"])


def _require_auth(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    return user


def _priority_to_severity(priority: int) -> str:
    """Map ntfy priority (1-5) to severity string."""
    if priority >= 5:
        return "critical"
    elif priority >= 4:
        return "warn"
    else:
        return "info"


# ---------------------------------------------------------------------------
# GET /api/ntfy/health — check ntfy server reachability
# ---------------------------------------------------------------------------

@router.get("/health", response_model=NtfyHealth)
async def check_health(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Check if the ntfy server is reachable and return topic info."""
    if not settings.ntfy_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ntfy not configured",
        )

    topic = settings.ntfy_topic
    poll_url = f"{settings.ntfy_url}/{topic}/json?poll=1&since=1h"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(poll_url, timeout=10.0)
            resp.raise_for_status()
            messages = resp.text.strip().split("\n") if resp.text.strip() else []
            message_count = len([m for m in messages if m.strip()])
    except httpx.HTTPError:
        return NtfyHealth(reachable=False, topic=topic, message_count=0)

    return NtfyHealth(reachable=True, topic=topic, message_count=message_count)


# ---------------------------------------------------------------------------
# GET /api/ntfy/messages — fetch recent messages from ntfy topic
# ---------------------------------------------------------------------------

@router.get("/messages")
async def get_messages(
    user: Annotated[AuthUser, Depends(_require_auth)],
    since: str = Query(default="1h", description="Time window for polling (e.g., 1h, 30m, 1d)"),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Fetch recent messages from the ntfy topic."""
    if not settings.ntfy_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ntfy not configured",
        )

    topic = settings.ntfy_topic
    poll_url = f"{settings.ntfy_url}/{topic}/json?poll=1&since={since}"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(poll_url, timeout=10.0)
            resp.raise_for_status()
            raw = resp.text.strip()
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ntfy API error: {e}",
        )

    if not raw:
        return {"messages": [], "count": 0}

    messages = []
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            messages.append(NtfyMessage(**data))
        except json.JSONDecodeError:
            continue

    return {"messages": messages[:limit], "count": len(messages)}


# ---------------------------------------------------------------------------
# POST /api/ntfy/sync — poll ntfy and create events
# ---------------------------------------------------------------------------

@router.post("/sync")
async def trigger_sync(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Poll ntfy for recent messages and create events."""
    from .collector import collect

    result = await collect()
    return result
# ---------------------------------------------------------------------------
# GET /api/ntfy/events — read cached ntfy events from the events table
# ---------------------------------------------------------------------------
@router.get("/events")
async def get_ntfy_events(
    user: Annotated[AuthUser, Depends(_require_auth)],
    priority: str = Query(default="all", description="Filter: all|high|critical"),
    since: str = Query(default="24h", description="Time window: 1h|6h|24h"),
):
    """Return ntfy events from the events table with optional filters.
    Falls back to a hardcoded interval mapping so we never pass user input
    to PostgreSQL as an interval string.
    """
    INTERVAL_MAP = {
        "1h": "1 hour",
        "6h": "6 hours",
        "24h": "24 hours",
    }
    interval = INTERVAL_MAP.get(since, "24 hours")
    severity_map: dict[str, list[str]] = {
        "all": ["critical", "warn", "info"],
        "high": ["critical", "warn"],
        "critical": ["critical"],
    }
    severities = severity_map.get(priority, ["critical", "warn", "info"])
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT id, ts, type, severity, title, body, metadata, tags
            FROM events
            WHERE source = 'ntfy'
              AND ts >= now() - interval '{interval}'
              AND severity = ANY($1)
            ORDER BY ts DESC
            LIMIT 100
            """,
            severities,
        )
        messages = []
        for row in rows:
            meta = dict(row)
            # Coerce metadata (JSONB may come back as string or dict)
            raw_meta = meta.get("metadata", {})
            if isinstance(raw_meta, str):
                try:
                    raw_meta = json.loads(raw_meta)
                except Exception:
                    raw_meta = {}
            messages.append(
                NtfyMessage(
                    id=str(meta["id"]),
                    time=int(meta["ts"].timestamp()) if meta.get("ts") else 0,
                    title=meta.get("title") or "ntfy event",
                    message=meta.get("body") or "",
                    priority=raw_meta.get("priority", 3),
                    tags=meta.get("tags", []),
                )
            )
        return {"messages": messages, "count": len(messages)}
