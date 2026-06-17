"""MCP consolidated tools — action-based dispatchers that group related tools.

Each consolidated tool is a single MCP tool that accepts an `action` enum
parameter and dispatches to the underlying handler. This shrinks the tool
catalog from 29 flat tools to 11 action-based tools while keeping all
existing handlers untouched.

Tool → Action → Handler map (see register_all() below):
  agent_documents     search, get, create, update
  agent_events        create, list
  agent_wiki          search, scratch
  agent_uptime        status, history
  lamadb_docs         (passthrough — no action)
  agent_kanban_tasks    my_tasks, find_work, get, create, create_from_template, update
  agent_kanban_workflow claim, start, complete, help_wanted
  agent_kanban_comments add
  agent_kanban_meta    my_instructions
  agent_messages        list_tasks, send
  admin_secrets         list, metadata, reveal, request_access
"""
import logging
from app.mcp_registry import register_consolidated_tool, register_tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Handler imports — done lazily to keep module import order safe.
# ---------------------------------------------------------------------------
def _core_handlers():
    from app.core.mcp import (
        search_documents,
        get_document,
        create_document,
        update_document,
        create_event,
        get_events,
        lamadb_docs,
    )
    return {
        "search_documents": search_documents,
        "get_document": get_document,
        "create_document": create_document,
        "update_document": update_document,
        "create_event": create_event,
        "get_events": get_events,
        "lamadb_docs": lamadb_docs,
    }


def _wiki_handlers():
    from modules.wiki.mcp import wiki_search, scratchpad_capture
    return {"wiki_search": wiki_search, "scratchpad_capture": scratchpad_capture}


def _uptime_handlers():
    from modules.uptime.mcp import get_uptime_status, get_uptime_history
    return {"get_uptime_status": get_uptime_status, "get_uptime_history": get_uptime_history}


def _kanban_handlers():
    from modules.kanban.mcp import (
        kanban_my_tasks,
        kanban_find_work,
        kanban_get_task,
        kanban_create_task,
        kanban_create_from_template,
        kanban_update_task,
        kanban_claim_task,
        kanban_start_task,
        kanban_complete_task,
        kanban_help_wanted,
        kanban_add_comment,
        kanban_my_instructions,
    )
    return {
        "kanban_my_tasks": kanban_my_tasks,
        "kanban_find_work": kanban_find_work,
        "kanban_get_task": kanban_get_task,
        "kanban_create_task": kanban_create_task,
        "kanban_create_from_template": kanban_create_from_template,
        "kanban_update_task": kanban_update_task,
        "kanban_claim_task": kanban_claim_task,
        "kanban_start_task": kanban_start_task,
        "kanban_complete_task": kanban_complete_task,
        "kanban_help_wanted": kanban_help_wanted,
        "kanban_add_comment": kanban_add_comment,
        "kanban_my_instructions": kanban_my_instructions,
    }


def _agent_board_handlers():
    from modules.agent_board.mcp import get_agent_tasks, send_agent_message
    return {"get_agent_tasks": get_agent_tasks, "send_agent_message": send_agent_message}


def _secrets_handlers():
    from modules.secrets.mcp import (
        list_secrets,
        get_secret_metadata,
        reveal_secret,
        request_secret_access,
    )
    return {
        "list_secrets": list_secrets,
        "get_secret_metadata": get_secret_metadata,
        "reveal_secret": reveal_secret,
        "request_secret_access": request_secret_access,
    }


