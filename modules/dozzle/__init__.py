# Module metadata for Dozzle log viewer integration
MODULE_NAME = "dozzle"
MODULE_DESCRIPTION = "Dozzle container log viewer and error aggregation"
MODULE_VERSION = "0.1.0"
ENABLED = True

MODULE_CONFIG_SCHEMA = {
    "dozzle_url": {"type": "str", "default": "", "env": "DOZZLE_URL", "label": "Dozzle URL", "description": "Dozzle log viewer API URL", "required": False, "placeholder": "http://probook:7080"},
}


def get_router():
    from .routes import router
    return router


def get_public_router():
    from .routes import public_router
    return public_router


async def collect():
    """Run the Dozzle log poller."""
    from .collector import collect as _collect
    return await _collect()
