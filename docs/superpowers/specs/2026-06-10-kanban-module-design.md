# LamaDB Kanban Module — Design Spec

> **Date:** 2026-06-10 | **Source:** LlamaBan (`~/LamaFiles/projects/kanban/`) backported into LamaDB
> **Status:** Approved — awaiting implementation plan

## Overview

Backport LlamaBan's agent orchestration smarts into LamaDB as a new `modules/kanban/` module. Port the backend logic (task state machines, dependency auto-start, agent routing, help-wanted protocol, MCP tools) and build a lightweight vanilla-JS Kanban board inside the existing dashboard. Single container, single codebase, same stack.

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                   LamaDB (8000)                       │
│                                                       │
│  modules/kanban/          app/core/                   │
│  ├── routes.py            ├── users.py  (new)         │
│  ├── models.py            └── dashboard.py (extended) │
│  ├── mcp.py                                           │
│  └── __init__.py                                      │
│                                                       │
│  static/js/pages/kanban.js   (new board UI)           │
│  static/js/pages/users.js    (new user mgmt)          │
│                                                       │
│  app/mcp_server.py           (extended: kanban tools) │
│  app/auth.py                 (extended: user_id join)  │
│                                                       │
│  PostgreSQL (shared DB)                               │
│  ├── users, api_keys (extended)                       │
│  ├── kanban_boards, kanban_columns                    │
│  ├── kanban_tasks, kanban_subtasks                    │
│  ├── kanban_task_dependencies                         │
│  ├── kanban_comments, kanban_agent_logs               │
└──────────────────────────────────────────────────────┘
```

## Data Model

### New tables (migration 014_kanban_core.sql)

**users** — Identity profiles (sits alongside api_keys)
```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL DEFAULT 'agent',  -- 'human' | 'agent'
    status TEXT NOT NULL DEFAULT 'active', -- active, inactive, suspended
    instructions TEXT,                     -- per-agent guidance on connect
    last_active_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE api_keys ADD COLUMN user_id UUID REFERENCES users(id);
ALTER TABLE agent_messages ALTER COLUMN from_agent TYPE TEXT; -- no schema change needed, just data fix
```

**kanban_boards**
```sql
CREATE TABLE kanban_boards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'agentic',  -- 'agentic' | 'personal'
    instructions TEXT,                      -- board-level agent instructions
    owner_id UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
