# Kanban Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backport LlamaBan's agent orchestration into LamaDB — Kanban boards, task state machines, user identity, MCP tools, and a dashboard board UI. Single container, vanilla JS frontend, same asyncpg/FastAPI stack.

**Architecture:** New `modules/kanban/` module (routes, models, MCP tools) + new `app/core/users.py` for identity + migration for 8 tables + vanilla JS Kanban board in dashboard + user management in settings. SSE extended for real-time task updates.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, Pydantic, SortableJS (existing), vanilla JS/CSS

---

## File Map

### Create
| File | Responsibility |
|------|---------------|
| `migrations/014_kanban_core.sql` | All 8 tables + NOTIFY triggers + api_keys.user_id FK |
| `modules/kanban/__init__.py` | Module metadata, ENABLED=True, MODULE_MCP_TOOLS |
| `modules/kanban/models.py` | Pydantic models: Board, Column, Task, Subtask, Comment, etc. |
| `modules/kanban/routes.py` | 30 API endpoints for boards, columns, tasks, subtasks, deps, comments, me |
| `modules/kanban/mcp.py` | 11 MCP tools: find_work, claim_task, complete_task, etc. |
| `app/core/users.py` | 6 user management endpoints: create, list, get, patch, rotate-key, delete |
| `static/js/pages/kanban.js` | Kanban board UI: columns, task cards, drag-drop, inline detail, quick-create |
| `static/js/pages/users.js` | User management UI: table, inline detail, create form, API key display |
| `tests/test_kanban.py` | Tests for boards, tasks, subtasks, deps, comments, MCP tools |
| `tests/test_users.py` | Tests for user CRUD, API key generation, rotation, agent connect |

### Modify
| File | What changes |
|------|-------------|
| `app/main.py` | Migration runner picks up 014; SSE pg_listener adds kanban_task_updated channel |
| `app/auth.py` | AuthUser adds user_id field; `from_agent` uses user.name instead of user.role |
| `app/core/dashboard.py` | Overview stats include kanban task counts |
| `app/mcp_server.py` | Tool registry includes kanban tools |
| `app/sse.py` | pg_listener subscribes to kanban_task_updated channel |
| `static/index.html` | Kanban page section, Users settings section, sidebar nav items, script tags |
| `static/js/app.js` | Nav to kanban page, users sub-tab in settings, SSE handler for kanban events |

---

## Task 1: Database Migration

**Files:**
- Create: `migrations/014_kanban_core.sql`

- [ ] **Step 1: Write the migration file**

```sql
-- Migration: 014_kanban_core.sql
-- Users table (identity profiles), kanban tables, and NOTIFY triggers

-- ── Users ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL DEFAULT 'agent',
    status TEXT NOT NULL DEFAULT 'active',
    instructions TEXT,
    last_active_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Link api_keys to users
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id);

-- Seed the admin user from the existing admin API key
INSERT INTO users (name, type, status, instructions)
SELECT 'ali', 'human', 'active', 'Primary human operator'
WHERE NOT EXISTS (SELECT 1 FROM users WHERE name = 'ali');

UPDATE api_keys SET user_id = (SELECT id FROM users WHERE name = 'ali')
WHERE role = 'admin' AND user_id IS NULL;

-- ── Kanban Boards ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS kanban_boards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'agentic',
    instructions TEXT,
    owner_id UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- ── Kanban Columns ────────────────────────────────────────

CREATE TABLE IF NOT EXISTS kanban_columns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    board_id UUID NOT NULL REFERENCES kanban_boards(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    position INT NOT NULL DEFAULT 0,
    wip_limit INT
);

-- ── Kanban Tasks ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS kanban_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    board_id UUID NOT NULL REFERENCES kanban_boards(id) ON DELETE CASCADE,
    column_id UUID NOT NULL REFERENCES kanban_columns(id),
    task_number INT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    priority TEXT DEFAULT 'medium',
    due_at TIMESTAMPTZ,
    assignee_id UUID REFERENCES users(id),
    position INT DEFAULT 0,
    help_wanted BOOLEAN DEFAULT false,
    help_wanted_message TEXT,
    estimate TEXT,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_kanban_tasks_board ON kanban_tasks(board_id, column_id);
CREATE INDEX IF NOT EXISTS idx_kanban_tasks_assignee ON kanban_tasks(assignee_id);

-- ── Kanban Subtasks ───────────────────────────────────────

CREATE TABLE IF NOT EXISTS kanban_subtasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES kanban_tasks(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    completed BOOLEAN DEFAULT false,
    position INT DEFAULT 0,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- ── Kanban Task Dependencies ──────────────────────────────

CREATE TABLE IF NOT EXISTS kanban_task_dependencies (
    task_id UUID NOT NULL REFERENCES kanban_tasks(id) ON DELETE CASCADE,
    depends_on_id UUID NOT NULL REFERENCES kanban_tasks(id) ON DELETE CASCADE,
    PRIMARY KEY (task_id, depends_on_id)
);

-- ── Kanban Comments ───────────────────────────────────────

CREATE TABLE IF NOT EXISTS kanban_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES kanban_tasks(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id),
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- ── Kanban Agent Logs ─────────────────────────────────────

CREATE TABLE IF NOT EXISTS kanban_agent_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    task_id UUID REFERENCES kanban_tasks(id),
    board_id UUID REFERENCES kanban_boards(id),
    action TEXT NOT NULL,
    details TEXT,
    tool TEXT,
    session_id TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_logs_board ON kanban_agent_logs(board_id, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_logs_user ON kanban_agent_logs(user_id, created_at);

-- ── NOTIFY Trigger for real-time task updates ─────────────

CREATE OR REPLACE FUNCTION trg_kanban_task_notify()
RETURNS TRIGGER AS $$
DECLARE
    payload text;
    board uuid;
    col uuid;
    op text;
BEGIN
    op := TG_OP;
    IF op = 'DELETE' THEN
        board := OLD.board_id;
        col := OLD.column_id;
    ELSE
        board := NEW.board_id;
        col := NEW.column_id;
    END IF;
    payload := json_build_object(
        'task_id', CASE WHEN op = 'DELETE' THEN OLD.id ELSE NEW.id END,
        'board_id', board,
        'column_id', col,
        'action', op
    )::text;
    PERFORM pg_notify('kanban_task_updated', payload);
    IF op = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_kanban_task_insert ON kanban_tasks;
CREATE TRIGGER trg_kanban_task_insert AFTER INSERT ON kanban_tasks
    FOR EACH ROW EXECUTE FUNCTION trg_kanban_task_notify();

DROP TRIGGER IF EXISTS trg_kanban_task_update ON kanban_tasks;
CREATE TRIGGER trg_kanban_task_update AFTER UPDATE ON kanban_tasks
    FOR EACH ROW EXECUTE FUNCTION trg_kanban_task_notify();

DROP TRIGGER IF EXISTS trg_kanban_task_delete ON kanban_tasks;
CREATE TRIGGER trg_kanban_task_delete AFTER DELETE ON kanban_tasks
    FOR EACH ROW EXECUTE FUNCTION trg_kanban_task_notify();
```

- [ ] **Step 2: Rebuild and verify migration runs**

```bash
docker compose build api && docker compose up -d api
```

Verify tables exist:

```bash
docker exec lamadb_postgres psql -U lamadb -d lamadb -c "\dt kanban_*"
docker exec lamadb_postgres psql -U lamadb -d lamadb -c "\dt users"
```

Expected: 8 kanban tables + users table visible.

- [ ] **Step 3: Commit**

```bash
git add migrations/014_kanban_core.sql
git commit -m "feat(kanban): add core tables, users, and NOTIFY triggers"
```

---

## Task 2: Pydantic Models

**Files:**
- Create: `modules/kanban/__init__.py`
- Create: `modules/kanban/models.py`

- [ ] **Step 1: Write `modules/kanban/__init__.py`**

```python
"""Kanban module — agent-orchestrated task boards backed by LamaDB."""
MODULE_NAME = "kanban"
MODULE_DESCRIPTION = "Kanban boards with agent task orchestration"
MODULE_VERSION = "0.1.0"
ENABLED = True

MODULE_MCP_TOOLS = [
    {"name": "kanban_my_tasks", "description": "Get open tasks assigned to the calling agent", "handler": "modules.kanban.mcp:kanban_my_tasks"},
    {"name": "kanban_find_work", "description": "Find unassigned backlog tasks to pick up", "handler": "modules.kanban.mcp:kanban_find_work"},
    {"name": "kanban_claim_task", "description": "Claim a task and move it to In Progress", "handler": "modules.kanban.mcp:kanban_claim_task"},
    {"name": "kanban_start_task", "description": "Start working on a task (auto-claims if unassigned)", "handler": "modules.kanban.mcp:kanban_start_task"},
    {"name": "kanban_complete_task", "description": "Complete a task and auto-start dependents", "handler": "modules.kanban.mcp:kanban_complete_task"},
    {"name": "kanban_create_task", "description": "Create a new task in a board", "handler": "modules.kanban.mcp:kanban_create_task"},
    {"name": "kanban_update_task", "description": "Update task fields", "handler": "modules.kanban.mcp:kanban_update_task"},
    {"name": "kanban_add_comment", "description": "Add a comment to a task", "handler": "modules.kanban.mcp:kanban_add_comment"},
    {"name": "kanban_get_task", "description": "Get full task details with subtasks and comments", "handler": "modules.kanban.mcp:kanban_get_task"},
    {"name": "kanban_help_wanted", "description": "Flag a task as needing human help", "handler": "modules.kanban.mcp:kanban_help_wanted"},
    {"name": "kanban_my_instructions", "description": "Get the calling agent's instructions", "handler": "modules.kanban.mcp:kanban_my_instructions"},
]

def get_router():
    from .routes import router
    return router
```

- [ ] **Step 2: Write `modules/kanban/models.py`**

