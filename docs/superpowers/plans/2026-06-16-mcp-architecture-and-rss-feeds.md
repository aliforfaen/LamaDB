# MCP Architecture + RSS Feeds — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor LamaDB's MCP server from 29 flat tools into consolidated admin/worker endpoints with a frontend control pane, then build agent-driven RSS feeds on the new architecture.

**Architecture:** Two MCP endpoints (`/mcp/admin` with 11 tools, `/mcp/worker` with 8 tools) replacing the single `/mcp` endpoint with 29 tools. Tools consolidated via action-based dispatchers — existing handler functions unchanged. In-memory tool call stats with admin dashboard. RSS feeds generated from `documents` table filtered by tags, agents publish via `create_document` with documented conventions.

**Tech Stack:** FastAPI, asyncpg, feedgen, vanilla JS (no framework), PostgreSQL 16

---

## Overview

Two tracks, sequential:

| Track | Focus | Tasks | Est. Effort |
|-------|-------|-------|-------------|
| **Track 1: MCP Architecture** | Consolidate tools, split endpoints, add stats + control pane | 1-7 | Medium-Large |
| **Track 2: RSS Feeds** | Create feeds, publishing convention, morning brief PoC | 8-11 | Small-Medium |

Track 1 first (foundational — RSS tool slots into the new architecture). Track 2 depends on Track 1 only for the `create_document` tool consolidation (which happens in Task 2).

---

## File Map

### Track 1: MCP Architecture

| File | Action | Purpose |
|------|--------|---------|
| `app/mcp_registry.py` | Modify | Add `toolset`, `module`, `enabled` fields; `register_consolidated_tool()`; `list_tools(toolset=)` filter; `toggle_tool()` |
| `app/mcp_consolidated.py` | **Create** | 11 `register_consolidated_tool()` calls with action dispatchers |
| `app/mcp_server.py` | Modify | Split into `_handle()` core + `/mcp/admin`, `/mcp/worker` endpoints; instrument with stats tracker; metadata-driven permissions |
| `app/mcp_tracker.py` | **Create** | In-memory per-tool call/error/duration counters |
| `app/mcp_admin.py` | **Create** | Admin API routes for stats, tool catalog, toggle |
| `app/main.py` | Modify | Pass `toolset`/`module` to core tool registrations; import `mcp_consolidated` |
| `modules/kanban/__init__.py` | Modify | Add `toolset`/`module` to MODULE_MCP_TOOLS entries |
| `modules/secrets/__init__.py` | Modify | Same |
| `modules/wiki/__init__.py` | Modify | Same |
| `modules/uptime/__init__.py` | Modify | Same |
| `modules/agent_board/__init__.py` | Modify | Same |
| `static/index.html` | Modify | Add MCP Server sub-tab in Settings |
| `static/js/pages/settings.js` | Modify | Add MCP tab logic (stats cards, tool list, toggle) |
| `static/css/dashboard.css` | Modify | MCP-specific styles |
| `tests/test_mcp_consolidated.py` | **Create** | Tests for consolidated tools and endpoint visibility |

### Track 2: RSS Feeds

| File | Action | Purpose |
|------|--------|---------|
| `modules/feeds/models.py` | Modify | Add `filter_published` field to Feed model |
| `modules/feeds/generator.py` | Modify | Configurable `BASE_URL`; filter on `source_type = 'agent_feed'` |
| `modules/feeds/routes.py` | Modify | Add `POST /api/feeds/{slug}/publish` convenience endpoint |
| `modules/feeds/__init__.py` | Modify | Add `MODULE_CONFIG_SCHEMA` for base_url |
| `app/config.py` | Modify | Add `feeds_base_url` setting |
| `migrations/029_feed_publishing.sql` | **Create** | Seed initial feeds (lamalab, media, life, briefing) |
| `modules/feeds/cleanup.py` | **Create** | Feed pruning function (configurable retention) |
| `tests/test_feeds_publishing.py` | **Create** | Tests for publish endpoint and feed filtering |

---

## Track 1: MCP Architecture

### Task 1: Extend MCP Registry with Metadata

**Files:**
- Modify: `app/mcp_registry.py`
- Modify: `app/main.py:315-409`

- [ ] **Step 1: Add metadata fields to `register_tool()`**

In `app/mcp_registry.py`, extend `register_tool()` and the `_tools` dict structure:

```python
def register_tool(
    name: str,
    description: str,
    inputSchema: dict,
    handler: Callable,
    toolset: str = "both",     # "admin" | "worker" | "both"
    module: str = "",           # scope source: "documents", "kanban", etc.
    enabled: bool = True,       # can be toggled off
):
    """Register a single tool in the MCP registry."""
    _tools[name] = {
        "name": name,
        "description": description,
        "inputSchema": inputSchema,
        "handler": handler,
        "toolset": toolset,
        "module": module,
        "enabled": enabled,
    }
    logger.info(f"MCP tool registered: {name} (toolset={toolset}, module={module})")
```

- [ ] **Step 2: Add `register_consolidated_tool()` helper**

Add to `app/mcp_registry.py`:

```python
import inspect

def _make_dispatcher(actions: dict[str, Callable], renames: dict[str, dict[str, str]] | None = None):
    """Create a dispatcher that routes an 'action' kwarg to a handler."""
    async def dispatcher(*, action: str, **kwargs):
        if action not in actions:
            raise ValueError(f"Unknown action: {action!r}. Valid: {sorted(actions.keys())}")
        handler = actions[action]
        # Apply renames for this action
        action_renames = (renames or {}).get(action, {})
        rewritten = {action_renames.get(k, k): v for k, v in kwargs.items()}
        # Filter kwargs to only those accepted by the handler
        sig = inspect.signature(handler)
        accepted = set(sig.parameters.keys())
        filtered = {k: v for k, v in rewritten.items() if k in accepted}
        return await handler(**filtered)
    return dispatcher


def register_consolidated_tool(
    name: str,
    description: str,
    inputSchema: dict,
    actions: dict[str, Callable],
    toolset: str = "both",
    module: str = "",
    renames: dict[str, dict[str, str]] | None = None,
):
    """Register a consolidated tool that dispatches by 'action' parameter."""
    register_tool(
        name=name,
        description=description,
        inputSchema=inputSchema,
        handler=_make_dispatcher(actions, renames),
        toolset=toolset,
        module=module,
    )
```

- [ ] **Step 3: Add `list_tools()` filter parameter**

Modify `list_tools()` in `app/mcp_registry.py`:

```python
def list_tools(toolset: str | None = None) -> list[dict]:
    """Return registered tools filtered by toolset. None = all tools."""
    out = []
    for t in _tools.values():
        if not t.get("enabled", True):
            continue
        if toolset and t["toolset"] not in (toolset, "both"):
            continue
        out.append({
            "name": t["name"],
            "description": t["description"],
            "inputSchema": t["inputSchema"],
        })
    return out
```

- [ ] **Step 4: Add `toggle_tool()` function**

```python
def toggle_tool(name: str, enabled: bool) -> bool:
    """Enable or disable a tool. Returns True if tool existed."""
    tool = _tools.get(name)
    if tool is None:
        return False
    tool["enabled"] = enabled
    logger.info(f"MCP tool {'enabled' if enabled else 'disabled'}: {name}")
    return True
```

- [ ] **Step 5: Update core tool registrations in `app/main.py`**

Pass `toolset` and `module` to each `register_tool()` call (lines 322-409). Example:

