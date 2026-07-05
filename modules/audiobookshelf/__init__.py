"""Audiobookshelf integration module — polls libraries and listening progress."""
MODULE_NAME = "audiobookshelf"
MODULE_DESCRIPTION = "Self-hosted audiobook & podcast library and listening progress from Audiobookshelf"
MODULE_VERSION = "0.1.0"
ENABLED = True

MODULE_CONFIG_SCHEMA = {
    "audiobookshelf_url": {
        "type": "str",
        "default": "",
        "env": "AUDIOBOOKSHELF_URL",
        "label": "Audiobookshelf Base URL",
        "required": True,
    },
    "audiobookshelf_token": {
        "type": "secret",
        "default": "",
        "env": "AUDIOBOOKSHELF_TOKEN",
        "label": "Audiobookshelf API Token (Bearer)",
        "required": True,
    },
    "audiobookshelf_poll_interval": {
        "type": "int",
        "default": 1800,
        "env": "AUDIOBOOKSHELF_POLL_INTERVAL",
        "label": "Poll interval (seconds)",
        "required": False,
        "restart_required": True,
    },
    "audiobookshelf_max_books_per_library": {
        "type": "int",
        "default": 50,
        "env": "AUDIOBOOKSHELF_MAX_BOOKS_PER_LIBRARY",
        "label": "Max books fetched per library per poll",
        "required": False,
        "restart_required": False,
    },
}


def get_router():
    from .routes import router
    return router


async def collect():
    """Run the Audiobookshelf poller."""
    from .collector import collect as _collect
    return await _collect()