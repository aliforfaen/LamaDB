"""Collector for polling Dozzle container logs and creating events."""
import json
import logging

import httpx

from app.db import get_pool
from app.config import settings

logger = logging.getLogger(__name__)


async def collect() -> dict:
    """
    Poll Dozzle API for recent error/warning logs, create events.

    Dozzle API returns NDJSON. For ERROR level, creates a ticker event.

    Returns:
        dict with errors, warnings, containers_scanned.
    """
    if not settings.dozzle_url:
        logger.info("Dozzle collector: not configured, skipping")
        return {"errors": 0, "warnings": 0, "containers_scanned": 0, "error": "not configured"}

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{settings.dozzle_url}/api/logs?since=5m&level=error",
                timeout=10.0,
            )
            resp.raise_for_status()
            raw = resp.text.strip()
    except Exception as e:
        logger.warning(f"Dozzle collector: error: {e}")
        return {"errors": 0, "warnings": 0, "containers_scanned": 0, "error": str(e)}

    if not raw:
        return {"errors": 0, "warnings": 0, "containers_scanned": 0}

    pool = get_pool()
    error_count = 0
    warn_count = 0
    containers_seen = set()

    async with pool.acquire() as conn:
        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            container = data.get("containerName", "unknown")
            level = data.get("level", "info")
            message = data.get("message", "")
            timestamp = data.get("timestamp", "")

            containers_seen.add(container)

            # Determine severity
            if level == "error":
                severity = "error"
                error_count += 1
                ticker = True
            elif level == "warn":
                severity = "warn"
                warn_count += 1
                ticker = False
            else:
                continue  # Skip info/debug for events

            # Truncate message for title
            title = f"{container}: {message[:100]}" if message else f"{container}: log event"

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
                    "container": container,
                    "level": level,
                    "timestamp": timestamp,
                }),
                ticker,
                ["dozzle", "container", level],
            )

    return {
        "errors": error_count,
        "warnings": warn_count,
        "containers_scanned": len(containers_seen),
    }
