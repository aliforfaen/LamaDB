"""Core MCP tools — document and event operations for AI agents."""
import json
import logging
import asyncio

from app.db import get_pool

logger = logging.getLogger(__name__)


async def search_documents(q: str, limit: int = 10) -> dict:
    """Full-text + semantic search across documents.

    Uses pg_trgm for text matching. Returns matching documents with scores.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                id, source_type, title, content, metadata, tags,
                created_at, updated_at,
                similarity(title, $1) AS title_sim,
                similarity(content, $1) AS content_sim
            FROM documents
            WHERE title % $1 OR content % $1
            ORDER BY (similarity(title, $1) + similarity(content, $1)) DESC
            LIMIT $2
            """,
            q,
            limit,
        )

    results = []
    for row in rows:
        meta = row["metadata"]
        if meta is not None and not isinstance(meta, dict):
            if isinstance(meta, str):
                meta = json.loads(meta)
            else:
                meta = dict(meta) if meta else {}
        elif meta is None:
            meta = {}

        results.append({
            "id": str(row["id"]),
            "source_type": row["source_type"],
            "title": row["title"],
            "content": (row["content"] or "")[:500],
            "tags": list(row["tags"]) if row["tags"] else [],
            "score": round(float(row["title_sim"]) + float(row["content_sim"]), 4),
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        })

    return {"results": results, "count": len(results), "query": q}


async def get_document(id: str) -> dict:
    """Get a single document by ID with its links."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, source_type, title, content, metadata, tags, created_at, updated_at
            FROM documents
            WHERE id = $1
            """,
            id,
        )
        if row is None:
            return {"error": f"Document {id} not found"}

        meta = row["metadata"]
        if meta is not None and not isinstance(meta, dict):
            if isinstance(meta, str):
                meta = json.loads(meta)
            else:
                meta = dict(meta) if meta else {}
        elif meta is None:
            meta = {}

        # Fetch outgoing links
        links_rows = await conn.fetch(
            """
            SELECT dl.id, dl.target_id, dl.link_type, dl.context, dl.created_at,
                   d.title AS target_title
            FROM document_links dl
            JOIN documents d ON d.id = dl.target_id
            WHERE dl.source_id = $1
            ORDER BY dl.created_at DESC
            """,
            id,
        )
        links = []
        for lr in links_rows:
            links.append({
                "id": lr["id"],
                "target_id": str(lr["target_id"]),
                "target_title": lr["target_title"],
                "link_type": lr["link_type"],
                "context": lr["context"],
                "created_at": lr["created_at"].isoformat() if lr["created_at"] else None,
            })

        return {
            "id": str(row["id"]),
            "source_type": row["source_type"],
            "title": row["title"],
            "content": row["content"],
            "metadata": meta,
            "tags": list(row["tags"]) if row["tags"] else [],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            "links": links,
        }


