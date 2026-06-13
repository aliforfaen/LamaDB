"""Notification rule CRUD + fire endpoint + log."""
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import AuthUser, get_current_user
from app.db import get_pool
from .models import RuleCreate, RuleUpdate, RuleResponse, FireRequest, FireResponse

router = APIRouter(prefix="", tags=["notifications"])
logger = logging.getLogger(__name__)


def _require_auth(user: Annotated[AuthUser, Depends(get_current_user)]) -> AuthUser:
    """Require authenticated user."""
    return user


def _rule_from_row(row) -> RuleResponse:
    """Convert an asyncpg row to a RuleResponse."""
    d = dict(row)
    # Coerce UUID to string
    if d.get("id") is not None:
        d["id"] = str(d["id"])
    # Coerce JSONB channel_config
    cc = d.get("channel_config")
    if cc is not None and not isinstance(cc, dict):
        if isinstance(cc, str):
            cc = json.loads(cc)
        else:
            cc = dict(cc) if cc else {}
    d["channel_config"] = cc or {}
    # Tags asyncpg returns a Python list for TEXT[]
    if "match_tags" not in d:
        d["match_tags"] = []
    # last_fired_at
    if d.get("last_fired_at"):
        d["last_fired_at"] = d["last_fired_at"]
    return RuleResponse(**d)


def _log_from_row(row) -> dict:
    """Convert an asyncpg notification_log row to a dict."""
    d = dict(row)
    # Remove asyncpg internal 'id' if needed but keep it
    d.pop("nr", None)
    return d


@router.post("/rules", response_model=RuleResponse, status_code=status.HTTP_201_CREATED)
async def create_rule(
    rule: RuleCreate,
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Create a notification rule. Requires admin or agent role."""
    if user.role not in ("admin", "agent"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO notification_rules
               (name, description, match_source, match_type, match_severity,
                match_tags, channel, channel_config, priority, cooldown_seconds)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
               RETURNING *""",
            rule.name,
            rule.description,
            rule.match_source,
            rule.match_type,
            rule.match_severity,
            rule.match_tags,
            rule.channel,
            json.dumps(rule.channel_config),
            rule.priority,
            rule.cooldown_seconds,
        )
    return _rule_from_row(row)


@router.get("/rules", response_model=list[RuleResponse])
async def list_rules(user: Annotated[AuthUser, Depends(_require_auth)]):
    """List all notification rules."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT * FROM notification_rules
               ORDER BY
                 CASE priority
                   WHEN 'critical' THEN 1
                   WHEN 'high'     THEN 2
                   WHEN 'normal'   THEN 3
                   WHEN 'low'      THEN 4
                   ELSE 5
                 END ASC,
                 created_at DESC"""
        )
    return [_rule_from_row(r) for r in rows]


