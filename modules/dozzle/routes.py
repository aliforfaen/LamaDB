"""Dozzle container log routes."""
import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
import httpx

from app.auth import AuthUser, get_current_user
from app.cache import cached
from app.db import get_pool
from app.config import settings

from .models import ContainerInfo, LogEntry, DozzleSyncResult
from .webhook import process_webhook_payload

router = APIRouter(tags=["dozzle"])
public_router = APIRouter(tags=["dozzle-webhook"])


# ----------------------------------------------------------------------
# Public webhook endpoint (no auth) — registered at /dozzle/webhook
# ----------------------------------------------------------------------

class DozzleWebhookResponse(BaseModel):
    received: bool
    event_id: int | None = None
    ticker_created: bool = False


@public_router.post(
    "/webhook",
    response_model=DozzleWebhookResponse,
    status_code=status.HTTP_201_CREATED,
)
async def receive_webhook(payload: dict) -> DozzleWebhookResponse:
    """
    Receive a Dozzle webhook notification (no auth required).

    Dozzle calls this endpoint when container log alerts fire.
    The payload is passed through as a raw dict since Dozzle's
    webhook format may vary between versions.

    This endpoint is public because Dozzle cannot send API keys.
    """
    result = await process_webhook_payload(payload)
    return DozzleWebhookResponse(
        received=True,
        event_id=result.get("event_id"),
        ticker_created=result.get("ticker_created", False),
    )


