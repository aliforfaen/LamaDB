# Module metadata for ntfy notifications integration
MODULE_NAME = "ntfy"
MODULE_DESCRIPTION = "ntfy notification receiver and poller"
MODULE_VERSION = "0.1.0"
ENABLED = True


def get_router():
    from .routes import router
    return router


async def collect():
    """Run the ntfy notification poller."""
    from .collector import collect as _collect
    return await _collect()
