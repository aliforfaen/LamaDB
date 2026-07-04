"""MCP tools for the Hermes module — read-only proxies over the Hermes API."""
import logging

import httpx

from app.config import settings

from .collector import _ensure_session_token, _get_headers

logger = logging.getLogger(__name__)


async def _hermes_get(path: str) -> dict | list | None:
    """GET from Hermes API and return JSON. None on error/unreachable.

    Mirrors the helper in `routes.py` so MCP callers get the same
    degradation behaviour (None rather than an exception) when Hermes
    is down. Uses a short connect timeout to avoid hanging the
    dispatcher when the upstream is unreachable from Docker.
    """
    if not settings.hermes_url:
        return None
    url = f"{settings.hermes_url.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient() as client:
            await _ensure_session_token(client)
            resp = await client.get(
                url,
                headers=_get_headers(),
                timeout=httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=5.0),
            )
            if resp.status_code == 200:
                return resp.json()
            logger.warning(f"Hermes MCP {path}: HTTP {resp.status_code}")
            return None
    except Exception as e:
        logger.warning(f"Hermes MCP {path}: {e}")
        return None


async def hermes_sessions(profile: str | None = None, limit: int = 20) -> dict:
    """Return recent Hermes sessions with token/cost metadata.

    Args:
        profile: Optional profile name filter (e.g. 'muninn', 'kark').
                 When set, hits `/api/profiles/sessions?profile=...`.
        limit:   Max sessions to return (1..100).

    Mirrors `GET /api/hermes/sessions`. Returns `{"error": "..."}` on
    unreachable upstream so MCP callers can distinguish from an empty
    result (which would come through as `sessions: []`).
    """
    limit = max(1, min(int(limit), 100))
    qs = f"limit={limit}"
    if profile:
        qs += f"&profile={profile}"
    data = await _hermes_get(f"/api/profiles/sessions?{qs}")
    if not data:
        return {"error": "Hermes unreachable", "sessions": [], "count": 0}
    return data


async def hermes_stats() -> dict:
    """Aggregate session/message stats across active and cross-profile data.

    Mirrors `GET /api/hermes/sessions/stats`: combines
    `/api/sessions/stats` (active profile) with `/api/profiles/sessions`
    (cross-profile totals) so agents see both breakdowns in one call.
    """
    stats = await _hermes_get("/api/sessions/stats") or {}
    profiles = await _hermes_get("/api/profiles/sessions?limit=1") or {}
    if not stats and not profiles:
        return {"error": "Hermes unreachable"}
    out = dict(stats) if isinstance(stats, dict) else {}
    if isinstance(profiles, dict):
        out["profile_totals"] = profiles.get("profile_totals", {})
        out["all_profile_total"] = profiles.get("total", 0)
    return out


async def hermes_health() -> dict:
    """Lightweight reachability probe for Hermes.

    Mirrors `GET /api/hermes/health`. Always returns a dict with a
    `reachable` boolean — never raises, so MCP dispatchers don't have
    to wrap.
    """
    if not settings.hermes_url:
        return {
            "reachable": False,
            "url": "",
            "error": "HERMES_URL not configured",
        }

    status = await _hermes_get("/api/status")
    if status:
        return {
            "reachable": True,
            "url": settings.hermes_url,
            "version": status.get("version"),
            "gateway_running": status.get("gateway_running"),
        }
    return {
        "reachable": False,
        "url": settings.hermes_url,
        "error": "Connection failed",
    }
