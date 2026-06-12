# Agent Onboarding Docs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create AGENTS_API.md for AI agents and expose it via MCP so agents can read it without file access.

**Architecture:** Documentation file in repo root + MCP tool handler that reads and returns the file content. Optional skill for structured guidance.

**Tech Stack:** Markdown, Python (FastAPI MCP handler)

---

## File Map

| Action | File | Purpose |
|--------|------|---------|
| Create | `AGENTS_API.md` | Agent-facing API reference |
| Modify | `app/core/mcp.py` | Add `lamadb_docs` tool handler |
| Modify | `app/core/__init__.py` | Register MCP tool |

---

### Task 1: Write AGENTS_API.md

**Files:**
- Create: `AGENTS_API.md`

- [ ] **Step 1: Create the document**

Write `AGENTS_API.md` in the repo root with these sections:

```markdown
# LamaDB Agent API Reference

> For AI agents connecting to LamaDB via MCP or REST API.

## Quick Start

**Connection:**
- REST API: `http://lamadb:8000/api/`
- MCP Server: `http://lamadb:8000/mcp` (JSON-RPC 2.0)
- Auth: `Authorization: Bearer <your-api-key>`

**Identity:** Your API key is linked to a user profile. The `user_id` from your key is used for task assignment, comments, and agent logs.

## MCP Tools

### kanban_my_tasks
Get open tasks assigned to you.

**Parameters:**
- `board_id` (optional, string): Filter to specific board

**Returns:**
```json
{
  "tasks": [
    {"id": "uuid", "board": "Sprint 1", "column": "In Progress", "task_number": 5, "title": "Fix login bug", "priority": "high"}
  ],
  "count": 1
}
```

### kanban_find_work
Find unassigned tasks in Backlog columns.

**Parameters:**
- `board_id` (optional, string): Filter to specific board

**Returns:**
```json
{
  "tasks": [
    {"id": "uuid", "board": "Sprint 1", "board_type": "agentic", "task_number": 12, "title": "Add tests", "priority": "medium", "description": "..."}
  ],
  "count": 1
}
```

### kanban_start_task
Start working on a task. Auto-claims if unassigned, moves to In Progress.

**Parameters:**
- `task_id` (required, string): Task UUID

**Returns:** `{"status": "started", "task_id": "uuid"}`

### kanban_complete_task
Complete a task. Moves to Done column and auto-starts dependents whose dependencies are all met.

**Parameters:**
- `task_id` (required, string): Task UUID
- `summary` (optional, string): Completion summary

**Returns:** `{"status": "completed", "task_id": "uuid"}`

### kanban_create_task
Create a new task in a board's Backlog column.

**Parameters:**
- `board_id` (required, string): Board UUID
- `title` (required, string): Task title
- `description` (optional, string): Task description
- `priority` (optional, string): "low" | "medium" | "high" | "critical" (default: "medium")

**Returns:** `{"status": "created", "task_id": "uuid", "task_number": 5}`

### kanban_update_task
Update task fields.

**Parameters:**
- `task_id` (required, string): Task UUID
- `title` (optional, string): New title
- `description` (optional, string): New description
- `priority` (optional, string): New priority

**Returns:** `{"status": "updated", "task_id": "uuid"}`

### kanban_add_comment
Add a comment to a task.

**Parameters:**
- `task_id` (required, string): Task UUID
- `body` (required, string): Comment text

**Returns:** `{"status": "commented", "task_id": "uuid"}`

### kanban_get_task
Get full task details including subtasks, comments, and dependencies.

**Parameters:**
- `task_id` (required, string): Task UUID

**Returns:**
```json
{
  "task": {
    "id": "uuid", "board": "Sprint 1", "column": "In Progress",
    "task_number": 5, "title": "Fix login bug", "description": "...",
    "priority": "high", "assignee": "muninn",
    "help_wanted": false, "help_wanted_message": null,
    "completed": false,
    "subtasks": [{"title": "Write test", "completed": true}],
    "comments": [{"user": "muninn", "body": "Started working on this"}],
    "dependencies": [{"depends_on": "Setup DB", "completed": true}]
  }
}
```

### kanban_help_wanted
Flag a task as needing human help.

**Parameters:**
- `task_id` (required, string): Task UUID
- `message` (required, string): What help is needed

**Returns:** `{"status": "flagged", "task_id": "uuid", "message": "..."}`

### kanban_my_instructions
Get your agent instructions and board-level instructions.

