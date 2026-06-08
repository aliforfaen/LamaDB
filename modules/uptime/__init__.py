# Module metadata for Uptime Kuma webhook integration
MODULE_NAME = "uptime"
MODULE_DESCRIPTION = "Uptime Kuma webhook receiver and monitor status tracking"
MODULE_VERSION = "0.1.0"
ENABLED = True

MODULE_CONFIG_SCHEMA = {
    "uptime_kuma_url": {"type": "str", "default": "", "env": "UPTIME_KUMA_URL", "label": "Uptime Kuma URL", "required": False},
    "uptime_kuma_api_key": {"type": "secret", "default": "", "env": "UPTIME_KUMA_API_KEY", "label": "API Key", "required": False},
    "uptime_kuma_user": {"type": "str", "default": "", "env": "UPTIME_KUMA_USER", "label": "Username", "required": False},
    "uptime_kuma_password": {"type": "secret", "default": "", "env": "UPTIME_KUMA_PASSWORD", "label": "Password", "required": False},
}

MODULE_MCP_TOOLS = [
    {
        "name": "get_uptime_status",
        "description": "Get the current status of all monitored services (up/down/pending)",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": "modules.uptime.mcp:get_uptime_status",
    },
    {
        "name": "get_uptime_history",
        "description": "Get recent status history for monitors",
        "inputSchema": {
            "type": "object",
            "properties": {
                "monitor_id": {"type": "string", "description": "Optional monitor ID to filter"},
                "limit": {"type": "integer", "description": "Max results (default 50)"},
            },
        },
        "handler": "modules.uptime.mcp:get_uptime_history",
    },
]


def get_router():
    from .routes import router
    return router
