"""Notflix media poller — collects data from Sonarr, Radarr, Tautulli."""
import json

import httpx

from app.config import settings
from app.db import get_pool


async def _poll_sonarr(client: httpx.AsyncClient) -> dict:
    """Fetch Sonarr library stats."""
    if not settings.sonarr_url or not settings.sonarr_api_key:
        return {"error": "Sonarr not configured"}

    headers = {"X-Api-Key": settings.sonarr_api_key}

    # Series count
    series_resp = await client.get(
        f"{settings.sonarr_url}/api/v3/series",
        headers=headers,
    )
    series_resp.raise_for_status()
    series = series_resp.json()
    series_count = len(series)

    # Episode stats — limit to first 50 series to avoid 5000+ API calls
    episodes = []
    for s in series[:50]:
        ep_resp = await client.get(
            f"{settings.sonarr_url}/api/v3/episode?seriesId={s['id']}",
            headers=headers,
        )
        ep_resp.raise_for_status()
        episodes.extend(ep_resp.json())

    total_episodes = len(episodes)
    episodes_with_file = sum(1 for ep in episodes if ep.get("hasFile"))

    # Missing episodes (use totalRecords, no need to fetch all)
    missing_resp = await client.get(
        f"{settings.sonarr_url}/api/v3/wanted/missing?page=1&pageSize=1",
        headers=headers,
    )
    missing_resp.raise_for_status()
    missing_count = missing_resp.json().get("totalRecords", 0)

    # Queue
    queue_resp = await client.get(
        f"{settings.sonarr_url}/api/v3/queue?page=1&pageSize=1",
        headers=headers,
    )
    queue_resp.raise_for_status()
    queue_count = queue_resp.json().get("totalRecords", 0)

    # Recent grabs (last 24h)
    history_resp = await client.get(
        f"{settings.sonarr_url}/api/v3/history?page=1&pageSize=20",
        headers=headers,
    )
    history_resp.raise_for_status()
    recent = history_resp.json().get("records", [])

    return {
        "series_count": series_count,
        "total_episodes": total_episodes,
        "episodes_available": episodes_with_file,
        "missing_count": missing_count,
        "queue_count": queue_count,
        "recent_grabs": len([r for r in recent if r.get("eventType") == "grabbed"]),
    }


async def _poll_radarr(client: httpx.AsyncClient) -> dict:
    """Fetch Radarr library stats."""
    if not settings.radarr_url or not settings.radarr_api_key:
        return {"error": "Radarr not configured"}

    headers = {"X-Api-Key": settings.radarr_api_key}

    # Movie count
    movies_resp = await client.get(
        f"{settings.radarr_url}/api/v3/movie",
        headers=headers,
    )
    movies_resp.raise_for_status()
    movies = movies_resp.json()
    movie_count = len(movies)
    movies_available = sum(1 for m in movies if m.get("hasFile"))

    # Missing (use totalRecords)
    missing_resp = await client.get(
        f"{settings.radarr_url}/api/v3/wanted/missing?page=1&pageSize=1",
        headers=headers,
    )
    missing_resp.raise_for_status()
    missing_count = missing_resp.json().get("totalRecords", 0)

    # Queue
    queue_resp = await client.get(
        f"{settings.radarr_url}/api/v3/queue?page=1&pageSize=1",
        headers=headers,
    )
    queue_resp.raise_for_status()
    queue_count = queue_resp.json().get("totalRecords", 0)

    # Recent grabs
    history_resp = await client.get(
        f"{settings.radarr_url}/api/v3/history?page=1&pageSize=20",
        headers=headers,
    )
    history_resp.raise_for_status()
    recent = history_resp.json().get("records", [])

    return {
        "movie_count": movie_count,
        "movies_available": movies_available,
        "missing_count": missing_count,
        "queue_count": queue_count,
        "recent_grabs": len([r for r in recent if r.get("eventType") == "grabbed"]),
    }


async def _poll_tautulli(client: httpx.AsyncClient) -> dict:
    """Fetch Tautulli Plex activity."""
    if not settings.tautulli_url or not settings.tautulli_api_key:
        return {"error": "Tautulli not configured"}

    # Current activity — Tautulli uses apikey query param, not header
    activity_resp = await client.get(
        f"{settings.tautulli_url}/api/v2",
        params={"apikey": settings.tautulli_api_key, "cmd": "get_activity"},
    )
    activity_resp.raise_for_status()
    activity = activity_resp.json()

    sessions = activity.get("response", {}).get("data", {}).get("sessions", [])
    active_streams = len(sessions)

    # Recent history (last 10 items)
    history_resp = await client.get(
        f"{settings.tautulli_url}/api/v2",
        params={"apikey": settings.tautulli_api_key, "cmd": "get_history", "length": 10},
    )
    history_resp.raise_for_status()
    history = history_resp.json()

    recent = history.get("response", {}).get("data", {}).get("data", [])
    recent_watches = [
        {
            "user": r.get("friendly_name", r.get("user", "")),
            "title": r.get("full_title", ""),
            "date": r.get("date", 0),
            "platform": r.get("platform", ""),
        }
        for r in recent[:5]
    ]

    return {
        "active_streams": active_streams,
        "recent_watches": recent_watches,
    }


async def collect() -> dict:
    """Poll all media services and store results in events table."""
    results: dict = {"sonarr": None, "radarr": None, "tautulli": None}

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            results["sonarr"] = await _poll_sonarr(client)
        except Exception as e:
            results["sonarr"] = {"error": str(e)}

        try:
            results["radarr"] = await _poll_radarr(client)
        except Exception as e:
            results["radarr"] = {"error": str(e)}

        try:
            results["tautulli"] = await _poll_tautulli(client)
        except Exception as e:
            results["tautulli"] = {"error": str(e)}

    # Store summary as a media_snapshot event
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO events (source, type, severity, title, body, metadata, ticker, tags)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
            "notflix",
            "media_snapshot",
            "info",
            "Media library snapshot",
            json.dumps(results),
            json.dumps(results),
            False,
            ["notflix", "media", "snapshot"],
        )

        # Check for new grabs and fire ticker events
        sonarr_data = results.get("sonarr") or {}
        radarr_data = results.get("radarr") or {}

        if sonarr_data.get("recent_grabs", 0) > 0:
            await conn.execute(
                """INSERT INTO events (source, type, severity, title, ticker, tags)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                "sonarr",
                "new_content",
                "info",
                f"{sonarr_data['recent_grabs']} new TV episodes grabbed",
                True,
                ["notflix", "sonarr", "new"],
            )

        if radarr_data.get("recent_grabs", 0) > 0:
            await conn.execute(
                """INSERT INTO events (source, type, severity, title, ticker, tags)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                "radarr",
                "new_content",
                "info",
                f"{radarr_data['recent_grabs']} new movies grabbed",
                True,
                ["notflix", "radarr", "new"],
            )

    return results
