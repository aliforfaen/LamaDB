"""YouTube integration module — polls Watch Later playlist and watch history."""
MODULE_NAME = "youtube"
MODULE_DESCRIPTION = "YouTube watch history and Watch Later playlist ingestion"
MODULE_VERSION = "0.1.0"
ENABLED = True

MODULE_CONFIG_SCHEMA = {
    "youtube_api_key": {"type": "secret", "default": "", "env": "YOUTUBE_API_KEY", "label": "YouTube Data API v3 Key", "required": True},
    "youtube_channel_id": {"type": "str", "default": "", "env": "YOUTUBE_CHANNEL_ID", "label": "YouTube Channel ID (for upload/history proxy)", "required": False},
    "youtube_watch_later_playlist_id": {"type": "str", "default": "", "env": "YOUTUBE_WATCH_LATER_PLAYLIST_ID", "label": "Watch Later playlist ID(s), comma-separated", "required": False},
    "youtube_poll_interval": {"type": "int", "default": 3600, "env": "YOUTUBE_POLL_INTERVAL", "label": "Poll interval (seconds)", "required": False, "restart_required": True},
}


def get_router():
    from .routes import router
    return router


async def collect():
    """Run the YouTube poller."""
    from .collector import collect as _collect
    return await _collect()