```python
register_tool(
    "search_documents",
    "Full-text + semantic search across documents",
    {"type": "object", "properties": {"q": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["q"]},
    search_documents,
    toolset="both",
    module="documents",
)
```

Do the same for all 7 core tools: `search_documents` (both/documents), `get_document` (both/documents), `create_document` (both/documents), `update_document` (both/documents), `create_event` (both/events), `get_events` (both/events), `lamadb_docs` (both/"").

- [ ] **Step 6: Update module `MODULE_MCP_TOOLS` declarations**

Add `toolset` and `module` to each tool in:
- `modules/kanban/__init__.py` — all 12 tools: `toolset="both"`, `module="kanban"`
- `modules/secrets/__init__.py` — all 4 tools: `toolset="admin"`, `module="secrets"`
- `modules/agent_board/__init__.py` — both tools: `toolset="both"`, `module="agent_board"`
- `modules/uptime/__init__.py` — both tools: `toolset="both"`, `module="uptime"`
- `modules/wiki/__init__.py` — both tools: `toolset="both"`, `module="wiki"`

Update `discover_module_tools()` in `app/mcp_registry.py` to read and pass `toolset` and `module`:

```python
for tool_def in tools:
    handler_path = tool_def["handler"]
    handler = _import_handler(handler_path)
    register_tool(
        name=tool_def["name"],
        description=tool_def["description"],
        inputSchema=tool_def.get("inputSchema", {"type": "object", "properties": {}}),
        handler=handler,
        toolset=tool_def.get("toolset", "both"),
        module=tool_def.get("module", ""),
    )
```

- [ ] **Step 7: Verify — all 29 tools still work, metadata visible in logs**

```bash
docker compose build api && docker compose up -d api --force-recreate
docker compose logs api | grep "MCP tool registered" | head -30
```

Expected: Each log line now shows `(toolset=both, module=kanban)` etc.

- [ ] **Step 8: Commit**

```bash
git add app/mcp_registry.py app/main.py modules/*/\__init__.py
git commit -m "feat(mcp): add toolset/module/enabled metadata to tool registry"
```

---

### Task 2: Consolidated Tool Definitions

**Files:**
- Create: `app/mcp_consolidated.py`
- Modify: `app/main.py` (import consolidated tools)

- [ ] **Step 1: Create `app/mcp_consolidated.py`**

This file registers 11 consolidated tools that dispatch to existing handlers. No handler functions are modified.

```python
"""Consolidated MCP tools — action-based dispatchers over existing handlers."""
from app.mcp_registry import register_consolidated_tool
from app.core.mcp import (
    search_documents, get_document, create_document, update_document,
    create_event, get_events, lamadb_docs,
)


def register_all():
    """Register all consolidated tools. Called once at startup."""

    # ── Core: documents ──────────────────────────────────────────────
    register_consolidated_tool(
        name="agent_documents",
        description=(
            "Document operations. Actions: search (full-text + semantic), "
            "get (by ID), create (new document), update (modify fields)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["search", "get", "create", "update"]},
                "q": {"type": "string", "description": "(search) Search query"},
                "limit": {"type": "integer", "description": "(search) Max results"},
                "id": {"type": "string", "description": "(get/update) Document UUID"},
                "title": {"type": "string", "description": "(create/update) Title"},
                "source_type": {"type": "string", "description": "(create) Source type"},
                "content": {"type": "string", "description": "(create/update) Body text"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "(create/update) Tags"},
                "metadata": {"type": "object", "description": "(create/update) JSON metadata"},
            },
            "required": ["action"],
        },
        actions={
            "search": search_documents,
            "get": get_document,
            "create": create_document,
            "update": update_document,
        },
        toolset="both",
        module="documents",
    )

    # ── Core: events ─────────────────────────────────────────────────
    register_consolidated_tool(
        name="agent_events",
        description="Event operations. Actions: create (new event), list (query with filters).",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create", "list"]},
                "source": {"type": "string", "description": "(create) Event source"},
                "type_": {"type": "string", "description": "(create) Event type"},
                "title": {"type": "string", "description": "(create) Event title"},
                "severity": {"type": "string", "enum": ["info", "warning", "critical"]},
                "body": {"type": "string"},
                "metadata": {"type": "object"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "description": "(list) Max events"},
            },
            "required": ["action"],
        },
        actions={"create": create_event, "list": get_events},
        toolset="both",
        module="events",
    )

    # ── Core: wiki ───────────────────────────────────────────────────
    from modules.wiki.mcp import wiki_search, scratchpad_capture

    register_consolidated_tool(
        name="agent_wiki",
        description="Wiki operations. Actions: search (pages by content), scratch (save quick note).",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["search", "scratch"]},
                "q": {"type": "string", "description": "(search) Search query"},
                "limit": {"type": "integer", "description": "(search) Max results"},
                "content": {"type": "string", "description": "(scratch) Note content"},
                "title": {"type": "string", "description": "(scratch) Note title"},
            },
            "required": ["action"],
        },
        actions={"search": wiki_search, "scratch": scratchpad_capture},
        toolset="both",
        module="wiki",
    )

    # ── Core: uptime ─────────────────────────────────────────────────
    from modules.uptime.mcp import get_uptime_status, get_uptime_history

    register_consolidated_tool(
        name="agent_uptime",
        description="Uptime monitoring. Actions: status (current), history (recent changes).",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["status", "history"]},
                "monitor_id": {"type": "string", "description": "(history) Filter by monitor"},
                "limit": {"type": "integer", "description": "(history) Max results"},
            },
            "required": ["action"],
        },
        actions={"status": get_uptime_status, "history": get_uptime_history},
        toolset="both",
        module="uptime",
    )

    # ── Core: docs ───────────────────────────────────────────────────
    register_consolidated_tool(
        name="lamadb_docs",
        description="Read LamaDB documentation. topic='api' for full agent API reference.",
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "default": "api"},
            },
        },
        actions={"default": lamadb_docs},
        toolset="both",
        module="",
    )

    # ── Kanban: tasks ────────────────────────────────────────────────
    from modules.kanban.mcp import (
        kanban_my_tasks, kanban_find_work, kanban_get_task,
        kanban_create_task, kanban_create_from_template, kanban_update_task,
    )

    register_consolidated_tool(
        name="agent_kanban_tasks",
        description=(
            "Kanban task operations. Actions: my_tasks (assigned to you), "
            "find_work (unassigned backlog), get (full details), create (new task), "
            "create_from_template, update (modify fields)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["my_tasks", "find_work", "get", "create", "create_from_template", "update"]},
                "board_id": {"type": "string", "description": "(my_tasks/find_work/create) Board filter"},
                "task_id": {"type": "string", "description": "(get/update) Task UUID"},
                "title": {"type": "string", "description": "(create/update) Task title"},
                "description": {"type": "string", "description": "(create/update) Description"},
                "priority": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "(create/update) Tags"},
                "template_id": {"type": "string", "description": "(create_from_template) Template UUID"},
                "title_override": {"type": "string", "description": "(create_from_template) Override title"},
            },
            "required": ["action"],
        },
        actions={
            "my_tasks": kanban_my_tasks,
            "find_work": kanban_find_work,
            "get": kanban_get_task,
            "create": kanban_create_task,
            "create_from_template": kanban_create_from_template,
            "update": kanban_update_task,
        },
        toolset="both",
        module="kanban",
    )

    # ── Kanban: workflow ─────────────────────────────────────────────
    from modules.kanban.mcp import (
        kanban_claim_task, kanban_start_task, kanban_complete_task, kanban_help_wanted,
    )

    register_consolidated_tool(
        name="agent_kanban_workflow",
        description=(
            "Kanban workflow actions. Actions: claim (take a task), "
            "start (begin work), complete (finish + auto-start dependents), "
            "help_wanted (flag for human help)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["claim", "start", "complete", "help_wanted"]},
                "task_id": {"type": "string", "description": "Task UUID"},
                "summary": {"type": "string", "description": "(complete) Work summary"},
                "message": {"type": "string", "description": "(help_wanted) Help message"},
            },
            "required": ["action", "task_id"],
        },
        actions={
            "claim": kanban_claim_task,
            "start": kanban_start_task,
            "complete": kanban_complete_task,
            "help_wanted": kanban_help_wanted,
        },
        toolset="both",
        module="kanban",
    )

    # ── Kanban: comments + meta ──────────────────────────────────────
    from modules.kanban.mcp import kanban_add_comment, kanban_my_instructions

    register_consolidated_tool(
        name="agent_kanban_comments",
        description="Add a comment to a kanban task.",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task UUID"},
                "body": {"type": "string", "description": "Comment text"},
            },
            "required": ["task_id", "body"],
        },
        actions={"add": kanban_add_comment},
        toolset="both",
        module="kanban",
    )

    register_consolidated_tool(
        name="agent_kanban_meta",
        description="Get your agent instructions for the current board.",
        inputSchema={"type": "object", "properties": {}},
        actions={"my_instructions": kanban_my_instructions},
        toolset="both",
        module="kanban",
    )

    # ── Agent board: messaging ───────────────────────────────────────
    from modules.agent_board.mcp import get_agent_tasks, send_agent_message

    register_consolidated_tool(
        name="agent_messages",
        description="Agent board messaging. Actions: list_tasks (agent task queue), send (message another agent).",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list_tasks", "send"]},
                "status": {"type": "string", "description": "(list_tasks) Filter by status"},
                "priority": {"type": "string", "description": "(list_tasks) Filter by priority"},
                "limit": {"type": "integer", "description": "(list_tasks) Max results"},
                "to_agent": {"type": "string", "description": "(send) Recipient"},
                "subject": {"type": "string", "description": "(send) Subject line"},
                "body": {"type": "string", "description": "(send) Message body"},
                "message_type": {"type": "string", "enum": ["info", "alert", "task"]},
                "metadata": {"type": "object"},
            },
            "required": ["action"],
        },
        actions={"list_tasks": get_agent_tasks, "send": send_agent_message},
        toolset="both",
        module="agent_board",
    )

    # ── Secrets: admin-only ──────────────────────────────────────────
    from modules.secrets.mcp import (
        list_secrets, get_secret_metadata, reveal_secret, request_secret_access,
    )

    register_consolidated_tool(
        name="admin_secrets",
        description=(
            "Secret management (admin only). Actions: list (metadata only), "
            "metadata (full details), reveal (decrypt value — audit logged), "
            "request_access (ask for reveal permission)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "metadata", "reveal", "request_access"]},
                "service": {"type": "string", "description": "(list) Filter by service"},
                "secret_id": {"type": "string", "description": "(metadata/reveal/request_access) Secret UUID"},
                "reason": {"type": "string", "description": "(request_access) Justification"},
            },
            "required": ["action"],
        },
        actions={
            "list": list_secrets,
            "metadata": get_secret_metadata,
            "reveal": reveal_secret,
            "request_access": request_secret_access,
        },
        renames={
            "metadata": {"secret_id": "id"},
            "reveal": {"secret_id": "id"},
            "request_access": {"secret_id": "id"},
        },
        toolset="admin",
        module="secrets",
    )
```

