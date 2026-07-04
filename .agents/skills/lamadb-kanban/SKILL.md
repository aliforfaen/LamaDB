# LamaDB Kanban

## When to Use

You are working with the LamaDB kanban board. Reach for these tools when the user asks you to:

- Find or pick up work ("what should I work on?", "find an open task", "pick up the next task")
- Move a task through its lifecycle (claim → start → complete)
- Create a new task ("add a task to <board>", "file a bug", "open a ticket")
- Update an existing task (change priority, edit description, add tags)
- Ask a human for help on a task you're stuck on
- Comment on a task thread
- Look up your own onboarding / runtime instructions
- Create a task from a saved template

**Don't use kanban for:** storing free-form notes, long-form documents, or wiki-style content. Use `agent_documents` (lamadb-docs skill) or `agent_wiki` for that.

## Connection

- Admin endpoint: `http://lamadb:8000/mcp/admin` (exposes kanban tools, plus admin-only tools)
- Worker endpoint: `http://lamadb:8000/mcp/worker` (also exposes kanban tools — `toolset="both"`)
- Auth header: `Authorization: Bearer <api_key>` (admin key for full access; agent key scoped to `kanban`)
- Protocol: JSON-RPC 2.0 over HTTP POST
- `user_id` is **injected automatically** from the API key — never pass it yourself

To discover boards/columns/tasks outside MCP, the REST surface is at `/api/kanban/...` (see [lamadb-docs skill](lamadb-docs)).

## Tools

All four tools use the consolidated action pattern: a single MCP tool name dispatches to one of several actions via the `action` parameter.

### `agent_kanban_tasks` — task CRUD + discovery

| Action | Purpose | Required params | Optional params |
|--------|---------|-----------------|-----------------|
| `my_tasks` | Open tasks assigned to **you** | — | `board_id` (filter to one board) |
| `find_work` | Unassigned tasks in Backlog columns (across boards) | — | `board_id` |
| `get` | Full task detail (subtasks, comments, deps) | `task_id` | — |
| `create` | New task in a board's Backlog | `board_id`, `title` | `description`, `priority`, `tags` |
| `create_from_template` | New task from a saved template | `board_id`, `template_id` | `title_override` |
| `update` | Edit fields of an existing task | `task_id` | `title`, `description`, `priority`, `tags` |

`priority` is a free-form string column. Conventional values: `low`, `medium`, `high`, `critical`. `tags` is a string array (GIN-indexed; filterable via REST `?tag=foo`).

### `agent_kanban_workflow` — task lifecycle

| Action | Purpose | Required params | Optional params |
|--------|---------|-----------------|-----------------|
| `claim` | Assign yourself + move to In Progress | `task_id` | — |
| `start` | Start work (auto-claims if unassigned) | `task_id` | — |
| `complete` | Mark Done + auto-start dependent tasks | `task_id` | `summary` (recorded in audit log) |
| `help_wanted` | Flag task as needing human help | `task_id`, `message` | — |

### `agent_kanban_comments` — discussion

| Action | Purpose | Required params |
|--------|---------|-----------------|
| `add` | Append a comment to a task | `task_id`, `body` |

### `agent_kanban_meta` — agent self-config

| Action | Purpose | Required params |
|--------|---------|-----------------|
| `my_instructions` | Get your per-agent instructions and any board-level guidance | — |

## Workflows

### Pick up the next available task

```bash
# 1. Find unassigned backlog work
curl -X POST http://lamadb:8000/mcp/admin \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "agent_kanban_tasks",
      "arguments": {"action": "find_work"}
    }
  }'

# 2. Pick the highest-priority task from the response, then claim it
curl -X POST http://lamadb:8000/mcp/admin \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "agent_kanban_workflow",
      "arguments": {"action": "claim", "task_id": "<uuid-from-step-1>"}
    }
  }'
```

### Run a task to completion

```json
// 1. Start (no-op if already yours and in progress)
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
  "name":"agent_kanban_workflow",
  "arguments":{"action":"start","task_id":"<task-id>"}}}

// 2. Do the work outside the tool...

// 3. Comment with progress (optional)
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{
  "name":"agent_kanban_comments",
  "arguments":{"action":"add","task_id":"<task-id>",
               "body":"Implemented X, ran tests, ready for review."}}}

// 4. Mark complete (move to Done column, auto-start any tasks whose deps are now met)
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{
  "name":"agent_kanban_workflow",
  "arguments":{"action":"complete","task_id":"<task-id>",
               "summary":"Implemented X, added tests, updated docs."}}}
```

