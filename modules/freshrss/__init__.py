# Module metadata for FreshRSS GReader API integration
MODULE_NAME = "freshrss"
MODULE_DESCRIPTION = "RSS feed sync from FreshRSS via GReader API"
MODULE_VERSION = "0.1.0"
ENABLED = True


def get_router():
    from .routes import router
    return router


async def collect():
    """Run the FreshRSS RSS poller."""
    from .collector import collect as _collect
    return await _collect()
