"""MCP tools for the Wiki module."""
import json
import re
from app.db import get_pool
from modules.wiki.wiki_db import search_pages
from modules.wiki.scratchpad import create_scratchpad_entry


async def wiki_search(q: str, limit: int = 20) -> dict:
    """Search wiki pages by title and content using pg_trgm similarity."""
    results = await search_pages(query=q, limit=limit)
    return {"results": results, "count": len(results), "query": q}


async def scratchpad_capture(content: str, title: str = "Scratchpad") -> dict:
    """Save a scratchpad entry to the documents table.

    Creates a document with source_type='scratchpad' and logs a wiki event.
    """
    doc = await create_scratchpad_entry(content=content, title=title)

    # Write a wiki event for the scratchpad creation
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO events (source, type, severity, title, body, metadata, ticker, tags)
            VALUES ('wiki', 'scratchpad_created', 'info', $1, $2, $3, false, $4)
            """,
            f"Scratchpad: {title}",
            content[:200] if content else "",
            json.dumps({"doc_id": doc["id"], "source": "scratchpad"}),
            ["wiki", "scratchpad"],
        )

    return {
        "id": doc["id"],
        "content": doc["content"],
        "created_at": doc["created_at"].isoformat() if doc["created_at"] else None,
    }
