"""Wiki module routes — scratchpad, wiki reader, wiki editor, and edit log."""
import json
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import AuthUser, get_current_user
from app.db import get_pool
from app.config import settings

from .models import (
    ScratchpadEntry,
    ScratchpadCreate,
    WikiPage,
    WikiPageContent,
    WikiLogEntry,
    SearchResult,
    WikiPageCreate,
    WikiPageUpdate,
)
from .scratchpad import create_scratchpad_entry, list_scratchpad_entries
from .wiki_reader import (
    list_pages as fs_list_pages,
    read_page as fs_read_page,
    parse_index,
    search_wiki as fs_search_wiki,
)
from .wiki_db import (
    create_page,
    get_page,
    get_page_by_path,
    update_page,
    delete_page,
    list_pages as db_list_pages,
    search_pages,
    sync_wikilinks,
)

router = APIRouter(tags=["wiki"])


# ─────────────────────────────────────────────────────────────────────────────
# SCRATCHPAD
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/scratchpad", response_model=ScratchpadEntry, status_code=status.HTTP_201_CREATED)
async def save_scratchpad(
    entry: ScratchpadCreate,
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> ScratchpadEntry:
    """
    Save a new scratchpad entry to the documents table.

    Creates a document with source_type='scratchpad' and source='wiki'.
    """
    if user.role not in ("admin", "agent"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    doc = await create_scratchpad_entry(content=entry.content, title=entry.title)

    # Write a wiki event for the scratchpad creation
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO events (source, type, severity, title, body, metadata, ticker, tags)
            VALUES ('wiki', 'scratchpad_created', 'info', $1, $2, $3, false, $4)
            """,
            f"Scratchpad: {entry.title}",
            entry.content[:200] if entry.content else "",
            json.dumps({"doc_id": doc["id"], "source": "scratchpad"}),
            ["wiki", "scratchpad"],
        )

    return ScratchpadEntry(
        id=doc["id"],
        content=doc["content"],
        created_at=doc["created_at"],
    )


@router.get("/scratchpad", response_model=list[ScratchpadEntry])
async def get_scratchpad_entries(
    user: Annotated[AuthUser, Depends(get_current_user)],
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[ScratchpadEntry]:
    """List recent scratchpad entries from the documents table."""
    docs = await list_scratchpad_entries(limit=limit, offset=offset)
    return [
        ScratchpadEntry(id=d["id"], content=d["content"], created_at=d["created_at"])
        for d in docs
    ]


# ─────────────────────────────────────────────────────────────────────────────
# WIKI PAGES — DB-backed CRUD
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/pages", status_code=status.HTTP_201_CREATED)
async def create_wiki_page(
    page: WikiPageCreate,
    user: Annotated[AuthUser, Depends(get_current_user)],
):
    """Create a new wiki page in the database."""
    if user.role not in ("admin", "agent"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    # Check for duplicate path
    existing = await get_page_by_path(page.path)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A page with path '{page.path}' already exists",
        )

    result = await create_page(
        title=page.title,
        content=page.content,
        path=page.path,
        tags=list(page.tags) if page.tags else [],
    )

    # Sync wikilinks
    await sync_wikilinks(result["id"], page.content)

    # Log event
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO events (source, type, severity, title, body, ticker, tags)
               VALUES ('wiki', 'page_created', 'info', $1, $2, false, $3)""",
            f"Page created: {page.title}",
            f"Path: {page.path}",
            ["wiki"],
        )

    return result


@router.get("/pages", response_model=list[WikiPage])
async def get_wiki_pages(
    user: Annotated[AuthUser, Depends(get_current_user)],
    sort: str = Query(default="updated_at", description="Sort field: updated_at, created_at, title"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List wiki pages from the database."""
    pages = await db_list_pages(sort=sort, limit=limit, offset=offset)
    return [WikiPage(**p) for p in pages]


@router.get("/pages/search", response_model=list[WikiPage])
async def search_wiki_pages_db(
    user: Annotated[AuthUser, Depends(get_current_user)],
    q: str = Query(..., min_length=1, description="Search term"),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Search wiki pages by title/content using pg_trgm similarity."""
    results = await search_pages(query=q, limit=limit)
    return [WikiPage(**r) for r in results]


@router.get("/pages/by-path")
async def get_wiki_page_by_path(
    user: Annotated[AuthUser, Depends(get_current_user)],
    path: str = Query(..., description="Filesystem path, e.g. 'entities/foo.md'"),
):
    """Get a wiki page by its filesystem path."""
    page = await get_page_by_path(path)
    if not page:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wiki page with path '{path}' not found",
        )
    return page


@router.get("/pages/{page_id}")
async def get_wiki_page_by_id(
    page_id: str,
    user: Annotated[AuthUser, Depends(get_current_user)],
):
    """Get a wiki page by its ID."""
    page = await get_page(page_id)
    if not page:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wiki page '{page_id}' not found",
        )
    return page


@router.patch("/pages/{page_id}")
async def update_wiki_page(
    page_id: str,
    update: WikiPageUpdate,
    user: Annotated[AuthUser, Depends(get_current_user)],
):
    """Update a wiki page (title, content, and/or tags)."""
    if user.role not in ("admin", "agent"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await update_page(
        page_id,
        title=update.title,
        content=update.content,
        tags=update.tags,
    )
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wiki page '{page_id}' not found",
        )

    # Sync wikilinks if content changed
    if update.content is not None:
        await sync_wikilinks(page_id, update.content)

    # Log event
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO events (source, type, severity, title, body, ticker, tags)
               VALUES ('wiki', 'page_updated', 'info', $1, $2, false, $3)""",
            f"Page updated: {result['title']}",
            f"Path: {result['path']}",
            ["wiki"],
        )

    return result


@router.delete("/pages/{page_id}")
async def delete_wiki_page(
    page_id: str,
    user: Annotated[AuthUser, Depends(get_current_user)],
):
    """Delete a wiki page."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    # Get page info before deleting for the event log
    page = await get_page(page_id)
    if not page:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wiki page '{page_id}' not found",
        )

    deleted = await delete_page(page_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wiki page '{page_id}' not found",
        )

    # Log event
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO events (source, type, severity, title, body, ticker, tags)
               VALUES ('wiki', 'page_deleted', 'info', $1, $2, false, $3)""",
            f"Page deleted: {page['title']}",
            f"Path: {page['path']}",
            ["wiki"],
        )

    return {"ok": True, "deleted": page_id}


# ─────────────────────────────────────────────────────────────────────────────
# WIKI PAGES — Filesystem fallback (source=fs query param)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/page/{path:path}")
async def get_wiki_page(
    path: str,
    user: Annotated[AuthUser, Depends(get_current_user)],
    source: str = Query(default="db", description="Source: 'db' (default) or 'fs' (filesystem)"),
):
    """Read a wiki page.

    path is relative to wiki root (e.g. "entities/homelab-services.md").
    Default source is 'db' — falls back to filesystem if page not found in DB.
    """
    if source == "db":
        page = await get_page_by_path(path)
        if page:
            return page
        # Fall through to filesystem if not found in DB

    # Filesystem fallback
    wiki_path = settings.wiki_path
    page = fs_read_page(wiki_path, path)
    if page is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wiki page '{path}' not found",
        )
    return page


@router.get("/pages-fs", response_model=list[WikiPage])
async def get_wiki_pages_fs(
    user: Annotated[AuthUser, Depends(get_current_user)],
):
    """List all wiki pages by scanning the filesystem (legacy endpoint)."""
    wiki_path = settings.wiki_path
    pages = fs_list_pages(wiki_path)
    return [WikiPage(**p) for p in pages]


@router.get("/search-fs", response_model=list[SearchResult])
async def search_wiki_pages_fs(
    user: Annotated[AuthUser, Depends(get_current_user)],
    q: str = Query(..., min_length=1, description="Search term"),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[SearchResult]:
    """Search wiki content by scanning .md files for the query term (legacy endpoint)."""
    wiki_path = settings.wiki_path
    results = fs_search_wiki(wiki_path, q, limit=limit)
    return [SearchResult(**r) for r in results]


# ─────────────────────────────────────────────────────────────────────────────
# EDIT LOG (WIKI ACTIVITY)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/log", response_model=list[WikiLogEntry])
async def get_wiki_log(
    user: Annotated[AuthUser, Depends(get_current_user)],
    limit: int = Query(default=50, ge=1, le=200),
    source: str | None = Query(default=None, description="Filter by source: wiki or scratchpad"),
) -> list[WikiLogEntry]:
    """
    Recent wiki/scratchpad activity from the events table.

    Shows events where source='wiki' or source='scratchpad'.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        if source:
            rows = await conn.fetch(
                """
                SELECT id, ts, source, type, severity, title, body, metadata
                FROM events
                WHERE source = $1
                ORDER BY ts DESC
                LIMIT $2
                """,
                source,
                limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, ts, source, type, severity, title, body, metadata
                FROM events
                WHERE source IN ('wiki', 'scratchpad')
                ORDER BY ts DESC
                LIMIT $1
                """,
                limit,
            )

        entries = []
        for row in rows:
            meta = row["metadata"]
            if meta is not None and not isinstance(meta, dict):
                if isinstance(meta, str):
                    meta = json.loads(meta)
                else:
                    meta = dict(meta) if meta else {}

            entries.append(WikiLogEntry(
                id=row["id"],
                ts=row["ts"],
                source=row["source"],
                title=row["title"],
                severity=row["severity"],
                body=row["body"],
            ))
        return entries
