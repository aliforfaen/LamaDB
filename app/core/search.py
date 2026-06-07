"""Full-text search routes using pg_trgm similarity."""
import hashlib
from uuid import UUID
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


def _text_to_pseudo_embedding(text: str, dims: int = 1536) -> list[float]:
    """Generate a deterministic pseudo-embedding from text using hash expansion.
    This is a placeholder until a real embedding model is connected.
    Uses SHA-256 hash of the text, expanded to `dims` dimensions, L2-normalized.
    Same input always produces the same vector.
    """
    h = hashlib.sha256(text.encode()).digest()
    vals = []
    for i in range(dims):
        seed = (h[i % 32] * 31 + i) % 256
        vals.append((seed / 128.0) - 1.0)
    norm = sum(v * v for v in vals) ** 0.5
    if norm > 0:
        vals = [v / norm for v in vals]
    return vals

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


@router.get("/semantic", response_model=list[Document])
async def search_semantic(
    user: Annotated[AuthUser, Depends(get_current_user)],
    q: str = Query(..., min_length=1, description="Search term"),
    limit: int = Query(default=10, ge=1, le=50, description="Max results"),
) -> list[Document]:
    """
    Semantic search on documents using pgvector cosine similarity.

    Generates a pseudo-embedding from the query text (deterministic hash-based)
    and ranks documents with stored embeddings by cosine similarity.
    Falls back to returning empty results when no embeddings exist yet.

    This is a placeholder until a real embedding model is connected.
    """
    pool = get_pool()
    embedding = _text_to_pseudo_embedding(q)
    # Format as pgvector literal string: '[a,b,c,...]'
    embedding_str = f"[{','.join(str(v) for v in embedding)}]"
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                id, source_type, title, content, metadata, tags,
                created_at, updated_at,
                1 - (embedding <=> $1::vector) AS sim
            FROM documents
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> $1::vector
            LIMIT $2
            """,
            embedding_str,
            limit,
        )
        return [_doc_from_row(row) for row in rows]
