"""Agent Board — coordination layer for AI agents."""
MODULE_NAME = "agent_board"
MODULE_DESCRIPTION = "Agent task queue, messaging, and LISTEN/NOTIFY coordination"
MODULE_VERSION = "0.1.0"
ENABLED = True

MODULE_MCP_TOOLS = [
    {
        "name": "get_agent_tasks",
        "description": "List agent tasks with optional status/priority filters",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter by status (pending, claimed, completed, failed)"},
                "priority": {"type": "string", "description": "Filter by priority (low, normal, high, critical)"},
                "limit": {"type": "integer", "description": "Max results (default 50)"},
            },
        },
        "handler": "modules.agent_board.mcp:get_agent_tasks",
        "toolset": "legacy",
        "module": "agent_board",
    },
    {
        "name": "send_agent_message",
        "description": "Send a message to another agent",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to_agent": {"type": "string", "description": "Recipient agent name"},
                "subject": {"type": "string", "description": "Message subject"},
                "body": {"type": "string", "description": "Message body"},
                "message_type": {"type": "string", "description": "Message type (info, alert, task)"},
                "metadata": {"type": "object", "description": "Additional metadata"},
            },
            "required": ["to_agent", "subject"],
        },
        "handler": "modules.agent_board.mcp:send_agent_message",
        "toolset": "legacy",
        "module": "agent_board",
    },
]


def get_router():
    from .routes import router
    return router
