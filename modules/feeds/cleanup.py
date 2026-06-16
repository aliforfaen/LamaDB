"""Feed entry pruning — removes old agent_feed documents based on retention policy."""
import logging

from app.db import get_pool

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 60


async def prune_feed_entries(retention_days: int = DEFAULT_RETENTION_DAYS) -> dict:
    """
    Delete agent_feed documents older than retention_days.
    Returns count of deleted entries.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM documents
            WHERE source_type = 'agent_feed'
              AND created_at < now() - $1::interval
            """,
            f"{retention_days} days",
        )
        count = int(result.split()[-1]) if result.startswith("DELETE") else 0
        if count > 0:
            logger.info(f"Pruned {count} feed entries older than {retention_days} days")
        return {"pruned": count, "retention_days": retention_days}
