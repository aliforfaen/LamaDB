"""
Uptime Kuma Monitor Registry Poller.

Fetches monitor list + tags from Uptime Kuma's API and stores in the
monitor_registry table. Runs on startup and every 5 minutes.

This solves the problem that Uptime Kuma only sends webhook notifications
on status changes — new monitors never appear until they change state.
"""
import asyncio
import json
import logging

from app.config import settings
from app.db import get_pool

logger = logging.getLogger("uptime.poller")

POLL_INTERVAL_SECONDS = 3600  # 1 hour


def _extract_tags(monitor: dict) -> list[str]:
    """Extract tag names from a monitor dict returned by the API.

    The API returns tags as a list of objects with 'name' key:
        [{"name": "tagname", "value": "...", "color": "..."}]

    But sometimes tags may be plain strings or other formats.
    """
    tags: list[str] = []
    raw_tags = monitor.get("tags", [])

    if isinstance(raw_tags, list):
        for t in raw_tags:
            if isinstance(t, dict) and "name" in t:
                tags.append(t["name"])
            elif isinstance(t, str):
                tags.append(t)

    return tags


def _fetch_kuma_data(url: str, username: str, password: str) -> tuple[list[dict], dict[str, dict]]:
    """Synchronous Uptime Kuma API fetch. Runs in a thread via asyncio.to_thread().

    Returns:
        (monitors_list, heartbeats_dict)
    """
    from uptime_kuma_api import UptimeKumaApi

    api = UptimeKumaApi(url)
    try:
        api.login(username, password)
        monitors = api.get_monitors()

        heartbeats = {}
        for m in monitors:
            try:
                beats = api.get_monitor_beats(m["id"], 1)
                if beats:
                    heartbeats[str(m["id"])] = beats[-1]
            except Exception:
                pass
    finally:
        api.disconnect()

    return monitors, heartbeats


async def poll_kuma_registry() -> dict:
    """Fetch monitors from Uptime Kuma and sync with monitor_registry.

    Compares polled monitors with existing registry:
    - Upserts new/changed monitors
    - Deletes monitors no longer in Uptime Kuma
    - Fetches latest heartbeat for each monitor

    Returns:
        Dict with sync stats: added, updated, deleted, total, heartbeats.
    """
    if not settings.uptime_kuma_url or not settings.uptime_kuma_user:
        logger.debug("Uptime Kuma API not configured, skipping poll")
        return {"added": 0, "updated": 0, "deleted": 0, "total": 0, "heartbeats": 0}

    try:
        from uptime_kuma_api import UptimeKumaApi
    except ImportError:
        logger.warning("uptime-kuma-api not installed, cannot poll")
        return {"added": 0, "updated": 0, "deleted": 0, "total": 0, "heartbeats": 0}

    try:
        # Run synchronous UptimeKumaApi calls in a thread to avoid
        # blocking the async event loop (the library uses requests).
        monitors, heartbeats = await asyncio.to_thread(
            _fetch_kuma_data,
            settings.uptime_kuma_url,
            settings.uptime_kuma_user,
            settings.uptime_kuma_password,
        )
    except Exception as e:
        logger.error(f"Failed to poll Uptime Kuma: {e}")
        return {"added": 0, "updated": 0, "deleted": 0, "total": 0, "heartbeats": 0}

    pool = get_pool()
    polled_ids: set[str] = set()
    added = 0
    updated = 0
    heartbeat_count = 0

    async with pool.acquire() as conn:
        # Get existing monitor IDs
        existing_rows = await conn.fetch("SELECT monitor_id FROM monitor_registry")
        existing_ids: set[str] = {r["monitor_id"] for r in existing_rows}

        for m in monitors:
            monitor_id = str(m["id"])
            polled_ids.add(monitor_id)
            tags = _extract_tags(m)
            parent = m.get("parent")
            parent_id = str(parent) if parent else None
            is_new = monitor_id not in existing_ids

            await conn.execute(
                """
                INSERT INTO monitor_registry
                    (monitor_id, monitor_name, monitor_url, monitor_type, tags, parent_id, active, last_seen, raw_data)
                VALUES ($1, $2, $3, $4, $5, $6, $7, now(), $8)
                ON CONFLICT (monitor_id) DO UPDATE SET
                    monitor_name = EXCLUDED.monitor_name,
                    monitor_url = EXCLUDED.monitor_url,
                    monitor_type = EXCLUDED.monitor_type,
                    tags = EXCLUDED.tags,
                    parent_id = EXCLUDED.parent_id,
                    active = EXCLUDED.active,
                    last_seen = now(),
                    raw_data = EXCLUDED.raw_data
                """,
                monitor_id,
                m.get("name", ""),
                m.get("url", ""),
                m.get("type", ""),
                tags,
                parent_id,
                m.get("active", True),
                json.dumps(m),
            )

            if is_new:
                added += 1
            else:
                updated += 1

            # Store heartbeat if available
            if monitor_id in heartbeats:
                beat = heartbeats[monitor_id]
                status_val = beat.get("status", 2)
                if hasattr(status_val, "value"):
                    status_val = status_val.value

                msg = beat.get("msg", "")
                duration = beat.get("duration", 0)
                time_str = beat.get("time", "")

                from datetime import datetime
                try:
                    received_at = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S.%f")
                except ValueError:
                    try:
                        received_at = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        received_at = None

                if received_at:
                    await conn.execute(
                        """
                        INSERT INTO monitor_status
                            (monitor_id, monitor_name, monitor_url, status, msg, duration_ms, tags, received_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                        ON CONFLICT DO NOTHING
                        """,
                        monitor_id,
                        m.get("name", ""),
                        m.get("url", ""),
                        status_val,
                        msg,
                        duration,
                        tags,
                        received_at,
                    )
                    heartbeat_count += 1

        # Delete monitors no longer in Uptime Kuma
        ids_to_delete = existing_ids - polled_ids
        deleted = 0
        if ids_to_delete:
            result = await conn.execute(
                "DELETE FROM monitor_registry WHERE monitor_id = ANY($1)",
                list(ids_to_delete),
            )
            deleted = int(result.split()[-1]) if result else 0

    stats = {
        "added": added,
        "updated": updated,
        "deleted": deleted,
        "total": len(monitors),
        "heartbeats": heartbeat_count,
    }
    logger.info(f"Polled {len(monitors)} monitors: +{added} new, ~{updated} updated, -{deleted} removed, {heartbeat_count} heartbeats synced")
    return stats


async def _poller_loop() -> None:
    """Background loop: poll on startup, then every POLL_INTERVAL_SECONDS."""
    # Poll immediately on startup
    await poll_kuma_registry()

    while True:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        try:
            await poll_kuma_registry()
        except Exception as e:
            logger.error(f"Poller loop error: {e}")


def start_poller() -> asyncio.Task:
    """Start the background poller and return the task."""
    return asyncio.create_task(_poller_loop())