- [ ] **Step 2: Import and call `register_all()` in `app/main.py`**

After the existing core tool registration (around line 410) and before `discover_module_tools()`:

```python
# Register consolidated tools
from app.mcp_consolidated import register_all as register_consolidated_tools
register_consolidated_tools()
```

- [ ] **Step 3: Verify — 40 tools visible (29 legacy + 11 consolidated)**

```bash
docker compose build api && docker compose up -d api --force-recreate
# Call tools/list via Swagger or curl
curl -s -X POST http://localhost:8000/mcp \
  -H "Authorization: Bearer <admin_key>" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python3 -c "
import json,sys
tools = json.load(sys.stdin)['result']['tools']
print(f'Total tools: {len(tools)}')
for t in tools:
    print(f'  {t[\"name\"]}')"
```

Expected: 40 tools listed (29 legacy + 11 consolidated).

- [ ] **Step 4: Test consolidated tool dispatch**

```bash
# Test agent_documents action=search
curl -s -X POST http://localhost:8000/mcp \
  -H "Authorization: Bearer <admin_key>" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"agent_documents","arguments":{"action":"search","q":"test","limit":3}}}'

# Test agent_kanban_tasks action=my_tasks
curl -s -X POST http://localhost:8000/mcp \
  -H "Authorization: Bearer <admin_key>" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"agent_kanban_tasks","arguments":{"action":"my_tasks"}}}'
```

Expected: Valid JSON responses matching the legacy tool behavior.

- [ ] **Step 5: Commit**

```bash
git add app/mcp_consolidated.py app/main.py
git commit -m "feat(mcp): add 11 consolidated tools with action-based dispatch"
```

---

### Task 3: Split into Admin/Worker Endpoints

**Files:**
- Modify: `app/mcp_server.py`
- Modify: `app/mcp_registry.py` (add `get_tool_with_meta()`)

- [ ] **Step 1: Refactor `mcp_server.py` into shared `_handle()` function**

Replace the current `mcp_handler()` with:

```python
async def _handle(request: Request, *, toolset: str | None):
    """Common JSON-RPC handler. Filters tools by toolset."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")
    token = auth_header[7:]
    user = await verify_api_key(token)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    try:
        body = await request.json()
    except Exception:
        return _jsonrpc_error(None, ERROR_PARSE, "Parse error")

    rpc_id = body.get("id")
    method = body.get("method", "")
    params = body.get("params", {})

    if method == "tools/list":
        return _jsonrpc_response(rpc_id, {"tools": list_tools(toolset=toolset)})

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool = get_tool(tool_name)
        if tool is None:
            return _jsonrpc_error(rpc_id, ERROR_METHOD_NOT_FOUND, f"Tool not found: {tool_name}")

        # Enforce toolset visibility
        if toolset and tool["toolset"] not in (toolset, "both"):
            return _jsonrpc_error(rpc_id, ERROR_METHOD_NOT_FOUND, f"Tool not available on this endpoint")

        # Check enabled
        if not tool.get("enabled", True):
            return _jsonrpc_error(rpc_id, ERROR_METHOD_NOT_FOUND, f"Tool disabled: {tool_name}")

        # Permission check (metadata-driven)
        perm_error = _check_permission(user, tool)
        if perm_error:
            return _jsonrpc_error(rpc_id, ERROR_INTERNAL, perm_error)

        arguments = params.get("arguments", {})
        try:
            result = await tool["handler"](**arguments)
            return _jsonrpc_response(rpc_id, {"content": [{"type": "text", "text": json.dumps(result)}]})
        except TypeError as e:
            return _jsonrpc_error(rpc_id, ERROR_INVALID_PARAMS, str(e))
        except Exception as e:
            logger.exception(f"MCP tool '{tool_name}' error")
            return _jsonrpc_error(rpc_id, ERROR_INTERNAL, str(e))

    return _jsonrpc_error(rpc_id, ERROR_METHOD_NOT_FOUND, f"Method not found: {method}")


def _check_permission(user: AuthUser, tool: dict) -> str | None:
    """Return error message if user lacks permission, else None."""
    if user.role == "admin":
        return None

    # Write tools require agent or admin role
    # Consolidated tools: check if any action is a write (conservative: if tool has write actions, require agent)
    write_tools = {
        "create_document", "update_document", "create_event", "send_agent_message",
        "agent_documents", "agent_events", "agent_messages",  # consolidated equivalents
    }
    if tool["name"] in write_tools and user.role not in ("admin", "agent"):
        return "Insufficient permissions: agent role required"

    # Scope check: tool's module must be in user's scopes
    module = tool.get("module", "")
    if module and module not in user.scopes and user.role != "admin":
        return f"Scope '{module}' required"

    return None
```