def _require_auth(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    return user


# ---------------------------------------------------------------------------
# SSE helpers — parse Dozzle v10 event stream
# ---------------------------------------------------------------------------

async def _read_sse_event(
    client: httpx.AsyncClient,
    url: str,
    event_type: str,
) -> str | None:
    """Connect to SSE stream and return data payload of first event matching *event_type*.

    Returns None if the stream closes without a match (shouldn't happen on a live stream).
    Callers wrap with asyncio.wait_for for timeout control.

    Uses a 3s connect timeout to fail fast when Dozzle is unreachable from
    Docker (DNS resolves but port not forwarded).
    """
    async with client.stream(
        "GET",
        url,
        timeout=httpx.Timeout(connect=3.0, read=10.0, write=5.0, pool=3.0),
    ) as resp:
        resp.raise_for_status()
        current_event: str | None = None
        async for line in resp.aiter_lines():
            if line.startswith("event: "):
                current_event = line[7:].strip()
            elif line.startswith("data: ") and current_event == event_type:
                return line[6:]
            elif line == "":
                current_event = None
        return None


async def _discover_host(container_id: str) -> str | None:
    """Discover the Dozzle v10 host UUID for a container by reading the SSE stream."""
    if not settings.dozzle_url:
        return None
    url = f"{settings.dozzle_url}/api/events/stream"
    async with httpx.AsyncClient() as client:
        try:
            data_raw = await asyncio.wait_for(
                _read_sse_event(client, url, "containers-changed"),
                timeout=5.0,
            )
        except (asyncio.TimeoutError, httpx.HTTPError):
            return None
    if not data_raw:
        return None
    try:
        containers = json.loads(data_raw)
        for c in containers:
            if c.get("id", "")[:12] == container_id[:12]:
                return c.get("host")
        return None
    except (json.JSONDecodeError, TypeError):
        return None


# ---------------------------------------------------------------------------
# GET /api/dozzle/containers — list containers from Dozzle v10
# ---------------------------------------------------------------------------

@router.get("/containers")
@cached(ttl_seconds=120, invalidate_tags=["dozzle"], key_prefix="dozzle_containers")
async def list_containers(
    request: Request,
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Proxy to Dozzle v10 SSE events stream to list containers.

    Returns a bare array (matches Dozzle v10 wire format) on success, or an
    empty array on unreachable hosts — the frontend handles empty arrays
    gracefully with a "No containers found" message. Logging the error gives
    operators visibility into Dozzle outages.
    """
    if not settings.dozzle_url:
        return []

    url = f"{settings.dozzle_url}/api/events/stream"
    async with httpx.AsyncClient() as client:
        try:
            data_raw = await asyncio.wait_for(
                _read_sse_event(client, url, "containers-changed"),
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            import logging
            logging.getLogger(__name__).warning(
                "Dozzle /containers: unreachable (no containers-changed within timeout)"
            )
            return []
        except httpx.HTTPError as e:
            import logging
            logging.getLogger(__name__).warning(f"Dozzle /containers API error: {e}")
            return []

    if data_raw is None:
        return []

    try:
        containers = json.loads(data_raw)
        return containers if isinstance(containers, list) else []
    except json.JSONDecodeError as e:
        import logging
        logging.getLogger(__name__).warning(f"Dozzle /containers invalid JSON: {e}")
        return []


# ---------------------------------------------------------------------------
# GET /api/dozzle/logs — recent log entries from Dozzle v10
# ---------------------------------------------------------------------------

@router.get("/logs")
@cached(ttl_seconds=30, invalidate_tags=["dozzle"], key_prefix="dozzle_logs")
async def get_logs(
    request: Request,
    user: Annotated[AuthUser, Depends(_require_auth)],
    container_id: str = Query(..., description="Container ID"),
    host: str | None = Query(default=None, description="Dozzle host UUID (auto-discovered if omitted)"),
    level: str = Query(default="error", description="Log level filter (error, warn, info, debug)"),
    limit: int = Query(default=50, ge=1, le=200),
    since: str = Query(default="30m", description="Time window (e.g., 5m, 30m, 1h, 1d) — client-side filter"),
):
    """Query recent log entries from Dozzle v10 host-based logs endpoint."""
    if not settings.dozzle_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dozzle not configured",
        )

    # Auto-discover host from SSE if not provided
    if not host:
        host = await _discover_host(container_id)
        if not host:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Container {container_id} not found or host could not be discovered",
            )

    levels_params = "&".join(f"levels={lvl}" for lvl in ["error", "warn", "info", "debug"])
    log_url = (
        f"{settings.dozzle_url}/api/hosts/{host}/containers/{container_id}/logs"
        f"?stdout=1&stderr=1&{levels_params}"
    )

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                log_url,
                timeout=httpx.Timeout(connect=3.0, read=10.0, write=5.0, pool=3.0),
                follow_redirects=True,
            )
            resp.raise_for_status()
            raw = resp.text.strip()
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Dozzle API error: {e}",
        )

    if not raw:
        return {"logs": [], "count": 0}

    entries = []
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        # v10 log entry: {t, m: {level, message, time, ...}, l, s, c, ts, id}
        msg_obj = data.get("m", {})
        if isinstance(msg_obj, dict):
            log_level = msg_obj.get("level", data.get("l", "info"))
            message = msg_obj.get("message", str(msg_obj))
            timestamp = msg_obj.get("time", "")
        else:
            log_level = data.get("l", "info")
            message = str(msg_obj) if msg_obj else ""
            timestamp = ""

        # Narrow to the user's requested level (v10 `levels` param passes all levels)
        if level and log_level != level:
            continue

        entries.append(LogEntry(
            container_name=data.get("c", container_id),
            level=log_level,
            message=message,
            timestamp=timestamp,
        ))

    return {"logs": entries[:limit], "count": len(entries)}

# ---------------------------------------------------------------------------
# GET /api/dozzle/errors — shortcut for error/warn logs
# ---------------------------------------------------------------------------

@router.get("/errors")
async def get_errors(
    user: Annotated[AuthUser, Depends(_require_auth)],
    limit: int = Query(default=50, ge=1, le=200),
    since: str = Query(default="30m"),
):
    """Shortcut endpoint for error and warning logs."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT source, type, severity, title, body, metadata, ts
            FROM events
            WHERE source = 'dozzle'
              AND severity IN ('error', 'warn')
              AND ts > now() - interval '1 hour'
            ORDER BY ts DESC
            LIMIT $1
            """,
            limit,
        )

    errors = []
    for row in rows:
        errors.append({
            "source": row["source"],
            "severity": row["severity"],
            "title": row["title"],
            "body": row["body"],
            "metadata": json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"],
            "ts": row["ts"].isoformat() if row["ts"] else None,
        })

    return {"errors": errors, "count": len(errors)}


# ---------------------------------------------------------------------------
# POST /api/dozzle/sync — manual trigger to fetch recent error logs
# ---------------------------------------------------------------------------

@router.post("/sync", response_model=DozzleSyncResult)
async def trigger_sync(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Manually trigger a Dozzle log sync."""
    from .collector import collect

    result = await collect()
    return DozzleSyncResult(**result)