```python
"""Pydantic models for the Kanban module."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


# ── Users ──────────────────────────────────────────────────

class UserProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    type: str = 'agent'
    status: str = 'active'
    instructions: Optional[str] = None
    last_active_at: Optional[datetime] = None
    api_key_count: int = 0
    open_tasks: int = 0
    completed_tasks: int = 0
    created_at: Optional[datetime] = None


class UserCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    type: str = Field(default='agent', pattern=r'^(human|agent)$')
    instructions: Optional[str] = None


class UserUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    instructions: Optional[str] = None


class UserWithKey(UserProfile):
    api_key: str  # shown ONCE on create
    api_key_id: str


class UserDetail(UserProfile):
    api_key_masked: Optional[str] = None
    api_key_id: Optional[str] = None


# ── Boards ─────────────────────────────────────────────────

class KanbanBoardCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    type: str = Field(default='agentic', pattern=r'^(agentic|personal)$')
    instructions: Optional[str] = None


class KanbanBoardUpdate(BaseModel):
    name: Optional[str] = None
    instructions: Optional[str] = None


class KanbanBoard(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    type: str
    instructions: Optional[str] = None
    owner_id: Optional[str] = None
    column_count: int = 0
    task_count: int = 0
    created_at: Optional[datetime] = None


# ── Columns ────────────────────────────────────────────────

class KanbanColumnCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    status: str = Field(..., min_length=1, max_length=50)
    position: int = 0
    wip_limit: Optional[int] = None


class KanbanColumnUpdate(BaseModel):
    name: Optional[str] = None
    position: Optional[int] = None
    wip_limit: Optional[int] = None


class KanbanColumn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    board_id: str
    name: str
    status: str
    position: int = 0
    wip_limit: Optional[int] = None
    task_count: int = 0


# ── Tasks ──────────────────────────────────────────────────

class KanbanTaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    priority: str = Field(default='medium', pattern=r'^(low|medium|high|critical)$')
    column_id: Optional[str] = None  # defaults to first Backlog/Inbox column
    assignee_id: Optional[str] = None
    due_at: Optional[datetime] = None
    estimate: Optional[str] = None


class KanbanTaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    due_at: Optional[datetime] = None
    assignee_id: Optional[str] = None
    estimate: Optional[str] = None
    help_wanted: Optional[bool] = None
    help_wanted_message: Optional[str] = None


class KanbanTaskMove(BaseModel):
    column_id: str
    position: int = 0


class KanbanTaskClaim(BaseModel):
    pass  # assignee comes from auth user


class KanbanTaskComplete(BaseModel):
    summary: Optional[str] = None


class KanbanTask(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    board_id: str
    column_id: str
    task_number: int
    title: str
    description: Optional[str] = None
    priority: str = 'medium'
    due_at: Optional[datetime] = None
    assignee_id: Optional[str] = None
    assignee_name: Optional[str] = None
    position: int = 0
    help_wanted: bool = False
    help_wanted_message: Optional[str] = None
    estimate: Optional[str] = None
    completed_at: Optional[datetime] = None
    subtask_count: int = 0
    subtask_done: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class KanbanTaskDetail(KanbanTask):
    subtasks: list['KanbanSubtask'] = []
    comments: list['KanbanComment'] = []
    dependencies: list['KanbanTaskDependency'] = []


# ── Subtasks ───────────────────────────────────────────────

class KanbanSubtaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)


class KanbanSubtaskUpdate(BaseModel):
    title: Optional[str] = None
    completed: Optional[bool] = None


class KanbanSubtask(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    title: str
    completed: bool = False
    position: int = 0
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


# ── Dependencies ───────────────────────────────────────────

class KanbanTaskDependencyCreate(BaseModel):
    depends_on_id: str


class KanbanTaskDependency(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: str
    depends_on_id: str
    depends_on_title: Optional[str] = None
    depends_on_completed: bool = False


# ── Comments ───────────────────────────────────────────────

class KanbanCommentCreate(BaseModel):
    body: str = Field(..., min_length=1)


class KanbanComment(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    body: str
    created_at: Optional[datetime] = None


# ── Agent Connect ──────────────────────────────────────────

class AgentConnect(BaseModel):
    user: UserProfile
    api_key_masked: str
    active_boards: list[KanbanBoard]
    my_open_tasks: list[KanbanTask]
    endpoints: dict


# ── Agent Log ──────────────────────────────────────────────

class KanbanAgentLog(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    task_id: Optional[str] = None
    board_id: Optional[str] = None
    action: str
    details: Optional[str] = None
    tool: Optional[str] = None
    created_at: Optional[datetime] = None
```

- [ ] **Step 3: Verify module loads**

```bash
docker exec lamadb_api python3 -c "from modules.kanban import MODULE_NAME, MODULE_MCP_TOOLS; print(MODULE_NAME, len(MODULE_MCP_TOOLS), 'tools')"
```

Expected: `kanban 11 tools`

- [ ] **Step 4: Commit**

```bash
git add modules/kanban/__init__.py modules/kanban/models.py
git commit -m "feat(kanban): add module metadata, Pydantic models, MCP tool declarations"
```

---

## Task 3: Users Backend (`app/core/users.py`)

**Files:**
- Create: `app/core/users.py`
- Modify: `app/main.py` (register users router)

- [ ] **Step 1: Write `app/core/users.py`**

```python
"""User management endpoints — identity profiles for agents and humans."""
import asyncio
import secrets
from typing import Annotated
from datetime import datetime, timezone

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import AuthUser, get_current_user, require_admin
from app.db import get_pool
from app.config import settings

router = APIRouter(tags=["users"])

USER_KEY_PREFIX = "lamadb_user_"


def _generate_api_key() -> str:
    """Generate a human-readable API key."""
    return USER_KEY_PREFIX + secrets.token_urlsafe(24)


async def _hash_key(raw_key: str) -> str:
    """Hash an API key with the configured salt."""
    salt = settings.api_key_salt.encode()
    return await asyncio.to_thread(
        lambda: bcrypt.hashpw((salt + raw_key).encode(), bcrypt.gensalt()).decode()
    )


@router.get("/users")
async def list_users(
    user: Annotated[AuthUser, Depends(require_admin)],
    status: str | None = Query(default=None, pattern=r'^(active|inactive|suspended)$'),
):
    """List all users with task stats."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT u.*,
                   (SELECT count(*) FROM api_keys WHERE user_id = u.id AND active = true) AS api_key_count,
                   (SELECT count(*) FROM kanban_tasks WHERE assignee_id = u.id AND completed_at IS NULL) AS open_tasks,
                   (SELECT count(*) FROM kanban_tasks WHERE assignee_id = u.id AND completed_at IS NOT NULL) AS completed_tasks
            FROM users u
            WHERE ($1::text IS NULL OR u.status = $1)
            ORDER BY u.name
        """, status)
    return [
        {
            "id": str(r["id"]), "name": r["name"], "type": r["type"],
            "status": r["status"], "instructions": r["instructions"],
            "last_active_at": r["last_active_at"],
            "api_key_count": r["api_key_count"], "open_tasks": r["open_tasks"],
            "completed_tasks": r["completed_tasks"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: dict,
    user: Annotated[AuthUser, Depends(require_admin)],
):
    """Create a user profile and auto-generate an API key."""
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")

    pool = get_pool()
    raw_key = _generate_api_key()
    key_hash = await _hash_key(raw_key)

    async with pool.acquire() as conn:
        existing = await conn.fetchval("SELECT id FROM users WHERE name = $1", name)
        if existing:
            raise HTTPException(status_code=409, detail=f"User '{name}' already exists")

        user_id = await conn.fetchval(
            """INSERT INTO users (name, type, status, instructions)
               VALUES ($1, $2, 'active', $3) RETURNING id""",
            name,
            body.get("type", "agent"),
            body.get("instructions"),
        )

        # Determine role: agents get 'agent' role, humans get 'admin'
        role = "admin" if body.get("type") == "human" else "agent"
        scopes = ["kanban", "documents", "events"] if role == "agent" else []

        key_id = await conn.fetchval(
            """INSERT INTO api_keys (name, key_hash, role, scopes, active, user_id)
               VALUES ($1, $2, $3, $4, true, $5) RETURNING id""",
            name, key_hash, role, scopes, user_id,
        )

    return {
        "user": {"id": str(user_id), "name": name, "type": body.get("type", "agent"), "status": "active"},
        "api_key": raw_key,
        "api_key_id": str(key_id),
    }


@router.get("/users/{user_id}")
async def get_user(
    user_id: str,
    user: Annotated[AuthUser, Depends(get_current_user)],
):
    """Get a user profile with masked API key."""
    if user.role != "admin" and str(user.key_id) != user_id and user.user_id != user_id:
        raise HTTPException(status_code=403, detail="Can only view your own profile")

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT u.*,
                   (SELECT key_hash FROM api_keys WHERE user_id = u.id AND active = true LIMIT 1) AS active_key_hash,
                   (SELECT id FROM api_keys WHERE user_id = u.id AND active = true LIMIT 1) AS active_key_id,
                   (SELECT count(*) FROM kanban_tasks WHERE assignee_id = u.id AND completed_at IS NULL) AS open_tasks,
                   (SELECT count(*) FROM kanban_tasks WHERE assignee_id = u.id AND completed_at IS NOT NULL) AS completed_tasks
            FROM users u WHERE u.id = $1""",
            user_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    # Mask the key for display
    key_masked = None
    if row["active_key_hash"]:
        key_masked = USER_KEY_PREFIX + "****"

    return {
        "id": str(row["id"]), "name": row["name"], "type": row["type"],
        "status": row["status"], "instructions": row["instructions"],
        "last_active_at": row["last_active_at"],
        "api_key_masked": key_masked, "api_key_id": str(row["active_key_id"]) if row["active_key_id"] else None,
        "open_tasks": row["open_tasks"], "completed_tasks": row["completed_tasks"],
        "created_at": row["created_at"],
    }


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    body: dict,
    user: Annotated[AuthUser, Depends(require_admin)],
):
    """Update a user profile."""
    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        if not existing:
            raise HTTPException(status_code=404, detail="User not found")

        updates = []
        params = []
        idx = 1

        for field in ["name", "type", "status", "instructions"]:
            if field in body:
                updates.append(f"{field} = ${idx}")
                params.append(body[field])
                idx += 1

        if updates:
            updates.append(f"updated_at = now()")
            params.append(user_id)
            await conn.execute(
                f"UPDATE users SET {', '.join(updates)} WHERE id = ${idx}",
                *params,
            )

    return {"status": "ok"}


@router.post("/users/{user_id}/rotate-key")
async def rotate_user_key(
    user_id: str,
    user: Annotated[AuthUser, Depends(require_admin)],
):
    """Rotate a user's API key. Returns the new key ONCE."""
    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        if not existing:
            raise HTTPException(status_code=404, detail="User not found")

        raw_key = _generate_api_key()
        key_hash = await _hash_key(raw_key)

        # Deactivate old active keys
        await conn.execute(
            "UPDATE api_keys SET active = false WHERE user_id = $1 AND active = true",
            user_id,
        )

        # Create new key
        key_id = await conn.fetchval(
            """INSERT INTO api_keys (name, key_hash, role, scopes, active, user_id)
               VALUES ($1, $2, $3, $4, true, $5) RETURNING id""",
            existing["name"],
            key_hash,
            "admin" if existing["type"] == "human" else "agent",
            ["kanban", "documents", "events"] if existing["type"] == "agent" else [],
            user_id,
        )

    return {"api_key": raw_key, "api_key_id": str(key_id)}


@router.delete("/users/{user_id}")
async def deactivate_user(
    user_id: str,
    user: Annotated[AuthUser, Depends(require_admin)],
):
    """Deactivate a user (soft-delete)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET status = 'inactive', updated_at = now() WHERE id = $1",
            user_id,
        )
        await conn.execute(
            "UPDATE api_keys SET active = false WHERE user_id = $1",
            user_id,
        )
    return {"status": "deactivated"}
```

- [ ] **Step 2: Register users router in `app/main.py`**

Add to the module discovery section (after existing dashboard router registration):

```python
from app.core.users import router as users_router
app.include_router(users_router, prefix="/api")
```

- [ ] **Step 3: Rebuild and verify**

```bash
docker compose build api && docker compose up -d api
```

Test the users endpoint:

```bash
curl -s -H "Authorization: Bearer lamadb_test_key_2026" http://localhost:8000/api/users | python3 -m json.tool
```

Expected: User list with at least the seeded "ali" user.

- [ ] **Step 4: Commit**

```bash
git add app/core/users.py app/main.py
git commit -m "feat(kanban): add user management endpoints"
```

---

## Task 4: Kanban Routes Backend

**Files:**
- Create: `modules/kanban/routes.py`
- Modify: `app/main.py` (module auto-discovery picks up kanban/ automatically)

**Note:** This is the largest task. The route file covers boards, columns, tasks, subtasks, dependencies, comments, and agent connect. I'll provide the full implementation.

