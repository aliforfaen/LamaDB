"""Hermes Agent framework integration — read-only polling."""
MODULE_NAME = "hermes"
MODULE_DESCRIPTION = "Hermes Agent analytics, session stats, and health monitoring"
MODULE_VERSION = "0.1.0"
ENABLED = True


def get_router():
    from .routes import router
    return router


async def collect():
    """Run the Hermes stats poller."""
    from .collector import collect as _collect
    return await _collect()
