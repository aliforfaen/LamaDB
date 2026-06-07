"""Smart Notification Routing module.

Routes events to Telegram, ntfy, and webhook channels based on
user-defined rules with AND-logic matching, priority ordering, and
cooldown enforcement.
"""
import logging

from .engine import seed_default_rules

MODULE_NAME = "notifications"
MODULE_DESCRIPTION = "Smart notification routing — Telegram, ntfy, webhook"
MODULE_VERSION = "0.1.0"
ENABLED = True

logger = logging.getLogger(__name__)


def get_router():
    """Return the authenticated API router for the notifications module."""
    from .routes import router
    return router


async def on_startup() -> None:
    """Seed default rules on first startup."""
    try:
        await seed_default_rules()
        logger.info("Notification default rules seeded")
    except Exception as e:
        logger.warning(f"Could not seed notification rules: {e}")
