"""YouTube module API routes."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth import AuthUser, get_current_user
from app.cache import cached
from app.config import settings
from app.db import get_pool

router = APIRouter(tags=["youtube"])


def _require_auth(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    return user


# ---------------------------------------------------------------------------
# GET /api/youtube/status — latest YouTube snapshot
# ---------------------------------------------------------------------------

@router.get("/status")
@cached(ttl_seconds=60, invalidate_tags=["youtube", "events"], key_prefix="youtube_status")
async def get_status(request: Request, user: Annotated[AuthUser, Depends(_require_auth)]):
    """Get the latest YouTube snapshot from the events table."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT metadata, ts FROM events
               WHERE source = 'youtube' AND type = 'youtube_snapshot'
               ORDER BY ts DESC LIMIT 1"""
        )
    if not row:
        return {"status": "no_data"}

    import json
    meta = row["metadata"]
    if isinstance(meta, str):
        meta = json.loads(meta)
    return {"data": meta, "ts": row["ts"].isoformat()}


# ---------------------------------------------------------------------------
# GET /api/youtube/videos — stored YouTube documents
# ---------------------------------------------------------------------------

@router.get("/videos")
@cached(ttl_seconds=30, invalidate_tags=["youtube", "documents"], key_prefix="youtube_videos")
async def get_videos(
    request: Request,
    user: Annotated[AuthUser, Depends(_require_auth)],
    list_type: str | None = Query(default=None, description="Filter by list_type"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """List YouTube videos stored as documents."""
    pool = get_pool()
    async with pool.acquire() as conn:
        conditions = ["source_type = 'youtube'"]
        params: list = []
        if list_type:
            conditions.append("metadata ->> 'list_type' = $" + str(len(params) + 1))
            params.append(list_type)

        where_clause = " AND ".join(conditions)
        query = f"""
            SELECT id, title, content, metadata, tags, created_at, updated_at
            FROM documents
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
        """
        params.extend([limit, offset])
        rows = await conn.fetch(query, *params)

    videos = []
    for row in rows:
        import json
        metadata = row["metadata"]
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        videos.append({
            "id": str(row["id"]),
            "title": row["title"],
            "content": row["content"],
            "metadata": metadata,
            "tags": list(row["tags"]) if row["tags"] else [],
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
        })

    return {"videos": videos, "count": len(videos)}


# ---------------------------------------------------------------------------
# GET /api/youtube/health — reachability check for the YouTube API
# ---------------------------------------------------------------------------

@router.get("/health")
@cached(ttl_seconds=120, invalidate_tags=["youtube"], key_prefix="youtube_health")
async def check_health(request: Request, user: Annotated[AuthUser, Depends(_require_auth)]):
    """Check whether the YouTube Data API is reachable with the configured key."""
    if not settings.youtube_api_key:
        return {"reachable": False, "reason": "API key not configured"}

    import httpx
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={
                    "part": "snippet",
                    "chart": "mostPopular",
                    "maxResults": 1,
                    "key": settings.youtube_api_key,
                },
                timeout=5.0,
            )
            if resp.status_code == 200:
                return {"reachable": True}
            return {"reachable": False, "reason": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"reachable": False, "reason": str(e)}


# ---------------------------------------------------------------------------
# POST /api/youtube/poll — force poll (also available via dashboard force-poll)
# ---------------------------------------------------------------------------

@router.post("/poll")
async def force_poll(user: Annotated[AuthUser, Depends(_require_auth)]):
    """Manually trigger the YouTube collector."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")

    from .collector import collect
    result = await collect()
    return {"success": "error" not in result, "result": result}