- [ ] **Step 1: Write `modules/kanban/routes.py`**

```python
"""Kanban module routes — boards, columns, tasks, subtasks, dependencies, comments."""
import json
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import AuthUser, get_current_user
from app.db import get_pool

from .models import (
    KanbanBoard, KanbanBoardCreate, KanbanBoardUpdate,
    KanbanColumn, KanbanColumnCreate, KanbanColumnUpdate,
    KanbanTask, KanbanTaskCreate, KanbanTaskUpdate, KanbanTaskMove,
    KanbanTaskComplete, KanbanTaskDetail,
    KanbanSubtask, KanbanSubtaskCreate, KanbanSubtaskUpdate,
    KanbanComment, KanbanCommentCreate,
    KanbanTaskDependency, KanbanTaskDependencyCreate,
    AgentConnect,
)

router = APIRouter(tags=["kanban"])


def _require_admin_or_agent(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    if user.role not in ("admin", "agent"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return user


# ── Agent Connect ──────────────────────────────────────────────

@router.get("/me")
async def agent_connect(user: Annotated[AuthUser, Depends(get_current_user)]):
    """Agent first-connect: profile, boards, open tasks, instructions."""
    pool = get_pool()
    async with pool.acquire() as conn:
        # User profile
        urow = await conn.fetchrow(
            "SELECT * FROM users WHERE id = $1", user.user_id
        ) if user.user_id else None

        if not urow:
            return {
                "user": {"name": user.name, "type": "human", "instructions": None},
                "api_key_masked": "****",
                "active_boards": [],
                "my_open_tasks": [],
                "endpoints": {"mcp": "/mcp", "api": "/api/kanban"},
            }

        # Active boards
        boards = await conn.fetch("""
            SELECT b.*, (SELECT count(*) FROM kanban_tasks t WHERE t.board_id = b.id AND t.completed_at IS NULL) AS task_count,
                   (SELECT count(*) FROM kanban_columns c WHERE c.board_id = b.id) AS column_count
            FROM kanban_boards b ORDER BY b.name
        """)

        # Agent's open tasks
        agent_tasks = []
        if urow["type"] == "agent":
            trows = await conn.fetch("""
                SELECT t.*, c.name AS column_name, c.status AS column_status
                FROM kanban_tasks t
                JOIN kanban_columns c ON c.id = t.column_id
                WHERE t.assignee_id = $1 AND t.completed_at IS NULL
                ORDER BY t.priority DESC, t.created_at DESC
            """, user.user_id)
            agent_tasks = [
                {
                    "id": str(t["id"]), "board_id": str(t["board_id"]),
                    "column_id": str(t["column_id"]), "task_number": t["task_number"],
                    "title": t["title"], "priority": t["priority"],
                    "column": t["column_name"],
                }
                for t in trows
            ]

    return {
        "user": {
            "id": str(urow["id"]), "name": urow["name"], "type": urow["type"],
            "instructions": urow["instructions"],
        },
        "api_key_masked": "lamadb_user_****",
        "active_boards": [
            {"id": str(b["id"]), "name": b["name"], "type": b["type"],
             "task_count": b["task_count"], "column_count": b["column_count"]}
            for b in boards
        ],
        "my_open_tasks": agent_tasks,
        "endpoints": {"mcp": "/mcp", "api": "/api/kanban"},
    }


# ── Boards ────────────────────────────────────────────────────

DEFAULT_COLUMNS_AGENTIC = [
    ("Backlog", "backlog", 0),
    ("In Progress", "in_progress", 1),
    ("Review", "review", 2),
    ("Done", "done", 3),
]

DEFAULT_COLUMNS_PERSONAL = [
    ("Inbox", "backlog", 0),
    ("In Progress", "in_progress", 1),
    ("Review", "review", 2),
    ("Done", "done", 3),
]


@router.get("/boards")
async def list_boards(user: Annotated[AuthUser, Depends(get_current_user)]):
    """List all kanban boards with column and task counts."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT b.*,
                   (SELECT count(*) FROM kanban_columns c WHERE c.board_id = b.id) AS column_count,
                   (SELECT count(*) FROM kanban_tasks t WHERE t.board_id = b.id) AS task_count
            FROM kanban_boards b ORDER BY b.name
        """)
    return [
        {
            "id": str(r["id"]), "name": r["name"], "type": r["type"],
            "instructions": r["instructions"], "owner_id": str(r["owner_id"]) if r["owner_id"] else None,
            "column_count": r["column_count"], "task_count": r["task_count"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


@router.post("/boards", status_code=status.HTTP_201_CREATED)
async def create_board(
    body: KanbanBoardCreate,
    user: Annotated[AuthUser, Depends(_require_admin_or_agent)],
):
    """Create a board with default columns."""
    pool = get_pool()
    cols = DEFAULT_COLUMNS_AGENTIC if body.type == "agentic" else DEFAULT_COLUMNS_PERSONAL

    async with pool.acquire() as conn:
        board_id = await conn.fetchval(
            "INSERT INTO kanban_boards (name, type, instructions, owner_id) VALUES ($1, $2, $3, $4) RETURNING id",
            body.name, body.type, body.instructions, user.user_id,
        )
        for idx, (col_name, col_status, col_pos) in enumerate(cols):
            await conn.execute(
                "INSERT INTO kanban_columns (board_id, name, status, position) VALUES ($1, $2, $3, $4)",
                board_id, col_name, col_status, col_pos,
            )

    return {"id": str(board_id), "name": body.name, "type": body.type, "columns": len(cols)}


@router.get("/boards/{board_id}")
async def get_board(board_id: str, user: Annotated[AuthUser, Depends(get_current_user)]):
    """Get a board with its columns and task counts per column."""
    pool = get_pool()
    async with pool.acquire() as conn:
        board = await conn.fetchrow("SELECT * FROM kanban_boards WHERE id = $1", board_id)
        if not board:
            raise HTTPException(status_code=404, detail="Board not found")

        columns = await conn.fetch("""
            SELECT c.*,
                   (SELECT count(*) FROM kanban_tasks t WHERE t.column_id = c.id AND t.completed_at IS NULL) AS task_count
            FROM kanban_columns c WHERE c.board_id = $1 ORDER BY c.position
        """, board_id)

    return {
        "id": str(board["id"]), "name": board["name"], "type": board["type"],
        "instructions": board["instructions"],
        "columns": [
            {"id": str(c["id"]), "board_id": str(c["board_id"]), "name": c["name"],
             "status": c["status"], "position": c["position"], "wip_limit": c["wip_limit"],
             "task_count": c["task_count"]}
            for c in columns
        ],
    }


@router.patch("/boards/{board_id}")
async def update_board(
    board_id: str, body: KanbanBoardUpdate,
    user: Annotated[AuthUser, Depends(_require_admin_or_agent)],
):
    """Update a board's name or instructions."""
    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchval("SELECT id FROM kanban_boards WHERE id = $1", board_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Board not found")

        updates = []
        params = []
        idx = 1
        if body.name is not None:
            updates.append(f"name = ${idx}"); params.append(body.name); idx += 1
        if body.instructions is not None:
            updates.append(f"instructions = ${idx}"); params.append(body.instructions); idx += 1
        if updates:
            updates.append("updated_at = now()")
            params.append(board_id)
            await conn.execute(f"UPDATE kanban_boards SET {', '.join(updates)} WHERE id = ${idx}", *params)

    return {"status": "ok"}


@router.delete("/boards/{board_id}")
async def delete_board(
    board_id: str, user: Annotated[AuthUser, Depends(_require_admin_or_agent)],
):
    """Delete a board and all its tasks/columns (CASCADE)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM kanban_boards WHERE id = $1", board_id)
    return {"status": "deleted"}


# ── Columns ───────────────────────────────────────────────────

@router.post("/boards/{board_id}/columns", status_code=status.HTTP_201_CREATED)
async def add_column(
    board_id: str, body: KanbanColumnCreate,
    user: Annotated[AuthUser, Depends(_require_admin_or_agent)],
):
    """Add a column to a board."""
    pool = get_pool()
    async with pool.acquire() as conn:
        col_id = await conn.fetchval(
            "INSERT INTO kanban_columns (board_id, name, status, position, wip_limit) VALUES ($1, $2, $3, $4, $5) RETURNING id",
            board_id, body.name, body.status, body.position, body.wip_limit,
        )
    return {"id": str(col_id), "board_id": board_id, "name": body.name, "status": body.status}


@router.patch("/columns/{column_id}")
async def update_column(
    column_id: str, body: KanbanColumnUpdate,
    user: Annotated[AuthUser, Depends(_require_admin_or_agent)],
):
    """Update a column."""
    pool = get_pool()
    async with pool.acquire() as conn:
        updates = []
        params = []
        idx = 1
        for field in ["name", "position", "wip_limit"]:
            val = getattr(body, field, None)
            if val is not None:
                updates.append(f"{field} = ${idx}"); params.append(val); idx += 1
        if updates:
            params.append(column_id)
            await conn.execute(f"UPDATE kanban_columns SET {', '.join(updates)} WHERE id = ${idx}", *params)
    return {"status": "ok"}


@router.delete("/columns/{column_id}")
async def delete_column(
    column_id: str, user: Annotated[AuthUser, Depends(_require_admin_or_agent)],
):
    """Delete a column. Tasks in this column are moved to the board's first column."""
    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT * FROM kanban_columns WHERE id = $1", column_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Column not found")

        # Reassign tasks to first column
        first_col = await conn.fetchval(
            "SELECT id FROM kanban_columns WHERE board_id = $1 ORDER BY position LIMIT 1",
            existing["board_id"],
        )
        if first_col and str(first_col) != column_id:
            await conn.execute(
                "UPDATE kanban_tasks SET column_id = $1 WHERE column_id = $2",
                first_col, column_id,
            )

        await conn.execute("DELETE FROM kanban_columns WHERE id = $1", column_id)
    return {"status": "deleted"}


# ── Tasks ─────────────────────────────────────────────────────

@router.get("/boards/{board_id}/tasks")
async def list_tasks(
    board_id: str, user: Annotated[AuthUser, Depends(get_current_user)],
    column_id: str | None = Query(default=None),
    assignee_id: str | None = Query(default=None),
    priority: str | None = Query(default=None),
):
    """List tasks for a board, optionally filtered."""
    pool = get_pool()
    async with pool.acquire() as conn:
        query = """
            SELECT t.*, u.name AS assignee_name,
                   (SELECT count(*) FROM kanban_subtasks s WHERE s.task_id = t.id) AS subtask_count,
                   (SELECT count(*) FROM kanban_subtasks s WHERE s.task_id = t.id AND s.completed = true) AS subtask_done
            FROM kanban_tasks t
            LEFT JOIN users u ON u.id = t.assignee_id
            WHERE t.board_id = $1
        """
        params = [board_id]
        idx = 2

        if column_id:
            query += f" AND t.column_id = ${idx}"; params.append(column_id); idx += 1
        if assignee_id:
            query += f" AND t.assignee_id = ${idx}"; params.append(assignee_id); idx += 1
        if priority:
            query += f" AND t.priority = ${idx}"; params.append(priority); idx += 1

        query += " ORDER BY t.position, t.created_at DESC"
        rows = await conn.fetch(query, *params)

    return [
        {
            "id": str(r["id"]), "board_id": str(r["board_id"]), "column_id": str(r["column_id"]),
            "task_number": r["task_number"], "title": r["title"], "description": r["description"],
            "priority": r["priority"], "due_at": r["due_at"],
            "assignee_id": str(r["assignee_id"]) if r["assignee_id"] else None,
            "assignee_name": r["assignee_name"],
            "position": r["position"], "help_wanted": r["help_wanted"],
            "help_wanted_message": r["help_wanted_message"], "estimate": r["estimate"],
            "completed_at": r["completed_at"],
            "subtask_count": r["subtask_count"], "subtask_done": r["subtask_done"],
            "created_at": r["created_at"], "updated_at": r["updated_at"],
        }
        for r in rows
    ]


@router.post("/boards/{board_id}/tasks", status_code=status.HTTP_201_CREATED)
async def create_task(
    board_id: str, body: KanbanTaskCreate,
    user: Annotated[AuthUser, Depends(_require_admin_or_agent)],
):
    """Create a task with auto-incrementing task_number."""
    pool = get_pool()
    async with pool.acquire() as conn:
        # Get or default column
        col_id = body.column_id
        if not col_id:
            col_id = await conn.fetchval(
                "SELECT id FROM kanban_columns WHERE board_id = $1 ORDER BY position LIMIT 1",
                board_id,
            )
            if not col_id:
                raise HTTPException(status_code=400, detail="Board has no columns")

        # Auto-increment task number
        next_num = await conn.fetchval(
            "SELECT COALESCE(MAX(task_number), 0) + 1 FROM kanban_tasks WHERE board_id = $1",
            board_id,
        )

        # Position: at end of column
        max_pos = await conn.fetchval(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM kanban_tasks WHERE column_id = $1",
            col_id,
        )

        task_id = await conn.fetchval("""
            INSERT INTO kanban_tasks (board_id, column_id, task_number, title, description,
                                      priority, assignee_id, position, due_at, estimate)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) RETURNING id
        """, board_id, col_id, next_num, body.title, body.description,
            body.priority, body.assignee_id, max_pos, body.due_at, body.estimate)

    return {"id": str(task_id), "task_number": next_num, "title": body.title}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, user: Annotated[AuthUser, Depends(get_current_user)]):
    """Get full task detail with subtasks, comments, dependencies."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT t.*, u.name AS assignee_name,
                   (SELECT count(*) FROM kanban_subtasks s WHERE s.task_id = t.id) AS subtask_count,
                   (SELECT count(*) FROM kanban_subtasks s WHERE s.task_id = t.id AND s.completed = true) AS subtask_done
            FROM kanban_tasks t
            LEFT JOIN users u ON u.id = t.assignee_id
            WHERE t.id = $1
        """, task_id)

        if not row:
            raise HTTPException(status_code=404, detail="Task not found")

        subtasks = await conn.fetch(
            "SELECT * FROM kanban_subtasks WHERE task_id = $1 ORDER BY position", task_id,
        )
        comments = await conn.fetch(
            """SELECT c.*, u.name AS user_name
               FROM kanban_comments c LEFT JOIN users u ON u.id = c.user_id
               WHERE c.task_id = $1 ORDER BY c.created_at""", task_id,
        )
        deps = await conn.fetch("""
            SELECT d.*, dt.title AS depends_on_title,
                   dt.completed_at IS NOT NULL AS depends_on_completed
            FROM kanban_task_dependencies d
            JOIN kanban_tasks dt ON dt.id = d.depends_on_id
            WHERE d.task_id = $1
        """, task_id)

    return {
        "id": str(row["id"]), "board_id": str(row["board_id"]), "column_id": str(row["column_id"]),
        "task_number": row["task_number"], "title": row["title"], "description": row["description"],
        "priority": row["priority"], "due_at": row["due_at"],
        "assignee_id": str(row["assignee_id"]) if row["assignee_id"] else None,
        "assignee_name": row["assignee_name"],
        "position": row["position"], "help_wanted": row["help_wanted"],
        "help_wanted_message": row["help_wanted_message"], "estimate": row["estimate"],
        "completed_at": row["completed_at"],
        "subtask_count": row["subtask_count"], "subtask_done": row["subtask_done"],
        "created_at": row["created_at"], "updated_at": row["updated_at"],
        "subtasks": [
            {"id": str(s["id"]), "task_id": str(s["task_id"]), "title": s["title"],
             "completed": s["completed"], "position": s["position"],
             "completed_at": s["completed_at"], "created_at": s["created_at"]}
            for s in subtasks
        ],
        "comments": [
            {"id": str(c["id"]), "task_id": str(c["task_id"]),
             "user_id": str(c["user_id"]) if c["user_id"] else None,
             "user_name": c["user_name"], "body": c["body"], "created_at": c["created_at"]}
            for c in comments
        ],
        "dependencies": [
            {"task_id": str(d["task_id"]), "depends_on_id": str(d["depends_on_id"]),
             "depends_on_title": d["depends_on_title"],
             "depends_on_completed": d["depends_on_completed"]}
            for d in deps
        ],
    }


@router.patch("/tasks/{task_id}")
async def update_task(
    task_id: str, body: KanbanTaskUpdate,
    user: Annotated[AuthUser, Depends(_require_admin_or_agent)],
):
    """Update task fields."""
    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchval("SELECT id FROM kanban_tasks WHERE id = $1", task_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Task not found")

        updates = []
        params = []
        idx = 1
        for field in ["title", "description", "priority", "due_at", "assignee_id",
                       "estimate", "help_wanted", "help_wanted_message"]:
            val = getattr(body, field, None)
            if val is not None:
                updates.append(f"{field} = ${idx}"); params.append(val); idx += 1

        if updates:
            updates.append("updated_at = now()")
            params.append(task_id)
            await conn.execute(f"UPDATE kanban_tasks SET {', '.join(updates)} WHERE id = ${idx}", *params)

    return {"status": "ok"}


@router.patch("/tasks/{task_id}/move")
async def move_task(
    task_id: str, body: KanbanTaskMove,
    user: Annotated[AuthUser, Depends(_require_admin_or_agent)],
):
    """Move a task to a different column."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE kanban_tasks SET column_id = $1, position = $2, updated_at = now() WHERE id = $3",
            body.column_id, body.position, task_id,
        )
    return {"status": "moved"}


@router.post("/tasks/{task_id}/claim")
async def claim_task(
    task_id: str, user: Annotated[AuthUser, Depends(_require_admin_or_agent)],
):
    """Claim a task (agent assigns it to themselves)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        task = await conn.fetchrow("SELECT * FROM kanban_tasks WHERE id = $1", task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        # Move to first In Progress column
        in_progress_col = await conn.fetchval(
            "SELECT id FROM kanban_columns WHERE board_id = $1 AND status = 'in_progress' ORDER BY position LIMIT 1",
            task["board_id"],
        )

        await conn.execute(
            "UPDATE kanban_tasks SET assignee_id = $1, column_id = COALESCE($2, column_id), updated_at = now() WHERE id = $3",
            user.user_id, in_progress_col, task_id,
        )

        # Log the claim
        await conn.execute(
            "INSERT INTO kanban_agent_logs (user_id, task_id, board_id, action) VALUES ($1, $2, $3, 'task_claimed')",
            user.user_id, task_id, task["board_id"],
        )

    return {"status": "claimed"}


@router.post("/tasks/{task_id}/complete")
async def complete_task(
    task_id: str, body: KanbanTaskComplete,
    user: Annotated[AuthUser, Depends(_require_admin_or_agent)],
):
    """Complete a task. Auto-starts dependent tasks whose dependencies are now all met."""
    pool = get_pool()
    async with pool.acquire() as conn:
        task = await conn.fetchrow("SELECT * FROM kanban_tasks WHERE id = $1", task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        # Mark completed
        now = datetime.now(timezone.utc)
        await conn.execute(
            "UPDATE kanban_tasks SET completed_at = $1, updated_at = now() WHERE id = $2",
            now, task_id,
        )

        # Auto-start dependents: find tasks that depend on this one,
        # check if ALL their dependencies are now completed, and move to In Progress
        dependents = await conn.fetch("""
            SELECT d.task_id FROM kanban_task_dependencies d
            WHERE d.depends_on_id = $1
        """, task_id)

        in_progress_col = await conn.fetchval(
            "SELECT id FROM kanban_columns WHERE board_id = $1 AND status = 'in_progress' ORDER BY position LIMIT 1",
            task["board_id"],
        )

        for dep in dependents:
            # Check if all deps for this dependent are completed
            incomplete = await conn.fetchval("""
                SELECT count(*) FROM kanban_task_dependencies d
                JOIN kanban_tasks t ON t.id = d.depends_on_id
                WHERE d.task_id = $1 AND t.completed_at IS NULL
            """, dep["task_id"])

            if incomplete == 0 and in_progress_col:
                await conn.execute(
                    "UPDATE kanban_tasks SET column_id = $1, updated_at = now() WHERE id = $2",
                    in_progress_col, dep["task_id"],
                )

        # Log
        await conn.execute(
            "INSERT INTO kanban_agent_logs (user_id, task_id, board_id, action, details) VALUES ($1, $2, $3, 'task_completed', $4)",
            user.user_id, task_id, task["board_id"], body.summary,
        )

    return {"status": "completed"}


# ── Subtasks ──────────────────────────────────────────────────

@router.post("/tasks/{task_id}/subtasks", status_code=status.HTTP_201_CREATED)
async def add_subtask(
    task_id: str, body: KanbanSubtaskCreate,
    user: Annotated[AuthUser, Depends(_require_admin_or_agent)],
):
    """Add a subtask to a task."""
    pool = get_pool()
    max_pos = await pool.acquire().then(lambda conn: conn.fetchval(
        "SELECT COALESCE(MAX(position), -1) + 1 FROM kanban_subtasks WHERE task_id = $1",
        task_id,
    ))
    async with pool.acquire() as conn:
        sub_id = await conn.fetchval(
            "INSERT INTO kanban_subtasks (task_id, title, position) VALUES ($1, $2, $3) RETURNING id",
            task_id, body.title, max_pos,
        )
    return {"id": str(sub_id), "task_id": task_id, "title": body.title}


@router.patch("/subtasks/{subtask_id}")
async def update_subtask(
    subtask_id: str, body: KanbanSubtaskUpdate,
    user: Annotated[AuthUser, Depends(_require_admin_or_agent)],
):
    """Update or toggle a subtask."""
    pool = get_pool()
    async with pool.acquire() as conn:
        if body.completed is not None:
            await conn.execute(
                "UPDATE kanban_subtasks SET completed = $1, completed_at = CASE WHEN $1 THEN now() ELSE NULL END WHERE id = $2",
                body.completed, subtask_id,
            )
        if body.title is not None:
            await conn.execute(
                "UPDATE kanban_subtasks SET title = $1 WHERE id = $2",
                body.title, subtask_id,
            )
    return {"status": "ok"}


# ── Dependencies ──────────────────────────────────────────────

@router.post("/tasks/{task_id}/dependencies", status_code=status.HTTP_201_CREATED)
async def add_dependency(
    task_id: str, body: KanbanTaskDependencyCreate,
    user: Annotated[AuthUser, Depends(_require_admin_or_agent)],
):
    """Add a task dependency."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO kanban_task_dependencies (task_id, depends_on_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            task_id, body.depends_on_id,
        )
    return {"status": "linked"}


@router.delete("/tasks/{task_id}/dependencies/{depends_on_id}")
async def remove_dependency(
    task_id: str, depends_on_id: str,
    user: Annotated[AuthUser, Depends(_require_admin_or_agent)],
):
    """Remove a task dependency."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM kanban_task_dependencies WHERE task_id = $1 AND depends_on_id = $2",
            task_id, depends_on_id,
        )
    return {"status": "unlinked"}


# ── Comments ──────────────────────────────────────────────────

@router.get("/tasks/{task_id}/comments")
async def list_comments(task_id: str, user: Annotated[AuthUser, Depends(get_current_user)]):
    """List comments on a task."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT c.*, u.name AS user_name
            FROM kanban_comments c LEFT JOIN users u ON u.id = c.user_id
            WHERE c.task_id = $1 ORDER BY c.created_at
        """, task_id)
    return [
        {"id": str(r["id"]), "task_id": str(r["task_id"]),
         "user_id": str(r["user_id"]) if r["user_id"] else None,
         "user_name": r["user_name"], "body": r["body"], "created_at": r["created_at"]}
        for r in rows
    ]


@router.post("/tasks/{task_id}/comments", status_code=status.HTTP_201_CREATED)
async def add_comment(
    task_id: str, body: KanbanCommentCreate,
    user: Annotated[AuthUser, Depends(get_current_user)],
):
    """Add a comment to a task."""
    pool = get_pool()
    async with pool.acquire() as conn:
        comment_id = await conn.fetchval(
            "INSERT INTO kanban_comments (task_id, user_id, body) VALUES ($1, $2, $3) RETURNING id",
            task_id, user.user_id, body.body,
        )
    return {"id": str(comment_id), "task_id": task_id, "body": body.body}
```

