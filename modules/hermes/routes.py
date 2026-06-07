"""Hermes Agent routes — read-only analytics and health."""
import json
import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Query

from app.auth import AuthUser, get_current_user
from app.config import settings
from app.db import get_pool

from .models import HermesHealth
from .collector import _get_headers, _ensure_session_token

logger = logging.getLogger(__name__)
router = APIRouter(tags=["hermes"])


def _require_auth(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    return user


async def _hermes_get(path: str) -> dict | list | None:
    """GET from Hermes API, return None on error."""
    url = f"{settings.hermes_url.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient() as client:
            await _ensure_session_token(client)
            resp = await client.get(url, headers=_get_headers(), timeout=10)
            if resp.status_code == 200:
                return resp.json()
            return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# GET /api/hermes/health — check Hermes reachability
# ---------------------------------------------------------------------------

@router.get("/health", response_model=HermesHealth)
async def check_health(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Check if Hermes is reachable and return basic status."""
    if not settings.hermes_url:
        return HermesHealth(reachable=False, url="", error="HERMES_URL not configured")

    status = await _hermes_get("/api/status")
    if status:
        return HermesHealth(
            reachable=True,
            url=settings.hermes_url,
            version=status.get("version"),
            gateway_running=status.get("gateway_running"),
        )
    return HermesHealth(reachable=False, url=settings.hermes_url, error="Connection failed")


# ---------------------------------------------------------------------------
# GET /api/hermes/status — full Hermes status
# ---------------------------------------------------------------------------

@router.get("/status")
async def get_status(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Return full Hermes status (version, gateway, platforms)."""
    status = await _hermes_get("/api/status")
    if not status:
        return {"error": "Hermes unreachable"}
    return status


# ---------------------------------------------------------------------------
# GET /api/hermes/sessions/stats — aggregate session statistics
# ---------------------------------------------------------------------------

@router.get("/sessions/stats")
async def get_session_stats(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Return aggregate session + message counts from Hermes."""
    stats = await _hermes_get("/api/sessions/stats")
    if not stats:
        return {"error": "Hermes unreachable"}
    return stats


# ---------------------------------------------------------------------------
# GET /api/hermes/sessions — recent sessions with token usage
# ---------------------------------------------------------------------------

@router.get("/sessions")
async def get_sessions(
    user: Annotated[AuthUser, Depends(_require_auth)],
    limit: int = Query(default=20, ge=1, le=100),
):
    """Return recent Hermes sessions with token and cost data."""
    data = await _hermes_get(f"/api/sessions?limit={limit}")
    if not data:
        return {"error": "Hermes unreachable"}
    return data


# ---------------------------------------------------------------------------
# GET /api/hermes/system — host system stats
# ---------------------------------------------------------------------------

@router.get("/system")
async def get_system_stats(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Return Hermes host system metrics (CPU, memory, disk)."""
    stats = await _hermes_get("/api/system/stats")
    if not stats:
        return {"error": "Hermes unreachable"}
    return stats


# ---------------------------------------------------------------------------
# GET /api/hermes/model — current model info
# ---------------------------------------------------------------------------

@router.get("/model")
async def get_model_info(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Return current model configuration and capabilities."""
    info = await _hermes_get("/api/model/info")
    if not info:
        return {"error": "Hermes unreachable"}
    return info


# ---------------------------------------------------------------------------
# GET /api/hermes/models — available models and providers
# ---------------------------------------------------------------------------

@router.get("/models")
async def get_model_options(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Return all available providers and their models."""
    opts = await _hermes_get("/api/model/options")
    if not opts:
        return {"error": "Hermes unreachable"}
    return opts


# ---------------------------------------------------------------------------
# GET /api/hermes/credentials — credential pool health
# ---------------------------------------------------------------------------

@router.get("/credentials")
async def get_credentials(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Return API key pool status per provider."""
    pool = await _hermes_get("/api/credentials/pool")
    if not pool:
        return {"error": "Hermes unreachable"}
    return pool


# ---------------------------------------------------------------------------
# GET /api/hermes/profiles — agent profiles
# ---------------------------------------------------------------------------

@router.get("/profiles")
async def get_profiles(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Return Hermes agent profiles with skill counts."""
    profiles = await _hermes_get("/api/profiles")
    if not profiles:
        return {"error": "Hermes unreachable"}
    return profiles


# ---------------------------------------------------------------------------
# GET /api/hermes/tools — available toolsets
# ---------------------------------------------------------------------------

@router.get("/tools")
async def get_tools(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Return available toolsets with enabled/configured state."""
    tools = await _hermes_get("/api/tools/toolsets")
    if not tools:
        return {"error": "Hermes unreachable"}
    return tools


# ---------------------------------------------------------------------------
# GET /api/hermes/mcp — MCP server connections
# ---------------------------------------------------------------------------

@router.get("/mcp")
async def get_mcp(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Return MCP server connections."""
    servers = await _hermes_get("/api/mcp/servers")
    if not servers:
        return {"error": "Hermes unreachable"}
    return servers


# ---------------------------------------------------------------------------
# GET /api/hermes/synced — read cached Hermes data from LamaDB
# ---------------------------------------------------------------------------

@router.get("/synced")
async def get_synced(
    user: Annotated[AuthUser, Depends(_require_auth)],
    limit: int = Query(default=20, ge=1, le=100),
):
    """Return Hermes sessions synced into LamaDB documents."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, content, metadata, tags, created_at
            FROM documents
            WHERE source_type = 'hermes_session'
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )

    sessions = []
    for row in rows:
        meta = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]
        sessions.append({
            "id": str(row["id"]),
            "title": row["title"],
            "preview": row["content"],
            "metadata": meta,
            "tags": list(row["tags"]) if row["tags"] else [],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        })

    return {"sessions": sessions, "count": len(sessions)}


# ---------------------------------------------------------------------------
# POST /api/hermes/sync — manual trigger sync
# ---------------------------------------------------------------------------

@router.post("/sync")
async def trigger_sync(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Manually trigger a Hermes data sync."""
    from .collector import collect
    result = await collect()
    return result
