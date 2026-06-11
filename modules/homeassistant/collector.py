"""Collector for polling Home Assistant entity states."""
import json
import logging
import os
from datetime import datetime, timezone

import httpx

from app.db import get_pool
from app.config import settings

logger = logging.getLogger(__name__)


async def collect() -> dict:
    """Fetch all HA entity states and store as a document snapshot."""
    ha_url = settings.homeassistant_url or os.environ.get("HOMEASSISTANT_URL", "") or os.environ.get("HA_URL", "")
    ha_token = settings.homeassistant_token or os.environ.get("HOMEASSISTANT_TOKEN", "") or os.environ.get("HA_TOKEN", "")
    if not ha_url or not ha_token:
        logger.warning("Home Assistant not configured — skipping collect")
        return {"error": "Home Assistant not configured"}

    headers = {
        "Authorization": f"Bearer {ha_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        # Fetch all states
        resp = await client.get(f"{ha_url}/api/states", headers=headers)
        resp.raise_for_status()
        entities = resp.json()

        # Fetch config for metadata
        try:
            config_resp = await client.get(f"{ha_url}/api/config", headers=headers)
            config_resp.raise_for_status()
            config = config_resp.json()
        except Exception:
            config = {}

    # Store as a document
    pool = get_pool()
    now = datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        # Upsert the snapshot document (use source_type + unique title to avoid duplicates)
        existing = await conn.fetchval(
            "SELECT id FROM documents WHERE source_type = 'homeassistant_snapshot' AND title = 'HA State Snapshot'"
        )
        doc_data = {
            "entity_count": len(entities),
            "ha_version": config.get("version", "unknown"),
            "location": config.get("location_name", "unknown"),
        }

        if existing:
            await conn.execute(
                """UPDATE documents
                   SET content = $1, metadata = $2, updated_at = $3
                   WHERE id = $4""",
                json.dumps(entities),
                json.dumps(doc_data),
                now,
                existing,
            )
        else:
            await conn.execute(
                """INSERT INTO documents (source_type, title, content, metadata, tags, created_at, updated_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                "homeassistant_snapshot",
                "HA State Snapshot",
                json.dumps(entities),
                json.dumps(doc_data),
                ["homeassistant", "snapshot"],
                now,
                now,
            )

    return {"entities": len(entities), "ha_version": config.get("version", "unknown")}