- [ ] **Step 2: Add three endpoints**

```python
@router.post("/mcp")
async def mcp_legacy_handler(request: Request):
    """Legacy endpoint — returns all tools. Deprecated."""
    logger.warning("Legacy /mcp endpoint used — clients should migrate to /mcp/admin or /mcp/worker")
    return await _handle(request, toolset=None)


@router.post("/mcp/admin")
async def mcp_admin_handler(request: Request):
    """Admin MCP endpoint — all consolidated tools."""
    return await _handle(request, toolset="admin")


@router.post("/mcp/worker")
async def mcp_worker_handler(request: Request):
    """Worker MCP endpoint — subset of tools for task agents."""
    return await _handle(request, toolset="worker")
```

- [ ] **Step 3: Remove the hard-coded `_tool_to_module()` map**

Delete the function and the `WRITE_TOOLS` set. The `_check_permission()` function replaces both.

- [ ] **Step 4: Verify endpoint filtering**

```bash
docker compose build api && docker compose up -d api --force-recreate

# Admin should see all 11 consolidated tools
curl -s -X POST http://localhost:8000/mcp/admin \
  -H "Authorization: Bearer <admin_key>" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python3 -c "
import json,sys
tools = json.load(sys.stdin)['result']['tools']
print(f'Admin tools: {len(tools)}')
for t in tools: print(f'  {t[\"name\"]}')"

# Worker should see 8 tools (no admin_secrets)
curl -s -X POST http://localhost:8000/mcp/worker \
  -H "Authorization: Bearer <agent_key>" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | python3 -c "
import json,sys
tools = json.load(sys.stdin)['result']['tools']
print(f'Worker tools: {len(tools)}')
for t in tools: print(f'  {t[\"name\"]}')"

# Calling admin_secrets on worker should fail
curl -s -X POST http://localhost:8000/mcp/worker \
  -H "Authorization: Bearer <agent_key>" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"admin_secrets","arguments":{"action":"list"}}}'
```

Expected:
- Admin: 11 tools (agent_documents, agent_events, agent_wiki, agent_uptime, lamadb_docs, agent_kanban_tasks, agent_kanban_workflow, agent_kanban_comments, agent_kanban_meta, agent_messages, admin_secrets)
- Worker: 8 tools (same as admin minus admin_secrets, agent_kanban_comments, agent_kanban_meta)
- Worker calling admin_secrets: `{"error": {"code": -32601, "message": "Tool not available on this endpoint"}}`

- [ ] **Step 5: Commit**

```bash
git add app/mcp_server.py
git commit -m "feat(mcp): split into /mcp/admin and /mcp/worker endpoints"
```

---

### Task 4: Tool Call Stats Tracker

**Files:**
- Create: `app/mcp_tracker.py`
- Modify: `app/mcp_server.py` (instrument handler)

- [ ] **Step 1: Create `app/mcp_tracker.py`**

```python
"""In-memory MCP tool call statistics tracker."""
import time
from datetime import datetime, timezone

_tool_stats: dict[str, dict] = {}


def track_call(name: str, duration_ms: float):
    """Record a successful tool call."""
    stat = _tool_stats.setdefault(name, {
        "calls": 0, "errors": 0, "last_call": None, "last_error": None, "total_duration_ms": 0,
    })
    stat["calls"] += 1
    stat["last_call"] = datetime.now(timezone.utc).isoformat()
    stat["total_duration_ms"] += duration_ms


def track_error(name: str, error: str, duration_ms: float):
    """Record a failed tool call."""
    stat = _tool_stats.setdefault(name, {
        "calls": 0, "errors": 0, "last_call": None, "last_error": None, "total_duration_ms": 0,
    })
    stat["calls"] += 1
    stat["errors"] += 1
    stat["last_call"] = datetime.now(timezone.utc).isoformat()
    stat["last_error"] = error[:200]  # truncate long errors
    stat["total_duration_ms"] += duration_ms


def get_stats() -> dict:
    """Return aggregated stats snapshot."""
    tools = []
    total_calls = 0
    total_errors = 0
    for name, stat in _tool_stats.items():
        total_calls += stat["calls"]
        total_errors += stat["errors"]
        avg_ms = (stat["total_duration_ms"] / stat["calls"]) if stat["calls"] > 0 else 0
        tools.append({
            "name": name,
            "calls": stat["calls"],
            "errors": stat["errors"],
            "last_call": stat["last_call"],
            "last_error": stat["last_error"],
            "avg_duration_ms": round(avg_ms, 1),
        })
    error_rate = (total_errors / total_calls * 100) if total_calls > 0 else 0
    return {
        "total_calls": total_calls,
        "total_errors": total_errors,
        "error_rate": round(error_rate, 2),
        "tools": sorted(tools, key=lambda t: t["calls"], reverse=True),
    }


def reset_stats():
    """Clear all counters (for testing)."""
    _tool_stats.clear()
```

- [ ] **Step 2: Instrument `mcp_server.py` `_handle()` with timing**

In the `tools/call` branch, wrap the handler invocation:

```python
from app.mcp_tracker import track_call, track_error

# ... inside tools/call, replace the handler call block:
start = time.monotonic()
try:
    result = await tool["handler"](**arguments)
    elapsed_ms = (time.monotonic() - start) * 1000
    track_call(tool_name, elapsed_ms)
    return _jsonrpc_response(rpc_id, {"content": [{"type": "text", "text": json.dumps(result)}]})
except TypeError as e:
    elapsed_ms = (time.monotonic() - start) * 1000
    track_error(tool_name, str(e), elapsed_ms)
    return _jsonrpc_error(rpc_id, ERROR_INVALID_PARAMS, str(e))
except Exception as e:
    elapsed_ms = (time.monotonic() - start) * 1000
    track_error(tool_name, str(e), elapsed_ms)
    logger.exception(f"MCP tool '{tool_name}' error")
    return _jsonrpc_error(rpc_id, ERROR_INTERNAL, str(e))
```

- [ ] **Step 3: Verify stats accumulate**

```bash
docker compose build api && docker compose up -d api --force-recreate
# Make a few calls, then check via a debug endpoint or log
```

- [ ] **Step 4: Commit**

```bash
git add app/mcp_tracker.py app/mcp_server.py
git commit -m "feat(mcp): add in-memory tool call stats tracking"
```

---

### Task 5: MCP Admin API Routes

**Files:**
- Create: `app/mcp_admin.py`
- Modify: `app/main.py` (register admin router)

- [ ] **Step 1: Create `app/mcp_admin.py`**

