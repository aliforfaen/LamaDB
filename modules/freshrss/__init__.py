# Module metadata for FreshRSS GReader API integration
MODULE_NAME = "freshrss"
MODULE_DESCRIPTION = "RSS feed sync from FreshRSS via GReader API"
MODULE_VERSION = "0.1.0"
ENABLED = True

MODULE_CONFIG_SCHEMA = {
    "freshrss_url": {"type": "str", "default": "", "env": "FRESHRSS_URL", "label": "FreshRSS URL", "description": "GReader API base URL", "required": True, "placeholder": "http://valhalla:8780/api"},
    "freshrss_username": {"type": "str", "default": "", "env": "FRESHRSS_USERNAME", "label": "Username", "required": False},
    "freshrss_api_password": {"type": "secret", "default": "", "env": "FRESHRSS_API_PASSWORD", "label": "API Password", "required": False},
}


def get_router():
    from .routes import router
    return router


async def collect():
    """Run the FreshRSS RSS poller."""
    from .collector import collect as _collect
    return await _collect()
