"""DB-backed wiki page storage — uses the documents table.

All wiki pages are stored in the `documents` table with source_type='wiki_page'.
Filesystem path is stored in metadata->>'path'.
"""
import json
import re
from typing import Optional
from uuid import uuid4

from app.db import get_pool


async def create_page(title: str, content: str, path: str, tags: list[str] = None) -> dict:
    """Create a wiki page in the documents table.

    Args:
        title: Page title
        content: Markdown body
        path: Filesystem path (e.g., "entities/my-page.md")
        tags: Optional list of tag strings

    Returns:
        Wiki page dict with id, title, content, path, tags, created_at, updated_at
    """
    pool = get_pool()
    page_id = str(uuid4())
    metadata = {"path": path, "type": "wiki_page"}

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO documents (id, source_type, title, content, metadata, tags)
               VALUES ($1, 'wiki_page', $2, $3, $4, $5)
               RETURNING id, title, content, metadata, tags, created_at, updated_at""",
            page_id, title, content, json.dumps(metadata), tags or [],
        )
    return _doc_to_page(dict(row))


async def get_page(page_id: str) -> Optional[dict]:
    """Get a wiki page by ID.

    Args:
        page_id: UUID string of the page

    Returns:
        Wiki page dict or None if not found
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM documents WHERE id = $1 AND source_type = 'wiki_page'",
            page_id,
        )
    if not row:
        return None
    return _doc_to_page(dict(row))


async def get_page_by_path(path: str) -> Optional[dict]:
    """Get a wiki page by filesystem path (stored in metadata).

    Args:
        path: Filesystem path relative to wiki root (e.g., "entities/foo.md")

    Returns:
        Wiki page dict or None if not found
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT * FROM documents
               WHERE source_type = 'wiki_page'
                 AND metadata->>'path' = $1
               LIMIT 1""",
            path,
        )
    if not row:
        return None
    return _doc_to_page(dict(row))


async def update_page(
    page_id: str,
    title: str = None,
    content: str = None,
    tags: list[str] = None,
) -> Optional[dict]:
    """Update a wiki page. Only provided fields are changed.

    Args:
        page_id: UUID string of the page
        title: New title (optional)
        content: New content (optional)
        tags: New tags list (optional)

    Returns:
        Updated wiki page dict or None if not found
    """
    pool = get_pool()
    updates = []
    params = []
    idx = 1

    if title is not None:
        updates.append(f"title = ${idx}")
        params.append(title)
        idx += 1
    if content is not None:
        updates.append(f"content = ${idx}")
        params.append(content)
        idx += 1
    if tags is not None:
        updates.append(f"tags = ${idx}")
        params.append(tags)
        idx += 1

    if not updates:
        return await get_page(page_id)

    updates.append("updated_at = now()")
    params.append(page_id)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""UPDATE documents
                SET {', '.join(updates)}
                WHERE id = ${idx} AND source_type = 'wiki_page'
                RETURNING *""",
            *params,
        )
    if not row:
        return None
    return _doc_to_page(dict(row))


async def delete_page(page_id: str) -> bool:
    """Delete a wiki page and its outgoing document links.

    Args:
        page_id: UUID string of the page

    Returns:
        True if a page was deleted, False if not found
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        # Delete outgoing links
        await conn.execute(
            "DELETE FROM document_links WHERE source_id = $1",
            page_id,
        )
        # Delete the page
        result = await conn.execute(
            "DELETE FROM documents WHERE id = $1 AND source_type = 'wiki_page'",
            page_id,
        )
    return result != "DELETE 0"


async def list_pages(
    sort: str = "updated_at",
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """List wiki pages with pagination.

    Args:
        sort: Sort field — "updated_at", "created_at", or "title"
        limit: Max results to return
        offset: Number of results to skip

    Returns:
        List of wiki page dicts (summary — no content field)
    """
    valid_sort = {"updated_at", "created_at", "title"}
    if sort not in valid_sort:
        sort = "updated_at"

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT id, title, metadata, tags, created_at, updated_at
               FROM documents
               WHERE source_type = 'wiki_page'
               ORDER BY {sort} DESC
               LIMIT $1 OFFSET $2""",
            limit, offset,
        )
    return [_doc_to_page(dict(r)) for r in rows]


async def search_pages(query: str, limit: int = 20) -> list[dict]:
    """Full-text search across wiki page titles and content using pg_trgm similarity.

    Args:
        query: Search term
        limit: Max results to return

    Returns:
        List of matching wiki page dicts, ordered by similarity
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, title, content, metadata, tags, created_at, updated_at,
                      similarity(title, $1) AS sim
               FROM documents
               WHERE source_type = 'wiki_page'
                 AND (title % $1 OR content % $1)
               ORDER BY sim DESC
               LIMIT $2""",
            query, limit,
        )
    return [_doc_to_page(dict(r)) for r in rows]


async def resolve_wikilink(title: str) -> Optional[str]:
    """Resolve a [[page-title]] wikilink to a document ID. Case-insensitive.

    Args:
        title: Page title to look up

    Returns:
        UUID string of the target document, or None if not found
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id FROM documents
               WHERE source_type = 'wiki_page'
                 AND LOWER(title) = LOWER($1)
               LIMIT 1""",
            title,
        )
    return str(row["id"]) if row else None


async def sync_wikilinks(page_id: str, content: str) -> None:
    """Parse [[wikilinks]] from markdown content and create document_links entries.

    Removes old wiki_link entries for this page and creates new ones based on
    the current content.

    Args:
        page_id: UUID string of the source page
        content: Markdown content to parse for [[wikilinks]]
    """
    pool = get_pool()

    # Find all [[page-name]] patterns
    wikilinks = re.findall(r'\[\[([^\]]+)\]\]', content)

    async with pool.acquire() as conn:
        # Remove old wikilinks for this page
        await conn.execute(
            "DELETE FROM document_links WHERE source_id = $1 AND link_type = 'wiki_link'",
            page_id,
        )

        # Resolve and create new links
        for link_title in wikilinks:
            target_id = await resolve_wikilink(link_title)
            if target_id and target_id != page_id:
                await conn.execute(
                    """INSERT INTO document_links (source_id, target_id, link_type, context)
                       VALUES ($1, $2, 'wiki_link', $3)
                       ON CONFLICT DO NOTHING""",
                    page_id, target_id, link_title,
                )


def _doc_to_page(d: dict) -> dict:
    """Convert a documents row dict to a wiki page dict.

    Handles asyncpg quirks:
    - JSONB metadata may come back as a string or dict
    - UUID columns come back as UUID objects, not strings

    Args:
        d: Row dict from asyncpg

    Returns:
        Wiki page dict with string id, iso timestamps, etc.
    """
    meta = d.get("metadata")
    if isinstance(meta, str):
        meta = json.loads(meta)

    return {
        "id": str(d["id"]) if d.get("id") else None,
        "title": d.get("title", ""),
        "content": d.get("content", ""),
        "path": meta.get("path", "") if meta else "",
        "tags": d.get("tags", []),
        "created_at": d.get("created_at").isoformat() if d.get("created_at") else None,
        "updated_at": d.get("updated_at").isoformat() if d.get("updated_at") else None,
    }
