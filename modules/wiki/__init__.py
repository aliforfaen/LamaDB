# Module metadata for Wiki reader, scratchpad, and edit log
MODULE_NAME = "wiki"
MODULE_DESCRIPTION = "Wiki reader, scratchpad, and edit log"
MODULE_VERSION = "0.1.0"
ENABLED = True

MODULE_MCP_TOOLS = [
    {
        "name": "wiki_search",
        "description": "Search wiki pages by title and content",
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Max results (default 20)"},
            },
            "required": ["q"],
        },
        "handler": "modules.wiki.mcp:wiki_search",
    },
    {
        "name": "scratchpad_capture",
        "description": "Save a scratchpad entry (quick note) to the wiki",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Note content"},
                "title": {"type": "string", "description": "Note title (default: Scratchpad)"},
            },
            "required": ["content"],
        },
        "handler": "modules.wiki.mcp:scratchpad_capture",
    },
]


def get_router():
    from .routes import router

    return router
