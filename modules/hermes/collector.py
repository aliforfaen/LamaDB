"""Collector for polling Hermes Agent API and creating events."""
import json
import logging

import httpx

from app.db import get_pool
from app.config import settings

logger = logging.getLogger(__name__)

# Cached session token (from config or extracted from dashboard HTML)
_session_token: str | None = None


def _get_token() -> str | None:
    """Return the best available auth token."""
    global _session_token
    if _session_token:
        return _session_token
    if settings.hermes_dashboard_session_token:
        return settings.hermes_dashboard_session_token
    if settings.hermes_api_key:
        return settings.hermes_api_key
    return None


def _get_headers() -> dict[str, str]:
    """Build auth headers for Hermes API."""
    token = _get_token()
    if token:
        return {"X-Hermes-Session-Token": token}
    return {}


async def _ensure_session_token(client: httpx.AsyncClient) -> None:
    """Extract session token from dashboard HTML if no token is configured.

    Uses a short connect timeout (3s) to avoid hanging when Hermes is
    unreachable from Docker.
    """
    global _session_token
    if _get_token():
        return
    url = f"{settings.hermes_url.rstrip('/')}/"
    try:
        resp = await client.get(
            url,
            timeout=httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=5.0),
        )
        if resp.status_code == 200:
            import re
            m = re.search(r'__HERMES_SESSION_TOKEN__="([^"]+)"', resp.text)
            if m:
                _session_token = m.group(1)
                logger.info("Hermes: extracted session token from dashboard")
    except Exception as e:
        logger.warning(f"Hermes: failed to extract session token: {e}")


async def _fetch_json(client: httpx.AsyncClient, path: str) -> dict | list | None:
    """Fetch JSON from Hermes API, return None on error.

    Uses a 5s connect timeout so unreachable hosts fail fast instead of
    hanging the collector loop for ~30s on every cycle.
    """
    url = f"{settings.hermes_url.rstrip('/')}{path}"
    try:
        resp = await client.get(
            url,
            headers=_get_headers(),
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0),
        )
        if resp.status_code == 200:
            return resp.json()
        logger.warning(f"Hermes {path}: HTTP {resp.status_code}")
        return None
    except Exception as e:
        logger.warning(f"Hermes {path}: {e}")
        return None