- [ ] **Step 2: Rebuild and verify endpoints**

```bash
docker compose build api && docker compose up -d api
```

Verify:

```bash
# Create a board
curl -s -X POST -H "Authorization: Bearer lamadb_test_key_2026" \
  -H "Content-Type: application/json" \
  -d '{"name":"Test Board","type":"agentic"}' \
  http://localhost:8000/api/kanban/boards | python3 -m json.tool

# List boards
curl -s -H "Authorization: Bearer lamadb_test_key_2026" \
  http://localhost:8000/api/kanban/boards | python3 -c "import sys,json; print(len(json.load(sys.stdin)), 'boards')"

# Create a task (replace BOARD_ID from above)
curl -s -X POST -H "Authorization: Bearer lamadb_test_key_2026" \
  -H "Content-Type: application/json" \
  -d '{"title":"Test task"}' \
  http://localhost:8000/api/kanban/boards/BOARD_ID/tasks | python3 -m json.tool
```

Expected: Board created with 4 columns, task created with task_number=1.

- [ ] **Step 3: Commit**

```bash
git add modules/kanban/routes.py
git commit -m "feat(kanban): add board, column, task, subtask, dependency, comment routes"
```

---

## Task 5: MCP Tools

**Files:**
- Create: `modules/kanban/mcp.py`

