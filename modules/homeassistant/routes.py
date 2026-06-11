"""Home Assistant API routes."""
import json
import os
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.auth import AuthUser, get_current_user
from app.cache import cached, cache_manager
from app.config import settings
from app.db import get_pool
from .models import ServiceCallRequest

router = APIRouter(tags=["homeassistant"])


def _require_auth(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    return user


def _ha_url() -> str:
    """Read HA URL: pydantic settings field first, then raw env, then .env-style fallback."""
    val = getattr(settings, "homeassistant_url", "") or ""
    if val:
        return val
    return os.environ.get("HOMEASSISTANT_URL", "") or os.environ.get("HA_URL", "") or ""


def _ha_token() -> str:
    """Read HA token with the same fallback chain as the URL."""
    val = getattr(settings, "homeassistant_token", "") or ""
    if val:
        return val
    return os.environ.get("HOMEASSISTANT_TOKEN", "") or os.environ.get("HA_TOKEN", "") or ""


def _highlight_ids() -> list[str]:
    raw = getattr(settings, "homeassistant_highlight_entities", "") or ""
    if not raw:
        raw = os.environ.get("HOMEASSISTANT_HIGHLIGHT_ENTITIES", "") or ""
    if not raw:
        return []
    return [h.strip() for h in raw.split(",") if h.strip()]


# ─── GET /api/homeassistant/status ───────────────────────────────────────

@router.get("/status")
@cached(ttl_seconds=120, invalidate_tags=["homeassistant"], key_prefix="ha_status")
async def get_status(request: Request, user: Annotated[AuthUser, Depends(_require_auth)]):
    """Get the latest HA entity snapshot from the document store."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT content, metadata, updated_at FROM documents WHERE source_type = 'homeassistant_snapshot' AND title = 'HA State Snapshot' ORDER BY updated_at DESC LIMIT 1"
        )
        if not row:
            return {
                "status": "no_data",
                "entities": [],
                "metadata": {},
                "highlight_ids": _highlight_ids(),
                "ts": None,
            }

        content = json.loads(row["content"]) if isinstance(row["content"], str) else row["content"]
        metadata = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]

    # Filter to highlighted entities if configured
    highlight_ids = _highlight_ids()

    entities = []
    for e in content:
        entity = {
            "entity_id": e.get("entity_id", ""),
            "state": e.get("state", ""),
            "attributes": {
                "friendly_name": e.get("attributes", {}).get("friendly_name", ""),
                "unit_of_measurement": e.get("attributes", {}).get("unit_of_measurement", ""),
                "device_class": e.get("attributes", {}).get("device_class", ""),
            },
            "last_changed": e.get("last_changed"),
            "last_updated": e.get("last_updated"),
        }
        entities.append(entity)

    return {
        "status": "ok",
        "entities": entities,
        "metadata": metadata,
        "highlight_ids": highlight_ids,
        "ts": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


# ─── GET /api/homeassistant/config ───────────────────────────────────────

@router.get("/config")
@cached(ttl_seconds=300, invalidate_tags=["homeassistant"], key_prefix="ha_config")
async def get_config(request: Request, user: Annotated[AuthUser, Depends(_require_auth)]):
    """Return HA connection status and config."""
    ha_url = _ha_url()
    ha_token = _ha_token()
    if not ha_url or not ha_token:
        return {"connected": False, "reason": "Not configured"}

    headers = {
        "Authorization": f"Bearer {ha_token}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{ha_url}/api/", headers=headers)
            resp.raise_for_status()
            config_resp = await client.get(f"{ha_url}/api/config", headers=headers)
            config_resp.raise_for_status()
            config = config_resp.json()
    except Exception as e:
        return {"connected": False, "reason": str(e)}

    return {
        "connected": True,
        "version": config.get("version", "unknown"),
        "location": config.get("location_name", "unknown"),
        "url": ha_url,
    }


# ─── POST /api/homeassistant/service ─────────────────────────────────────

@router.post("/service")
async def call_service(
    req: ServiceCallRequest,
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Call a Home Assistant service (turn on light, set temp, activate scene, etc.)."""
    ha_url = _ha_url()
    ha_token = _ha_token()
    if not ha_url or not ha_token:
        raise HTTPException(status_code=503, detail="Home Assistant not configured")

    headers = {
        "Authorization": f"Bearer {ha_token}",
        "Content-Type": "application/json",
    }

    # Build service data
    service_data = {}
    if req.entity_id:
        service_data["entity_id"] = req.entity_id
    if req.data:
        service_data.update(req.data)

    url = f"{ha_url}/api/services/{req.domain}/{req.service}"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, headers=headers, json=service_data)
            resp.raise_for_status()
            result = resp.json() if resp.text else []
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"HA returned {e.response.status_code}: {e.response.text[:200]}",
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"HA call failed: {str(e)}")

    cache_manager.invalidate("homeassistant")
    return {
        "success": True,
        "message": f"Called {req.domain}/{req.service}",
        "changed_states": result if isinstance(result, list) else None,
    }
