"""Collector for polling Dozzle v10 container logs and creating events."""
import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx

from app.db import get_pool
from app.config import settings

logger = logging.getLogger(__name__)

# Maximum events to insert per container per cycle to limit CPU/DB load
MAX_EVENTS_PER_CONTAINER = 50

# Window of logs to fetch per cycle. Must be >= the poller interval (300s in
# main.py) so a container that logs once per cycle still surfaces. Bounded so
# Dozzle's fetchLogsBetweenDates doesn't walk back through container history
# for noisy containers (jellyseerr, affine), which used to exceed the read
# timeout.
DEFAULT_LOG_WINDOW_MINUTES = 10

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def _sanitize(text: str) -> str:
    """Strip ANSI escape codes, null bytes, and replace non-UTF8 sequences."""
    text = _ANSI_RE.sub('', text)
    text = text.replace("\x00", "")
    return text.encode("utf-8", errors="replace").decode("utf-8")


_ISO_TS_RE = re.compile(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?')
# Common log line prefixes like "[Sun, 14 Jun 2026 23:32:01 +0200]" — RFC 2822 style
_RFC_TS_RE = re.compile(r'\[\w{3},\s+\d{1,2}\s+\w{3}\s+\d{4}\s+\d{2}:\d{2}:\d{2}\s+[+-]\d{4}\]')
# "Mon DD, YYYY HH:MM:SS" — Sonarr/Radarr/Syncthing/Agregarr log prefix style,
# e.g. "Jun 15, 2026 13:17:00". Without stripping this, every minute yields a
# unique dedup_key for the same recurring error.
_MON_DD_TS_RE = re.compile(r'\w{3}\s+\d{1,2},\s+\d{4}\s+\d{2}:\d{2}:\d{2}')
# ANSI control sequences (move-to, color, etc.) — re-strip here in case sanitize missed a path
_CTRL_RE = re.compile(r'\x1b\[[0-9;?]*[a-zA-Z]')
# Sequence numbers / uuids / ports that vary per line but don't change the error
_VAR_TOKEN_RE = re.compile(r'\[?\b[0-9a-f]{8,}\b\]?', re.IGNORECASE)


def _normalize_for_dedup(message: str) -> str:
    """Strip volatile tokens (timestamps, hex ids) so identical errors dedupe.

    Without this, the same recurring error from a container (e.g. agregarr's
    'cookie agregarr.sid required' once per minute) becomes 1 unique event
    per timestamp. We collapse those here so recurring errors get a single
    event per container/level/message-triple.
    """
    s = message or ""
    s = _ISO_TS_RE.sub('TS', s)
    s = _RFC_TS_RE.sub('TS', s)
    s = _MON_DD_TS_RE.sub('TS', s)
    s = _CTRL_RE.sub('', s)
    s = _VAR_TOKEN_RE.sub('ID', s)
    # Collapse repeated whitespace
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _event_dedup_key(container_id: str, level: str, message: str) -> str:
    """Generate a deduplication key for a log event.

    Uses a hash of container_id + level + normalized_message[:200] so identical
    log entries don't generate duplicate events across polling cycles. Volatile
    tokens (timestamps, uuids, ANSI codes) are stripped before hashing so a
    recurring error from a container collapses to a single event.
    """
    normalized = _normalize_for_dedup(message)[:200]
    fingerprint = f"{container_id}|{level}|{normalized}"
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
    # Track per-cycle timeout warnings so a single noisy container doesn't
    # flood the log once per poller interval. Reset every collect() call.
    warned_containers: set[str] = set()

    # Bound the log window so Dozzle's fetchLogsBetweenDates doesn't walk
    # back through all history for noisy containers (jellyseerr, affine).
    # See DEFAULT_LOG_WINDOW_MINUTES comment for the rationale.
    now_utc = datetime.now(timezone.utc)
    from_ts = (now_utc - timedelta(minutes=DEFAULT_LOG_WINDOW_MINUTES)).isoformat()
    to_ts = now_utc.isoformat()

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
                entries = await _fetch_container_logs(host, cid, from_ts=from_ts, to_ts=to_ts)
            except Exception as e:
                if cid not in warned_containers:
                    logger.warning(f"Dozzle collector: log fetch error for {name}: {e}")
                    warned_containers.add(cid)
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
                # Use normalized message for the title so consolidation queries
                # that group by (source, title) can collapse recurring errors.
                norm_for_title = _sanitize(_normalize_for_dedup(message))[:100]
                title = _sanitize(f"{name}: {norm_for_title}" if norm_for_title else f"{name}: log event")

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


async def _fetch_container_logs(
    host: str,
    container_id: str,
    from_ts: str | None = None,
    to_ts: str | None = None,
) -> list[dict]:
    """
    Fetch parsed log entries for a container via Dozzle v10 API.

    Only fetches error/warn levels to minimize bandwidth and CPU (info/debug
    logs are voluminous and not actionable). Parsing is offloaded to a thread
    pool via asyncio.to_thread() to avoid blocking the event loop.

    Uses a 3s connect timeout so unreachable hosts fail fast — callers
    skip the container and continue scanning the rest of the fleet. The
    30s read timeout is generous enough for noisy containers (jellyseerr,
    affine) over Tailscale, where a 500-line ring-buffer response can take
    10–20s to serialize and transmit.

    ``from_ts``/``to_ts`` (RFC3339) bound the log window so Dozzle's
    fetchLogsBetweenDates doesn't walk back through container history for
    noisy containers. Without bounds, a single ``levels=error&levels=warn``
    query can hit a 500-event ceiling and keep doubling the search window
    until the response exceeds the read timeout.

    Returns list of dicts with ``level`` and ``message`` keys, limited to
    first 500 lines per container.
    """
    params = "stdout=1&stderr=1&levels=error&levels=warn"
    if from_ts:
        params += f"&from={from_ts}"
    if to_ts:
        params += f"&to={to_ts}"
    url = (
        f"{settings.dozzle_url}/api/hosts/{host}/containers/"
        f"{container_id}/logs?{params}"
    )

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                timeout=httpx.Timeout(connect=3.0, read=30.0, write=5.0, pool=3.0),
            )
            response.raise_for_status()
            text = response.text
    except (httpx.HTTPError, httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
        logger.debug(f"Dozzle collector: log fetch timeout/error for {container_id[:12]}: {e}")
        return []
    except Exception as e:
        logger.debug(f"Dozzle collector: log fetch error for {container_id[:12]}: {e}")
        return []

    # Offload JSON parsing to thread pool to keep event loop responsive
    if not text.strip():
        return []
    return await _parse_logs_in_thread(text)
