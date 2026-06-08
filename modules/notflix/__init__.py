"""Notflix media stack poller — Sonarr, Radarr, Tautulli."""
MODULE_NAME = "notflix"
MODULE_DESCRIPTION = "Media library health and activity from Sonarr, Radarr, Tautulli"
MODULE_VERSION = "0.1.0"
ENABLED = True

MODULE_CONFIG_SCHEMA = {
    "sonarr_url": {"type": "str", "default": "", "env": "SONARR_URL", "label": "Sonarr URL", "required": False},
    "sonarr_api_key": {"type": "secret", "default": "", "env": "SONARR_API_KEY", "label": "Sonarr API Key", "required": False},
    "radarr_url": {"type": "str", "default": "", "env": "RADARR_URL", "label": "Radarr URL", "required": False},
    "radarr_api_key": {"type": "secret", "default": "", "env": "RADARR_API_KEY", "label": "Radarr API Key", "required": False},
    "tautulli_url": {"type": "str", "default": "", "env": "TAUTULLI_URL", "label": "Tautulli URL", "required": False},
    "tautulli_api_key": {"type": "secret", "default": "", "env": "TAUTULLI_API_KEY", "label": "Tautulli API Key", "required": False},
}


def get_router():
    from .routes import router
    return router


async def collect():
    """Run the media poller."""
    from .collector import collect as _collect
    return await _collect()
