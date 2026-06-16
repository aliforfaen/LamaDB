"""
Feeds API routes.

Endpoints:
  - POST /api/feeds              — create a new feed (admin/agent only)
  - GET  /api/feeds              — list all feeds (auth required)
  - GET  /api/feeds/{slug}       — get feed by slug (auth required)
  - PUT  /api/feeds/{slug}       — update feed (admin/agent only)
  - DELETE /api/feeds/{slug}     — delete feed (admin only)
  - POST /api/feeds/{slug}/publish — publish an entry to a feed (admin/agent only)

The public RSS endpoint is in get_public_router().
"""
import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.auth import AuthUser, get_current_user
from app.db import get_pool

from .generator import generate_feed
from .models import Feed, FeedCreate, FeedUpdate, PublishEntry

router = APIRouter(tags=["feeds"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _feed_from_row(row) -> Feed:
    """Convert an asyncpg row to a Feed model."""
    return Feed(
        id=row["id"],
        name=row["name"],
        slug=row["slug"],
        description=row["description"],
        filter_tags=list(row["filter_tags"]) if row["filter_tags"] else [],
        filter_source_types=list(row["filter_source_types"]) if row["filter_source_types"] else [],
        max_items=row["max_items"],
        created_at=row["created_at"],
    )


# ---------------------------------------------------------------------------
# POST /api/feeds — create feed
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=Feed,
    status_code=status.HTTP_201_CREATED,
)
async def create_feed(
    feed_create: FeedCreate,
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> Feed:
    """
    Create a new RSS feed.

    Requires admin or agent role.
    """
    if user.role not in ("admin", "agent"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or agent role required",
        )

    pool = get_pool()
    async with pool.acquire() as conn:
        # Check slug uniqueness
        existing = await conn.fetchrow(
            "SELECT id FROM feeds WHERE slug = $1",
            feed_create.slug,
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Feed with slug '{feed_create.slug}' already exists",
            )

        row = await conn.fetchrow(
            """
            INSERT INTO feeds (name, slug, description, filter_tags, filter_source_types, max_items)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id, name, slug, description, filter_tags, filter_source_types, max_items, created_at
            """,
            feed_create.name,
            feed_create.slug,
            feed_create.description,
            feed_create.filter_tags,
            feed_create.filter_source_types,
            feed_create.max_items,
        )
        return _feed_from_row(row)


# ---------------------------------------------------------------------------
# GET /api/feeds — list all feeds
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[Feed],
)
async def list_feeds(
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> list[Feed]:
    """List all RSS feeds."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, slug, description, filter_tags, filter_source_types, max_items, created_at
            FROM feeds
            ORDER BY created_at DESC
            """
        )
        return [_feed_from_row(row) for row in rows]


# ---------------------------------------------------------------------------
# GET /api/feeds/{slug} — get feed by slug
# ---------------------------------------------------------------------------


@router.get(
    "/{slug}",
    response_model=Feed,
)
async def get_feed(
    slug: str,
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> Feed:
    """Get a single feed by slug."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, name, slug, description, filter_tags, filter_source_types, max_items, created_at
            FROM feeds
            WHERE slug = $1
            """,
            slug,
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Feed '{slug}' not found",
            )
        return _feed_from_row(row)


# ---------------------------------------------------------------------------
# PUT /api/feeds/{slug} — update feed
# ---------------------------------------------------------------------------


@router.put(
    "/{slug}",
    response_model=Feed,
)
async def update_feed(
    slug: str,
    feed_update: FeedUpdate,
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> Feed:
    """
    Update an existing RSS feed.

    Requires admin or agent role.
    """
    if user.role not in ("admin", "agent"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or agent role required",
        )

    pool = get_pool()
    async with pool.acquire() as conn:
        # Check feed exists
        existing = await conn.fetchrow(
            "SELECT id FROM feeds WHERE slug = $1",
            slug,
        )
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Feed '{slug}' not found",
            )

        # Check new slug uniqueness if changing
        if feed_update.slug and feed_update.slug != slug:
            conflicting = await conn.fetchrow(
                "SELECT id FROM feeds WHERE slug = $1 AND slug != $2",
                feed_update.slug,
                slug,
            )
            if conflicting:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Feed with slug '{feed_update.slug}' already exists",
                )

        # Build dynamic update
        updates = []
        params = []
        param_idx = 1

        if feed_update.name is not None:
            updates.append(f"name = ${param_idx}")
            params.append(feed_update.name)
            param_idx += 1

        if feed_update.slug is not None:
            updates.append(f"slug = ${param_idx}")
            params.append(feed_update.slug)
            param_idx += 1

        if feed_update.description is not None:
            updates.append(f"description = ${param_idx}")
            params.append(feed_update.description)
            param_idx += 1

        if feed_update.filter_tags is not None:
            updates.append(f"filter_tags = ${param_idx}")
            params.append(feed_update.filter_tags)
            param_idx += 1

        if feed_update.filter_source_types is not None:
            updates.append(f"filter_source_types = ${param_idx}")
            params.append(feed_update.filter_source_types)
            param_idx += 1

        if feed_update.max_items is not None:
            updates.append(f"max_items = ${param_idx}")
            params.append(feed_update.max_items)
            param_idx += 1

        if not updates:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields to update",
            )

        params.append(slug)
        row = await conn.fetchrow(
            f"""
            UPDATE feeds
            SET {', '.join(updates)}
            WHERE slug = ${param_idx}
            RETURNING id, name, slug, description, filter_tags, filter_source_types, max_items, created_at
            """,
            *params,
        )
        return _feed_from_row(row)


