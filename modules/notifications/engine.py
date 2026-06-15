"""Notification routing engine: rule matching + channel dispatch."""
import json
import logging
from datetime import datetime
from typing import Optional

import httpx

from app.db import get_pool
from app.config import settings
from .models import FireResponse

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Rule matching
# ─────────────────────────────────────────────────────────────────

def _rule_matches(rule: dict, event: dict) -> bool:
    """Check if a rule matches an event. All non-null conditions must match (AND logic)."""
    if rule.get("match_source") and rule["match_source"] != event.get("source"):
        return False
    if rule.get("match_type") and rule["match_type"] != event.get("type"):
        return False
    if rule.get("match_severity") and rule["match_severity"] != event.get("severity"):
        return False
    if rule.get("match_tags"):
        event_tags = set(event.get("tags", []))
        required_tags = set(rule["match_tags"])
        if not required_tags.issubset(event_tags):
            return False
    return True


async def _check_cooldown(conn, rule: dict) -> bool:
    """Return True if the rule can fire (cooldown has elapsed or is 0/None)."""
    cooldown = rule.get("cooldown_seconds")
    if not cooldown or cooldown <= 0:
        return True
    last_fired = rule.get("last_fired_at")
    if not last_fired:
        return True
    elapsed = (datetime.utcnow() - last_fired.replace(tzinfo=None)).total_seconds()
    return elapsed >= cooldown


# ─────────────────────────────────────────────────────────────────
# Channel dispatchers
# ─────────────────────────────────────────────────────────────────

async def _dispatch_telegram(config: dict, title: str, body: str) -> dict:
    """Send a message via Telegram bot API."""
    chat_id = config.get("chat_id", "7521274750")
    token = config.get("bot_token")

    if not token:
        token = getattr(settings, "telegram_bot_token", None)
    if not token:
        return {"status": "failed", "error": "No Telegram bot token configured"}

    # Strip markdown bold from title to avoid parse errors
    clean_title = title.replace("*", "")
    message = f"*{clean_title}*\n{body}" if body else clean_title

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "Markdown",
                    "disable_notification": False,
                },
            )
            if resp.status_code == 200:
                return {"status": "sent"}
            return {"status": "failed", "error": f"Telegram API: {resp.status_code}"}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


async def _dispatch_ntfy(config: dict, title: str, body: str) -> dict:
    """Send a notification via ntfy."""
    topic = config.get("topic", "hermes-worker")
    server = config.get("server", settings.ntfy_url)
    priority = config.get("priority", "default")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{server}/{topic}",
                content=body.encode("utf-8") if body else b"",
                headers={
                    "Title": title,
                    "Priority": priority,
                    "Tags": "loudspeaker",
                },
            )
            if resp.status_code == 200:
                return {"status": "sent"}
            return {"status": "failed", "error": f"ntfy API: {resp.status_code}"}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


async def _dispatch_webhook(config: dict, event: dict) -> dict:
    """POST event payload to a webhook URL."""
    url = config.get("url")
    if not url:
        return {"status": "failed", "error": "No webhook URL configured"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=event)
            if resp.status_code < 500:
                return {"status": "sent"}
            return {"status": "failed", "error": f"Webhook: {resp.status_code}"}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


async def _dispatch(rule: dict, event: dict) -> dict:
    """Dispatch a notification to the configured channel."""
    channel = rule.get("channel", "")
    config = rule.get("channel_config", {}) or {}
    title = event.get("title", "Notification")
    body = event.get("body", "")

    if channel == "telegram":
        return await _dispatch_telegram(config, title, body)
    elif channel == "ntfy":
        return await _dispatch_ntfy(config, title, body)
    elif channel == "webhook":
        return await _dispatch_webhook(config, event)
    else:
        return {"status": "failed", "error": f"Unknown channel: {channel}"}


# ─────────────────────────────────────────────────────────────────
# Main fire function
# ─────────────────────────────────────────────────────────────────