```python
"""MCP admin API — stats, tool catalog, toggle."""
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from app.auth import AuthUser, get_current_user
from app.mcp_registry import list_tools as registry_list_tools, get_tool, toggle_tool
from app.mcp_tracker import get_stats

router = APIRouter(prefix="/api/mcp/admin", tags=["mcp-admin"])


def _require_admin(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user


@router.get("/stats")
async def mcp_stats(user: Annotated[AuthUser, Depends(_require_admin)]):
    """Return tool call statistics."""
    stats = get_stats()
    # Enrich with registry metadata
    for tool_stat in stats["tools"]:
        tool = get_tool(tool_stat["name"])
        if tool:
            tool_stat["module"] = tool.get("module", "")
            tool_stat["toolset"] = tool.get("toolset", "both")
            tool_stat["enabled"] = tool.get("enabled", True)
    return stats


@router.get("/tools")
async def mcp_tools(user: Annotated[AuthUser, Depends(_require_admin)]):
    """Return full tool catalog with metadata."""
    tools = registry_list_tools()  # all tools, no filter
    result = []
    for t in tools:
        tool = get_tool(t["name"])
        result.append({
            **t,
            "module": tool.get("module", "") if tool else "",
            "toolset": tool.get("toolset", "both") if tool else "both",
            "enabled": tool.get("enabled", True) if tool else True,
        })
    return {"tools": result}


@router.patch("/tools/{tool_name}")
async def toggle_mcp_tool(
    tool_name: str,
    body: dict,
    user: Annotated[AuthUser, Depends(_require_admin)],
):
    """Enable or disable a tool."""
    enabled = body.get("enabled")
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=400, detail="'enabled' must be a boolean")
    if not toggle_tool(tool_name, enabled):
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
    return {"status": "ok", "tool": tool_name, "enabled": enabled}
```

- [ ] **Step 2: Register router in `app/main.py`**

After the MCP router registration (around line 312):

```python
from app.mcp_admin import router as mcp_admin_router
app.include_router(mcp_admin_router)
```

- [ ] **Step 3: Verify endpoints**

```bash
docker compose build api && docker compose up -d api --force-recreate
curl -s http://localhost:8000/api/mcp/admin/stats -H "Authorization: Bearer <admin_key>" | python3 -m json.tool
curl -s http://localhost:8000/api/mcp/admin/tools -H "Authorization: Bearer <admin_key>" | python3 -m json.tool
```

- [ ] **Step 4: Commit**

```bash
git add app/mcp_admin.py app/main.py
git commit -m "feat(mcp): add admin API routes for stats and tool management"
```

---

### Task 6: Frontend MCP Control Pane

**Files:**
- Modify: `static/index.html` — add MCP tab in Settings
- Modify: `static/js/pages/settings.js` — add MCP tab logic
- Modify: `static/css/dashboard.css` — MCP styles

- [ ] **Step 1: Add MCP sub-tab button to Settings tab bar**

In `static/index.html`, find the Settings tab bar (around line 1229) and add:

```html
<button class="tab-btn" data-tab="settings-mcp" onclick="window.switchSettingsTab('mcp')">MCP Server</button>
```

- [ ] **Step 2: Add MCP tab panel HTML**

After the last existing tab panel in Settings:

```html
<div id="tab-settings-mcp" class="tab-panel" style="display:none;">
  <h3>MCP Server</h3>
  <div class="mcp-stat-grid" id="mcp-stat-grid"></div>
  <div class="mcp-tools-section">
    <div class="mcp-tools-header">
      <h3>Registered Tools</h3>
      <div class="mcp-tools-toolbar">
        <div class="filter-tabs" id="mcp-filter-tabs">
          <button class="filter-tab active" data-filter="all" onclick="window.filterMcpTools('all', this)">All</button>
          <button class="filter-tab" data-filter="admin" onclick="window.filterMcpTools('admin', this)">Admin</button>
          <button class="filter-tab" data-filter="worker" onclick="window.filterMcpTools('worker', this)">Worker</button>
          <button class="filter-tab" data-filter="disabled" onclick="window.filterMcpTools('disabled', this)">Disabled</button>
        </div>
        <input type="text" id="mcp-tool-search" placeholder="Search tools..." oninput="window.filterMcpToolsList()" class="mcp-search-input" />
      </div>
    </div>
    <div id="mcp-tools-list"></div>
  </div>
</div>
```

- [ ] **Step 3: Add MCP tab logic to `static/js/pages/settings.js`**

Inside the existing IIFE, add:

```javascript
// ── MCP Tab ──────────────────────────────────────────────────────
var _mcpToolsCache = [];
var _mcpStatsCache = null;
var _mcpFilterActive = 'all';

window.loadMcpTab = async function() {
  try {
    var statsRes = await window.api('/api/mcp/admin/stats');
    _mcpStatsCache = statsRes;
    renderMcpStatCards(statsRes);
  } catch (e) {
    document.getElementById('mcp-stat-grid').innerHTML =
      '<div class="stat-card"><div class="label">Error</div><div class="value">' + window.escHtml(e.message) + '</div></div>';
  }
  try {
    var toolsRes = await window.api('/api/mcp/admin/tools');
    _mcpToolsCache = toolsRes.tools || [];
    renderMcpToolsList(_mcpToolsCache);
  } catch (e) {
    document.getElementById('mcp-tools-list').innerHTML =
      '<div class="mcp-error">Failed to load tools: ' + window.escHtml(e.message) + '</div>';
  }
};

function renderMcpStatCards(stats) {
  var grid = document.getElementById('mcp-stat-grid');
  var enabledCount = stats.tools.filter(function(t) { return t.enabled !== false; }).length;
  var total = stats.tools.length;
  grid.innerHTML =
    '<div class="stat-card"><div class="label">Total Calls</div><div class="value">' + stats.total_calls.toLocaleString() + '</div></div>' +
    '<div class="stat-card"><div class="label">Error Rate</div><div class="value">' + stats.error_rate.toFixed(1) + '%</div></div>' +
    '<div class="stat-card"><div class="label">Tools Active</div><div class="value">' + enabledCount + '/' + total + '</div></div>' +
    '<div class="stat-card"><div class="label">Avg Duration</div><div class="value">' + (stats.tools.length > 0 ? (stats.tools.reduce(function(s,t){ return s + t.avg_duration_ms; }, 0) / stats.tools.length).toFixed(0) : '—') + 'ms</div></div>';
}

function renderMcpToolsList(tools) {
  var container = document.getElementById('mcp-tools-list');
  // Group by module
  var groups = {};
  tools.forEach(function(t) {
    var mod = t.module || 'core';
    if (!groups[mod]) groups[mod] = [];
    groups[mod].push(t);
  });
  var html = '';
  Object.keys(groups).sort().forEach(function(mod) {
    var modTools = groups[mod];
    var modCalls = modTools.reduce(function(s,t){ return s + (t.calls || 0); }, 0);
    var modErrors = modTools.reduce(function(s,t){ return s + (t.errors || 0); }, 0);
    html += '<div class="mcp-module-group">';
    html += '<div class="mcp-module-header" onclick="this.parentElement.classList.toggle(\'collapsed\')">';
    html += '<span class="mcp-module-name">' + window.escHtml(mod) + '</span>';
    html += '<span class="mcp-module-stats">' + modTools.length + ' tools · ' + modCalls + ' calls · ' + modErrors + ' errors</span>';
    html += '<span class="mcp-expand-icon">▼</span>';
    html += '</div>';
    html += '<div class="mcp-module-tools">';
    modTools.forEach(function(t) {
      var enabled = t.enabled !== false;
      var toolsetBadge = t.toolset === 'admin' ? '<span class="mcp-badge admin">admin</span>' : '<span class="mcp-badge worker">worker</span>';
      var errorClass = t.errors > 0 ? ' has-errors' : '';
      html += '<div class="mcp-tool-row' + errorClass + (enabled ? '' : ' disabled') + '">';
      html += '<span class="mcp-tool-name">' + window.escHtml(t.name) + '</span>';
      html += toolsetBadge;
      html += '<span class="mcp-tool-calls">' + (t.calls || 0) + ' calls</span>';
      html += '<span class="mcp-tool-errors">' + (t.errors || 0) + ' errors</span>';
      html += '<span class="mcp-tool-last">' + (t.last_call ? window.relativeTime(t.last_call) : 'never') + '</span>';
      html += '<label class="toggle"><input type="checkbox" ' + (enabled ? 'checked' : '') + ' onchange="window.toggleMcpTool(\'' + window.escAttr(t.name) + '\', this.checked)"><span class="toggle-slider"></span></label>';
      html += '</div>';
    });
    html += '</div></div>';
  });
  container.innerHTML = html;
}

window.toggleMcpTool = function(name, enabled) {
  window.api('/api/mcp/admin/tools/' + encodeURIComponent(name), {
    method: 'PATCH',
    body: JSON.stringify({ enabled: enabled }),
  }).then(function() {
    window.showToast('Tool "' + name + '" ' + (enabled ? 'enabled' : 'disabled'));
    // Update cache
    var tool = _mcpToolsCache.find(function(t) { return t.name === name; });
    if (tool) tool.enabled = enabled;
    // Update stats
    if (_mcpStatsCache) renderMcpStatCards(_mcpStatsCache);
  }).catch(function(e) {
    window.showError('Failed: ' + e.message);
    window.loadMcpTab(); // reload to revert
  });
};

window.filterMcpTools = function(filter, btn) {
  _mcpFilterActive = filter;
  // Update active tab
  document.querySelectorAll('#mcp-filter-tabs .filter-tab').forEach(function(b) { b.classList.remove('active'); });
  if (btn) btn.classList.add('active');
  window.filterMcpToolsList();
};

window.filterMcpToolsList = function() {
  var search = (document.getElementById('mcp-tool-search').value || '').toLowerCase();
  var filtered = _mcpToolsCache.filter(function(t) {
    if (_mcpFilterActive === 'disabled' && t.enabled !== false) return false;
    if (_mcpFilterActive === 'admin' && t.toolset !== 'admin') return false;
    if (_mcpFilterActive === 'worker' && t.toolset === 'admin') return false;
    if (search && t.name.toLowerCase().indexOf(search) === -1 && (t.description || '').toLowerCase().indexOf(search) === -1) return false;
    return true;
  });
  renderMcpToolsList(filtered);
};
```

