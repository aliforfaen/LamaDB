"""
Handle incoming Uptime Kuma webhook payloads.

Parses the payload, inserts a row into monitor_status, and writes
a corresponding event to the events table.
"""
import json
from app.db import get_pool
from app.models.events import EventCreate


# Status code to event severity mapping
_STATUS_TO_SEVERITY = {
    0: "critical",  # DOWN
    1: "info",      # UP
    2: "warn",      # pending
    3: "warn",      # maintained
}

# Status code to human-readable label
_STATUS_TO_LABEL = {
    0: "DOWN",
    1: "UP",
    2: "PENDING",
    3: "MAINTAINED",
}


def _derive_severity(status: int) -> str:
    """Map a heartbeat status code to an event severity string."""
    return _STATUS_TO_SEVERITY.get(status, "info")


def _build_event_title(monitor_name: str, status: int) -> str:
    """Build the event title from monitor name and status."""
    label = _STATUS_TO_LABEL.get(status, "UNKNOWN")
    return f"{monitor_name} is {label}"


async def process_webhook(payload: "UptimeWebhookPayload") -> None:
    """
    Process a validated Uptime Kuma webhook payload.

    Inserts a row into monitor_status and writes a corresponding event.

    Args:
        payload: Validated UptimeWebhookPayload from the webhook endpoint.
    """
    pool = get_pool()
    severity = _derive_severity(payload.heartbeat.status)
    title = _build_event_title(payload.monitor.name, payload.heartbeat.status)
    metadata = {
        "monitor_id": payload.monitor.id,
        "monitor_name": payload.monitor.name,
        "monitor_url": payload.monitor.url,
        "status": payload.heartbeat.status,
        "msg": payload.heartbeat.msg,
        "duration": payload.heartbeat.duration,
        "heartbeat_time": payload.heartbeat.time,
    }

    # Extract tag names from KumaTag objects
    tag_names = [t.name for t in payload.monitor.tags] if payload.monitor.tags else []

    async with pool.acquire() as conn:
        # Insert into monitor_status
        await conn.execute(
            """
            INSERT INTO monitor_status
                (monitor_id, monitor_name, monitor_url, status, msg, duration_ms, tags)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            str(payload.monitor.id),
            payload.monitor.name,
            payload.monitor.url,
            payload.heartbeat.status,
            payload.heartbeat.msg,
            payload.heartbeat.duration,
            tag_names,
        )

        # Insert into events
        await conn.execute(
            """
            INSERT INTO events (source, type, severity, title, metadata)
            VALUES ($1, $2, $3, $4, $5)
            """,
            "uptime_kuma",
            "monitor_status",
            severity,
            title,
            json.dumps(metadata),
        )

        # Check for status change to create a ticker event
        # Use OFFSET 1 because the current heartbeat has already been inserted,
        # so the most recent row is the current one, not the previous
        previous = await conn.fetchval(
            "SELECT status FROM monitor_status WHERE monitor_id = $1 ORDER BY received_at DESC LIMIT 1 OFFSET 1",
            str(payload.monitor.id)
        )

        # Only create ticker event on status change (not on first heartbeat)
        if previous is not None and previous != payload.heartbeat.status:
            is_down = payload.heartbeat.status == 0
            ticker_tags = ['breaking', 'uptime', 'down'] if is_down else ['status', 'uptime', 'recovered']
            change_title = f"{payload.monitor.name} is DOWN" if is_down else f"{payload.monitor.name} recovered — UP"

            await conn.execute(
                """
                INSERT INTO events (source, type, severity, title, body, metadata, ticker, tags)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                "uptime_kuma",
                "status_change",
                severity,
                change_title,
                payload.heartbeat.msg,
                json.dumps(metadata),
                True,
                ticker_tags,
            )
