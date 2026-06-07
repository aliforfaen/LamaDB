"""Document CRUD routes."""
import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import AuthUser, get_current_user
from app.db import get_pool
from app.models.documents import (
    Document,
    DocumentCreate,
    DocumentUpdate,
    DocumentLink,
    DocumentLinkCreate,
    DocumentLinkResponse,
)

router = APIRouter(prefix="/api/documents", tags=["documents"])


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


def _doc_from_row(row) -> "Document":
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


@router.post("", response_model=Document, status_code=status.HTTP_201_CREATED)
async def create_document(
    doc: DocumentCreate,
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> Document:
    """Create a new document."""
    if user.role not in ("admin", "agent"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO documents (source_type, title, content, metadata, tags)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, source_type, title, content, metadata, tags, created_at, updated_at
            """,
            doc.source_type,
            doc.title,
            doc.content,
            json.dumps(doc.metadata),
            doc.tags,
        )
        return _doc_from_row(row)


@router.get("", response_model=list[Document])
async def list_documents(
    user: Annotated[AuthUser, Depends(get_current_user)],
    tag: str | None = Query(default=None, description="Filter by tag"),
    source_type: str | None = Query(default=None, description="Filter by source_type"),
    limit: int = Query(default=50, ge=1, le=500, description="Max results"),
    offset: int = Query(default=0, ge=0, description="Skip first N results"),
) -> list[Document]:
    """List documents with optional filters and pagination."""
    pool = get_pool()
    async with pool.acquire() as conn:
        # Build query dynamically
        conditions = []
        params = []
        param_idx = 1

        if tag:
            conditions.append(f"${param_idx} = ANY(tags)")
            params.append(tag)
            param_idx += 1

        if source_type:
            conditions.append(f"source_type = ${param_idx}")
            params.append(source_type)
            param_idx += 1

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        query = f"""
            SELECT id, source_type, title, content, metadata, tags, created_at, updated_at
            FROM documents
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """
        params.extend([limit, offset])

        rows = await conn.fetch(query, *params)
        return [_doc_from_row(row) for row in rows]


@router.get("/{doc_id}", response_model=Document)
async def get_document(
    doc_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> Document:
    """Get a single document by ID."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, source_type, title, content, metadata, tags, created_at, updated_at
            FROM documents
            WHERE id = $1
            """,
            doc_id,
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document {doc_id} not found",
            )
        return _doc_from_row(row)


@router.put("/{doc_id}", response_model=Document)
async def update_document(
    doc_id: UUID,
    doc: DocumentUpdate,
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> Document:
    """Update an existing document."""
    if user.role not in ("admin", "agent"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    pool = get_pool()
    async with pool.acquire() as conn:
        # Build dynamic UPDATE
        updates = []
        params = []
        param_idx = 1

        if doc.source_type is not None:
            updates.append(f"source_type = ${param_idx}")
            params.append(doc.source_type)
            param_idx += 1

        if doc.title is not None:
            updates.append(f"title = ${param_idx}")
            params.append(doc.title)
            param_idx += 1

        if doc.content is not None:
            updates.append(f"content = ${param_idx}")
            params.append(doc.content)
            param_idx += 1

        if doc.metadata is not None:
            updates.append(f"metadata = ${param_idx}")
            params.append(json.dumps(doc.metadata))
            param_idx += 1

        if doc.tags is not None:
            updates.append(f"tags = ${param_idx}")
            params.append(doc.tags)
            param_idx += 1

        if not updates:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields to update",
            )

        updates.append("updated_at = now()")

        params.append(doc_id)
        query = f"""
            UPDATE documents
            SET {', '.join(updates)}
            WHERE id = ${param_idx}
            RETURNING id, source_type, title, content, metadata, tags, created_at, updated_at
        """

        row = await conn.fetchrow(query, *params)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document {doc_id} not found",
            )
        return _doc_from_row(row)


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> None:
    """Delete a document."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required for deletion",
        )

    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM documents WHERE id = $1",
            doc_id,
        )
        if result == "DELETE 0":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document {doc_id} not found",
            )


# --- Document Links ---

@router.post("/{doc_id}/links", response_model=DocumentLink, status_code=status.HTTP_201_CREATED)
async def create_document_link(
    doc_id: UUID,
    link: DocumentLinkCreate,
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> DocumentLink:
    """Create a link from a document to another document."""
    if user.role not in ("admin", "agent"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    pool = get_pool()
    async with pool.acquire() as conn:
        # Verify source and target exist
        source = await conn.fetchrow("SELECT id FROM documents WHERE id = $1", doc_id)
        if source is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source document {doc_id} not found",
            )

        target = await conn.fetchrow("SELECT id FROM documents WHERE id = $1", link.target_id)
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Target document {link.target_id} not found",
            )

        row = await conn.fetchrow(
            """
            INSERT INTO document_links (source_id, target_id, link_type, context)
            VALUES ($1, $2, $3, $4)
            RETURNING id, source_id, target_id, link_type, context, created_at
            """,
            doc_id,
            link.target_id,
            link.link_type,
            link.context,
        )
        return DocumentLink(**dict(row))


@router.get("/{doc_id}/links", response_model=list[DocumentLinkResponse])
async def list_document_links(
    doc_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> list[DocumentLinkResponse]:
    """List all links from a document."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                dl.id, dl.source_id, dl.target_id, dl.link_type, dl.context, dl.created_at,
                d.title as target_title
            FROM document_links dl
            JOIN documents d ON d.id = dl.target_id
            WHERE dl.source_id = $1
            ORDER BY dl.created_at DESC
            """,
            doc_id,
        )
        return [DocumentLinkResponse(**dict(row)) for row in rows]