- [ ] **Step 4: Wire up tab loading in `switchSettingsTab()`**

In the existing `switchSettingsTab()` function, add:

```javascript
else if (tab === 'mcp') { window.loadMcpTab(); }
```

- [ ] **Step 5: Add MCP styles to `static/css/dashboard.css`**

```css
/* MCP Control Pane */
.mcp-stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 24px;
}
.mcp-tools-section { margin-top: 16px; }
.mcp-tools-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px; }
.mcp-tools-toolbar { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.mcp-search-input { padding: 6px 12px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg); color: var(--text); font-size: 0.85rem; width: 200px; }
.mcp-module-group { border: 1px solid var(--border); border-radius: 8px; margin-bottom: 12px; overflow: hidden; }
.mcp-module-header { display: flex; justify-content: space-between; align-items: center; padding: 10px 16px; background: var(--bg-secondary); cursor: pointer; user-select: none; }
.mcp-module-header:hover { background: var(--bg-hover); }
.mcp-module-name { font-weight: 600; font-size: 0.95rem; }
.mcp-module-stats { font-size: 0.8rem; color: var(--muted); }
.mcp-expand-icon { font-size: 0.75rem; transition: transform 0.2s; }
.mcp-module-group.collapsed .mcp-module-tools { display: none; }
.mcp-module-group.collapsed .mcp-expand-icon { transform: rotate(-90deg); }
.mcp-module-tools { padding: 0; }
.mcp-tool-row { display: grid; grid-template-columns: 1fr auto auto auto auto auto; gap: 12px; align-items: center; padding: 8px 16px; border-top: 1px solid var(--border); font-size: 0.85rem; }
.mcp-tool-row:hover { background: var(--bg-hover); }
.mcp-tool-row.disabled { opacity: 0.5; }
.mcp-tool-row.has-errors { border-left: 3px solid var(--danger); }
.mcp-tool-name { font-family: monospace; font-size: 0.82rem; }
.mcp-badge { font-size: 0.7rem; padding: 2px 6px; border-radius: 4px; font-weight: 500; }
.mcp-badge.admin { background: var(--accent-dim); color: var(--accent); }
.mcp-badge.worker { background: var(--bg-secondary); color: var(--muted); }
.mcp-tool-calls { color: var(--muted); }
.mcp-tool-errors { color: var(--danger); }
.mcp-tool-row .mcp-tool-errors:not(.has-errors) { color: var(--muted); }
.mcp-tool-last { color: var(--muted); font-size: 0.8rem; }
@media (max-width: 768px) {
  .mcp-tool-row { grid-template-columns: 1fr auto; gap: 4px; }
  .mcp-tool-calls, .mcp-tool-errors, .mcp-tool-last { display: none; }
}
```

- [ ] **Step 6: Rebuild and test**

```bash
docker build --no-cache -t lamadb-api:latest -f Dockerfile . && docker compose up -d api --force-recreate
```

Open Settings → MCP Server tab. Verify:
- Stat cards show call counts
- Tools grouped by module
- Toggle switches work
- Filter tabs work
- Search filters in real time

- [ ] **Step 7: Commit**

```bash
git add static/index.html static/js/pages/settings.js static/css/dashboard.css
git commit -m "feat(mcp): add frontend control pane in Settings"
```

---

### Task 7: Write Tests for MCP Consolidation

**Files:**
- Create: `tests/test_mcp_consolidated.py`

- [ ] **Step 1: Write tests**