### Create a new task

First, get the board ID from the REST API (the MCP `find_work`/`my_tasks` outputs also include the board name, not the ID — you need the UUID for `create`):

```bash
curl -H "Authorization: Bearer $API_KEY" \
  http://lamadb:8000/api/kanban/boards
```

Then create:

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
  "name":"agent_kanban_tasks",
  "arguments":{
    "action":"create",
    "board_id":"<uuid>",
    "title":"Investigate slow /api/search",
    "description":"Search latency spiked to 800ms. Check HNSW index, query plan.",
    "priority":"high",
    "tags":["perf","search"]
  }}}
```

The task lands in the board's first `status='backlog'` column (Backlog for agentic boards, Inbox for personal). It auto-numbers per-board.

### Create from a template

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
  "name":"agent_kanban_tasks",
  "arguments":{
    "action":"create_from_template",
    "board_id":"<uuid>",
    "template_id":"<template-uuid>",
    "title_override":"Triage upstream CVE-2026-1234"
  }}}
```

Templates pre-fill title, description, priority, tags, and create the configured subtasks.

### Ask a human for help

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
  "name":"agent_kanban_workflow",
  "arguments":{
    "action":"help_wanted",
    "task_id":"<uuid>",
    "message":"Need a Postgres superuser to run ANALYZE on events table. Bot lacks privilege."
  }}}
```

The task gets `help_wanted=true` plus the message; a human reviews and reassigns.

### Read your own instructions

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
  "name":"agent_kanban_meta",
  "arguments":{"action":"my_instructions"}}}
```

Returns `{agent, instructions, board_instructions: [{board, instructions}]}`. Read this once at the start of a session before doing kanban work — it may contain per-board rules and your own runbook.

## Gotchas

- **`board_id` is a UUID, not a board name.** `find_work` and `my_tasks` return `board_name` for display — the create/update/claim paths all need the actual UUID. If you don't have it, hit `GET /api/kanban/boards`.
- **`task_id` is a UUID string.** All MCP results serialize it as `str(...)` so it's safe to pass back; just don't try to coerce to int.
- **`priority` accepts any string** — the schema doesn't validate against an enum. Stick to `low|medium|high|critical` to stay consistent with the dashboard UI.
- **`complete` moves the task to the `status='done'` column AND auto-starts dependents.** Any task in `kanban_task_dependencies` whose other deps are also complete will jump to In Progress. This is the explicit design — don't call `start` on a task that was just unblocked by `complete`.
- **`start` is a soft claim.** It uses `COALESCE(assignee_id, $1)`, so calling it on a task someone else owns will NOT reassign — only `claim` reassigns unconditionally.
- **`claim` only works on unassigned tasks in the literal sense.** If a task is already yours and you call `claim`, it just moves the column; it won't error.
- **`my_tasks` filters by `completed_at IS NULL`.** Completed tasks won't appear — use the REST API if you need history.
- **`find_work` filters by `c.status = 'backlog'`.** Tasks in `in_progress` or `review` won't show up, even if unassigned.
- **No DELETE action.** You can't remove a task via MCP. If you need to, do it through the REST API or ask a human.
- **Cache invalidation:** `create` does NOT invalidate the cache (only `complete` and `create_from_template` do). If you create a task and the dashboard doesn't show it, it's a stale-cache symptom, not a write failure.
- **Tags are an array, not a comma-separated string.** Pass `["perf","search"]`, not `"perf,search"`.
- **`summary` on `complete` is the audit log entry.** It's visible in the task's history. Use it to record what you actually did.
- **JSON-RPC result wrapping:** `tools/call` returns `result.content[0].text` as a JSON string. Parse that string to get the actual payload — don't treat the outer JSON as your data.
- **Endpoint choice:** `/mcp/worker` works for all kanban tools (they're `toolset="both"`). Use `/mcp/admin` only if you also need admin-only tools in the same session.
- **You can't move a task to a specific column via MCP.** The lifecycle is fixed: claim → In Progress, complete → Done, help_wanted → stays where it is (with a flag). Column moves are dashboard-only.