# ---------------------------------------------------------------------------
# Consolidated tool registration
# ---------------------------------------------------------------------------
def register_all() -> None:
    """Register all 11 consolidated tools."""
    core = _core_handlers()
    wiki = _wiki_handlers()
    uptime = _uptime_handlers()
    kanban = _kanban_handlers()
    agent_board = _agent_board_handlers()
    secrets = _secrets_handlers()

    # 1. agent_documents — search/get/create/update documents
    register_consolidated_tool(
        name="agent_documents",
        description="Document CRUD. Actions: search, get, create, update.",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["search", "get", "create", "update"]},
                "q": {"type": "string"},
                "limit": {"type": "integer"},
                "id": {"type": "string"},
                "title": {"type": "string"},
                "source_type": {"type": "string"},
                "content": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "metadata": {"type": "object"},
            },
            "required": ["action"],
        },
        actions={
            "search": core["search_documents"],
            "get": core["get_document"],
            "create": core["create_document"],
            "update": core["update_document"],
        },
        toolset="both",
        module="documents",
    )

    # 2. agent_events — create/list events
    register_consolidated_tool(
        name="agent_events",
        description="Event bus. Actions: create, list.",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create", "list"]},
                "source": {"type": "string"},
                "event_type": {"type": "string"},
                "title": {"type": "string"},
                "severity": {"type": "string", "enum": ["info", "warning", "critical"]},
                "body": {"type": "string"},
                "metadata": {"type": "object"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer"},
            },
            "required": ["action"],
        },
        actions={
            "create": core["create_event"],
            "list": core["get_events"],
        },
        toolset="both",
        module="events",
    )

    # 3. agent_wiki — search pages / capture scratchpad
    register_consolidated_tool(
        name="agent_wiki",
        description="Wiki pages. Actions: search, scratch.",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["search", "scratch"]},
                "q": {"type": "string"},
                "limit": {"type": "integer"},
                "content": {"type": "string"},
                "title": {"type": "string"},
            },
            "required": ["action"],
        },
        actions={
            "search": wiki["wiki_search"],
            "scratch": wiki["scratchpad_capture"],
        },
        toolset="both",
        module="wiki",
    )

    # 4. agent_uptime — status / history
    register_consolidated_tool(
        name="agent_uptime",
        description="Uptime monitors. Actions: status, history.",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["status", "history"]},
                "monitor_id": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["action"],
        },
        actions={
            "status": uptime["get_uptime_status"],
            "history": uptime["get_uptime_history"],
        },
        toolset="both",
        module="uptime",
    )

    # 5. lamadb_docs — passthrough (no action dispatch)
    register_tool(
        name="lamadb_docs",
        description="LamaDB docs. topic='api' for full reference.",
        inputSchema={
            "type": "object",
            "properties": {"topic": {"type": "string", "default": "api"}},
        },
        handler=core["lamadb_docs"],
        toolset="both",
        module="",
    )

    # 6. agent_kanban_tasks — task CRUD + discovery
    register_consolidated_tool(
        name="agent_kanban_tasks",
        description="Kanban tasks. Actions: my_tasks, find_work, get, create, create_from_template, update.",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "my_tasks", "find_work", "get", "create",
                        "create_from_template", "update",
                    ],
                },
                "board_id": {"type": "string"},
                "task_id": {"type": "string"},
                "template_id": {"type": "string"},
                "title": {"type": "string"},
                "title_override": {"type": "string"},
                "description": {"type": "string"},
                "priority": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["action"],
        },
        actions={
            "my_tasks": kanban["kanban_my_tasks"],
            "find_work": kanban["kanban_find_work"],
            "get": kanban["kanban_get_task"],
            "create": kanban["kanban_create_task"],
            "create_from_template": kanban["kanban_create_from_template"],
            "update": kanban["kanban_update_task"],
        },
        toolset="both",
        module="kanban",
    )

    # 7. agent_kanban_workflow — claim/start/complete/help_wanted
    register_consolidated_tool(
        name="agent_kanban_workflow",
        description="Kanban lifecycle. Actions: claim, start, complete, help_wanted.",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["claim", "start", "complete", "help_wanted"],
                },
                "task_id": {"type": "string"},
                "summary": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["action"],
        },
        actions={
            "claim": kanban["kanban_claim_task"],
            "start": kanban["kanban_start_task"],
            "complete": kanban["kanban_complete_task"],
            "help_wanted": kanban["kanban_help_wanted"],
        },
        toolset="both",
        module="kanban",
    )

    # 8. agent_kanban_comments — add comment
    register_consolidated_tool(
        name="agent_kanban_comments",
        description="Kanban comments. Actions: add.",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add"]},
                "task_id": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["action"],
        },
        actions={"add": kanban["kanban_add_comment"]},
        toolset="both",
        module="kanban",
    )

    # 9. agent_kanban_meta — my_instructions
    register_consolidated_tool(
        name="agent_kanban_meta",
        description="Kanban agent config. Actions: my_instructions.",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["my_instructions"]},
            },
            "required": ["action"],
        },
        actions={"my_instructions": kanban["kanban_my_instructions"]},
        toolset="both",
        module="kanban",
    )

    # 10. agent_messages — list_tasks / send
    register_consolidated_tool(
        name="agent_messages",
        description="Agent messaging. Actions: list_tasks, send.",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list_tasks", "send"]},
                "status": {"type": "string"},
                "priority": {"type": "string"},
                "limit": {"type": "integer"},
                "to_agent": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "message_type": {"type": "string"},
                "metadata": {"type": "object"},
            },
            "required": ["action"],
        },
        actions={
            "list_tasks": agent_board["get_agent_tasks"],
            "send": agent_board["send_agent_message"],
        },
        toolset="both",
        module="agent_board",
    )

    # 11. admin_secrets — list/metadata/reveal/request_access
    # Renames: the public API uses 'secret_id', the handlers take 'id'.
    register_consolidated_tool(
        name="admin_secrets",
        description="Secrets (admin). Actions: list, metadata, reveal, request_access.",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "metadata", "reveal", "request_access"],
                },
                "user_id": {"type": "string"},
                "secret_id": {"type": "string"},
                "service": {"type": "string"},
                "secret_type": {"type": "string"},
                "tag": {"type": "string"},
                "accessible": {"type": "boolean"},
                "reason": {"type": "string"},
            },
            "required": ["action"],
        },
        actions={
            "list": secrets["list_secrets"],
            "metadata": secrets["get_secret_metadata"],
            "reveal": secrets["reveal_secret"],
            "request_access": secrets["request_secret_access"],
        },
        renames={
            "metadata": {"secret_id": "id"},
            "reveal": {"secret_id": "id"},
            "request_access": {"secret_id": "id"},
        },
        toolset="admin",
        module="secrets",
    )

    logger.info("Registered 11 consolidated MCP tools")