@router.get("/rules/{rule_id}", response_model=RuleResponse)
async def get_rule(rule_id: str, user: Annotated[AuthUser, Depends(_require_auth)]):
    """Get a single notification rule by ID."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM notification_rules WHERE id = $1",
            rule_id,
        )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return _rule_from_row(row)


@router.patch("/rules/{rule_id}", response_model=RuleResponse)
async def update_rule(
    rule_id: str,
    update: RuleUpdate,
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Partial update of a notification rule. Requires admin or agent role."""
    if user.role not in ("admin", "agent"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    # Build dynamic SET clause from non-None fields
    updates = []
    params = []
    idx = 1

    if update.name is not None:
        updates.append(f"name = ${idx}")
        params.append(update.name)
        idx += 1
    if update.description is not None:
        updates.append(f"description = ${idx}")
        params.append(update.description)
        idx += 1
    if update.enabled is not None:
        updates.append(f"enabled = ${idx}")
        params.append(update.enabled)
        idx += 1
    if update.match_source is not None:
        updates.append(f"match_source = ${idx}")
        params.append(update.match_source)
        idx += 1
    if update.match_type is not None:
        updates.append(f"match_type = ${idx}")
        params.append(update.match_type)
        idx += 1
    if update.match_severity is not None:
        updates.append(f"match_severity = ${idx}")
        params.append(update.match_severity)
        idx += 1
    if update.match_tags is not None:
        updates.append(f"match_tags = ${idx}")
        params.append(update.match_tags)
        idx += 1
    if update.channel is not None:
        updates.append(f"channel = ${idx}")
        params.append(update.channel)
        idx += 1
    if update.channel_config is not None:
        updates.append(f"channel_config = ${idx}")
        params.append(json.dumps(update.channel_config))
        idx += 1
    if update.priority is not None:
        updates.append(f"priority = ${idx}")
        params.append(update.priority)
        idx += 1
    if update.cooldown_seconds is not None:
        updates.append(f"cooldown_seconds = ${idx}")
        params.append(update.cooldown_seconds)
        idx += 1

    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    updates.append("updated_at = now()")
    params.append(rule_id)

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""UPDATE notification_rules
                SET {', '.join(updates)}
                WHERE id = ${idx}
                RETURNING *""",
            *params,
        )

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return _rule_from_row(row)


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: str, user: Annotated[AuthUser, Depends(_require_auth)]):
    """Delete a notification rule. Requires admin role."""
    if user.role not in ("admin",):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")

    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM notification_rules WHERE id = $1",
            rule_id,
        )
        if result == "DELETE 0":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return {"ok": True}


@router.post("/fire", response_model=FireResponse)
async def fire_notification(
    event: FireRequest,
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Evaluate all enabled rules against an event and dispatch notifications."""
    if user.role not in ("admin", "agent"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    from .engine import fire_event
    return await fire_event(event.model_dump())


@router.get("/log")
async def get_log(
    user: Annotated[AuthUser, Depends(_require_auth)],
    limit: int = Query(default=50, ge=1, le=200),
):
    """Get recent notification delivery log entries."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT nl.*, nr.name as rule_name
               FROM notification_log nl
               LEFT JOIN notification_rules nr ON nl.rule_id = nr.id
               ORDER BY nl.fired_at DESC
               LIMIT $1""",
            limit,
        )
    return {
        "log": [_log_from_row(r) for r in rows],
        "count": len(rows),
    }


# ---------------------------------------------------------------------------
# GET /api/notifications/unread
# ---------------------------------------------------------------------------

@router.get("/unread")
async def get_unread(
    user: Annotated[AuthUser, Depends(_require_auth)],
    limit: int = Query(default=20, ge=1, le=100),
):
    """Get top N actionable (unprocessed, warning/error/critical) events.

    Designed for the Overview page: a middle ground between 0 (all caught up) and
    the full /api/events stream (hundreds of rows). Returns events that are likely
    worth a human's attention — anything at warn/error/critical that hasn't been
    marked as processed yet.

    NOTE on severity names: the spec called for `('warning', 'error')` but the
    codebase uses the shorter forms `('warn', 'error', 'critical')` (see
    modules/ntfy/collector.py _priority_to_severity, modules/hermes/collector.py,
    modules/dozzle/collector.py). Using the actual values here so we don't miss
    events.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, ts, source, type, severity, title, body, tags, metadata
            FROM events
            WHERE processed = false
              AND severity IN ('warn', 'error', 'critical')
            ORDER BY ts DESC
            LIMIT $1
            """,
            limit,
        )

        total_row = await conn.fetchrow(
            """
            SELECT count(*) AS cnt
            FROM events
            WHERE processed = false
              AND severity IN ('warn', 'error', 'critical')
            """
        )

    items = []
    for r in rows:
        meta = r["metadata"]
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (ValueError, TypeError):
                meta = {}
        if not isinstance(meta, dict):
            meta = {}

        items.append({
            "id": r["id"],
            "ts": r["ts"].isoformat() if r["ts"] else None,
            "source": r["source"],
            "type": r["type"],
            "severity": r["severity"],
            "title": r["title"] or "",
            "body": r["body"] or "",
            "tags": list(r["tags"]) if r["tags"] else [],
            "metadata": meta,
        })

    return {
        "items": items,
        "count": len(items),
        "total_unread": total_row["cnt"] if total_row else 0,
    }


@router.get("/channels")
async def channel_status(user: Annotated[AuthUser, Depends(_require_auth)]):
    """Check which channels are configured and reachable."""
    from app.config import settings

    channels = {}

    # Telegram
    tg_token = getattr(settings, "telegram_bot_token", None)
    channels["telegram"] = {"configured": bool(tg_token)}

    # ntfy — configured if ntfy_url is set
    channels["ntfy"] = {"configured": bool(settings.ntfy_url)}

    return channels
