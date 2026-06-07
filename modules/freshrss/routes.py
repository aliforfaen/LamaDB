"""FreshRSS GReader API feed sync routes."""
import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
import httpx

from app.auth import AuthUser, get_current_user
from app.db import get_pool
from app.config import settings

from .models import ArticleSyncResult

router = APIRouter(tags=["freshrss"])

_API_PATH = "/greader.php"


def _require_auth(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    return user


async def _get_auth_token() -> str:
    """Authenticate with FreshRSS and return the GoogleLogin auth token."""
    if not settings.freshrss_url or not settings.freshrss_api_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FreshRSS not configured",
        )

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{settings.freshrss_url}{_API_PATH}/accounts/ClientLogin",
            data={
                "Email": settings.freshrss_username,
                "Passwd": settings.freshrss_api_password,
                "source": "lamadb-freshrss",
                "service": "reader",
            },
            timeout=15.0,
        )
        if resp.status_code == 403:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="FreshRSS authentication failed — check credentials",
            )
        resp.raise_for_status()
        body = resp.text
        import re
        match = re.search(r"Auth=(\S+)", body)
        if not match:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"No Auth token in ClientLogin response: {body[:200]}",
            )
        return match.group(1)


# ---------------------------------------------------------------------------
# GET /api/freshrss/feeds — list subscriptions via GReader API
# ---------------------------------------------------------------------------

@router.get("/feeds")
async def list_feeds(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Proxy to FreshRSS GReader API to list all subscribed feeds."""
    if not settings.freshrss_url or not settings.freshrss_api_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FreshRSS not configured",
        )

    try:
        auth_token = await _get_auth_token()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"FreshRSS auth error: {e}",
        )

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{settings.freshrss_url}{_API_PATH}/reader/api/0/subscription/list",
            params={"output": "json"},
            headers={"Authorization": f"GoogleLogin auth={auth_token}"},
            timeout=10.0,
        )
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# GET /api/freshrss/articles — recent articles from documents table
# ---------------------------------------------------------------------------

@router.get("/articles")
async def list_articles(
    user: Annotated[AuthUser, Depends(_require_auth)],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Query articles stored from RSS sync."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, source_type, title, content, metadata, tags, created_at
            FROM documents
            WHERE source_type = 'rss_article'
            ORDER BY created_at DESC
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )

    articles = []
    for row in rows:
        articles.append({
            "id": str(row["id"]),
            "source_type": row["source_type"],
            "title": row["title"],
            "content": row["content"],
            "metadata": json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"],
            "tags": list(row["tags"]) if row["tags"] else [],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        })
    return {"articles": articles, "count": len(articles)}


# ---------------------------------------------------------------------------
# POST /api/freshrss/sync — trigger manual sync
# ---------------------------------------------------------------------------

@router.post("/sync", response_model=ArticleSyncResult)
async def trigger_sync(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Trigger a manual sync from FreshRSS."""
    from .collector import collect

    result = await collect()
    return ArticleSyncResult(**result)


# ---------------------------------------------------------------------------
# GET /api/freshrss/status — sync status overview
# ---------------------------------------------------------------------------

@router.get("/status")
async def get_status(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Return FreshRSS sync status: last event time and article count."""
    pool = get_pool()
    async with pool.acquire() as conn:
        # Last event from freshrss source
        last_event = await conn.fetchrow(
            """
            SELECT ts, title, severity
            FROM events
            WHERE source = 'freshrss'
            ORDER BY ts DESC
            LIMIT 1
            """
        )

        # Article count
        article_count = await conn.fetchval(
            "SELECT count(*) FROM documents WHERE source_type = 'rss_article'"
        )

        # Feeds synced (distinct feeds from metadata)
        feeds_count = await conn.fetchval(
            """
            SELECT count(DISTINCT metadata->>'feed_id')
            FROM documents
            WHERE source_type = 'rss_article'
              AND metadata ? 'feed_id'
            """
        )

    return {
        "configured": bool(settings.freshrss_url and settings.freshrss_api_password),
        "last_sync": last_event["ts"].isoformat() if last_event else None,
        "last_sync_title": last_event["title"] if last_event else None,
        "article_count": article_count or 0,
        "feeds_count": feeds_count or 0,
    }
