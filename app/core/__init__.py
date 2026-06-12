"""Core module — document/event operations and agent docs."""

MODULE_MCP_TOOLS = [
    {
        "name": "lamadb_docs",
        "description": "Read LamaDB documentation. topic='api' for full agent API reference.",
        "handler": "app.core.mcp:lamadb_docs",
    },
]
