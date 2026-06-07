"""
Handle incoming Dozzle webhook payloads (public, no auth).

Dozzle sends notifications when container logs match alert rules.
Payload format (subject to Dozzle version):
  {
    "type": "notification" | "test",
    "title": str,
    "body": str,
    "tags": list[str],         -- e.g. ["error", "nginx"]
    "priority": int,           -- 1-5 (higher = more urgent)
    "timestamp": str,          -- ISO 8601
    "containerName": str,      -- container that triggered the alert
    "containerId": str,        -- container ID
  }

The endpoint creates:
  1. An event in the events table with source='dozzle'
  2. A ticker event for high-severity notifications (priority >= 4 or level=error)
"""
import json
import logging

from app.db import get_pool

logger = logging.getLogger(__name__)


# Map Dozzle priority (1-5) to severity strings
_PRIORITY_TO_SEVERITY = {
    1: "debug",
    2: "info",
    3: "info",
    4: "warn",
    5: "critical",
}


def _priority_to_severity(priority: int) -> str:
    return _PRIORITY_TO_SEVERITY.get(priority, "info")


async def process_webhook_payload(payload: dict) -> dict:
    """
    Process a validated Dozzle webhook payload and store it.

    Args:
        payload: Parsed JSON from Dozzle webhook POST.

    Returns:
        dict with keys: event_id, ticker_created
    """
    notif_type = payload.get("type", "notification")
    title = payload.get("title", "Dozzle notification")
    body = payload.get("body", "")
    tags = payload.get("tags", [])
    priority = payload.get("priority", 2)
    timestamp = payload.get("timestamp", "")
    container_name = payload.get("containerName", payload.get("container_name", ""))
    container_id = payload.get("containerId", payload.get("container_id", ""))

    # Handle test notifications gracefully
    if notif_type == "test":
        logger.info("Dozzle webhook test received")
        return {"event_id": None, "ticker_created": False, "test": True}

    severity = _priority_to_severity(priority)

    # Create ticker events for high priority or error-level tags
    is_error = severity in ("error", "critical") or "error" in tags
    ticker = is_error or priority >= 4

    # Build event tags: include dozzle, container name, and original tags
    event_tags = ["dozzle", "webhook"]
    if container_name:
        event_tags.append(container_name.replace(" ", "_").lower())
    event_tags.extend(tags)

    metadata = {
        "container_name": container_name,
        "container_id": container_id,
        "priority": priority,
        "notification_type": notif_type,
        "raw_tags": tags,
    }

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO events (source, type, severity, title, body, metadata, ticker, tags)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id
            """,
            "dozzle",
            "webhook_notification",
            severity,
            title,
            body,
            json.dumps(metadata),
            ticker,
            event_tags,
        )
        event_id = row["id"]

    logger.info(
        f"Dozzle webhook: severity={severity}, ticker={ticker}, "
        f"container={container_name}, title={title[:60]}"
    )

    return {"event_id": event_id, "ticker_created": ticker, "test": False}
