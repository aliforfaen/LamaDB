"""Audiobookshelf poller — libraries, books, and listening progress."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings
from app.db import get_pool

logger = logging.getLogger(__name__)

ABS_API_PREFIX = "/api"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.audiobookshelf_token}"}


def _abs_url(path: str) -> str:
    base = (settings.audiobookshelf_url or "").rstrip("/")
    return f"{base}{ABS_API_PREFIX}{path}"


async def _fetch_libraries(client: httpx.AsyncClient) -> list[dict]:
    """List all libraries visible to the configured user."""
    resp = await client.get(_abs_url("/libraries"), headers=_headers())
    resp.raise_for_status()
    data = resp.json()
    libs = data.get("libraries") or []
    out = []
    for lib in libs:
        media_type = lib.get("mediaType", "book")
        out.append({
            "id": lib.get("id"),
            "name": lib.get("name"),
            "media_type": media_type,
            "icon": lib.get("icon"),
            "item_count": int(lib.get("bookCount") or lib.get("podcastCount") or 0),
        })
    return out


async def _fetch_recent_items(
    client: httpx.AsyncClient,
    library_id: str,
    limit: int,
) -> list[dict]:
    """Fetch the most recent items in a library, sorted by addedAt desc."""
    params = {
        "limit": min(limit, 100),
        "page": 0,
        "sort": "addedAt",
        "order": "desc",
        "minified": 0,
        "include": "progress",
    }
    resp = await client.get(
        _abs_url(f"/libraries/{library_id}/items"),
        params=params,
        headers=_headers(),
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("results") or []


def _book_from_item(item: dict, library: dict) -> dict | None:
    """Normalize an ABS library item into the dict we store on a document."""
    media = item.get("media") or {}
    metadata = media.get("metadata") or {}
    if not media:
        return None

    item_id = item.get("id") or media.get("id")
    if not item_id:
        return None

    progress = item.get("progress") or {}
    is_finished = bool(progress.get("isFinished"))
    progress_pct = progress.get("progress")
    try:
        progress_pct = float(progress_pct) if progress_pct is not None else None
    except (TypeError, ValueError):
        progress_pct = None

    tracks = media.get("tracks") or []
    chapters = media.get("chapters") or []
    duration = media.get("duration")
    try:
        duration = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration = None

    added_at = item.get("addedAt") or item.get("added_at")
    updated_at = item.get("updatedAt") or item.get("updated_at")
    added_iso = _iso_or_none(added_at)
    updated_iso = _iso_or_none(updated_at)

    return {
        "item_id": str(item_id),
        "library_id": library.get("id"),
        "library_name": library.get("name"),
        "title": metadata.get("title") or "Untitled",
        "author": metadata.get("authorName"),
        "narrator": metadata.get("narratorName"),
        "description": metadata.get("description"),
        "isbn": metadata.get("isbn"),
        "language": metadata.get("language"),
        "published_year": metadata.get("publishedYear"),
        "genres": list(metadata.get("genres") or []),
        "series": _series_names(metadata.get("series")),
        "duration": duration,
        "track_count": len(tracks) if tracks else len(chapters),
        "added_at": added_iso,
        "updated_at": updated_iso,
        "progress_percent": progress_pct,
        "is_finished": is_finished,
        "num_tracks": len(tracks),
        "num_chapters": len(chapters),
        "media_id": media.get("id"),
        "path": item.get("path"),
    }


def _series_names(series: Any) -> list[str]:
    """ABS returns series as a list of dicts with a `name` field; flatten."""
    if not series:
        return []
    if isinstance(series, list):
        return [s.get("name") for s in series if isinstance(s, dict) and s.get("name")]
    if isinstance(series, str):
        return [series]
    return []


def _iso_or_none(value: Any) -> str | None:
    """Convert a millisecond epoch timestamp to ISO string, or pass through."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            return None
    if isinstance(value, str):
        return value
    return None


