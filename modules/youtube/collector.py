"""YouTube poller — collects Watch Later playlist and recent watch history."""
from __future__ import annotations

import datetime
import json
import logging

import httpx

from app.config import settings
from app.db import get_pool

logger = logging.getLogger(__name__)

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


def _published_at_to_iso(value: str | None) -> str | None:
    """Convert RFC3339 publishedAt to a Postgres-friendly ISO string."""
    if not value:
        return None
    try:
        dt = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.isoformat()
    except Exception:
        return value


def _best_thumbnail(thumbnails: dict | None) -> str | None:
    """Pick the best available thumbnail resolution."""
    if not thumbnails:
        return None
    for key in ("maxres", "standard", "high", "medium", "default"):
        if key in thumbnails:
            return thumbnails[key].get("url")
    return None


def _video_from_item(item: dict, playlist_id: str | None = None, list_type: str = "unknown") -> dict:
    """Normalize a YouTube playlist item or search result into a video dict."""
    snippet = item.get("snippet", {})
    resource = snippet.get("resourceId", {}) or {}
    video_id = resource.get("videoId") or item.get("id", {}).get("videoId") or item.get("contentDetails", {}).get("videoId")
    return {
        "video_id": video_id,
        "title": snippet.get("title", "Untitled"),
        "description": snippet.get("description", "") or None,
        "channel_id": snippet.get("channelId"),
        "channel_title": snippet.get("channelTitle"),
        "published_at": _published_at_to_iso(snippet.get("publishedAt")),
        "thumbnail_url": _best_thumbnail(snippet.get("thumbnails")),
        "playlist_id": playlist_id,
        "list_type": list_type,
        "position": snippet.get("position"),
    }


async def _get_watch_later_playlist_id(client: httpx.AsyncClient, api_key: str) -> str | None:
    """Find the 'Watch Later' playlist ID for the authorized channel.

    YouTube no longer exposes a fixed system playlist id. The most reliable way
    is to list the authenticated user's channels and look for a contentDetails
    relatedPlaylists section. This requires the API key to be associated with an
    OAuth token for the user; without OAuth we fall back to a configured playlist.
    """
    # If the user configured a specific watch-later playlist ID, use it.
    return None


