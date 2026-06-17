"""Kanban module — agent-orchestrated task boards backed by LamaDB."""
MODULE_NAME = "kanban"
MODULE_DESCRIPTION = "Kanban boards with agent task orchestration"
MODULE_VERSION = "0.1.0"
ENABLED = True

MODULE_MCP_TOOLS = [
    {"name": "kanban_my_tasks", "description": "Get open tasks assigned to the calling agent", "handler": "modules.kanban.mcp:kanban_my_tasks", "toolset": "legacy", "module": "kanban"},
    {"name": "kanban_find_work", "description": "Find unassigned backlog tasks to pick up", "handler": "modules.kanban.mcp:kanban_find_work", "toolset": "legacy", "module": "kanban"},
    {"name": "kanban_claim_task", "description": "Claim a task and move it to In Progress", "handler": "modules.kanban.mcp:kanban_claim_task", "toolset": "legacy", "module": "kanban"},
    {"name": "kanban_start_task", "description": "Start working on a task (auto-claims if unassigned)", "handler": "modules.kanban.mcp:kanban_start_task", "toolset": "legacy", "module": "kanban"},
    {"name": "kanban_complete_task", "description": "Complete a task and auto-start dependents", "handler": "modules.kanban.mcp:kanban_complete_task", "toolset": "legacy", "module": "kanban"},
    {"name": "kanban_create_task", "description": "Create a new task in a board", "handler": "modules.kanban.mcp:kanban_create_task", "toolset": "legacy", "module": "kanban"},
    {"name": "kanban_create_from_template", "description": "Create a new kanban task from a template. Pre-fills title, description, priority, tags, and subtasks.", "inputSchema": {"type": "object", "properties": {"board_id": {"type": "string", "description": "Board ID"}, "template_id": {"type": "string", "description": "Template ID"}, "title_override": {"type": "string", "description": "Override template title (optional)"}}, "required": ["board_id", "template_id"]}, "handler": "modules.kanban.mcp:kanban_create_from_template", "toolset": "legacy", "module": "kanban"},
    {"name": "kanban_update_task", "description": "Update task fields", "handler": "modules.kanban.mcp:kanban_update_task", "toolset": "legacy", "module": "kanban"},
    {"name": "kanban_add_comment", "description": "Add a comment to a task", "handler": "modules.kanban.mcp:kanban_add_comment", "toolset": "legacy", "module": "kanban"},
    {"name": "kanban_get_task", "description": "Get full task details with subtasks and comments", "handler": "modules.kanban.mcp:kanban_get_task", "toolset": "legacy", "module": "kanban"},
    {"name": "kanban_help_wanted", "description": "Flag a task as needing human help", "handler": "modules.kanban.mcp:kanban_help_wanted", "toolset": "legacy", "module": "kanban"},
    {"name": "kanban_my_instructions", "description": "Get the calling agent's instructions", "handler": "modules.kanban.mcp:kanban_my_instructions", "toolset": "legacy", "module": "kanban"},
]

def get_router():
    from .routes import router
    return router
