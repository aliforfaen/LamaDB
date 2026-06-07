# Module metadata for feeds RSS generator
MODULE_NAME = "feeds"
MODULE_DESCRIPTION = "RSS feed generator from LamaDB documents"
MODULE_VERSION = "0.1.0"
ENABLED = True
PUBLIC_PREFIX = False  # RSS XML endpoints served at root (/feeds/{slug}.xml)


def get_router():
    """Return the authenticated API router for the feeds module."""
    from .routes import router
    return router


def get_public_router():
    """Return the public (no-auth) router for RSS XML endpoints."""
    from .routes import public_router
    return public_router
