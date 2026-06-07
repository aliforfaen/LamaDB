"""Scratchpad CRUD helpers using the documents table."""
import json
import uuid
from datetime import datetime

from app.db import get_pool


async def create_scratchpad_entry(content: str, title: str = "Scratchpad") -> dict:
    """
    Create a new scratchpad entry in the documents table.

    source_type='scratchpad', tags=['scratchpad']
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO documents (source_type, title, content, metadata, tags)
            VALUES ('scratchpad', $1, $2, $3, $4)
            RETURNING id, source_type, title, content, metadata, tags, created_at, updated_at
            """,
            title,
            content,
            json.dumps({"source": "scratchpad"}),
            ["scratchpad"],
        )
        return _doc_from_row(row)


async def list_scratchpad_entries(limit: int = 20, offset: int = 0) -> list[dict]:
    """List recent scratchpad entries ordered by created_at desc."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, source_type, title, content, metadata, tags, created_at, updated_at
            FROM documents
            WHERE source_type = 'scratchpad'
            ORDER BY created_at DESC
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )
        return [_doc_from_row(row) for row in rows]


def _doc_from_row(row) -> dict:
    """Convert asyncpg row to a dict, coercing JSONB metadata."""
    meta = row["metadata"]
    if meta is not None and not isinstance(meta, dict):
        if isinstance(meta, str):
            meta = json.loads(meta)
        else:
            meta = dict(meta) if meta else {}
    return {
        "id": str(row["id"]),
        "content": row["content"] or "",
        "created_at": row["created_at"],
    }