```python
"""Tests for consolidated MCP tools and endpoint filtering."""
import httpx
import pytest

BASE = "http://localhost:8000"


@pytest.fixture
async def admin_headers(admin_key):
    return {"Authorization": f"Bearer {admin_key}", "Content-Type": "application/json"}


@pytest.fixture
async def agent_headers(agent_key):
    return {"Authorization": f"Bearer {agent_key}", "Content-Type": "application/json"}


async def mcp_call(client, endpoint, headers, tool_name, arguments):
    """Helper to call an MCP tool."""
    resp = await client.post(
        f"{BASE}{endpoint}",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        },
    )
    return resp


async def mcp_list(client, endpoint, headers):
    """Helper to list MCP tools."""
    resp = await client.post(
        f"{BASE}{endpoint}",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    return resp


@pytest.mark.anyio
async def test_admin_endpoint_returns_all_consolidated_tools(client, admin_headers):
    resp = await mcp_list(client, "/mcp/admin", admin_headers)
    assert resp.status_code == 200
    tools = resp.json()["result"]["tools"]
    names = {t["name"] for t in tools}
    expected = {
        "agent_documents", "agent_events", "agent_wiki", "agent_uptime", "lamadb_docs",
        "agent_kanban_tasks", "agent_kanban_workflow", "agent_kanban_comments", "agent_kanban_meta",
        "agent_messages", "admin_secrets",
    }
    assert expected.issubset(names), f"Missing tools: {expected - names}"


@pytest.mark.anyio
async def test_worker_endpoint_excludes_admin_tools(client, agent_headers):
    resp = await mcp_list(client, "/mcp/worker", agent_headers)
    assert resp.status_code == 200
    tools = resp.json()["result"]["tools"]
    names = {t["name"] for t in tools}
    assert "admin_secrets" not in names
    assert "agent_documents" in names


@pytest.mark.anyio
async def test_worker_cannot_call_admin_tool(client, agent_headers):
    resp = await mcp_call(client, "/mcp/worker", agent_headers, "admin_secrets", {"action": "list"})
    assert resp.status_code == 200
    body = resp.json()
    assert "error" in body
    assert "not available" in body["error"]["message"].lower()


@pytest.mark.anyio
async def test_consolidated_document_search(client, admin_headers):
    resp = await mcp_call(client, "/mcp/admin", admin_headers, "agent_documents", {"action": "search", "q": "test", "limit": 3})
    assert resp.status_code == 200
    body = resp.json()
    assert "result" in body


@pytest.mark.anyio
async def test_consolidated_unknown_action(client, admin_headers):
    resp = await mcp_call(client, "/mcp/admin", admin_headers, "agent_documents", {"action": "nonexistent"})
    assert resp.status_code == 200
    body = resp.json()
    assert "error" in body


@pytest.mark.anyio
async def test_toggle_tool_disables_it(client, admin_headers):
    # Disable a tool
    resp = await client.patch(
        f"{BASE}/api/mcp/admin/tools/lamadb_docs",
        headers=admin_headers,
        json={"enabled": False},
    )
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False

    # Verify it's gone from tools/list
    list_resp = await mcp_list(client, "/mcp/admin", admin_headers)
    tools = list_resp.json()["result"]["tools"]
    names = {t["name"] for t in tools}
    assert "lamadb_docs" not in names

    # Re-enable
    await client.patch(
        f"{BASE}/api/mcp/admin/tools/lamadb_docs",
        headers=admin_headers,
        json={"enabled": True},
    )
```

- [ ] **Step 2: Run tests**

```bash
docker exec lamadb_api python3 -m pytest tests/test_mcp_consolidated.py -v --timeout=30
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_mcp_consolidated.py
git commit -m "test(mcp): consolidated tools and endpoint filtering tests"
```

---

## Track 2: RSS Feeds

### Task 8: Create Initial Feeds

**Files:**
- Create: `migrations/029_feed_publishing.sql`
- Modify: `modules/feeds/generator.py` (configurable BASE_URL)
- Modify: `modules/feeds/__init__.py` (add MODULE_CONFIG_SCHEMA)

- [ ] **Step 1: Create migration with initial feeds**

```sql
-- migrations/029_feed_publishing.sql
-- Seed initial RSS feeds for agent-driven content

INSERT INTO feeds (name, slug, description, filter_tags, filter_source_types, max_items)
VALUES
  ('LamaLab', 'lamalab', 'Homelab updates: service status, agent activity, deployments, infra alerts',
   ARRAY['homelab', 'service', 'agent', 'infra'], ARRAY['agent_feed'], 50),
  ('Media', 'media', 'Media stack: new Plex content, watch history, download updates',
   ARRAY['media', 'notflix', 'plex'], ARRAY['agent_feed'], 30),
  ('Life', 'life', 'Life management: reminders, task completions, health nudges, appointments',
   ARRAY['reminder', 'todo', 'health', 'life'], ARRAY['agent_feed'], 30),
  ('Briefing', 'briefing', 'Agent briefings: morning brief, evening wind-down, weekly review',
   ARRAY['briefing', 'digest'], ARRAY['agent_feed'], 20)
ON CONFLICT (slug) DO NOTHING;
```

- [ ] **Step 2: Make BASE_URL configurable in `modules/feeds/generator.py`**

Replace the hard-coded `BASE_URL = "http://localhost:8000"` (line 18) with:

```python
from app.config import settings

def _get_base_url() -> str:
    """Return the public base URL for feed links."""
    return getattr(settings, 'feeds_base_url', '') or 'http://localhost:8000'
```

Use `_get_base_url()` in `_generate_feed_xml()` instead of `BASE_URL`.

- [ ] **Step 3: Add `feeds_base_url` to config**

In `app/config.py`, add to the Settings class:

```python
feeds_base_url: str = ""  # Public URL for RSS feed links (e.g. http://lamadb.tailnet:8000)
```

In `modules/feeds/__init__.py`, add:

```python
MODULE_CONFIG_SCHEMA = {
    "feeds_base_url": {
        "type": "str", "default": "", "env": "FRESHRSS_URL",
        "label": "Feed Base URL",
        "description": "Public URL for RSS feed links (default: http://localhost:8000)",
        "required": False,
        "placeholder": "http://lamadb:8000",
    },
}
```

- [ ] **Step 4: Apply migration and verify**

```bash
docker compose build api && docker compose up -d api --force-recreate
# Check feeds were created
docker compose exec -T postgres psql -U lamadb -d lamadb -c "SELECT slug, name, filter_tags FROM feeds;"
```

Expected: 4 feeds (lamalab, media, life, briefing).

- [ ] **Step 5: Commit**

```bash
git add migrations/029_feed_publishing.sql modules/feeds/generator.py modules/feeds/__init__.py app/config.py
git commit -m "feat(feeds): seed initial feeds + configurable base URL"
```

---

### Task 9: Feed Publish Endpoint + Convention

**Files:**
- Modify: `modules/feeds/routes.py` (add publish endpoint)
- Modify: `modules/feeds/models.py` (add PublishEntry model)

- [ ] **Step 1: Add `PublishEntry` model to `modules/feeds/models.py`**

```python
class PublishEntry(BaseModel):
    """Model for publishing an entry to a feed."""
    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(default="")
    tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
```

- [ ] **Step 2: Add `POST /api/feeds/{slug}/publish` to `modules/feeds/routes.py`**

```python
from .models import Feed, FeedCreate, FeedUpdate, PublishEntry


@router.post(
    "/{slug}/publish",
    status_code=status.HTTP_201_CREATED,
)
async def publish_to_feed(
    slug: str,
    entry: PublishEntry,
    user: Annotated[AuthUser, Depends(get_current_user)],
):
    """
    Publish an entry to an RSS feed. Creates a document with source_type='agent_feed'
    and tags matching the feed's filter_tags.
    """
    if user.role not in ("admin", "agent"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin or agent role required")

    pool = get_pool()
    async with pool.acquire() as conn:
        # Look up the feed
        feed_row = await conn.fetchrow(
            "SELECT id, filter_tags, filter_source_types FROM feeds WHERE slug = $1", slug
        )
        if feed_row is None:
            raise HTTPException(status_code=404, detail=f"Feed '{slug}' not found")

        feed_tags = list(feed_row["filter_tags"]) if feed_row["filter_tags"] else []

        # Merge feed tags with entry tags (deduplicated)
        all_tags = list(set(feed_tags + entry.tags))

        # Create the document
        doc_id = await conn.fetchval(
            """
            INSERT INTO documents (source_type, title, content, tags, metadata)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            "agent_feed",
            entry.title,
            entry.content,
            all_tags,
            json.dumps({
                **entry.metadata,
                "feed_slug": slug,
                "published_by": user.user_id or user.key_prefix,
            }),
        )

        return {"status": "published", "document_id": str(doc_id), "feed": slug, "tags": all_tags}
```