async def fire_event(event: dict) -> FireResponse:
    """Match an event against enabled rules and dispatch to all matching channels."""
    pool = get_pool()

    # Load all enabled rules ordered by priority
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT * FROM notification_rules
               WHERE enabled = true
               ORDER BY
                 CASE priority
                   WHEN 'critical' THEN 1
                   WHEN 'high'     THEN 2
                   WHEN 'normal'   THEN 3
                   WHEN 'low'      THEN 4
                   ELSE 5
                 END ASC"""
        )

    rules_matched = 0
    notifications_sent = 0
    results = []

    async with pool.acquire() as conn:
        for row in rows:
            rule = dict(row)
            # Coerce JSONB channel_config from string to dict (asyncpg returns JSONB as str)
            cc = rule.get("channel_config")
            if cc is not None and not isinstance(cc, dict):
                if isinstance(cc, str):
                    cc = json.loads(cc)
                else:
                    cc = dict(cc) if cc else {}
            rule["channel_config"] = cc or {}
            if not _rule_matches(rule, event):
                continue
            rules_matched += 1

            # Check cooldown
            if not await _check_cooldown(conn, rule):
                await conn.execute(
                    """INSERT INTO notification_log
                          (rule_id, event_id, channel, status, message)
                       VALUES ($1, $2, $3, 'cooldown', 'In cooldown')""",
                    rule["id"], event.get("id"), rule["channel"],
                )
                results.append({
                    "rule_id": str(rule["id"]),
                    "rule_name": rule["name"],
                    "channel": rule["channel"],
                    "status": "cooldown",
                })
                continue

            # Dispatch
            result = await _dispatch(rule, event)
            result["rule_id"] = str(rule["id"])
            result["rule_name"] = rule["name"]
            result["channel"] = rule["channel"]
            results.append(result)

            # Update tracking on success
            if result.get("status") == "sent":
                await conn.execute(
                    """UPDATE notification_rules
                       SET last_fired_at = now(),
                           fire_count = fire_count + 1,
                           updated_at = now()
                       WHERE id = $1""",
                    rule["id"],
                )
                notifications_sent += 1

            # Log
            await conn.execute(
                """INSERT INTO notification_log
                      (rule_id, event_id, channel, status, message, error)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                rule["id"],
                event.get("id"),
                rule["channel"],
                result.get("status"),
                result.get("message", ""),
                result.get("error"),
            )

    return FireResponse(
        event_id=event.get("id", 0),
        rules_matched=rules_matched,
        notifications_sent=notifications_sent,
        results=results,
    )


# ─────────────────────────────────────────────────────────────────
# Seed default rules
# ─────────────────────────────────────────────────────────────────

async def seed_default_rules() -> None:
    """Create 3 default notification rules if the table is empty."""
    pool = get_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM notification_rules")
        if count > 0:
            return

    defaults = [
        {
            "name": "Critical alerts → Telegram",
            "match_severity": "critical",
            "channel": "telegram",
            "priority": "critical",
            "channel_config": {"chat_id": "7521274750"},
        },
        {
            "name": "Uptime breaking → ntfy",
            "match_source": "uptime_kuma",
            "match_tags": ["breaking"],
            "channel": "ntfy",
            "priority": "high",
            "channel_config": {"topic": "hermes-worker", "priority": "high"},
        },
        {
            "name": "New media content → Telegram",
            "match_source": "notflix",
            "match_type": "new_content",
            "channel": "telegram",
            "priority": "low",
            "cooldown_seconds": 3600,
            "channel_config": {"chat_id": "7521274750"},
        },
    ]

    async with pool.acquire() as conn:
        for d in defaults:
            await conn.execute(
                """INSERT INTO notification_rules
                      (name, description, match_source, match_type, match_severity,
                       match_tags, channel, channel_config, priority, cooldown_seconds)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
                d["name"],
                "",
                d.get("match_source"),
                d.get("match_type"),
                d.get("match_severity"),
                d.get("match_tags", []),
                d["channel"],
                json.dumps(d.get("channel_config", {})),
                d.get("priority", "normal"),
                d.get("cooldown_seconds", 0),
            )