# ---------------------------------------------------------------------------
# DELETE /api/feeds/{slug} — delete feed
# ---------------------------------------------------------------------------


@router.delete(
    "/{slug}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_feed(
    slug: str,
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> None:
    """
    Delete an RSS feed.

    Requires admin role.
    """
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required for deletion",
        )

    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM feeds WHERE slug = $1",
            slug,
        )
        if result == "DELETE 0":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Feed '{slug}' not found",
            )


# ---------------------------------------------------------------------------
# POST /api/feeds/{slug}/publish — publish entry to feed
# ---------------------------------------------------------------------------


@router.post(
    "/{slug}/publish",
    status_code=status.HTTP_201_CREATED,
)
async def publish_to_feed(
    slug: str,
    entry: PublishEntry,
    user: Annotated[AuthUser, Depends(get_current_user)],
):
    """
    Publish an entry to an RSS feed. Creates a document with source_type='agent_feed'
    and tags merged from the feed's filter_tags + entry tags.
    """
    if user.role not in ("admin", "agent"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or agent role required",
        )

    pool = get_pool()
    async with pool.acquire() as conn:
        feed_row = await conn.fetchrow(
            "SELECT id, filter_tags, filter_source_types FROM feeds WHERE slug = $1",
            slug,
        )
        if feed_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Feed '{slug}' not found",
            )

        feed_tags = list(feed_row["filter_tags"]) if feed_row["filter_tags"] else []
        all_tags = list(set(feed_tags + entry.tags))

        doc_id = await conn.fetchval(
            """
            INSERT INTO documents (source_type, title, content, tags, metadata)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            "agent_feed",
            entry.title,
            entry.content,
            all_tags,
            json.dumps({
                **entry.metadata,
                "feed_slug": slug,
                "published_by": user.user_id or "unknown",
            }),
        )

        return {
            "status": "published",
            "document_id": str(doc_id),
            "feed": slug,
            "tags": all_tags,
        }


# ---------------------------------------------------------------------------
# Public RSS endpoint (no auth) — separate router registered in main.py
# ---------------------------------------------------------------------------

public_router = APIRouter(tags=["feeds-public"])


@public_router.get("/feeds/{slug}.xml")
async def get_feed_rss_xml(slug: str) -> Response:
    """
    Serve RSS XML for a feed (public, no auth required).

    This endpoint is registered at /feeds/{slug}.xml (top-level, not under /api/).
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, name, slug, description, filter_tags, filter_source_types, max_items, created_at
            FROM feeds
            WHERE slug = $1
            """,
            slug,
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Feed '{slug}' not found",
            )

    feed = _feed_from_row(row)
    xml_content = await generate_feed(feed)

    return Response(
        content=xml_content,
        media_type="application/xml",
    )
