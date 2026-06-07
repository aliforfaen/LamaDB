"""Collector for polling ntfy notifications and creating events."""
import json
import logging

import httpx

from app.db import get_pool
from app.config import settings

logger = logging.getLogger(__name__)


def _priority_to_severity(priority: int) -> str:
    """Map ntfy priority (1-5) to severity string."""
    if priority >= 5:
        return "critical"
    elif priority >= 4:
        return "warn"
    else:
        return "info"


async def collect() -> dict:
    """
    Poll ntfy server for recent messages, create events for each.

    ntfy returns NDJSON (one JSON object per line).
    For priority >= 4, creates a ticker event.

    Returns:
        dict with message_count, new_events, ticker_events.
    """
    if not settings.ntfy_url:
        logger.info("ntfy collector: not configured, skipping")
        return {"message_count": 0, "new_events": 0, "ticker_events": 0, "error": "not configured"}

    topic = settings.ntfy_topic
    poll_url = f"{settings.ntfy_url}/{topic}/json?poll=1&since=5m"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(poll_url, timeout=10.0)
            resp.raise_for_status()
            raw = resp.text.strip()
    except Exception as e:
        logger.warning(f"ntfy collector: error: {e}")
        return {"message_count": 0, "new_events": 0, "ticker_events": 0, "error": str(e)}

    if not raw:
        return {"message_count": 0, "new_events": 0, "ticker_events": 0}

    pool = get_pool()
    new_events = 0
    ticker_events = 0

    async with pool.acquire() as conn:
        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_id = msg.get("id", "")
            title = msg.get("title") or msg.get("message", "")[:100]
            message = msg.get("message", "")
            priority = msg.get("priority", 3)
            tags = msg.get("tags", [])
            severity = _priority_to_severity(priority)

            # Create event
            await conn.execute(
                """
                INSERT INTO events (source, type, severity, title, body, metadata, ticker, tags)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                "ntfy",
                "notification",
                severity,
                title,
                message,
                json.dumps({
                    "message_id": msg_id,
                    "priority": priority,
                    "tags": tags,
                }),
                priority >= 4,  # ticker for high priority
                ["ntfy", "notification"] + tags,
            )
            new_events += 1
            if priority >= 4:
                ticker_events += 1

    return {
        "message_count": len(raw.split("\n")),
        "new_events": new_events,
        "ticker_events": ticker_events,
    }
