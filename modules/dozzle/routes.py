"""Dozzle container log routes."""
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
import httpx

from app.auth import AuthUser, get_current_user
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
# GET /api/dozzle/containers — list containers from Dozzle
# ---------------------------------------------------------------------------

@router.get("/containers")
async def list_containers(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Proxy to Dozzle API to list containers."""
    if not settings.dozzle_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dozzle not configured",
        )

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{settings.dozzle_url}/api/containers",
                timeout=10.0,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Dozzle API error: {e}",
            )


# ---------------------------------------------------------------------------
# GET /api/dozzle/logs — recent log entries filtered by level
# ---------------------------------------------------------------------------

@router.get("/logs")
async def get_logs(
    user: Annotated[AuthUser, Depends(_require_auth)],
    level: str = Query(default="error", description="Log level filter (error, warn, info, debug)"),
    limit: int = Query(default=50, ge=1, le=200),
    since: str = Query(default="30m", description="Time window (e.g., 5m, 30m, 1h, 1d)"),
):
    """Query recent log entries from Dozzle, filtered by level."""
    if not settings.dozzle_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dozzle not configured",
        )

    # Dozzle logs endpoint uses NDJSON
    log_url = f"{settings.dozzle_url}/api/logs?since={since}&level={level}"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(log_url, timeout=10.0)
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
            entries.append(LogEntry(**data))
        except (json.JSONDecodeError, TypeError):
            continue

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