- [ ] **Step 1: Write `modules/kanban/mcp.py`**

```python
"""MCP tools for the Kanban module — agent-first task orchestration."""
import json
from app.db import get_pool


async def _log_action(user_id: str, task_id: str | None, board_id: str | None,
                      action: str, details: str | None = None, tool: str | None = None):
    """Log an agent action to kanban_agent_logs."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO kanban_agent_logs (user_id, task_id, board_id, action, details, tool)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            user_id, task_id, board_id, action, details, tool,
        )


async def kanban_my_tasks(user_id: str, board_id: str | None = None) -> dict:
    """Get open tasks assigned to the calling agent."""
    pool = get_pool()
    async with pool.acquire() as conn:
        query = """
            SELECT t.*, b.name AS board_name, c.name AS column_name
            FROM kanban_tasks t
            JOIN kanban_boards b ON b.id = t.board_id
            JOIN kanban_columns c ON c.id = t.column_id
            WHERE t.assignee_id = $1 AND t.completed_at IS NULL
        """
        params = [user_id]
        if board_id:
            query += " AND t.board_id = $2"
            params.append(board_id)
        query += " ORDER BY t.priority DESC, t.created_at DESC"

        rows = await conn.fetch(query, *params)
    return {
        "tasks": [
            {"id": str(r["id"]), "board": r["board_name"], "column": r["column_name"],
             "task_number": r["task_number"], "title": r["title"], "priority": r["priority"]}
            for r in rows
        ],
        "count": len(rows),
    }


async def kanban_find_work(user_id: str, board_id: str | None = None) -> dict:
    """Find unassigned tasks in Backlog/Inbox columns."""
    pool = get_pool()
    async with pool.acquire() as conn:
        query = """
            SELECT t.*, b.name AS board_name, b.type AS board_type
            FROM kanban_tasks t
            JOIN kanban_columns c ON c.id = t.column_id
            JOIN kanban_boards b ON b.id = t.board_id
            WHERE t.assignee_id IS NULL AND t.completed_at IS NULL
              AND c.status = 'backlog'
        """
        params = []
        if board_id:
            query += " AND t.board_id = $1"
            params.append(board_id)
        query += " ORDER BY t.priority DESC, t.created_at DESC LIMIT 20"

        rows = await conn.fetch(query, *params)
    return {
        "tasks": [
            {"id": str(r["id"]), "board": r["board_name"], "board_type": r["board_type"],
             "task_number": r["task_number"], "title": r["title"], "priority": r["priority"],
             "description": r["description"]}
            for r in rows
        ],
        "count": len(rows),
    }


async def kanban_claim_task(user_id: str, task_id: str) -> dict:
    """Claim a task and move it to In Progress."""
    pool = get_pool()
    async with pool.acquire() as conn:
        task = await conn.fetchrow("SELECT * FROM kanban_tasks WHERE id = $1", task_id)
        if not task:
            return {"error": "Task not found"}

        in_progress = await conn.fetchval(
            "SELECT id FROM kanban_columns WHERE board_id = $1 AND status = 'in_progress' ORDER BY position LIMIT 1",
            task["board_id"],
        )

        await conn.execute(
            "UPDATE kanban_tasks SET assignee_id = $1, column_id = COALESCE($2, column_id), updated_at = now() WHERE id = $3",
            user_id, in_progress, task_id,
        )
        await _log_action(user_id, task_id, task["board_id"], "task_claimed", tool="kanban_claim_task")

    return {"status": "claimed", "task_id": task_id}


async def kanban_start_task(user_id: str, task_id: str) -> dict:
    """Start a task (auto-claims if unassigned)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        task = await conn.fetchrow("SELECT * FROM kanban_tasks WHERE id = $1", task_id)
        if not task:
            return {"error": "Task not found"}

        in_progress = await conn.fetchval(
            "SELECT id FROM kanban_columns WHERE board_id = $1 AND status = 'in_progress' ORDER BY position LIMIT 1",
            task["board_id"],
        )

        await conn.execute(
            "UPDATE kanban_tasks SET assignee_id = COALESCE(assignee_id, $1), column_id = COALESCE($2, column_id), updated_at = now() WHERE id = $3",
            user_id, in_progress, task_id,
        )
        await _log_action(user_id, task_id, task["board_id"], "task_started", tool="kanban_start_task")

    return {"status": "started", "task_id": task_id}


async def kanban_complete_task(user_id: str, task_id: str, summary: str | None = None) -> dict:
    """Complete a task. Auto-starts dependents whose deps are now met."""
    from datetime import datetime, timezone
    pool = get_pool()
    async with pool.acquire() as conn:
        task = await conn.fetchrow("SELECT * FROM kanban_tasks WHERE id = $1", task_id)
        if not task:
            return {"error": "Task not found"}

        now = datetime.now(timezone.utc)
        await conn.execute(
            "UPDATE kanban_tasks SET completed_at = $1, updated_at = now() WHERE id = $2",
            now, task_id,
        )

        # Auto-start dependents
        dependents = await conn.fetch(
            "SELECT d.task_id, t.board_id FROM kanban_task_dependencies d JOIN kanban_tasks t ON t.id = d.task_id WHERE d.depends_on_id = $1",
            task_id,
        )
        for dep in dependents:
            incomplete = await conn.fetchval(
                """SELECT count(*) FROM kanban_task_dependencies d
                   JOIN kanban_tasks t ON t.id = d.depends_on_id
                   WHERE d.task_id = $1 AND t.completed_at IS NULL""",
                dep["task_id"],
            )
            if incomplete == 0:
                in_progress = await conn.fetchval(
                    "SELECT id FROM kanban_columns WHERE board_id = $1 AND status = 'in_progress' ORDER BY position LIMIT 1",
                    dep["board_id"],
                )
                if in_progress:
                    await conn.execute(
                        "UPDATE kanban_tasks SET column_id = $1, updated_at = now() WHERE id = $2",
                        in_progress, dep["task_id"],
                    )

        await _log_action(user_id, task_id, task["board_id"], "task_completed", summary, "kanban_complete_task")

    return {"status": "completed", "task_id": task_id}


async def kanban_create_task(user_id: str, board_id: str, title: str,
                             description: str | None = None, priority: str = "medium") -> dict:
    """Create a new task in a board's Backlog column."""
    pool = get_pool()
    async with pool.acquire() as conn:
        col_id = await conn.fetchval(
            "SELECT id FROM kanban_columns WHERE board_id = $1 AND status = 'backlog' ORDER BY position LIMIT 1",
            board_id,
        )
        if not col_id:
            # Fallback to first column
            col_id = await conn.fetchval(
                "SELECT id FROM kanban_columns WHERE board_id = $1 ORDER BY position LIMIT 1",
                board_id,
            )

        next_num = await conn.fetchval(
            "SELECT COALESCE(MAX(task_number), 0) + 1 FROM kanban_tasks WHERE board_id = $1",
            board_id,
        )
        task_id = await conn.fetchval(
            """INSERT INTO kanban_tasks (board_id, column_id, task_number, title, description, priority)
               VALUES ($1, $2, $3, $4, $5, $6) RETURNING id""",
            board_id, col_id, next_num, title, description, priority,
        )
        await _log_action(user_id, task_id, board_id, "task_created", tool="kanban_create_task")

    return {"status": "created", "task_id": str(task_id), "task_number": next_num}


async def kanban_update_task(user_id: str, task_id: str, title: str | None = None,
                             description: str | None = None, priority: str | None = None) -> dict:
    """Update task fields."""
    pool = get_pool()
    async with pool.acquire() as conn:
        task = await conn.fetchrow("SELECT * FROM kanban_tasks WHERE id = $1", task_id)
        if not task:
            return {"error": "Task not found"}

        updates = []
        params = []
        idx = 1
        if title is not None:
            updates.append(f"title = ${idx}"); params.append(title); idx += 1
        if description is not None:
            updates.append(f"description = ${idx}"); params.append(description); idx += 1
        if priority is not None:
            updates.append(f"priority = ${idx}"); params.append(priority); idx += 1

        if updates:
            updates.append("updated_at = now()")
            params.append(task_id)
            await conn.execute(f"UPDATE kanban_tasks SET {', '.join(updates)} WHERE id = ${idx}", *params)

    return {"status": "updated", "task_id": task_id}


async def kanban_add_comment(user_id: str, task_id: str, body: str) -> dict:
    """Add a comment to a task."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO kanban_comments (task_id, user_id, body) VALUES ($1, $2, $3)",
            task_id, user_id, body,
        )
    return {"status": "commented", "task_id": task_id}


async def kanban_get_task(user_id: str, task_id: str) -> dict:
    """Get full task details."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT t.*, u.name AS assignee_name, b.name AS board_name, c.name AS column_name
            FROM kanban_tasks t
            LEFT JOIN users u ON u.id = t.assignee_id
            JOIN kanban_boards b ON b.id = t.board_id
            JOIN kanban_columns c ON c.id = t.column_id
            WHERE t.id = $1
        """, task_id)
        if not row:
            return {"error": "Task not found"}

        subtasks = await conn.fetch(
            "SELECT * FROM kanban_subtasks WHERE task_id = $1 ORDER BY position", task_id,
        )
        comments = await conn.fetch(
            "SELECT c.*, u.name AS user_name FROM kanban_comments c LEFT JOIN users u ON u.id = c.user_id WHERE c.task_id = $1 ORDER BY c.created_at", task_id,
        )
        deps = await conn.fetch("""
            SELECT d.*, dt.title AS depends_on_title, dt.completed_at IS NOT NULL AS depends_on_completed
            FROM kanban_task_dependencies d JOIN kanban_tasks dt ON dt.id = d.depends_on_id
            WHERE d.task_id = $1
        """, task_id)

    return {
        "task": {
            "id": str(row["id"]), "board": row["board_name"], "column": row["column_name"],
            "task_number": row["task_number"], "title": row["title"], "description": row["description"],
            "priority": row["priority"], "assignee": row["assignee_name"],
            "help_wanted": row["help_wanted"], "help_wanted_message": row["help_wanted_message"],
            "completed": row["completed_at"] is not None,
            "subtasks": [
                {"title": s["title"], "completed": s["completed"]} for s in subtasks
            ],
            "comments": [
                {"user": c["user_name"] or "unknown", "body": c["body"]} for c in comments
            ],
            "dependencies": [
                {"depends_on": d["depends_on_title"], "completed": d["depends_on_completed"]}
                for d in deps
            ],
        }
    }


async def kanban_help_wanted(user_id: str, task_id: str, message: str) -> dict:
    """Flag a task as needing human help."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE kanban_tasks SET help_wanted = true, help_wanted_message = $1, updated_at = now() WHERE id = $2",
            message, task_id,
        )
        await _log_action(user_id, task_id, None, "help_wanted", message, "kanban_help_wanted")
    return {"status": "flagged", "task_id": task_id, "message": message}


async def kanban_my_instructions(user_id: str) -> dict:
    """Get the calling agent's instructions."""
    pool = get_pool()
    async with pool.acquire() as conn:
        user_row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        if not user_row:
            return {"instructions": None, "board_instructions": []}

        # Active boards with instructions
        boards = await conn.fetch(
            "SELECT name, instructions FROM kanban_boards WHERE instructions IS NOT NULL"
        )

    return {
        "agent": user_row["name"],
        "instructions": user_row["instructions"],
        "board_instructions": [
            {"board": b["name"], "instructions": b["instructions"]} for b in boards
        ],
    }
```

