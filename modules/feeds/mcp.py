"""MCP tools for the Feeds module — RSS feed discovery + entry inspection."""
from app.db import get_pool


async def list_feeds() -> dict:
    """List every configured RSS feed.

    Mirrors `GET /api/feeds`. Returns the feed catalog (name, slug,
    description, filter tags, max items, created_at) without any
    document payloads. Cheap to call — single indexed scan.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, slug, description, filter_tags,
                   filter_source_types, max_items, created_at
            FROM feeds
            ORDER BY created_at DESC
            """
        )

    feeds = []
    for row in rows:
        feeds.append({
            "id": str(row["id"]),
            "name": row["name"],
            "slug": row["slug"],
            "description": row["description"],
            "filter_tags": list(row["filter_tags"]) if row["filter_tags"] else [],
            "filter_source_types": (
                list(row["filter_source_types"]) if row["filter_source_types"] else []
            ),
            "max_items": row["max_items"],
            "created_at": (
                row["created_at"].isoformat() if row["created_at"] else None
            ),
        })

    return {"feeds": feeds, "count": len(feeds)}


async def latest_feed_entries(
    slug: str | None = None,
    limit: int = 10,
) -> dict:
    """Return most recent entries that would appear in a feed.

    Args:
        slug:  Optional feed slug. When set, the same filter rules as
               the RSS generator are applied (filter_tags ANY match,
               filter_source_types exact match, defaulting to
               source_type='summary' if no source filter is configured).
               When omitted, returns the most recent `agent_feed`
               documents — the entries produced by
               `POST /api/feeds/{slug}/publish`.
        limit: Max entries to return (1..50).

    Returns a dict with `entries` (list of {id, title, source_type,
    tags, created_at, feed_slug}) and `count`. The `feed_slug` column
    is the slug on which the entry was published (from document
    metadata), or the requested `slug` for filtered queries.
    """
    limit = max(1, min(int(limit), 50))
    pool = get_pool()
    entries: list[dict] = []

    if slug is not None:
        async with pool.acquire() as conn:
            feed_row = await conn.fetchrow(
                """
                SELECT id, filter_tags, filter_source_types, max_items
                FROM feeds
                WHERE slug = $1
                """,
                slug,
            )
            if feed_row is None:
                return {"entries": [], "count": 0, "slug": slug, "error": "feed not found"}

            conditions: list[str] = []
            params: list = []
            idx = 1

            if feed_row["filter_tags"]:
                conditions.append(f"tags && ${idx}")
                params.append(list(feed_row["filter_tags"]))
                idx += 1
            if feed_row["filter_source_types"]:
                conditions.append(f"source_type = ANY(${idx})")
                params.append(list(feed_row["filter_source_types"]))
                idx += 1
            else:
                conditions.append("source_type = 'summary'")

            where_clause = " AND ".join(conditions)
            params.append(limit)
            rows = await conn.fetch(
                f"""
                SELECT id, title, source_type, tags, created_at, metadata
                FROM documents
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT ${idx}
                """,
                *params,
            )

            for row in rows:
                entries.append({
                    "id": str(row["id"]),
                    "title": row["title"],
                    "source_type": row["source_type"],
                    "tags": list(row["tags"]) if row["tags"] else [],
                    "created_at": (
                        row["created_at"].isoformat() if row["created_at"] else None
                    ),
                    "feed_slug": slug,
                })
        return {"entries": entries, "count": len(entries), "slug": slug}

    # No slug: most recent agent_feed documents (entries published via the
    # /api/feeds/{slug}/publish endpoint).
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, source_type, tags, created_at, metadata
            FROM documents
            WHERE source_type = 'agent_feed'
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
        for row in rows:
            meta = row["metadata"]
            if isinstance(meta, str):
                import json
                meta = json.loads(meta)
            meta = meta or {}
            entries.append({
                "id": str(row["id"]),
                "title": row["title"],
                "source_type": row["source_type"],
                "tags": list(row["tags"]) if row["tags"] else [],
                "created_at": (
                    row["created_at"].isoformat() if row["created_at"] else None
                ),
                "feed_slug": meta.get("feed_slug"),
            })
    return {"entries": entries, "count": len(entries)}
