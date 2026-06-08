"""Hermes Agent framework integration — read-only polling."""
MODULE_NAME = "hermes"
MODULE_DESCRIPTION = "Hermes Agent analytics, session stats, and health monitoring"
MODULE_VERSION = "0.1.0"
ENABLED = True

MODULE_CONFIG_SCHEMA = {
    "hermes_url": {"type": "str", "default": "", "env": "HERMES_URL", "label": "Hermes API URL", "description": "Hermes Agent API base URL", "required": True, "placeholder": "http://dev-vm:9119"},
    "hermes_api_key": {"type": "secret", "default": "", "env": "HERMES_API_KEY", "label": "API Key", "required": False},
    "hermes_dashboard_session_token": {"type": "secret", "default": "", "env": "HERMES_DASHBOARD_SESSION_TOKEN", "label": "Dashboard Session Token", "required": False},
}


def get_router():
    from .routes import router
    return router


async def collect():
    """Run the Hermes stats poller."""
    from .collector import collect as _collect
    return await _collect()