- [ ] **Step 2: Verify MCP tools load**

```bash
docker exec lamadb_api python3 -c "
from modules.kanban.mcp import kanban_my_tasks, kanban_find_work
import asyncio
print('MCP tools imported successfully')
"
```

- [ ] **Step 3: Commit**

```bash
git add modules/kanban/mcp.py
git commit -m "feat(kanban): add 11 MCP tools for agent task orchestration"
```

---

## Task 6: Auth Extension — user_id in AuthUser

**Files:**
- Modify: `app/auth.py`

- [ ] **Step 1: Update AuthUser model and auth lookup**

In `app/auth.py`, update the `AuthUser` model to include `user_id`:

```python
class AuthUser(BaseModel):
    key_id: str
    name: str
    role: str
    scopes: list[str]
    user_id: str | None = None  # NEW: link to users table
```

In the `get_current_user` dependency function, after the key lookup, join to `users` table:

```python
# After: row = await conn.fetchrow("SELECT id, name, key_hash, role, scopes, active FROM api_keys WHERE ...")
# Add user_id lookup:

user_profile = await conn.fetchrow(
    "SELECT id FROM users WHERE id = $1", row["user_id"]
) if row.get("user_id") else None

return AuthUser(
    key_id=str(row["id"]),
    name=row["name"],
    role=row["role"],
    scopes=row["scopes"] if row["scopes"] else [],
    user_id=str(user_profile["id"]) if user_profile else None,
)
```

Also update `last_active_at` on auth:

```python
if row.get("user_id"):
    await conn.execute(
        "UPDATE users SET last_active_at = now() WHERE id = $1",
        row["user_id"],
    )
```

- [ ] **Step 2: Fix from_agent attribution**

In the existing agent_board routes (and the new kanban routes), change any `from_agent = user.role` to use `user.name` instead. This is in `modules/agent_board/routes.py` around line 605 where messages are sent.

- [ ] **Step 3: Rebuild and verify**

```bash
docker compose build api && docker compose up -d api
```

Verify auth still works:

```bash
curl -s -H "Authorization: Bearer lamadb_test_key_2026" http://localhost:8000/api/dashboard/overview | python3 -c "import sys,json; print('auth ok' if 'documents' in json.load(sys.stdin) else 'auth failed')"
```

- [ ] **Step 4: Commit**

```bash
git add app/auth.py modules/agent_board/routes.py
git commit -m "feat(kanban): add user_id to AuthUser, fix agent attribution to use name"
```

---

## Task 7: SSE Extension + Cache

**Files:**
- Modify: `app/sse.py` (add kanban_task_updated channel)
- Modify: `app/main.py` (subscribe listener)
- Modify: `modules/kanban/routes.py` (add @cached decorators)

- [ ] **Step 1: Add kanban channel to pg_listener**

In `app/sse.py`, add `kanban_task_updated` to the LISTEN channels:

```python
# In the pg_listener startup, add:
await listener_conn.execute("LISTEN kanban_task_updated")
```

In the notification handler, forward kanban events to SSE clients:

```python
elif channel == "kanban_task_updated":
    await sse_manager.broadcast("kanban_task_updated", payload)
```

- [ ] **Step 2: Add @cached to kanban read endpoints**

In `modules/kanban/routes.py`, add caching:

```python
from app.cache import cached
from fastapi import Request

@router.get("/boards")
@cached(ttl_seconds=120, invalidate_tags=["kanban"], key_prefix="kanban_boards")
async def list_boards(request: Request, user: ...):
    ...

@router.get("/boards/{board_id}/tasks")
@cached(ttl_seconds=30, invalidate_tags=["kanban_tasks"], key_prefix="kanban_board_tasks")
async def list_tasks(request: Request, board_id: str, ...):
    ...
```

Write endpoints should invalidate cache:

```python
from app.cache import cache_manager

# In create_task, update_task, move_task, claim_task, complete_task:
cache_manager.invalidate("kanban_tasks")
# In create_board, delete_board:
cache_manager.invalidate("kanban")
```

- [ ] **Step 3: Commit**

```bash
git add app/sse.py app/main.py modules/kanban/routes.py
git commit -m "feat(kanban): add SSE channel + cache for real-time board updates"
```

---

## Task 8: Kanban Board Frontend UI

**Files:**
- Create: `static/js/pages/kanban.js`
- Modify: `static/index.html` (page section + sidebar nav + script tag)
- Modify: `static/js/app.js` (navigation)

- [ ] **Step 1: Add HTML for Kanban page**

In `static/index.html`, after the agent_board page section, add:

```html
<!-- Kanban page -->
<section id="page-kanban" class="page" aria-label="Kanban">
  <div id="kanban-board-selector" style="display:flex;gap:6px;margin-bottom:14px;overflow-x:auto;padding-bottom:4px;"></div>
  <div id="kanban-columns" style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;min-height:300px;"></div>
</section>
```

Add sidebar nav item (after Agent Board):

```html
<button class="nav-item" data-page="kanban">
  <span class="nav-icon">▦</span>
  <span>Kanban</span>
</button>
```

Add script tag:

```html
<script src="/js/pages/kanban.js"></script>
```

- [ ] **Step 2: Write `static/js/pages/kanban.js`**

