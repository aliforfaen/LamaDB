# AGENTS_API.md — LamaDB Agent API Reference

Reference for AI agents connecting to LamaDB via MCP or REST.

## Quick Start

- **REST base**: `http://lamadb:8000/api/`
- **MCP endpoint**: `http://lamadb:8000/mcp` (JSON-RPC 2.0)
- **Auth**: `Authorization: Bearer <api_key>` header
- **Identity**: each key is linked to a `users` row; MCP tools use `user_id` for task assignment and audit

Get your key from the dashboard (`/users`) or from an admin. The key's `user_id` is your identity — you are whoever created/owns that key.

## MCP Tools (11 kanban tools)

All tools receive `user_id` automatically from the authenticated key. Call via JSON-RPC 2.0:

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "kanban_my_tasks", "arguments": {}}}
```

### 1. `kanban_my_tasks`
Get open tasks assigned to you.
- **Params**: `board_id` (optional UUID)
- **Returns**: `{tasks: [{id, board, column, task_number, title, priority}], count}`

### 2. `kanban_find_work`
Find unassigned backlog tasks. Use to find work you can claim.
- **Params**: `board_id` (optional UUID)
- **Returns**: `{tasks: [{id, board, board_type, task_number, title, priority, description}], count}` — limited to 20, ordered by priority desc

### 3. `kanban_claim_task`
Claim a task — sets you as assignee and moves to In Progress.
- **Params**: `task_id` (required UUID)
- **Returns**: `{status: "claimed", task_id}` or `{error: "Task not found"}`
- **Logs**: `task_claimed` in `kanban_agent_logs`

### 4. `kanban_start_task`
Start working on a task. Auto-claims if unassigned.
- **Params**: `task_id` (required UUID)
- **Returns**: `{status: "started", task_id}`
- **Logs**: `task_started`

### 5. `kanban_complete_task`
Complete a task. Moves to Done and auto-starts dependent tasks whose deps are now satisfied.
- **Params**: `task_id` (required UUID), `summary` (optional string)
- **Returns**: `{status: "completed", task_id}`
- **Side effect**: any dependent task with all deps complete is moved to In Progress
- **Logs**: `task_completed` with summary as details

### 6. `kanban_create_task`
Create a new task in a board's Backlog column.
- **Params**:
  - `board_id` (required UUID)
  - `title` (required string)
  - `description` (optional string)
  - `priority` (optional, default `"medium"` — `low|medium|high`)
- **Returns**: `{status: "created", task_id, task_number}`

### 7. `kanban_update_task`
Update mutable task fields. Only provided fields are updated.
- **Params**:
  - `task_id` (required UUID)
  - `title` (optional)
  - `description` (optional)
  - `priority` (optional)
- **Returns**: `{status: "updated", task_id}`

### 8. `kanban_add_comment`
Add a comment to a task. Comments are visible to all who can see the task.
- **Params**: `task_id` (required UUID), `body` (required string)
- **Returns**: `{status: "commented", task_id}`

### 9. `kanban_get_task`
Full task details with subtasks, comments, and dependencies.
- **Params**: `task_id` (required UUID)
- **Returns**:
```json
{
  "task": {
    "id": "uuid",
    "board": "string",
    "column": "string",
    "task_number": 42,
    "title": "string",
    "description": "string",
    "priority": "high",
    "assignee": "agent-name or null",
    "help_wanted": false,
    "help_wanted_message": null,
    "completed": false,
    "subtasks": [{"title": "string", "completed": false}],
    "comments": [{"user": "string", "body": "string"}],
    "dependencies": [{"depends_on": "string", "completed": false}]
  }
}
```

### 10. `kanban_help_wanted`
Flag a task as needing human intervention. Sets `help_wanted=true` with a message.
- **Params**: `task_id` (required UUID), `message` (required string)
- **Returns**: `{status: "flagged", task_id, message}`
- **Logs**: `help_wanted` in `kanban_agent_logs`

### 11. `kanban_my_instructions`
Get your per-agent instructions and any board-level instructions.
- **Params**: none
- **Returns**:
```json
{
  "agent": "your-name",
  "instructions": "string or null",
  "board_instructions": [{"board": "string", "instructions": "string"}]
}
```

## Task Lifecycle

```
Backlog  →  In Progress  →  Review  →  Done
   │           │              │
   │           └─ help_wanted ─┘  (any time, flag for human)
   │
   └─ (Personal boards use "Inbox" instead of "Backlog")
```

- **Claim** an unassigned task → moves to In Progress, sets you as assignee
- **Complete** a task → moves to Done; any dependent tasks with all deps satisfied are auto-moved to In Progress
- **help_wanted** → does not move columns; sets a flag visible in the UI

## Board Types

Boards are created as one of two types, which determines default column names:

| Type | Columns |
|------|---------|
| `agentic` | Backlog → In Progress → Review → Done |
| `personal` | Inbox → In Progress → Review → Done |

Column status values (`backlog`, `in_progress`, `review`, `done`) are stable across types — only the human-readable name differs.

## REST API

For agents that prefer HTTP over MCP. All endpoints require `Authorization: Bearer <key>`.

### Boards

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/kanban/boards` | List boards |
| POST | `/api/kanban/boards` | Create board |
| GET | `/api/kanban/boards/{id}` | Board details with columns |
| PATCH | `/api/kanban/boards/{id}` | Update board |
| DELETE | `/api/kanban/boards/{id}` | Delete board |

### Columns

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/kanban/boards/{id}/columns` | List columns |
| POST | `/api/kanban/boards/{id}/columns` | Add column |

### Tasks

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/kanban/boards/{id}/tasks` | List tasks on board |
| POST | `/api/kanban/tasks` | Create task |
| GET | `/api/kanban/tasks/{id}` | Task details |
| PATCH | `/api/kanban/tasks/{id}` | Update task |
| DELETE | `/api/kanban/tasks/{id}` | Delete task |
| POST | `/api/kanban/tasks/{id}/claim` | Claim task |
| POST | `/api/kanban/tasks/{id}/start` | Start task |
| POST | `/api/kanban/tasks/{id}/complete` | Complete task |
| POST | `/api/kanban/tasks/{id}/move` | Move to column |
| POST | `/api/kanban/tasks/{id}/comments` | Add comment |
| GET | `/api/kanban/tasks/{id}/comments` | List comments |
| POST | `/api/kanban/tasks/{id}/subtasks` | Add subtask |
| POST | `/api/kanban/tasks/{id}/dependencies` | Add dependency |
| POST | `/api/kanban/tasks/{id}/help-wanted` | Flag for help |

### My Work

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/kanban/me/tasks` | Tasks assigned to you |
| GET | `/api/kanban/me/boards` | Boards you have access to |

Request/response shapes mirror the MCP tool return values.

## Error Handling

REST returns standard HTTP codes:
- `400` — bad request (missing/invalid params)
- `401` — missing or invalid API key
- `403` — key lacks scope for this module
- `404` — resource not found
- `409` — conflict (e.g., duplicate `task_number` race — server retries once)
- `500` — server error

MCP tool errors come back in the result body as `{"error": "..."}` — not as JSON-RPC errors. Check for the `error` key before assuming success.

Retry on `500` and `409`. Do not retry on `400` or `404`.

## Real-time Updates

Subscribe to SSE at `http://lamadb:8000/api/events/stream` (requires auth). The `kanban_task_updated` channel fires on every INSERT/UPDATE/DELETE of `kanban_tasks`. Event payload:

```json
{"channel": "kanban_task_updated", "data": {"id": "uuid", "board_id": "uuid", ...}}
```

Use SSE to react to task state changes without polling.
