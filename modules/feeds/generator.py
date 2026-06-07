"""
RSS feed generation logic for the Feeds module.

Queries the documents table matching the feed's filter criteria
and generates RSS XML using the feedgen library.
"""
import textwrap
from datetime import datetime

from feedgen.feed import FeedGenerator

from app.db import get_pool

from .models import Feed


# Base URL for document links (can be overridden via settings)
BASE_URL = "http://localhost:8000"


def _generate_feed_xml(feed: Feed, items: list[dict]) -> str:
    """
    Generate RSS XML string from a feed and matching documents.

    Args:
        feed: The Feed model with filter criteria.
        items: List of document dicts matching the feed filters.

    Returns:
        RSS XML string.
    """
    fg = FeedGenerator()
    fg.title(feed.name)
    fg.description(feed.description or "")
    fg.link(href=f"{BASE_URL}/feeds/{feed.slug}.xml", rel="self")
    fg.language("en")

    for item in items:
        fe = fg.add_item()
        fe.title(item["title"])

        # Link to document or API endpoint
        doc_id = item["id"]
        fe.link(href=f"{BASE_URL}/api/documents/{doc_id}")

        # Description: content or first 500 chars
        content = item.get("content") or ""
        if len(content) > 500:
            content = content[:500].rstrip() + "..."
        fe.description(content)

        # PubDate
        pub_date: datetime = item["created_at"]
        fe.pubDate(pub_date)

    return fg.rss_str(pretty=True).decode("utf-8")


async def generate_feed(feed: Feed) -> str:
    """
    Generate RSS XML for a feed by querying matching documents.

    Document matching rules:
    - filter_tags: ANY tag match using `tags && $1` (if non-empty)
    - filter_source_types: exact match using `source_type = ANY($2)` (if non-empty)
    - Default behavior: when filter_source_types is empty, filter for source_type='summary'

    Results ordered by created_at DESC, limited to feed.max_items.

    Args:
        feed: The Feed model with filter criteria.

    Returns:
        RSS XML string.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        # Build query based on filters
        conditions = []
        params = []
        param_idx = 1

        # Tag filtering (ANY match via GIN operator)
        if feed.filter_tags:
            conditions.append(f"tags && ${param_idx}")
            params.append(feed.filter_tags)
            param_idx += 1

        # Source type filtering
        if feed.filter_source_types:
            conditions.append(f"source_type = ANY(${param_idx})")
            params.append(feed.filter_source_types)
            param_idx += 1
        else:
            # Default: serve only summaries, not raw logs
            conditions.append("source_type = 'summary'")

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        query = f"""
            SELECT id, source_type, title, content, created_at
            FROM documents
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ${param_idx}
        """
        params.append(feed.max_items)

        rows = await conn.fetch(query, *params)

    # Convert rows to dicts for the generator
    items = [
        {
            "id": row["id"],
            "source_type": row["source_type"],
            "title": row["title"],
            "content": row["content"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]

    return _generate_feed_xml(feed, items)