```javascript
// Page: Kanban
(function() {
  'use strict';

  var _boards = [];
  var _currentBoardId = null;
  var _tasks = {};
  var _sortables = {};

  window.loadKanbanPage = async function() {
    try {
      _boards = await window.api('/api/kanban/boards');
      renderBoardSelector();
      if (_boards.length > 0) {
        await selectBoard(_boards[0].id);
      }
    } catch(e) {
      document.getElementById('kanban-columns').innerHTML =
        '<div style="color:var(--danger);padding:20px;">Failed to load boards: ' + e.message + '</div>';
    }
  };

  function renderBoardSelector() {
    var el = document.getElementById('kanban-board-selector');
    if (!el) return;
    el.innerHTML = _boards.map(function(b) {
      var active = b.id === _currentBoardId ? ' active' : '';
      return '<button class="btn btn-sm' + active + '" style="background:var(--surface-2);border:1px solid var(--border);" onclick="window.selectKanbanBoard(\'' + b.id + '\')">' +
        window.escHtml(b.name) + ' <span style="color:var(--muted);font-size:11px;">(' + b.task_count + ')</span>' +
      '</button>';
    }).join('') +
    '<button class="btn btn-sm" style="background:var(--accent);color:#fff;border:none;" onclick="window.newKanbanBoard()">+ New Board</button>';
  }

  window.selectKanbanBoard = async function(boardId) {
    _currentBoardId = boardId;
    renderBoardSelector();
    try {
      var board = await window.api('/api/kanban/boards/' + boardId);
      renderBoard(board);
    } catch(e) {
      document.getElementById('kanban-columns').innerHTML =
        '<div style="color:var(--danger);padding:20px;">Failed: ' + e.message + '</div>';
    }
  };

  function renderBoard(board) {
    var el = document.getElementById('kanban-columns');
    if (!el) return;
    if (!board.columns || board.columns.length === 0) {
      el.innerHTML = '<div style="color:var(--muted);padding:20px;">No columns</div>';
      return;
    }

    // Destroy old sortables
    Object.values(_sortables).forEach(function(s) { if (s) s.destroy(); });
    _sortables = {};

    el.innerHTML = board.columns.map(function(col) {
      return '<div class="kanban-col" data-col-id="' + col.id + '" style="background:var(--surface-2);border-radius:var(--radius);padding:10px;min-height:100px;">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">' +
          '<h4 style="margin:0;font-size:13px;color:var(--fg);">' + window.escHtml(col.name) +
            (col.wip_limit ? ' <span style="color:var(--muted);font-size:11px;">' + col.task_count + '/' + col.wip_limit + '</span>' : '') +
          '</h4>' +
        '</div>' +
        '<div class="kanban-task-list" data-col-id="' + col.id + '" style="min-height:40px;">' +
          '<div class="loading" style="font-size:12px;color:var(--muted);">Loading\u2026</div>' +
        '</div>' +
        '<button class="btn btn-sm" style="width:100%;margin-top:8px;color:var(--muted);background:transparent;border:1px dashed var(--border);" onclick="window.quickAddTask(\'' + col.id + '\')">+ Add</button>' +
      '</div>';
    }).join('');

    // Load tasks
    window.api('/api/kanban/boards/' + board.id + '/tasks').then(function(tasks) {
      _tasks = {};
      tasks.forEach(function(t) {
        if (!_tasks[t.column_id]) _tasks[t.column_id] = [];
        _tasks[t.column_id].push(t);
      });
      board.columns.forEach(function(col) {
        renderTaskList(col.id, _tasks[col.id] || []);
      });
      initSortable();
    });
  }

  function renderTaskList(colId, tasks) {
    var list = document.querySelector('.kanban-task-list[data-col-id="' + colId + '"]');
    if (!list) return;
    if (tasks.length === 0) {
      list.innerHTML = '<div style="color:var(--muted);font-size:12px;padding:10px;text-align:center;">Empty</div>';
      return;
    }
    list.innerHTML = tasks.map(function(t) {
      var prioColor = {low:'var(--success)', medium:'var(--accent-yellow)', high:'var(--warn)', critical:'var(--danger)'}[t.priority] || 'var(--muted)';
      var subProgress = t.subtask_count > 0 ? ' <span style="font-size:10px;color:var(--muted);">' + t.subtask_done + '/' + t.subtask_count + '</span>' : '';
      return '<div class="kanban-card" data-task-id="' + t.id + '" style="background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);padding:8px;margin-bottom:6px;cursor:grab;' + (t.completed_at ? 'opacity:0.5;' : '') + '" onclick="window.openTaskDetail(\'' + t.id + '\')">' +
        '<div style="display:flex;justify-content:space-between;align-items:flex-start;">' +
          '<span style="font-size:13px;color:var(--fg);font-weight:500;flex:1;">' + window.escHtml(t.title) + '</span>' +
          '<span style="color:' + prioColor + ';font-size:16px;line-height:1;margin-left:4px;">\u25cf</span>' +
        '</div>' +
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-top:6px;">' +
          '<span style="font-size:11px;color:var(--muted);font-family:var(--font-mono);">#' + t.task_number + '</span>' +
          '<span style="font-size:11px;color:var(--fg-2);">' +
            (t.assignee_name || '') +
            (t.help_wanted ? ' <span style="color:var(--warn);">\u26a0</span>' : '') +
          '</span>' +
          subProgress +
        '</div>' +
      '</div>';
    }).join('');
  }

  function initSortable() {
    document.querySelectorAll('.kanban-task-list').forEach(function(el) {
      if (window.Sortable) {
        _sortables[el.dataset.colId] = new Sortable(el, {
          group: 'kanban',
          animation: 150,
          onEnd: function(evt) {
            var taskId = evt.item.dataset.taskId;
            var newColId = evt.to.dataset.colId;
            if (taskId && newColId) {
              window.api('/api/kanban/tasks/' + taskId + '/move', {
                method: 'PATCH',
                body: JSON.stringify({ column_id: newColId, position: evt.newIndex })
              });
            }
          }
        });
      }
    });
  }

  window.openTaskDetail = async function(taskId) {
    try {
      var task = await window.api('/api/kanban/tasks/' + taskId);
      showTaskModal(task);
    } catch(e) {
      window.showToast('Failed to load task: ' + e.message, 'error');
    }
  };

  function showTaskModal(task) {
    var modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.innerHTML = '<div class="modal" style="max-width:600px;max-height:80vh;overflow-y:auto;">' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">' +
        '<h3 style="margin:0;">#' + task.task_number + ' ' + window.escHtml(task.title) + '</h3>' +
        '<button class="btn btn-sm btn-secondary" onclick="this.closest(\'.modal-overlay\').remove()">\u00d7</button>' +
      '</div>' +
      (task.description ? '<div style="color:var(--fg-2);font-size:13px;margin-bottom:12px;line-height:1.5;">' + window.escHtml(task.description) + '</div>' : '') +
      '<div style="display:flex;gap:12px;font-size:12px;color:var(--muted);margin-bottom:12px;">' +
        '<span>Priority: ' + task.priority + '</span>' +
        '<span>Assignee: ' + (task.assignee_name || 'unassigned') + '</span>' +
        (task.estimate ? '<span>Estimate: ' + task.estimate + '</span>' : '') +
      '</div>' +
      (task.subtasks.length > 0 ? '<div style="margin-bottom:12px;"><h4 style="font-size:12px;color:var(--muted);margin-bottom:4px;">Subtasks</h4>' +
        task.subtasks.map(function(s) {
          return '<div style="font-size:12px;padding:4px 0;">' +
            (s.completed ? '\u2705 ' : '\u25a1 ') + window.escHtml(s.title) +
          '</div>';
        }).join('') +
      '</div>' : '') +
      (task.comments.length > 0 ? '<div style="margin-bottom:12px;"><h4 style="font-size:12px;color:var(--muted);margin-bottom:4px;">Comments</h4>' +
        task.comments.map(function(c) {
          return '<div style="background:var(--surface-2);padding:8px;border-radius:var(--radius-sm);margin-bottom:4px;font-size:12px;">' +
            '<span style="color:var(--accent);font-weight:500;">' + window.escHtml(c.user_name || 'unknown') + '</span>: ' + window.escHtml(c.body) +
          '</div>';
        }).join('') +
      '</div>' : '') +
      (task.dependencies.length > 0 ? '<div style="margin-bottom:12px;"><h4 style="font-size:12px;color:var(--muted);margin-bottom:4px;">Dependencies</h4>' +
        task.dependencies.map(function(d) {
          return '<div style="font-size:12px;padding:2px 0;color:' + (d.depends_on_completed ? 'var(--success)' : 'var(--muted)') + ';">' +
            (d.depends_on_completed ? '\u2705 ' : '\u23f3 ') + window.escHtml(d.depends_on_title) +
          '</div>';
        }).join('') +
      '</div>' : '') +
      '<div style="display:flex;gap:8px;border-top:1px solid var(--border);padding-top:12px;">' +
        '<input type="text" id="kanban-comment-input" placeholder="Add comment\u2026" style="flex:1;background:var(--surface-2);border:1px solid var(--border);border-radius:var(--radius-sm);padding:6px 10px;color:var(--fg);font-size:13px;" />' +
        '<button class="btn btn-sm btn-primary" onclick="window.addKanbanComment(\'' + task.id + '\')">Post</button>' +
      '</div>' +
    '</div>';
    document.body.appendChild(modal);
    modal.addEventListener('click', function(e) { if (e.target === modal) modal.remove(); });
  }

  window.addKanbanComment = async function(taskId) {
    var input = document.getElementById('kanban-comment-input');
    if (!input || !input.value.trim()) return;
    try {
      await window.api('/api/kanban/tasks/' + taskId + '/comments', {
        method: 'POST',
        body: JSON.stringify({ body: input.value.trim() })
      });
      input.value = '';
      window.openTaskDetail(taskId);
    } catch(e) {
      window.showToast('Failed: ' + e.message, 'error');
    }
  };

  window.quickAddTask = function(colId) {
    var list = document.querySelector('.kanban-task-list[data-col-id="' + colId + '"]');
    if (!list) return;
    var existing = document.getElementById('quick-add-' + colId);
    if (existing) { existing.remove(); return; }

    var input = document.createElement('div');
    input.id = 'quick-add-' + colId;
    input.style.cssText = 'display:flex;gap:4px;margin-top:4px;';
    input.innerHTML = '<input type="text" id="quick-add-input-' + colId + '" placeholder="Task title\u2026" style="flex:1;background:var(--surface);border:1px solid var(--accent);border-radius:var(--radius-sm);padding:5px 8px;color:var(--fg);font-size:12px;" />' +
      '<button class="btn btn-sm btn-primary" onclick="window.submitQuickTask(\'' + colId + '\')">Add</button>';
    list.parentNode.insertBefore(input, list.nextSibling);

    var inp = document.getElementById('quick-add-input-' + colId);
    if (inp) {
      inp.focus();
      inp.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') window.submitQuickTask(colId);
        if (e.key === 'Escape') { document.getElementById('quick-add-' + colId).remove(); }
      });
    }
  };

  window.submitQuickTask = async function(colId) {
    var input = document.getElementById('quick-add-input-' + colId);
    if (!input || !input.value.trim()) return;
    try {
      await window.api('/api/kanban/boards/' + _currentBoardId + '/tasks', {
        method: 'POST',
        body: JSON.stringify({ title: input.value.trim(), column_id: colId })
      });
      document.getElementById('quick-add-' + colId).remove();
      window.selectKanbanBoard(_currentBoardId);
    } catch(e) {
      window.showToast('Failed: ' + e.message, 'error');
    }
  };

  window.newKanbanBoard = async function() {
    var name = prompt('Board name:');
    if (!name) return;
    var type = confirm('Agentic board? (OK=agentic, Cancel=personal)') ? 'agentic' : 'personal';
    try {
      await window.api('/api/kanban/boards', {
        method: 'POST',
        body: JSON.stringify({ name: name, type: type })
      });
      window.loadKanbanPage();
    } catch(e) {
      window.showToast('Failed: ' + e.message, 'error');
    }
  };

  // SSE handler for real-time updates
  if (window._sseCallbacks) {
    window._sseCallbacks['kanban_task_updated'] = function() {
      if (_currentBoardId) window.selectKanbanBoard(_currentBoardId);
    };
  }
})();
```

- [ ] **Step 3: Add navigation in `static/js/app.js`**

In the page titles map, add:
```javascript
'kanban': 'Kanban',
```

- [ ] **Step 4: Commit**

```bash
git add static/js/pages/kanban.js static/index.html static/js/app.js
git commit -m "feat(kanban): add Kanban board frontend UI with drag-drop"
```

---

## Task 9: User Management Frontend UI

**Files:**
- Create: `static/js/pages/users.js`
- Modify: `static/index.html` (settings sub-tab)
- Modify: `static/js/app.js` (navigation)

- [ ] **Step 1: Add Users settings tab in `static/index.html`**

In the Settings page section, add a Users tab panel:

```html
<!-- Users tab in Settings -->
<div id="tab-settings-users" class="tab-panel" style="display:none;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
    <h3 style="margin:0;">Users</h3>
    <button class="btn btn-sm btn-primary" onclick="window.showNewUserForm()">+ New User</button>
  </div>
  <div id="users-table"><p class="loading">Loading\u2026</p></div>
  <div id="new-user-form" style="display:none;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:14px;margin-top:12px;"></div>
</div>
```

Add settings sub-tab button:
```html
<button class="tab-btn" data-tab="settings-users">Users</button>
```

Add script tag:
```html
<script src="/js/pages/users.js"></script>
```

- [ ] **Step 2: Write `static/js/pages/users.js`**