**Parameters:** None

**Returns:**
```json
{
  "agent": "muninn",
  "instructions": "You are a helpful assistant...",
  "board_instructions": [
    {"board": "Sprint 1", "instructions": "Focus on bug fixes"}
  ]
}
```

### kanban_claim_task
Claim a task and move it to In Progress.

**Parameters:**
- `task_id` (required, string): Task UUID

**Returns:** `{"status": "claimed", "task_id": "uuid"}`

## Task Lifecycle

```
Backlog → In Progress → Review → Done
   ↑          ↓
   └── help_wanted (escalate to human)
```

1. **Find work:** Call `kanban_find_work` to see available tasks
2. **Start:** Call `kanban_start_task` to claim and move to In Progress
3. **Work:** Use `kanban_add_comment` to log progress
4. **Complete:** Call `kanban_complete_task` when done
5. **Dependencies:** Completing a task auto-starts dependents

## Board Types

| Type | Default Columns | Use Case |
|------|----------------|----------|
| Agentic | Backlog → In Progress → Review → Done | Agent task queues |
| Personal | Inbox → In Progress → Review → Done | Human task tracking |

## REST API (Alternative to MCP)

If you prefer HTTP over MCP:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/kanban/boards` | GET | List boards |
| `/api/kanban/boards/{id}/tasks` | GET | List tasks |
| `/api/kanban/tasks` | POST | Create task |
| `/api/kanban/tasks/{id}` | GET | Get task |
| `/api/kanban/tasks/{id}` | PATCH | Update task |
| `/api/kanban/tasks/{id}/claim` | POST | Claim task |
| `/api/kanban/tasks/{id}/complete` | POST | Complete task |
| `/api/kanban/tasks/{id}/comments` | POST | Add comment |

## Error Handling

All errors return: `{"error": "message"}`

Common patterns:
- Task not found: `{"error": "Task not found"}`
- Invalid input: HTTP 422 with validation details
- Rate limiting: HTTP 429 (retry after delay)

## Real-time Updates

Subscribe to `kanban_task_updated` SSE channel for task changes:
```
GET /api/dashboard/stream?key=<your-api-key>
```
Events: `task_created`, `task_claimed`, `task_completed`, `task_moved`
```

- [ ] **Step 2: Commit**

```bash
git add AGENTS_API.md
git commit -m "docs: add AGENTS_API.md for AI agent onboarding"
```

---

### Task 2: Add lamadb_docs MCP Tool

**Files:**
- Modify: `app/core/mcp.py`
- Modify: `app/core/__init__.py`

- [ ] **Step 1: Add the tool handler to mcp.py**

At the end of `app/core/mcp.py`, add:

```python
async def lamadb_docs(topic: str = "api") -> dict:
    """Read LamaDB documentation. Use topic='api' for the full agent API reference."""
    from pathlib import Path

    docs = {
        "api": Path(__file__).parent.parent.parent / "AGENTS_API.md",
    }

    path = docs.get(topic)
    if not path or not path.exists():
        return {"error": f"Documentation topic '{topic}' not found", "available": list(docs.keys())}

    content = await asyncio.to_thread(path.read_text)
    return {"topic": topic, "content": content}
```

- [ ] **Step 2: Register the tool in __init__.py**

Create `app/core/__init__.py` (currently empty) with the MCP tool registration:

```python
"""Core module — document/event operations and agent docs."""

MODULE_MCP_TOOLS = [
    {
        "name": "lamadb_docs",
        "description": "Read LamaDB documentation. topic='api' for full agent API reference.",
        "handler": "app.core.mcp:lamadb_docs",
    },
]
```

- [ ] **Step 3: Verify MCP registry discovers the tool**

Check that `app/mcp_registry.py` picks up tools from `app/core/__init__.py`. The registry scans modules in `modules/` but core tools may need explicit registration.

- [ ] **Step 4: Commit**

```bash
git add app/core/mcp.py app/core/__init__.py
git commit -m "feat(mcp): add lamadb_docs tool for agent self-documentation"
```

---

### Task 3: Verify MCP Tool Works

**Files:**
- Test manually via Swagger or MCP client

- [ ] **Step 1: Rebuild and restart**

```bash
docker compose build api && docker compose up -d api
```

- [ ] **Step 2: Test via MCP**

Send MCP request to verify the tool returns AGENTS_API.md content.

- [ ] **Step 3: Commit any fixes if needed**