```

**kanban_columns**
```sql
CREATE TABLE kanban_columns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    board_id UUID NOT NULL REFERENCES kanban_boards(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    status TEXT NOT NULL,           -- 'backlog', 'in_progress', 'review', 'done'
    position INT NOT NULL DEFAULT 0,
    wip_limit INT
);
```

**kanban_tasks**
```sql
CREATE TABLE kanban_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    board_id UUID NOT NULL REFERENCES kanban_boards(id) ON DELETE CASCADE,
    column_id UUID NOT NULL REFERENCES kanban_columns(id),
    task_number INT NOT NULL,       -- per-board human-readable counter
    title TEXT NOT NULL,
    description TEXT,
    priority TEXT DEFAULT 'medium', -- low, medium, high, critical
    due_at TIMESTAMPTZ,
    assignee_id UUID REFERENCES users(id),
    position INT DEFAULT 0,
    help_wanted BOOLEAN DEFAULT false,
    help_wanted_message TEXT,
    estimate TEXT,                   -- freeform: "2h", "1d", "XL"
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
```

**kanban_subtasks**
```sql
CREATE TABLE kanban_subtasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES kanban_tasks(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    completed BOOLEAN DEFAULT false,
    position INT DEFAULT 0,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

**kanban_task_dependencies**
```sql
CREATE TABLE kanban_task_dependencies (
    task_id UUID NOT NULL REFERENCES kanban_tasks(id) ON DELETE CASCADE,
    depends_on_id UUID NOT NULL REFERENCES kanban_tasks(id) ON DELETE CASCADE,
    PRIMARY KEY (task_id, depends_on_id)
);
```

**kanban_comments**
```sql
CREATE TABLE kanban_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES kanban_tasks(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id),
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
```

**kanban_agent_logs**
```sql
CREATE TABLE kanban_agent_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    task_id UUID REFERENCES kanban_tasks(id),
    board_id UUID REFERENCES kanban_boards(id),
    action TEXT NOT NULL,            -- 'task_created', 'task_claimed', etc.
    details TEXT,
    tool TEXT,                       -- MCP tool name
    session_id TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_agent_logs_board ON kanban_agent_logs(board_id, created_at);
CREATE INDEX idx_agent_logs_user ON kanban_agent_logs(user_id, created_at);
```

### NOTIFY triggers (real-time updates)

```sql
CREATE OR REPLACE FUNCTION trg_kanban_task_notify()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify('kanban_task_updated', json_build_object(
        'task_id', NEW.id,
        'board_id', NEW.board_id,
        'column_id', NEW.column_id,
        'action', TG_OP
    )::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_kanban_task_insert AFTER INSERT ON kanban_tasks
    FOR EACH ROW EXECUTE FUNCTION trg_kanban_task_notify();
CREATE TRIGGER trg_kanban_task_update AFTER UPDATE ON kanban_tasks
    FOR EACH ROW EXECUTE FUNCTION trg_kanban_task_notify();
CREATE TRIGGER trg_kanban_task_delete AFTER DELETE ON kanban_tasks
    FOR EACH ROW EXECUTE FUNCTION trg_kanban_task_notify();
```

## API Endpoints

All under existing auth (`Authorization: Bearer <key>`). New router at `/api/kanban/*`.

### Users (`app/core/users.py`)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/users` | admin | List users with stats |
| `POST` | `/api/users` | admin | Create user + auto-generate API key |
| `GET` | `/api/users/{id}` | admin/self | Profile + masked key + stats |
| `PATCH` | `/api/users/{id}` | admin | Update profile |
| `POST` | `/api/users/{id}/rotate-key` | admin | Rotate API key |
| `DELETE` | `/api/users/{id}` | admin | Deactivate user |

### Boards

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/kanban/boards` | any | List boards |
| `POST` | `/api/kanban/boards` | admin | Create board + default columns |
| `GET` | `/api/kanban/boards/{id}` | any | Board with columns + counts |
| `PATCH` | `/api/kanban/boards/{id}` | admin | Update board |
| `DELETE` | `/api/kanban/boards/{id}` | admin | Delete board |

### Columns

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `POST` | `/api/kanban/boards/{id}/columns` | admin | Add column |
| `PATCH` | `/api/kanban/columns/{id}` | admin | Update column |
| `DELETE` | `/api/kanban/columns/{id}` | admin | Remove column |

### Tasks

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/kanban/boards/{id}/tasks` | any | Tasks with filters |
| `POST` | `/api/kanban/boards/{id}/tasks` | admin/agent | Create task |
| `GET` | `/api/kanban/tasks/{id}` | any | Full task detail |
| `PATCH` | `/api/kanban/tasks/{id}` | admin/agent | Update task fields |
| `PATCH` | `/api/kanban/tasks/{id}/move` | admin/agent | Move to column |
| `POST` | `/api/kanban/tasks/{id}/claim` | agent | Claim task |
| `POST` | `/api/kanban/tasks/{id}/complete` | admin/agent | Complete task |

### Subtasks

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `POST` | `/api/kanban/tasks/{id}/subtasks` | admin/agent | Add subtask |
| `PATCH` | `/api/kanban/subtasks/{id}` | admin/agent | Update/toggle subtask |

### Dependencies

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `POST` | `/api/kanban/tasks/{id}/dependencies` | admin/agent | Link dependency |
| `DELETE` | `/api/kanban/tasks/{id}/dependencies/{dep_id}` | admin/agent | Remove dependency |

### Comments

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/kanban/tasks/{id}/comments` | any | Task comments |
| `POST` | `/api/kanban/tasks/{id}/comments` | any | Add comment |

### Agent Connect

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/kanban/me` | any | Agent profile + boards + tasks + instructions |

**Total: 30 endpoints across 8 resource types.**

**`GET /api/kanban/me` response:**
```json
{
  "user": {
    "name": "muninn", "type": "agent",
    "instructions": "You are the orchestrator..."
  },
  "api_key": "lamadb_muninn_****",
  "active_boards": [
    {"id": "...", "name": "Coding Tasks", "type": "agentic"}
  ],
  "my_open_tasks": [
    {"id": "...", "title": "Fix auth bug", "column": "in_progress", "priority": "high"}
  ],
  "endpoints": {
    "mcp": "http://lamadb:8000/mcp",
    "api": "http://lamadb:8000/api/kanban"
  }
}
```

## MCP Tools

Registered via `MODULE_MCP_TOOLS` in `modules/kanban/__init__.py`. Auth via existing Bearer token + role/scope checks.

| Tool | Inputs | Behavior |
|------|--------|----------|
| `kanban_my_tasks` | `board_id?` | Open tasks for calling agent |
| `kanban_find_work` | `board_id?` | Unassigned backlog tasks |
| `kanban_claim_task` | `task_id` | Claim + move to In Progress |
| `kanban_start_task` | `task_id` | Start (auto-claim if needed) |
| `kanban_complete_task` | `task_id`, `summary?` | Complete + auto-start dependents |
| `kanban_create_task` | `board_id`, `title`, `description?`, `priority?` | Create in Backlog |
| `kanban_update_task` | `task_id`, `title?`, `description?`, `priority?` | Update fields |
| `kanban_add_comment` | `task_id`, `body` | Post comment |
| `kanban_get_task` | `task_id` | Full detail with subtasks/comments/deps |
| `kanban_help_wanted` | `task_id`, `message` | Flag help_wanted |
| `kanban_my_instructions` | — | Per-agent + board instructions |

**All tool calls log to `kanban_agent_logs`.**

## Frontend

### Kanban Board (`static/js/pages/kanban.js`)

- **Columns:** CSS grid, 4 columns (Backlog / In Progress / Review / Done for agentic; Inbox / In Progress / Review / Done for personal)
- **Task cards:** Priority dot, task number (#N), title, assignee badge, help-wanted flag, subtask progress (2/5)
- **Drag-drop:** SortableJS between columns. On drop → `PATCH /move`
- **Real-time:** SSE channel `kanban_task_updated` refreshes affected column
- **Inline detail:** Click card → expands inline showing description, subtasks (checkboxes), comments thread, dependency chain, agent log
- **Quick-create:** `[+Add]` at column bottom → inline input
- **Board selector:** Tab bar across top. Click tab to switch boards. `[+ New Board]` as last tab

### User Management (`static/js/pages/users.js`)

- **Table:** Users with type badge, status dot, last active, open tasks count
- **Inline detail:** Click row → expand with full profile, masked API key, rotate button, recent agent logs
- **Create form:** Name, type dropdown, instructions textarea → shows API key once

### Dashboard Integration

- New sidebar nav item "Kanban" (between Agent Board and Wiki)
- New Settings sub-tab "Users" (between API Keys and Module Config)
- SSE extended: `kanban_task_updated` channel added to `pg_listener`

## Task Lifecycle

```
POST /tasks (admin/agent)
       │
       ▼
  ┌──────────┐       agent calls         ┌──────────┐
  │ BACKLOG  │ ──── kanban_find_work ──▶ │ CLAIMED  │
  └──────────┘                           └────┬─────┘
       ▲                                      │
       │                           agent calls kanban_start_task
       │                                      ▼
       │                              ┌──────────────┐
       │                              │ IN PROGRESS  │
       │                              └──────┬───────┘
       │                                     │
       │                      agent calls kanban_complete_task
       │                                     ▼
       │                              ┌──────────┐
       │ ┌───────────────────────────│  REVIEW  │ (agentic boards only)
       │ │                            └────┬─────┘
       │ │                                 │ human approves
       │ │                                 ▼
       │ │                            ┌──────────┐
       │ └─── reopen if blocked ─────│   DONE   │
       │                              └──────────┘
       │                                     │
       └─── reopen (PATCH back to backlog) ──┘

On complete: auto-start dependents if all their deps are now met.
```

## Deferred (Post-Fundamentals)

These are explicitly NOT in this implementation phase but tracked for follow-up:

- **Encrypted secrets** — per-agent secret storage (migrated from LlamaBan's `Secret` model)
- **Tags** — per-board colored labels on tasks
- **Custom fields** — board-level custom field definitions
- **Task templates** — reusable task blueprints per board
- **Board templates** — pre-configured board + column sets
- **Board sharing** — public read-only share links
- **Approval workflow** — human approval gates for agent actions
- **Task transitions audit** — full column movement history
- **User groups** — group-based API key and permission management
- **Swimlanes** — group tasks by assignee within columns

## Cache Strategy

All read endpoints use `@cached` decorator:
- Boards/columns: TTL 120s, tag `kanban`
- Tasks per board: TTL 30s, tag `kanban_tasks`
- Single task detail: TTL 30s, tag `kanban_tasks`
- Users list: TTL 300s, tag `users`

Write endpoints invalidate relevant tags (`kanban`, `kanban_tasks`, `users`).

## Implementation Order

1. **Migration + users table** — foundation, nothing else works without it
2. **`modules/kanban/` backend** — routes, models, MCP tools
3. **NOTIFY triggers + SSE** — real-time updates
4. **Kanban board frontend** — board UI + task cards + drag-drop
5. **User management frontend** — admin UI for users
6. **Dashboard integration** — sidebar nav, SSE channels, tab wiring
7. **Migration script** — port existing `api_keys` entries to `users` table
8. **Agent migration** — update `from_agent`/`created_by` to use `user.name` instead of `user.role`
9. **Dogfood QA** — full pass on boards, tasks, agent workflow