async def _upsert_books(books: list[dict]) -> dict:
    """Upsert books into the documents table, keyed by item_id."""
    if not books:
        return {"inserted": 0, "updated": 0, "skipped": 0}

    pool = get_pool()
    inserted = 0
    updated = 0
    skipped = 0

    async with pool.acquire() as conn:
        for book in books:
            item_id = book.get("item_id")
            if not item_id:
                skipped += 1
                continue

            title = book.get("title") or "Untitled"
            description = book.get("description") or ""
            tags = ["audiobookshelf", book.get("media_type", "book")]
            library_name = book.get("library_name")
            if library_name:
                tags.append(f"library:{library_name}")
            if book.get("is_finished"):
                tags.append("finished")
            elif (book.get("progress_percent") or 0) > 0:
                tags.append("in_progress")

            try:
                row = await conn.fetchrow(
                    """
                    INSERT INTO documents (source_type, title, content, metadata, tags)
                    VALUES ($1, $2, $3, $4::jsonb, $5)
                    ON CONFLICT (source_type, (metadata ->> 'item_id'))
                    WHERE source_type = 'audiobookshelf'
                    DO UPDATE SET
                        title = EXCLUDED.title,
                        content = EXCLUDED.content,
                        metadata = EXCLUDED.metadata,
                        tags = EXCLUDED.tags,
                        updated_at = now()
                    RETURNING (xmax = 0) AS inserted
                    """,
                    "audiobookshelf",
                    title,
                    description,
                    json.dumps(book),
                    tags,
                )
            except Exception as e:
                logger.warning(f"Audiobookshelf upsert failed for {item_id}: {e}")
                skipped += 1
                continue

            if row and row["inserted"]:
                inserted += 1
            else:
                updated += 1

    return {"inserted": inserted, "updated": updated, "skipped": skipped}


def _summarise(books: list[dict]) -> dict:
    """Build the per-poll summary stored on the abs_snapshot event."""
    finished = sum(1 for b in books if b.get("is_finished"))
    in_progress = sum(
        1 for b in books
        if not b.get("is_finished") and (b.get("progress_percent") or 0) > 0
    )
    return {
        "book_count": len(books),
        "finished_count": finished,
        "in_progress_count": in_progress,
    }


async def collect() -> dict:
    """Poll Audiobookshelf: fetch libraries + recent items, upsert as documents,
    and emit an abs_snapshot event with the summary."""
    if not settings.audiobookshelf_url or not settings.audiobookshelf_token:
        return {"error": "Audiobookshelf URL or token not configured"}

    per_library_limit = int(
        getattr(settings, "audiobookshelf_max_books_per_library", 50) or 50
    )

    libraries: list[dict] = []
    all_books: list[dict] = []
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            libraries = await _fetch_libraries(client)
        except Exception as e:
            logger.warning(f"Audiobookshelf libraries fetch failed: {e}")
            return {"error": f"libraries fetch failed: {e}"}

        for library in libraries:
            if library.get("media_type") != "book":
                continue
            try:
                items = await _fetch_recent_items(
                    client, library["id"], per_library_limit
                )
            except Exception as e:
                logger.warning(
                    f"Audiobookshelf items fetch failed for {library.get('id')}: {e}"
                )
                errors.append(f"{library.get('name')}: {e}")
                continue

            for item in items:
                book = _book_from_item(item, library)
                if book:
                    all_books.append(book)

    upsert_stats = await _upsert_books(all_books)
    summary = _summarise(all_books)

    snapshot = {
        "libraries": libraries,
        **summary,
        "recently_added": all_books[:10],
        "upsert": upsert_stats,
        "errors": errors,
        "ts": _now_iso(),
    }

    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO events (source, type, severity, title, body, metadata, ticker, tags)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
            "audiobookshelf",
            "abs_snapshot",
            "info",
            (
                f"Audiobookshelf: {summary['book_count']} books across "
                f"{len(libraries)} libraries "
                f"({summary['finished_count']} finished, "
                f"{summary['in_progress_count']} in progress)"
            ),
            json.dumps(snapshot),
            json.dumps(snapshot),
            False,
            ["audiobookshelf", "snapshot"],
        )

    return snapshot