async def collect() -> dict:
    """
    Poll Hermes for stats, recent sessions, and system health.
    Creates events for notable changes (new sessions, health issues).
    Returns summary dict for the poller_loop logger.
    """
    if not settings.hermes_url:
        logger.info("hermes collector: not configured, skipping")
        return {"status": "not configured"}

    async with httpx.AsyncClient() as client:
        await _ensure_session_token(client)

        # Fetch all analytics endpoints
        status = await _fetch_json(client, "/api/status")
        if not status:
            return {"status": "unreachable", "error": "Hermes API unreachable"}

        session_stats = await _fetch_json(client, "/api/sessions/stats") or {}
        system_stats = await _fetch_json(client, "/api/system/stats") or {}
        # /api/profiles/sessions returns sessions ACROSS ALL profiles with
        # per-session "profile" attribution and a "profile_totals" summary.
        # /api/sessions only returns the active profile (no attribution).
        sessions = await _fetch_json(client, "/api/profiles/sessions?limit=50") or {}
        active_profile = await _fetch_json(client, "/api/profiles/active") or {}

    gateway_state = status.get("gateway_state", "unknown")
    platforms = status.get("gateway_platforms", {})

    pool = get_pool()
    new_events = 0

    async with pool.acquire() as conn:
        # --- Gateway health event ---
        await conn.execute(
            """
            INSERT INTO events (source, type, severity, title, body, metadata)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            "hermes",
            "hermes.health",
            "info" if gateway_state == "running" else "error",
            f"Hermes gateway: {gateway_state}",
            f"Version {status.get('version')}, platforms: {', '.join(platforms.keys())}",
            _jsonb({
                "version": status.get("version"),
                "gateway_state": gateway_state,
                "gateway_pid": status.get("gateway_pid"),
                "platforms": {k: v.get("state") for k, v in platforms.items()},
                "active_sessions": status.get("active_sessions", 0),
            }),
        )
        new_events += 1

        # --- Session stats event ---
        if session_stats:
            total = session_stats.get("total", 0)
            messages = session_stats.get("messages", 0)
            by_source = session_stats.get("by_source", {})
            await conn.execute(
                """
                INSERT INTO events (source, type, severity, title, body, metadata)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                "hermes",
                "hermes.session_stats",
                "info",
                f"Hermes: {total} sessions, {messages} messages",
                f"Sources: {', '.join(f'{k}={v}' for k, v in by_source.items())}",
                _jsonb(session_stats),
            )
            new_events += 1

        # --- System stats event ---
        if system_stats:
            mem = system_stats.get("memory", {})
            disk = system_stats.get("disk", {})
            proc = system_stats.get("process", {})
            severity = "info"
            if mem.get("percent", 0) > 85 or disk.get("percent", 0) > 90:
                severity = "warn"

            await conn.execute(
                """
                INSERT INTO events (source, type, severity, title, body, metadata)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                "hermes",
                "hermes.system_stats",
                severity,
                f"Hermes host: mem={mem.get('percent', 0):.0f}%, disk={disk.get('percent', 0):.0f}%",
                f"CPU {system_stats.get('cpu_percent', 0):.1f}%, uptime {system_stats.get('uptime_seconds', 0) // 3600}h",
                _jsonb({
                    "hostname": system_stats.get("hostname"),
                    "cpu_percent": system_stats.get("cpu_percent"),
                    "memory_percent": mem.get("percent"),
                    "disk_percent": disk.get("percent"),
                    "uptime_seconds": system_stats.get("uptime_seconds"),
                    "process_rss": proc.get("rss"),
                }),
            )
            new_events += 1

        # --- Recent sessions as documents ---
        session_list = sessions.get("sessions", []) if isinstance(sessions, dict) else []
        docs_created = 0
        for s in session_list[:10]:
            sid = s.get("id", "")
            existing = await conn.fetchval(
                "SELECT id FROM documents WHERE metadata->>'hermes_session_id' = $1",
                sid,
            )
            if existing:
                continue

            total_tokens = (
                s.get("input_tokens", 0)
                + s.get("output_tokens", 0)
                + s.get("reasoning_tokens", 0)
            )
            title = s.get("title") or s.get("preview", "")[:80] or f"Hermes session {sid}"
            profile = s.get("profile") or "default"

            await conn.execute(
                """
                INSERT INTO documents (source_type, title, content, metadata, tags)
                VALUES ($1, $2, $3, $4, $5)
                """,
                "hermes_session",
                title,
                s.get("preview", ""),
                _jsonb({
                    "hermes_session_id": sid,
                    "source": s.get("source"),
                    "model": s.get("model"),
                    "profile": profile,
                    "message_count": s.get("message_count", 0),
                    "tool_call_count": s.get("tool_call_count", 0),
                    "input_tokens": s.get("input_tokens", 0),
                    "output_tokens": s.get("output_tokens", 0),
                    "cache_read_tokens": s.get("cache_read_tokens", 0),
                    "reasoning_tokens": s.get("reasoning_tokens", 0),
                    "total_tokens": total_tokens,
                    "api_call_count": s.get("api_call_count", 0),
                    "estimated_cost_usd": s.get("estimated_cost_usd"),
                    "started_at": s.get("started_at"),
                    "ended_at": s.get("ended_at"),
                    "end_reason": s.get("end_reason"),
                }),
                ["hermes", profile, s.get("source", "unknown")],
            )
            docs_created += 1

        # --- Active profile event (for visibility into what's being polled) ---
        active_name = active_profile.get("active") or "unknown"
        await conn.execute(
            """
            INSERT INTO events (source, type, severity, title, body, metadata)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            "hermes",
            "hermes.active_profile",
            "info",
            f"Hermes active profile: {active_name}",
            f"Profile totals: {json.dumps(sessions.get('profile_totals', {}))}",
            _jsonb({
                "active_profile": active_name,
                "profile_totals": sessions.get("profile_totals", {}),
            }),
        )
        new_events += 1

    return {
        "status": "ok",
        "version": status.get("version"),
        "gateway_state": gateway_state,
        "active_profile": active_profile.get("active", "unknown"),
        "total_sessions": session_stats.get("total", 0),
        "total_messages": session_stats.get("messages", 0),
        "profile_totals": sessions.get("profile_totals", {}) if isinstance(sessions, dict) else {},
        "new_events": new_events,
        "new_docs": docs_created,
    }


def _jsonb(d: dict) -> str:
    """Serialize dict to JSON string for JSONB column."""
    return json.dumps(d)