async def create_document(title: str, source_type: str, content: str = "",
                          tags: list[str] = None, metadata: dict = None) -> dict:
    """Create a new document."""
    from app.embeddings import embed_document_async

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO documents (source_type, title, content, metadata, tags)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, source_type, title, content, metadata, tags, created_at, updated_at
            """,
            source_type,
            title,
            content,
            json.dumps(metadata or {}),
            tags or [],
        )
        # Fire-and-forget embedding
        asyncio.create_task(embed_document_async(str(row["id"]), title, content))

    meta = row["metadata"]
    if meta is not None and not isinstance(meta, dict):
        if isinstance(meta, str):
            meta = json.loads(meta)
        else:
            meta = dict(meta) if meta else {}
    elif meta is None:
        meta = {}

    return {
        "id": str(row["id"]),
        "source_type": row["source_type"],
        "title": row["title"],
        "content": row["content"],
        "tags": list(row["tags"]) if row["tags"] else [],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


async def update_document(id: str, title: str = None, content: str = None,
                          tags: list[str] = None, metadata: dict = None,
                          source_type: str = None) -> dict:
    """Update an existing document. Only provided fields are changed."""
    from app.embeddings import embed_document_async

    pool = get_pool()
    updates = []
    params = []
    param_idx = 1

    if source_type is not None:
        updates.append(f"source_type = ${param_idx}")
        params.append(source_type)
        param_idx += 1

    if title is not None:
        updates.append(f"title = ${param_idx}")
        params.append(title)
        param_idx += 1

    if content is not None:
        updates.append(f"content = ${param_idx}")
        params.append(content)
        param_idx += 1

    if metadata is not None:
        updates.append(f"metadata = ${param_idx}")
        params.append(json.dumps(metadata))
        param_idx += 1

    if tags is not None:
        updates.append(f"tags = ${param_idx}")
        params.append(tags)
        param_idx += 1

    if not updates:
        return {"error": "No fields to update"}

    updates.append("updated_at = now()")
    params.append(id)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE documents
            SET {', '.join(updates)}
            WHERE id = ${param_idx}
            RETURNING id, source_type, title, content, metadata, tags, created_at, updated_at
            """,
            *params,
        )
        if row is None:
            return {"error": f"Document {id} not found"}

        # Re-embed if title or content changed
        if title is not None or content is not None:
            asyncio.create_task(embed_document_async(str(row["id"]), row["title"], row["content"]))

    meta = row["metadata"]
    if meta is not None and not isinstance(meta, dict):
        if isinstance(meta, str):
            meta = json.loads(meta)
        else:
            meta = dict(meta) if meta else {}
    elif meta is None:
        meta = {}

    return {
        "id": str(row["id"]),
        "source_type": row["source_type"],
        "title": row["title"],
        "content": row["content"],
        "tags": list(row["tags"]) if row["tags"] else [],
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


async def create_event(source: str, event_type: str, title: str, severity: str = "info",
                       body: str = "", metadata: dict = None, tags: list[str] = None) -> dict:
    """Create a new event."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO events (source, type, severity, title, body, metadata, tags)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id, ts, source, type, severity, title, body, metadata, tags
            """,
            source,
            event_type,
            severity,
            title,
            body,
            json.dumps(metadata or {}),
            tags or [],
        )

    meta = row["metadata"]
    if meta is not None and not isinstance(meta, dict):
        if isinstance(meta, str):
            meta = json.loads(meta)
        else:
            meta = dict(meta) if meta else {}
    elif meta is None:
        meta = {}

    return {
        "id": row["id"],
        "ts": row["ts"].isoformat() if row["ts"] else None,
        "source": row["source"],
        "type": row["type"],
        "severity": row["severity"],
        "title": row["title"],
        "body": row["body"],
        "tags": list(row["tags"]) if row["tags"] else [],
    }


async def get_events(source: str = None, event_type: str = None, severity: str = None,
                     limit: int = 50) -> dict:
    """Get events with optional filters."""
    pool = get_pool()
    async with pool.acquire() as conn:
        conditions = []
        params = []
        param_idx = 1

        if source is not None:
            conditions.append(f"source = ${param_idx}")
            params.append(source)
            param_idx += 1

        if event_type is not None:
            conditions.append(f"type = ${param_idx}")
            params.append(event_type)
            param_idx += 1

        if severity is not None:
            conditions.append(f"severity = ${param_idx}")
            params.append(severity)
            param_idx += 1

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        query = f"""
            SELECT id, ts, source, type, severity, title, body, metadata, tags
            FROM events
            {where_clause}
            ORDER BY ts DESC
            LIMIT ${param_idx}
        """
        params.append(limit)

        rows = await conn.fetch(query, *params)

    events = []
    for row in rows:
        meta = row["metadata"]
        if meta is not None and not isinstance(meta, dict):
            if isinstance(meta, str):
                meta = json.loads(meta)
            else:
                meta = dict(meta) if meta else {}
        elif meta is None:
            meta = {}

        events.append({
            "id": row["id"],
            "ts": row["ts"].isoformat() if row["ts"] else None,
            "source": row["source"],
            "type": row["type"],
            "severity": row["severity"],
            "title": row["title"],
            "body": row["body"],
            "tags": list(row["tags"]) if row["tags"] else [],
        })

    return {"events": events, "count": len(events)}


async def lamadb_docs(topic: str = "api") -> dict:
    """Read LamaDB documentation. Use topic='api' for the full agent API reference."""
    from pathlib import Path

    docs = {
        "api": Path(__file__).parent.parent.parent / "AGENTS_API.md",
    }

    path = docs.get(topic)
    if not path or not path.exists():
        return {"error": f"Documentation topic '{topic}' not found", "available": list(docs.keys())}

    content = await asyncio.to_thread(path.read_text)
    return {"topic": topic, "content": content}