- [ ] **Step 3: Test the publish endpoint**

```bash
# Publish to lamalab feed
curl -s -X POST http://localhost:8000/api/feeds/lamalab/publish \
  -H "Authorization: Bearer <admin_key>" \
  -H "Content-Type: application/json" \
  -d '{"title":"Test agent entry","content":"This is a test of the RSS publishing system.","tags":["test"]}'

# Check it appears in the RSS XML
curl -s http://localhost:8000/feeds/lamalab.xml | head -30
```

Expected: Document created, RSS XML shows the new entry.

- [ ] **Step 4: Commit**

```bash
git add modules/feeds/routes.py modules/feeds/models.py
git commit -m "feat(feeds): add POST /api/feeds/{slug}/publish endpoint"
```

---

### Task 10: Morning Brief Proof of Concept

**Files:**
- Create: `modules/feeds/briefing.py` (briefing generator)
- Modify: `app/main.py` (optional: add briefing to poller loop)

This task creates a standalone function that generates a morning brief from LamaDB data. It can be called by an agent via cron, or wired into the poller loop later.

- [ ] **Step 1: Create `modules/feeds/briefing.py`**

```python
"""Morning brief generator — creates a briefing feed entry from LamaDB data."""
import json
from datetime import datetime, timezone

from app.db import get_pool


async def generate_morning_brief() -> dict:
    """
    Generate a morning brief by querying LamaDB for notable overnight activity.
    Returns the published document info.

    Called by agents via cron or manually. Writes a document to the 'briefing' feed.
    """
    pool = get_pool()
    sections = []

    async with pool.acquire() as conn:
        # 1. Overnight uptime incidents
        incidents = await conn.fetch(
            """
            SELECT title, severity, ts FROM events
            WHERE source = 'uptime_kuma' AND severity IN ('critical', 'warning')
              AND ts > now() - interval '12 hours'
            ORDER BY ts DESC LIMIT 5
            """
        )
        if incidents:
            lines = [f"- {r['title']} ({r['severity']})" for r in incidents]
            sections.append("## Service Incidents\n" + "\n".join(lines))

        # 2. Recent kanban completions
        completions = await conn.fetch(
            """
            SELECT e.title, e.ts FROM events e
            WHERE e.source = 'kanban' AND e.type = 'task_completed'
              AND e.ts > now() - interval '12 hours'
            ORDER BY e.ts DESC LIMIT 5
            """
        )
        if completions:
            lines = [f"- {r['title']}" for r in completions]
            sections.append("## Tasks Completed\n" + "\n".join(lines))

        # 3. New Plex content (from notflix events)
        new_media = await conn.fetch(
            """
            SELECT title, ts FROM events
            WHERE source = 'notflix' AND type = 'new_content'
              AND ts > now() - interval '24 hours'
            ORDER BY ts DESC LIMIT 5
            """
        )
        if new_media:
            lines = [f"- {r['title']}" for r in new_media]
            sections.append("## New Media\n" + "\n".join(lines))

        # 4. Unread notification count
        unread = await conn.fetchval(
            "SELECT count(*) FROM events WHERE processed = false AND severity IN ('warning', 'critical')"
        )
        if unread and unread > 0:
            sections.append(f"## Notifications\n- {unread} unread notifications require attention")

        # 5. Active agents
        agents = await conn.fetch(
            """
            SELECT name, last_active_at FROM users
            WHERE type = 'agent' AND status = 'active'
              AND last_active_at > now() - interval '12 hours'
            ORDER BY last_active_at DESC LIMIT 5
            """
        )
        if agents:
            lines = [f"- {r['name']} (active {r['last_active_at'].strftime('%H:%M')})" for r in agents]
            sections.append("## Active Agents\n" + "\n".join(lines))

    # Build the brief
    now = datetime.now(timezone.utc)
    if not sections:
        content = "Quiet night — nothing notable to report. All systems nominal."
        title = f"Morning Brief — {now.strftime('%B %d, %Y')} — All Clear"
    else:
        content = "\n\n".join(sections)
        title = f"Morning Brief — {now.strftime('%B %d, %Y')}"

    # Publish to the briefing feed
    async with pool.acquire() as conn:
        doc_id = await conn.fetchval(
            """
            INSERT INTO documents (source_type, title, content, tags, metadata)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            "agent_feed",
            title,
            content,
            ["briefing", "digest", "morning"],
            json.dumps({"brief_type": "morning", "generated_at": now.isoformat()}),
        )

    return {"status": "published", "document_id": str(doc_id), "title": title, "sections": len(sections)}
```

- [ ] **Step 2: Test manually**

```bash
# Call the briefing generator via API (add a quick debug endpoint or call from Python)
docker compose exec api python3 -c "
import asyncio
from modules.feeds.briefing import generate_morning_brief
result = asyncio.run(generate_morning_brief())
print(result)
"

# Check the briefing feed
curl -s http://localhost:8000/feeds/briefing.xml | head -40
```

- [ ] **Step 3: Commit**

```bash
git add modules/feeds/briefing.py
git commit -m "feat(feeds): morning brief generator from LamaDB data"
```

---

### Task 11: Feed Pruning

**Files:**
- Create: `modules/feeds/cleanup.py`
- Modify: `app/main.py` (add to daily maintenance)

- [ ] **Step 1: Create `modules/feeds/cleanup.py`**

```python
"""Feed entry pruning — removes old agent_feed documents based on retention policy."""
import logging

from app.db import get_pool

logger = logging.getLogger(__name__)

# Default retention: 60 days
DEFAULT_RETENTION_DAYS = 60


async def prune_feed_entries(retention_days: int = DEFAULT_RETENTION_DAYS) -> dict:
    """
    Delete agent_feed documents older than retention_days.
    Returns count of deleted entries.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM documents
            WHERE source_type = 'agent_feed'
              AND created_at < now() - $1::interval
            """,
            f"{retention_days} days",
        )
        # result is like "DELETE 42"
        count = int(result.split()[-1]) if result.startswith("DELETE") else 0
        if count > 0:
            logger.info(f"Pruned {count} feed entries older than {retention_days} days")
        return {"pruned": count, "retention_days": retention_days}
```

- [ ] **Step 2: Wire into daily maintenance**

In the existing daily maintenance task (if `run_maintenance()` exists), add a call to `prune_feed_entries()`. Alternatively, add a comment noting it can be called from the poller loop or a cron job.

- [ ] **Step 3: Test**

```bash
docker compose exec api python3 -c "
import asyncio
from modules.feeds.cleanup import prune_feed_entries
result = asyncio.run(prune_feed_entries(retention_days=0))  # delete all for test
print(result)
"
```

- [ ] **Step 4: Commit**

```bash
git add modules/feeds/cleanup.py
git commit -m "feat(feeds): add feed entry pruning with configurable retention"
```

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-16-mcp-architecture-and-rss-feeds.md`.**

**Two tracks:**
- **Track 1 (Tasks 1-7):** MCP Architecture — consolidate 29→11 tools, split admin/worker endpoints, add stats + frontend control pane
- **Track 2 (Tasks 8-11):** RSS Feeds — seed feeds, publish endpoint, morning brief, pruning

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Best for Track 1 since tasks are sequential with dependencies.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints. Best if you want to stay in one conversation.

**Which approach?**
