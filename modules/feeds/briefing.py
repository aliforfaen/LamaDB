"""Morning brief generator — creates a briefing feed entry from LamaDB data."""
import json
import logging
from datetime import datetime, timezone

from app.db import get_pool

logger = logging.getLogger(__name__)


async def generate_morning_brief() -> dict:
    """
    Generate a morning brief by querying LamaDB for notable overnight activity.
    Returns the published document info.

    Queries (gracefully degrades if any source has no recent events):
      1. Overnight uptime incidents (last 12h, warning/critical)
      2. Recent kanban task completions (last 12h)
      3. New Plex content via notflix events (last 24h)
      4. Unread warning/critical notification count
      5. Active agents (last 12h)

    Writes one document to source_type='agent_feed' with tags
    ['briefing', 'digest', 'morning'] so it appears in the 'briefing' feed.
    """
    pool = get_pool()
    sections = []

    async with pool.acquire() as conn:
        # 1. Overnight uptime incidents
        try:
            incidents = await conn.fetch(
                """
                SELECT title, severity, ts FROM events
                WHERE source = 'uptime_kuma' AND severity IN ('critical', 'warning')
                  AND ts > now() - interval '12 hours'
                ORDER BY ts DESC LIMIT 5
                """
            )
            if incidents:
                lines = [f"- {r['title']} ({r['severity']})" for r in incidents]
                sections.append("## Service Incidents\n" + "\n".join(lines))
        except Exception as e:
            logger.warning(f"Morning brief: uptime incidents query failed: {e}")

        # 2. Recent kanban completions
        try:
            completions = await conn.fetch(
                """
                SELECT title, ts FROM events
                WHERE source = 'kanban' AND type = 'task_completed'
                  AND ts > now() - interval '12 hours'
                ORDER BY ts DESC LIMIT 5
                """
            )
            if completions:
                lines = [f"- {r['title']}" for r in completions]
                sections.append("## Tasks Completed\n" + "\n".join(lines))
        except Exception as e:
            logger.warning(f"Morning brief: kanban completions query failed: {e}")

        # 3. New Plex content
        try:
            new_media = await conn.fetch(
                """
                SELECT title, ts FROM events
                WHERE source = 'notflix' AND type = 'new_content'
                  AND ts > now() - interval '24 hours'
                ORDER BY ts DESC LIMIT 5
                """
            )
            if new_media:
                lines = [f"- {r['title']}" for r in new_media]
                sections.append("## New Media\n" + "\n".join(lines))
        except Exception as e:
            logger.warning(f"Morning brief: notflix new_content query failed: {e}")

        # 4. Unread notification count
        try:
            unread = await conn.fetchval(
                """
                SELECT count(*) FROM events
                WHERE processed = false AND severity IN ('warning', 'critical')
                """
            )
            if unread and unread > 0:
                sections.append(
                    f"## Notifications\n- {unread} unread notifications require attention"
                )
        except Exception as e:
            logger.warning(f"Morning brief: unread count query failed: {e}")

        # 5. Active agents
        try:
            agents = await conn.fetch(
                """
                SELECT name, last_active_at FROM users
                WHERE type = 'agent' AND status = 'active'
                  AND last_active_at > now() - interval '12 hours'
                ORDER BY last_active_at DESC LIMIT 5
                """
            )
            if agents:
                lines = [
                    f"- {r['name']} (active {r['last_active_at'].strftime('%H:%M')})"
                    for r in agents
                ]
                sections.append("## Active Agents\n" + "\n".join(lines))
        except Exception as e:
            logger.warning(f"Morning brief: active agents query failed: {e}")

    now = datetime.now(timezone.utc)
    if not sections:
        content = "Quiet night — nothing notable to report. All systems nominal."
        title = f"Morning Brief — {now.strftime('%B %d, %Y')} — All Clear"
    else:
        content = "\n\n".join(sections)
        title = f"Morning Brief — {now.strftime('%B %d, %Y')}"

    async with pool.acquire() as conn:
        doc_id = await conn.fetchval(
            """
            INSERT INTO documents (source_type, title, content, tags, metadata)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            "agent_feed",
            title,
            content,
            ["briefing", "digest", "morning"],
            json.dumps({"brief_type": "morning", "generated_at": now.isoformat()}),
        )

    logger.info(f"Morning brief published: {doc_id} ({title})")
    return {
        "status": "published",
        "document_id": str(doc_id),
        "title": title,
        "sections": len(sections),
    }