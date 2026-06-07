"""Full-text search routes using pg_trgm similarity."""
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.auth import AuthUser, get_current_user
from app.db import get_pool
from app.models.documents import Document

router = APIRouter(prefix="/api/search", tags=["search"])


def _coerce_jsonb(value):
    """Coerce asyncpg JSONB return values to a dict."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return json.loads(value)
    try:
        return dict(value)
    except (TypeError, ValueError):
        return {}


def _doc_from_row(row) -> Document:
    """Convert an asyncpg row to a Document, coercing JSONB metadata."""
    return Document(
        id=row["id"],
        source_type=row["source_type"],
        title=row["title"],
        content=row["content"],
        metadata=_coerce_jsonb(row["metadata"]),
        tags=list(row["tags"]) if row["tags"] else [],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.get("", response_model=list[Document])
async def search_documents(
    user: Annotated[AuthUser, Depends(get_current_user)],
    q: str = Query(..., min_length=1, description="Search term"),
    limit: int = Query(default=20, ge=1, le=100, description="Max results"),
) -> list[Document]:
    """
    Full-text search on documents using pg_trgm similarity.

    Searches both title and content using trigram matching.
    Results are ordered by similarity score descending.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        # Use similarity on both title and content
        # Combine scores with COALESCE to handle NULL content
        rows = await conn.fetch(
            """
            SELECT
                id, source_type, title, content, metadata, tags,
                created_at, updated_at,
                greatest(
                    similarity(title, $1),
                    coalesce(similarity(content, $1), 0)
                ) AS sim
            FROM documents
            WHERE
                similarity(title, $1) > 0.1
                OR similarity(content, $1) > 0.1
            ORDER BY sim DESC
            LIMIT $2
            """,
            q,
            limit,
        )
        return [_doc_from_row(row) for row in rows]
