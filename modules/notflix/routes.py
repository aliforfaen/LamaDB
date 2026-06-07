"""Notflix notification routes."""
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Query
import httpx

from app.auth import AuthUser, get_current_user
from app.config import settings
from app.db import get_pool

router = APIRouter(tags=["notflix"])


def _require_auth(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    return user


# ---------------------------------------------------------------------------
# GET /api/notflix/status — latest media library snapshot
# ---------------------------------------------------------------------------

@router.get("/status")
async def get_status(user: Annotated[AuthUser, Depends(_require_auth)]):
    """Get the latest media library snapshot from the events table."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT metadata, ts FROM events
               WHERE source = 'notflix' AND type = 'media_snapshot'
               ORDER BY ts DESC LIMIT 1"""
        )
    if not row:
        return {"status": "no_data"}

    meta = row["metadata"]
    if isinstance(meta, str):
        meta = json.loads(meta)
    return {"data": meta, "ts": row["ts"].isoformat()}


# ---------------------------------------------------------------------------
# GET /api/notflix/activity — recent media activity events
# ---------------------------------------------------------------------------

@router.get("/activity")
async def get_activity(
    user: Annotated[AuthUser, Depends(_require_auth)],
    limit: int = Query(default=20, ge=1, le=100),
):
    """Get recent media activity (recent grabs, watches) from events."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT source, type, severity, title, body, metadata, ts
               FROM events
               WHERE source IN ('sonarr', 'radarr', 'tautulli', 'notflix')
               ORDER BY ts DESC LIMIT $1""",
            limit,
        )

    events = []
    for row in rows:
        meta = row["metadata"]
        if isinstance(meta, str):
            meta = json.loads(meta)
        events.append({
            "source": row["source"],
            "type": row["type"],
            "title": row["title"],
            "body": row["body"],
            "metadata": meta,
            "ts": row["ts"].isoformat(),
        })

    return {"events": events, "count": len(events)}


# ---------------------------------------------------------------------------
# GET /api/notflix/health — reachability check for all 3 services
# ---------------------------------------------------------------------------

@router.get("/health")
async def check_health(user: Annotated[AuthUser, Depends(_require_auth)]):
    """Check which media services are reachable."""
    results = {}
    async with httpx.AsyncClient(timeout=10.0) as client:
        for name, url, key in [
            ("sonarr", settings.sonarr_url, settings.sonarr_api_key),
            ("radarr", settings.radarr_url, settings.radarr_api_key),
            ("tautulli", settings.tautulli_url, settings.tautulli_api_key),
        ]:
            if not url:
                results[name] = {"reachable": False, "reason": "not configured"}
                continue
            try:
                if name == "tautulli":
                    resp = await client.get(
                        f"{url}/api/v2",
                        params={"apikey": key, "cmd": "get_activity"},
                        timeout=5.0,
                    )
                else:
                    headers = {"X-Api-Key": key} if key else {}
                    resp = await client.get(
                        f"{url}/api/v3/system/status",
                        headers=headers,
                        timeout=5.0,
                    )
                results[name] = {"reachable": resp.status_code < 500}
            except Exception as e:
                results[name] = {"reachable": False, "reason": str(e)}

    return results
