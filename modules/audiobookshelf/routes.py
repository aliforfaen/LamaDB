"""Audiobookshelf API routes."""
from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth import AuthUser, get_current_user
from app.cache import cached
from app.config import settings
from app.db import get_pool

router = APIRouter(tags=["audiobookshelf"])


def _require_auth(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    return user


# ---------------------------------------------------------------------------
# GET /api/audiobookshelf/status — latest snapshot from the events table
# ---------------------------------------------------------------------------

@router.get("/status")
@cached(ttl_seconds=60, invalidate_tags=["audiobookshelf", "events"], key_prefix="abs_status")
async def get_status(request: Request, user: Annotated[AuthUser, Depends(_require_auth)]):
    """Get the latest Audiobookshelf snapshot from the events table."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT metadata, ts FROM events
               WHERE source = 'audiobookshelf' AND type = 'abs_snapshot'
               ORDER BY ts DESC LIMIT 1"""
        )
    if not row:
        return {"status": "no_data"}

    meta = row["metadata"]
    if isinstance(meta, str):
        meta = json.loads(meta)
    return {"data": meta, "ts": row["ts"].isoformat()}


# ---------------------------------------------------------------------------
# GET /api/audiobookshelf/libraries — list libraries (live from ABS or cached)
# ---------------------------------------------------------------------------

@router.get("/libraries")
@cached(ttl_seconds=120, invalidate_tags=["audiobookshelf"], key_prefix="abs_libraries")
async def list_libraries(request: Request, user: Annotated[AuthUser, Depends(_require_auth)]):
    """List libraries from the latest snapshot."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT metadata, ts FROM events
               WHERE source = 'audiobookshelf' AND type = 'abs_snapshot'
               ORDER BY ts DESC LIMIT 1"""
        )
    if not row:
        return {"libraries": [], "ts": None}

    meta = row["metadata"]
    if isinstance(meta, str):
        meta = json.loads(meta)
    return {"libraries": meta.get("libraries", []), "ts": row["ts"].isoformat()}


# ---------------------------------------------------------------------------
# GET /api/audiobookshelf/books — stored Audiobookshelf documents
# ---------------------------------------------------------------------------

@router.get("/books")
@cached(ttl_seconds=30, invalidate_tags=["audiobookshelf", "documents"], key_prefix="abs_books")
async def list_books(
    request: Request,
    user: Annotated[AuthUser, Depends(_require_auth)],
    library_id: str | None = Query(default=None, description="Filter by library_id"),
    progress: str | None = Query(default=None, description="'in_progress' | 'finished' | 'unstarted'"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """List Audiobookshelf books stored as documents."""
    pool = get_pool()
    async with pool.acquire() as conn:
        conditions = ["source_type = 'audiobookshelf'"]
        params: list[Any] = []
        if library_id:
            conditions.append("metadata ->> 'library_id' = $" + str(len(params) + 1))
            params.append(library_id)
        if progress == "in_progress":
            conditions.append("(metadata ->> 'is_finished')::boolean = false")
            conditions.append("(metadata ->> 'progress_percent')::float > 0")
        elif progress == "finished":
            conditions.append("(metadata ->> 'is_finished')::boolean = true")
        elif progress == "unstarted":
            conditions.append(
                "(metadata ->> 'is_finished')::boolean = false "
                "AND COALESCE((metadata ->> 'progress_percent')::float, 0) = 0"
            )

        where_clause = " AND ".join(conditions)
        query = f"""
            SELECT id, title, content, metadata, tags, created_at, updated_at
            FROM documents
            WHERE {where_clause}
            ORDER BY updated_at DESC
            LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
        """
        params.extend([limit, offset])
        rows = await conn.fetch(query, *params)

    books = []
    for row in rows:
        metadata = row["metadata"]
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        books.append({
            "id": str(row["id"]),
            "title": row["title"],
            "content": row["content"],
            "metadata": metadata,
            "tags": list(row["tags"]) if row["tags"] else [],
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
        })

    return {"books": books, "count": len(books)}


# ---------------------------------------------------------------------------
# GET /api/audiobookshelf/health — reachability check for the ABS server
# ---------------------------------------------------------------------------

@router.get("/health")
@cached(ttl_seconds=120, invalidate_tags=["audiobookshelf"], key_prefix="abs_health")
async def check_health(request: Request, user: Annotated[AuthUser, Depends(_require_auth)]):
    """Check whether the Audiobookshelf server is reachable with the configured token."""
    if not settings.audiobookshelf_url or not settings.audiobookshelf_token:
        return {"reachable": False, "reason": "URL or token not configured"}

    import httpx
    headers = {"Authorization": f"Bearer {settings.audiobookshelf_token}"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                f"{settings.audiobookshelf_url.rstrip('/')}/api/libraries",
                headers=headers,
                timeout=5.0,
            )
            if resp.status_code == 200:
                return {"reachable": True}
            return {"reachable": False, "reason": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"reachable": False, "reason": str(e)}


# ---------------------------------------------------------------------------
# POST /api/audiobookshelf/poll — force poll (also available via dashboard force-poll)
# ---------------------------------------------------------------------------

@router.post("/poll")
async def force_poll(user: Annotated[AuthUser, Depends(_require_auth)]):
    """Manually trigger the Audiobookshelf collector."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")

    from .collector import collect
    result = await collect()
    return {"success": "error" not in result, "result": result}