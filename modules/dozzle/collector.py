"""Collector for polling Dozzle v10 container logs and creating events."""
import json
import logging

import httpx

from app.db import get_pool
from app.config import settings

logger = logging.getLogger(__name__)

def _sanitize(text: str) -> str:
    """Strip null bytes and replace non-UTF8 sequences so Postgres accepts the text."""
    return text.replace("\x00", "").encode("utf-8", errors="replace").decode("utf-8")


async def collect() -> dict:
    """
    Poll Dozzle v10 API for container logs, create events for errors/warnings.

    Uses SSE events stream for container discovery, then fetches logs per
    running container via the v10 API. Error/warn detection is done client-side
    via keyword matching since v10 has no server-side level filter.

    Returns:
        dict with errors, warnings, containers_scanned.
    """
    if not settings.dozzle_url:
        logger.info("Dozzle collector: not configured, skipping")
        return {"errors": 0, "warnings": 0, "containers_scanned": 0, "error": "not configured"}

    try:
        containers = await _fetch_containers()
    except Exception as e:
        logger.warning(f"Dozzle collector: container discovery error: {e}")
        return {"errors": 0, "warnings": 0, "containers_scanned": 0, "error": str(e)}

    if not containers:
        return {"errors": 0, "warnings": 0, "containers_scanned": 0}

    pool = get_pool()
    error_count = 0
    warn_count = 0
    containers_scanned = 0

    async with pool.acquire() as conn:
        for container in containers:
            cid = container.get("id", "")
            name = container.get("name", cid[:12] if cid else "unknown")
            host = container.get("host", "")
            state = container.get("state", "")

            if state != "running":
                continue

            containers_scanned += 1

            try:
                entries = await _fetch_container_logs(host, cid)
            except Exception as e:
                logger.warning(f"Dozzle collector: log fetch error for {name}: {e}")
                continue

            for entry in entries:
                level = entry.get("level", "")
                message = entry.get("message", "")

                if level in ("warn", "warning"):
                    severity = "warn"
                    warn_count += 1
                elif level in ("error", "err", "fatal", "critical", "panic", "emerg", "alert", "crit"):
                    severity = "error"
                    error_count += 1
                else:
                    continue

                message = _sanitize(message)
                ticker = severity == "error"
                title = _sanitize(f"{name}: {message[:100]}" if message else f"{name}: log event")

                await conn.execute(
                    """
                    INSERT INTO events (source, type, severity, title, body, metadata, ticker, tags)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    "dozzle",
                    "container_log",
                    severity,
                    title,
                    message,
                    json.dumps({
                        "container": name,
                        "container_id": cid,
                        "host": host,
                        "level": level,
                    }),
                    ticker,
                    ["dozzle", "container", severity],
                )

    return {
        "errors": error_count,
        "warnings": warn_count,
        "containers_scanned": containers_scanned,
    }


async def _fetch_containers() -> list[dict]:
    """Fetch container list from Dozzle v10 SSE events stream.

    Reads the first ``containers-changed`` event from the SSE stream, then
    disconnects. Returns all containers (running and stopped); caller filters.
    Timeouts after 5 seconds if no event received.
    """
    url = f"{settings.dozzle_url}/api/events/stream"
    containers: list[dict] = []
    async with httpx.AsyncClient() as client:
        async with client.stream("GET", url, timeout=5.0) as response:
            response.raise_for_status()
            event_type = ""
            event_data = ""

            async for line_bytes in response.aiter_lines():
                line = line_bytes.strip()

                if line.startswith("event:"):
                    # SSE spec allows "event:type" (no space) or "event: type"
                    event_type = line[6:].lstrip()
                elif line.startswith("data:"):
                    event_data = line[5:].lstrip()
                elif line == "":
                    if event_type == "containers-changed" and event_data:
                        try:
                            containers = json.loads(event_data)
                        except json.JSONDecodeError:
                            logger.warning(
                                "Dozzle collector: failed to parse containers-changed data"
                            )
                        break
                    event_type = ""
                    event_data = ""

    return containers


async def _fetch_container_logs(host: str, container_id: str) -> list[dict]:
    """
    Fetch parsed log entries for a container via Dozzle v10 API.

    Returns list of dicts with ``level`` and ``message`` keys, limited to
    first 500 lines per container.  The ``everything`` flag fetches all
    buffered stdout+stderr; the ``levels`` param requests only error and
    warning lines to keep responses small.
    """
    levels = "levels=error&levels=warn&levels=info&levels=debug"
    url = (
        f"{settings.dozzle_url}/api/hosts/{host}/containers/"
        f"{container_id}/logs?stdout=1&stderr=1&{levels}"
    )

    async with httpx.AsyncClient() as client:
        response = await client.get(url, timeout=10.0)
        response.raise_for_status()
        text = response.text

    entries: list[dict] = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        # v10 log entry: {t, m: {level, message, time, ...}, l, s, c, ts, id}
        msg_obj = data.get("m", {})
        if isinstance(msg_obj, dict):
            level = msg_obj.get("level", data.get("l", "info"))
            message = msg_obj.get("message", str(msg_obj))
        else:
            level = data.get("l", "info")
            message = str(msg_obj) if msg_obj else ""

        entries.append({"level": level.lower(), "message": message})
        if len(entries) >= 500:
            break

    return entries
