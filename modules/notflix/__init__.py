"""Notflix media stack poller — Sonarr, Radarr, Tautulli."""
MODULE_NAME = "notflix"
MODULE_DESCRIPTION = "Media library health and activity from Sonarr, Radarr, Tautulli"
MODULE_VERSION = "0.1.0"
ENABLED = True


def get_router():
    from .routes import router
    return router


async def collect():
    """Run the media poller."""
    from .collector import collect as _collect
    return await _collect()
