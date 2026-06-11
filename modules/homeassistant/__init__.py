"""Home Assistant integration — entity states, service calls."""
MODULE_NAME = "homeassistant"
MODULE_DESCRIPTION = "Home Assistant entity monitoring and service calls"
MODULE_VERSION = "0.1.0"
ENABLED = True

MODULE_CONFIG_SCHEMA = {
    "homeassistant_url": {
        "type": "str", "default": "", "env": "HOMEASSISTANT_URL",
        "label": "Home Assistant URL",
        "description": "Base URL of your HA instance (e.g. http://ha.local:8123)",
        "required": True, "placeholder": "http://ha.local:8123"
    },
    "homeassistant_token": {
        "type": "secret", "default": "", "env": "HOMEASSISTANT_TOKEN",
        "label": "Long-Lived Access Token",
        "description": "Generate in HA: Profile → Long-Lived Access Tokens",
        "required": True
    },
    "homeassistant_highlight_entities": {
        "type": "str", "default": "",
        "env": "HOMEASSISTANT_HIGHLIGHT_ENTITIES",
        "label": "Highlight Entities",
        "description": "Comma-separated entity_ids to highlight on the dashboard (empty = show all)",
        "required": False
    },
}


def get_router():
    from .routes import router
    return router


async def collect():
    """Run the Home Assistant poller."""
    from .collector import collect as _collect
    return await _collect()
