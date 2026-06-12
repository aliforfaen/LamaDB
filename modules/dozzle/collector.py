"""Collector for polling Dozzle v10 container logs and creating events."""
import asyncio
import hashlib
import json
import logging
import re

import httpx

from app.db import get_pool
from app.config import settings

logger = logging.getLogger(__name__)

# Maximum events to insert per container per cycle to limit CPU/DB load
MAX_EVENTS_PER_CONTAINER = 50

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def _sanitize(text: str) -> str:
    """Strip ANSI escape codes, null bytes, and replace non-UTF8 sequences."""
    text = _ANSI_RE.sub('', text)
    text = text.replace("\x00", "")
    return text.encode("utf-8", errors="replace").decode("utf-8")


def _event_dedup_key(container_id: str, level: str, message: str) -> str:
    """Generate a deduplication key for a log event.

    Uses a hash of container_id + level + message[:200] so identical log
    entries don't generate duplicate events across polling cycles.
    """
    fingerprint = f"{container_id}|{level}|{message[:200]}"
    return hashlib.sha256(fingerprint.encode()).hexdigest()


async def _parse_logs_in_thread(text: str) -> list[dict]:
    """Parse JSONL log entries in a thread to avoid blocking the event loop."""
    return await asyncio.to_thread(_parse_logs_sync, text)


def _parse_logs_sync(text: str) -> list[dict]:
    """Synchronous JSONL parser — runs in thread pool via _parse_logs_in_thread."""
    entries: list[dict] = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_obj = data.get("m", {})
        # Dozzle v10 can return m as:
        # - dict: {"level": "warn", "message": "..."}
        # - list: [{"m": "line1"}, {"m": "line2"}] (grouped messages)
        # - str: "plain message"
        if isinstance(msg_obj, dict):
            level = msg_obj.get("level", data.get("l", "info"))
            message = msg_obj.get("message", str(msg_obj))
        elif isinstance(msg_obj, list):
            # Grouped messages - extract and join
            level = data.get("l", "info")
            messages = []
            for item in msg_obj:
                if isinstance(item, dict) and "m" in item:
                    messages.append(str(item["m"]))
                else:
                    messages.append(str(item))
            message = "\n".join(messages)
        else:
            level = data.get("l", "info")
            message = str(msg_obj) if msg_obj else ""

        entries.append({"level": level.lower(), "message": message})
        if len(entries) >= 500:
            break
    return entries


async def collect() -> dict:
    """
    Poll Dozzle v10 API for container logs, create events for errors/warnings.

    Uses SSE events stream for container discovery, then fetches logs per
    running container via the v10 API. Only fetches error/warn levels to
    minimize bandwidth and CPU. Events are deduplicated across cycles using
    a content-based hash stored in metadata.

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

            # Fetch existing dedup keys for this container (last 500 events)
            existing_keys = set()
            rows = await conn.fetch(
                """SELECT metadata->>'dedup_key' as dk
                   FROM events
                   WHERE source = 'dozzle'
                     AND metadata->>'container_id' = $1
                     AND metadata->>'dedup_key' IS NOT NULL
                   ORDER BY id DESC
                   LIMIT 500""",
                cid,
            )
            for r in rows:
                if r["dk"]:
                    existing_keys.add(r["dk"])

            container_events = 0
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

                # Deduplicate by content hash
                dedup_key = _event_dedup_key(cid, level, message)
                if dedup_key in existing_keys:
                    continue
                existing_keys.add(dedup_key)

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
                        "dedup_key": dedup_key,
                    }),
                    ticker,
                    ["dozzle", "container", severity],
                )

                container_events += 1
                if container_events >= MAX_EVENTS_PER_CONTAINER:
                    break

    return {
        "errors": error_count,
        "warnings": warn_count,
        "containers_scanned": containers_scanned,
    }


async def _fetch_containers() -> list[dict]:
    """Fetch container list from Dozzle v10 SSE events stream.

    Reads the first ``containers-changed`` event from the SSE stream, then
    disconnects. Returns all containers (running and stopped); caller filters.

    Uses a 3s connect timeout so unreachable hosts fail fast — otherwise the
    collector hangs for ~30s on the OS TCP timeout and blocks the poller
    loop. The outer collect() already catches exceptions, but failing fast
    also keeps the poller's error log informative.
    """
    url = f"{settings.dozzle_url}/api/events/stream"
    containers: list[dict] = []
    try:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "GET",
                url,
                timeout=httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=3.0),
            ) as response:
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
    except (httpx.HTTPError, httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
        logger.warning(f"Dozzle collector: container discovery failed: {e}")
        return []
    except Exception as e:
        logger.warning(f"Dozzle collector: unexpected error in container discovery: {e}")
        return []

    return containers


async def _fetch_container_logs(host: str, container_id: str) -> list[dict]:
    """
    Fetch parsed log entries for a container via Dozzle v10 API.

    Only fetches error/warn levels to minimize bandwidth and CPU (info/debug
    logs are voluminous and not actionable). Parsing is offloaded to a thread
    pool via asyncio.to_thread() to avoid blocking the event loop.

    Uses a 3s connect timeout so unreachable hosts fail fast — callers
    skip the container and continue scanning the rest of the fleet.

    Returns list of dicts with ``level`` and ``message`` keys, limited to
    first 500 lines per container.
    """
    url = (
        f"{settings.dozzle_url}/api/hosts/{host}/containers/"
        f"{container_id}/logs?stdout=1&stderr=1&levels=error&levels=warn"
    )

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                timeout=httpx.Timeout(connect=3.0, read=10.0, write=5.0, pool=3.0),
            )
            response.raise_for_status()
            text = response.text
    except (httpx.HTTPError, httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
        logger.warning(f"Dozzle collector: log fetch timeout/error for {container_id[:12]}: {e}")
        return []
    except Exception as e:
        logger.warning(f"Dozzle collector: log fetch error for {container_id[:12]}: {e}")
        return []

    # Offload JSON parsing to thread pool to keep event loop responsive
    if not text.strip():
        return []
    return await _parse_logs_in_thread(text)