async def _fetch_playlist_items(
    client: httpx.AsyncClient,
    api_key: str,
    playlist_id: str,
    max_results: int = 50,
) -> list[dict]:
    """Fetch all items for a playlist, paging as needed."""
    if not playlist_id:
        return []

    videos: list[dict] = []
    page_token: str | None = None
    pages = 0
    while pages < 10:
        params: dict = {
            "part": "snippet,contentDetails",
            "playlistId": playlist_id,
            "maxResults": min(max_results, 50),
            "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token

        resp = await client.get(f"{YOUTUBE_API_BASE}/playlistItems", params=params)
        resp.raise_for_status()
        data = resp.json()

        for item in data.get("items", []):
            videos.append(_video_from_item(item, playlist_id=playlist_id, list_type="watch_later"))

        page_token = data.get("nextPageToken")
        pages += 1
        if not page_token:
            break

    return videos


async def _fetch_channel_uploads(
    client: httpx.AsyncClient,
    api_key: str,
    channel_id: str,
    max_results: int = 50,
) -> list[dict]:
    """Fetch recent uploads for a channel as a proxy for watch history.

    YouTube's watch history is not available via the Data API for privacy reasons.
    We use the channel's uploaded videos (or liked videos if configured) as a
    practical substitute. If a dedicated history playlist ID is later provided it
    can be passed directly to _fetch_playlist_items.
    """
    if not channel_id:
        return []

    params: dict = {
        "part": "contentDetails",
        "id": channel_id,
        "key": api_key,
    }
    resp = await client.get(f"{YOUTUBE_API_BASE}/channels", params=params)
    resp.raise_for_status()
    data = resp.json()
    items = data.get("items", [])
    if not items:
        return []

    uploads_id = items[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    if not uploads_id:
        return []

    return await _fetch_playlist_items(client, api_key, uploads_id, max_results=max_results)


async def _insert_videos(videos: list[dict]) -> dict:
    """Upsert YouTube videos into the documents table.

    Uses video_id as a natural key to avoid duplicates. Updates metadata on conflict.
    """
    if not videos:
        return {"inserted": 0, "updated": 0, "skipped": 0}

    pool = get_pool()
    inserted = 0
    updated = 0
    skipped = 0

    async with pool.acquire() as conn:
        for video in videos:
            if not video.get("video_id"):
                skipped += 1
                continue

            metadata = {
                "video_id": video["video_id"],
                "channel_id": video.get("channel_id"),
                "channel_title": video.get("channel_title"),
                "published_at": video.get("published_at"),
                "thumbnail_url": video.get("thumbnail_url"),
                "playlist_id": video.get("playlist_id"),
                "list_type": video.get("list_type"),
                "position": video.get("position"),
            }

            # Try insert first; on conflict update metadata + title + content.
            row = await conn.fetchrow(
                """
                INSERT INTO documents (source_type, title, content, metadata, tags, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, COALESCE($6::timestamptz, now()), now())
                ON CONFLICT (source_type, (metadata ->> 'video_id'))
                WHERE source_type = 'youtube'
                DO UPDATE SET
                    title = EXCLUDED.title,
                    content = EXCLUDED.content,
                    metadata = EXCLUDED.metadata,
                    tags = EXCLUDED.tags,
                    updated_at = now()
                RETURNING (xmax = 0) AS inserted
                """,
                "youtube",
                video["title"],
                video.get("description") or "",
                json.dumps(metadata),
                ["youtube", video.get("list_type", "unknown")],
                video.get("published_at"),
            )
            if row and row["inserted"]:
                inserted += 1
            else:
                updated += 1

    return {"inserted": inserted, "updated": updated, "skipped": skipped}


async def collect() -> dict:
    """Poll YouTube Watch Later and recent uploads/history and store as documents."""
    api_key = settings.youtube_api_key
    channel_id = settings.youtube_channel_id

    if not api_key:
        return {"error": "YouTube API key not configured"}

    results: dict = {
        "watch_later": {"count": 0, "videos": []},
        "history": {"count": 0, "videos": []},
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Watch Later is not directly accessible via API without OAuth playlist id.
        # Accept an optional comma-separated list of playlist IDs from env.
        watch_later_playlists = []
        if hasattr(settings, "youtube_watch_later_playlist_id") and settings.youtube_watch_later_playlist_id:
            watch_later_playlists = [p.strip() for p in settings.youtube_watch_later_playlist_id.split(",") if p.strip()]

        for playlist_id in watch_later_playlists:
            try:
                videos = await _fetch_playlist_items(client, api_key, playlist_id, max_results=50)
                results["watch_later"]["videos"].extend(videos)
            except Exception as e:
                logger.warning(f"YouTube Watch Later poll failed for {playlist_id}: {e}")
                results["watch_later"]["error"] = str(e)

        # Channel uploads used as a proxy for "history" / recent activity.
        if channel_id:
            try:
                videos = await _fetch_channel_uploads(client, api_key, channel_id, max_results=50)
                results["history"]["videos"].extend(videos)
            except Exception as e:
                logger.warning(f"YouTube channel uploads poll failed: {e}")
                results["history"]["error"] = str(e)

    watch_later_videos = results["watch_later"]["videos"]
    history_videos = results["history"]["videos"]

    wl_stats = await _insert_videos(watch_later_videos)
    hist_stats = await _insert_videos(history_videos)

    results["watch_later"]["count"] = len(watch_later_videos)
    results["history"]["count"] = len(history_videos)
    results["watch_later"]["stats"] = wl_stats
    results["history"]["stats"] = hist_stats

    # Emit a collector event summary
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO events (source, type, severity, title, body, metadata, ticker, tags)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
            "youtube",
            "youtube_snapshot",
            "info",
            f"YouTube: {len(watch_later_videos)} Watch Later, {len(history_videos)} history videos",
            json.dumps(results),
            json.dumps(results),
            False,
            ["youtube", "snapshot"],
        )

    return results