```javascript
// Page: Users (Settings sub-tab)
(function() {
  'use strict';

  window.loadUsersPage = async function() {
    var el = document.getElementById('users-table');
    if (!el) return;
    el.innerHTML = '<p class="loading">Loading\u2026</p>';
    try {
      var users = await window.api('/api/users');
      if (!users || users.length === 0) {
        el.innerHTML = '<div style="color:var(--muted);padding:20px;text-align:center;">No users found.</div>';
        return;
      }
      el.innerHTML = '<div class="table-wrap"><table><thead><tr><th>Name</th><th>Type</th><th>Status</th><th>Last Active</th><th>Open Tasks</th><th></th></tr></thead><tbody>' +
        users.map(function(u) {
          var statusDot = u.status === 'active' ? '<span class="status-dot" style="background:var(--success);display:inline-block;"></span>' : '<span class="status-dot" style="background:var(--muted);display:inline-block;"></span>';
          var typeBadge = u.type === 'agent' ? '<span class="badge" style="background:var(--accent-cyan);">agent</span>' : '<span class="badge" style="background:var(--accent);">human</span>';
          return '<tr style="cursor:pointer;" onclick="window.toggleUserDetail(\'' + u.id + '\')">' +
            '<td style="font-weight:500;">' + window.escHtml(u.name) + '</td>' +
            '<td>' + typeBadge + '</td>' +
            '<td>' + statusDot + ' ' + u.status + '</td>' +
            '<td class="mono" style="font-size:12px;">' + (u.last_active_at ? window.relativeTime(u.last_active_at) : 'never') + '</td>' +
            '<td class="mono">' + u.open_tasks + '</td>' +
            '<td><button class="btn btn-sm btn-secondary" onclick="event.stopPropagation();window.showUserActions(\'' + u.id + '\', \'' + window.escAttr(u.name) + '\')">\u22ef</button></td>' +
          '</tr>' +
          '<tr id="user-detail-' + u.id + '" style="display:none;"><td colspan="6">Loading\u2026</td></tr>';
        }).join('') +
      '</tbody></table></div>';
    } catch(e) {
      el.innerHTML = '<div style="color:var(--danger);padding:10px;">Failed: ' + e.message + '</div>';
    }
  };

  window.toggleUserDetail = async function(userId) {
    var row = document.getElementById('user-detail-' + userId);
    if (!row) return;
    if (row.style.display !== 'none' && row.innerHTML !== 'Loading\u2026') {
      row.style.display = row.style.display === 'none' ? '' : 'none';
      return;
    }
    row.style.display = '';
    try {
      var user = await window.api('/api/users/' + userId);
      row.innerHTML = '<td colspan="6" style="padding:16px;background:var(--surface-2);">' +
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">' +
          '<div>' +
            '<div style="font-size:12px;color:var(--muted);margin-bottom:4px;">API Key</div>' +
            '<code style="background:var(--surface);padding:4px 8px;border-radius:var(--radius-sm);font-size:12px;">' + (user.api_key_masked || 'No key') + '</code>' +
            '<button class="btn btn-sm btn-secondary" style="margin-left:8px;" onclick="window.rotateUserKey(\'' + userId + '\')">Rotate</button>' +
          '</div>' +
          '<div>' +
            '<div style="font-size:12px;color:var(--muted);margin-bottom:4px;">Instructions</div>' +
            '<div style="font-size:12px;color:var(--fg-2);">' + (user.instructions || 'None') + '</div>' +
          '</div>' +
          '<div>' +
            '<div style="font-size:12px;color:var(--muted);margin-bottom:4px;">Stats</div>' +
            '<div style="font-size:12px;">Open tasks: ' + user.open_tasks + ' | Completed: ' + user.completed_tasks + '</div>' +
          '</div>' +
          '<div>' +
            '<button class="btn btn-sm btn-danger" onclick="window.deactivateUser(\'' + userId + '\')">Deactivate</button>' +
          '</div>' +
        '</div>' +
      '</td>';
    } catch(e) {
      row.innerHTML = '<td colspan="6" style="color:var(--danger);">Failed: ' + e.message + '</td>';
    }
  };

  window.showNewUserForm = function() {
    var el = document.getElementById('new-user-form');
    if (!el) return;
    el.style.display = 'block';
    el.innerHTML = '<h4 style="margin:0 0 10px;">Create User</h4>' +
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">' +
        '<div><label style="font-size:12px;color:var(--muted);">Name</label><input id="nu-name" type="text" style="width:100%;background:var(--surface-2);border:1px solid var(--border);border-radius:var(--radius-sm);padding:6px 8px;color:var(--fg);" placeholder="agent-name" /></div>' +
        '<div><label style="font-size:12px;color:var(--muted);">Type</label><select id="nu-type" style="width:100%;background:var(--surface-2);border:1px solid var(--border);border-radius:var(--radius-sm);padding:6px 8px;color:var(--fg);"><option value="agent">Agent</option><option value="human">Human</option></select></div>' +
      '</div>' +
      '<div style="margin-top:10px;"><label style="font-size:12px;color:var(--muted);">Instructions</label><textarea id="nu-instructions" style="width:100%;background:var(--surface-2);border:1px solid var(--border);border-radius:var(--radius-sm);padding:6px 8px;color:var(--fg);font-size:12px;" rows="3" placeholder="Agent onboarding instructions\u2026"></textarea></div>' +
      '<div style="display:flex;gap:8px;margin-top:10px;">' +
        '<button class="btn btn-sm btn-primary" onclick="window.createUser()">Create</button>' +
        '<button class="btn btn-sm btn-secondary" onclick="document.getElementById(\'new-user-form\').style.display=\'none\'">Cancel</button>' +
      '</div>';
  };

  window.createUser = async function() {
    var name = document.getElementById('nu-name').value.trim();
    if (!name) { alert('Name required'); return; }
    try {
      var result = await window.api('/api/users', {
        method: 'POST',
        body: JSON.stringify({
          name: name,
          type: document.getElementById('nu-type').value,
          instructions: document.getElementById('nu-instructions').value.trim()
        })
      });
      document.getElementById('new-user-form').style.display = 'none';
      alert('User created!\n\nAPI Key (save now - won\'t be shown again):\n' + result.api_key);
      window.loadUsersPage();
    } catch(e) {
      alert('Failed: ' + e.message);
    }
  };

  window.rotateUserKey = async function(userId) {
    if (!confirm('Rotate API key for this user? The old key will stop working immediately.')) return;
    try {
      var result = await window.api('/api/users/' + userId + '/rotate-key', { method: 'POST' });
      alert('New API key:\n' + result.api_key);
      window.toggleUserDetail(userId);
    } catch(e) {
      alert('Failed: ' + e.message);
    }
  };

  window.deactivateUser = async function(userId) {
    if (!confirm('Deactivate this user? All their API keys will be revoked.')) return;
    try {
      await window.api('/api/users/' + userId, { method: 'DELETE' });
      alert('User deactivated.');
      window.loadUsersPage();
    } catch(e) {
      alert('Failed: ' + e.message);
    }
  };
})();
```

- [ ] **Step 3: Commit**

```bash
git add static/js/pages/users.js static/index.html
git commit -m "feat(kanban): add user management frontend UI"
```

---

## Task 10: Agent Logs + Activity Feed

**Files:**
- Modify: `modules/kanban/routes.py` (add agent log endpoint)
- Modify: `static/js/pages/kanban.js` (show activity in task detail)

- [ ] **Step 1: Add agent logs endpoint to routes.py**

```python
@router.get("/boards/{board_id}/logs")
async def get_board_logs(
    board_id: str, user: Annotated[AuthUser, Depends(get_current_user)],
    limit: int = Query(default=20, ge=1, le=100),
):
    """Get recent agent activity for a board."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT l.*, u.name AS user_name
            FROM kanban_agent_logs l
            LEFT JOIN users u ON u.id = l.user_id
            WHERE l.board_id = $1
            ORDER BY l.created_at DESC LIMIT $2
        """, board_id, limit)
    return [
        {"id": str(r["id"]), "user_name": r["user_name"], "action": r["action"],
         "details": r["details"], "tool": r["tool"], "created_at": r["created_at"]}
        for r in rows
    ]
```

- [ ] **Step 2: Commit**

```bash
git add modules/kanban/routes.py
git commit -m "feat(kanban): add agent activity log endpoint"
```

---

## Task 11: Migration Script & Agent Connect Verification

**Files:**
- Create: `scripts/migrate_users.py` (one-time script to backfill users table from api_keys)

- [ ] **Step 1: Write migration script**

```python
"""One-time: backfill users table from existing api_keys."""
import asyncio, asyncpg, os

async def main():
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    # Create users for api_keys that don't have one
    rows = await conn.fetch("""
        INSERT INTO users (name, type, status)
        SELECT DISTINCT k.name, 'human', 'active'
        FROM api_keys k
        WHERE k.user_id IS NULL
          AND NOT EXISTS (SELECT 1 FROM users u WHERE u.name = k.name)
        RETURNING id, name
    """)
    for r in rows:
        print(f"Created user: {r['name']} ({r['id']})")
        await conn.execute(
            "UPDATE api_keys SET user_id = $1 WHERE name = $2 AND user_id IS NULL",
            r["id"], r["name"],
        )
    await conn.close()
    print("Migration complete.")

asyncio.run(main())
```

- [ ] **Step 2: Run migration**

```bash
docker exec lamadb_api python3 scripts/migrate_users.py
```

- [ ] **Step 3: Verify agent connect**

```bash
curl -s -H "Authorization: Bearer lamadb_test_key_2026" http://localhost:8000/api/kanban/me | python3 -m json.tool
```

Expected: Returns user profile with active boards and open tasks.

- [ ] **Step 4: Commit**

```bash
git add scripts/migrate_users.py
git commit -m "feat(kanban): add user migration script + verify agent connect"
```

---

## Task 12: Dogfood QA

**Files:**
- None (verification only)

- [ ] **Step 1: Create a board via API and verify it renders in dashboard**

```bash
# Create agentic board
curl -s -X POST -H "Authorization: Bearer lamadb_test_key_2026" \
  -H "Content-Type: application/json" \
  -d '{"name":"Coding Tasks","type":"agentic","instructions":"All coding tasks go here."}' \
  http://localhost:8000/api/kanban/boards

# Create personal board
curl -s -X POST -H "Authorization: Bearer lamadb_test_key_2026" \
  -H "Content-Type: application/json" \
  -d '{"name":"Personal","type":"personal"}' \
  http://localhost:8000/api/kanban/boards

# List boards
curl -s -H "Authorization: Bearer lamadb_test_key_2026" \
  http://localhost:8000/api/kanban/boards | python3 -m json.tool
```

- [ ] **Step 2: Create tasks, move between columns, verify MCP tools**

```bash
# Create a task
TASK=$(curl -s -X POST -H "Authorization: Bearer lamadb_test_key_2026" \
  -H "Content-Type: application/json" \
  -d '{"title":"Test task for QA","priority":"high"}' \
  http://localhost:8000/api/kanban/boards/BOARD_ID/tasks)
echo $TASK | python3 -m json.tool

# Verify MCP find_work (replace USER_ID)
docker exec lamadb_api python3 -c "
import asyncio
from modules.kanban.mcp import kanban_find_work
async def main():
    result = await kanban_find_work('USER_ID')
    print(result)
asyncio.run(main())
"
```

- [ ] **Step 3: Dashboard testing**

Load `http://localhost:8000` in browser:
- Navigate to Kanban tab — verify boards show in tab bar
- Click board — verify 4 columns render with tasks
- Drag a task between columns — verify position persists on reload
- Click task card — verify detail modal shows description, subtasks, comments
- Add a comment — verify it appears
- Navigate to Settings → Users — verify user list loads
- Create a new user — verify API key is shown once

- [ ] **Step 4: Commit QA results**

```bash
git commit --allow-empty -m "qa(kanban): dogfood QA passed — boards, tasks, drag-drop, users verified"
```

---

## Deferred Features (Not in this plan)

After fundamentals are stable, these follow in subsequent plans:
- **Encrypted secrets storage** — per-agent secrets, encrypted at rest
- **Tags** — per-board colored labels on tasks
- **Custom fields** — board-level custom field definitions
- **Task templates** — reusable task blueprints
- **Board templates** — pre-configured board + column sets
- **Board sharing** — public read-only share links
- **Approval workflow** — human approval gates for agent actions
- **Task transitions audit** — full column movement history
- **User groups** — group-based API key and permission management
- **Swimlanes** — group tasks by assignee within columns
