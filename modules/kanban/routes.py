"""Kanban module routes — boards, columns, tasks, subtasks, dependencies, comments."""
import json
from datetime import datetime, timezone
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.auth import AuthUser, get_current_user
from app.cache import cache_manager, cached
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
@cached(ttl_seconds=60, invalidate_tags=["kanban"], key_prefix="kanban_me")
async def agent_connect(
    request: Request,
    user: Annotated[AuthUser, Depends(get_current_user)],
):
    """Agent first-connect: profile, boards, open tasks, instructions."""
    pool = get_pool()
    async with pool.acquire() as conn:
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

        boards = await conn.fetch("""
            SELECT b.*,
                   (SELECT count(*) FROM kanban_tasks t WHERE t.board_id = b.id AND t.completed_at IS NULL) AS task_count,
                   (SELECT count(*) FROM kanban_columns c WHERE c.board_id = b.id) AS column_count
            FROM kanban_boards b ORDER BY b.name
        """)

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
@cached(ttl_seconds=120, invalidate_tags=["kanban"], key_prefix="kanban_boards")
async def list_boards(
    request: Request,
    user: Annotated[AuthUser, Depends(get_current_user)],
):
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
            "instructions": r["instructions"],
            "owner_id": str(r["owner_id"]) if r["owner_id"] else None,
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

    cache_manager.invalidate("kanban")
    return {"id": str(board_id), "name": body.name, "type": body.type, "columns": len(cols)}


@router.get("/boards/{board_id}")
@cached(ttl_seconds=60, invalidate_tags=["kanban"], key_prefix="kanban_board")
async def get_board(
    request: Request,
    board_id: str,
    user: Annotated[AuthUser, Depends(get_current_user)],
):
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

    cache_manager.invalidate("kanban")
    return {"status": "ok"}


@router.delete("/boards/{board_id}")
async def delete_board(
    board_id: str, user: Annotated[AuthUser, Depends(_require_admin_or_agent)],
):
    """Delete a board and all its tasks/columns (CASCADE)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        # Delete agent logs first (FK may not have CASCADE)
        await conn.execute("DELETE FROM kanban_agent_logs WHERE board_id = $1", board_id)
        await conn.execute("DELETE FROM kanban_boards WHERE id = $1", board_id)
    cache_manager.invalidate("kanban")
    cache_manager.invalidate("kanban_tasks")
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
    cache_manager.invalidate("kanban")
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
    cache_manager.invalidate("kanban")
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
    cache_manager.invalidate("kanban")
    return {"status": "deleted"}


# ── Tasks ─────────────────────────────────────────────────────

@router.get("/boards/{board_id}/tasks")
@cached(ttl_seconds=30, invalidate_tags=["kanban_tasks"], key_prefix="kanban_board_tasks")
async def list_tasks(
    request: Request,
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
        col_id = body.column_id
        if not col_id:
            col_id = await conn.fetchval(
                "SELECT id FROM kanban_columns WHERE board_id = $1 ORDER BY position LIMIT 1",
                board_id,
            )
            if not col_id:
                raise HTTPException(status_code=400, detail="Board has no columns")

        max_pos = await conn.fetchval(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM kanban_tasks WHERE column_id = $1",
            col_id,
        )

        # Compute next_num and INSERT; retry once on unique-constraint conflict.
        # The UNIQUE (board_id, task_number) constraint added in migration 014
        # prevents duplicate task_numbers from concurrent inserts.
        next_num = await conn.fetchval(
            "SELECT COALESCE(MAX(task_number), 0) + 1 FROM kanban_tasks WHERE board_id = $1",
            board_id,
        )
        try:
            task_id = await conn.fetchval("""
                INSERT INTO kanban_tasks (board_id, column_id, task_number, title, description,
                                          priority, assignee_id, position, due_at, estimate)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) RETURNING id
            """, board_id, col_id, next_num, body.title, body.description,
                body.priority, body.assignee_id, max_pos, body.due_at, body.estimate)
        except asyncpg.exceptions.UniqueViolationError:
            # Lost a race — recompute and retry once.
            next_num = await conn.fetchval(
                "SELECT COALESCE(MAX(task_number), 0) + 1 FROM kanban_tasks WHERE board_id = $1",
                board_id,
            )
            task_id = await conn.fetchval("""
                INSERT INTO kanban_tasks (board_id, column_id, task_number, title, description,
                                          priority, assignee_id, position, due_at, estimate)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) RETURNING id
            """, board_id, col_id, next_num, body.title, body.description,
                body.priority, body.assignee_id, max_pos, body.due_at, body.estimate)

    cache_manager.invalidate("kanban_tasks")
    return {"id": str(task_id), "task_number": next_num, "title": body.title}


@router.get("/tasks/{task_id}")
@cached(ttl_seconds=30, invalidate_tags=["kanban_tasks"], key_prefix="kanban_task")
async def get_task(
    request: Request,
    task_id: str,
    user: Annotated[AuthUser, Depends(get_current_user)],
):
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

    cache_manager.invalidate("kanban_tasks")
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
    cache_manager.invalidate("kanban_tasks")
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

        in_progress_col = await conn.fetchval(
            "SELECT id FROM kanban_columns WHERE board_id = $1 AND status = 'in_progress' ORDER BY position LIMIT 1",
            task["board_id"],
        )

        await conn.execute(
            "UPDATE kanban_tasks SET assignee_id = $1, column_id = COALESCE($2, column_id), updated_at = now() WHERE id = $3",
            user.user_id, in_progress_col, task_id,
        )

        await conn.execute(
            "INSERT INTO kanban_agent_logs (user_id, task_id, board_id, action) VALUES ($1, $2, $3, 'task_claimed')",
            user.user_id, task_id, task["board_id"],
        )

    cache_manager.invalidate("kanban_tasks")
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

        now = datetime.now(timezone.utc)
        await conn.execute(
            "UPDATE kanban_tasks SET completed_at = $1, updated_at = now() WHERE id = $2",
            now, task_id,
        )

        # Move to Done column
        done_col = await conn.fetchval(
            "SELECT id FROM kanban_columns WHERE board_id = $1 AND status = 'done' ORDER BY position LIMIT 1",
            task["board_id"],
        )
        if done_col:
            await conn.execute(
                "UPDATE kanban_tasks SET column_id = $1, updated_at = now() WHERE id = $2",
                done_col, task_id,
            )

        dependents = await conn.fetch("""
            SELECT d.task_id, t.board_id as board_id FROM kanban_task_dependencies d
            JOIN kanban_tasks t ON t.id = d.task_id
            WHERE d.depends_on_id = $1
        """, task_id)

        in_progress_col = await conn.fetchval(
            "SELECT id FROM kanban_columns WHERE board_id = $1 AND status = 'in_progress' ORDER BY position LIMIT 1",
            task["board_id"],
        )

        for dep in dependents:
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
                # Log auto-start for each dependent
                await conn.execute(
                    "INSERT INTO kanban_agent_logs (user_id, task_id, board_id, action, details) VALUES ($1, $2, $3, 'task_auto_started', 'Dependencies completed')",
                    user.user_id, dep["task_id"], dep["board_id"],
                )

        await conn.execute(
            "INSERT INTO kanban_agent_logs (user_id, task_id, board_id, action, details) VALUES ($1, $2, $3, 'task_completed', $4)",
            user.user_id, task_id, task["board_id"], body.summary,
        )

    cache_manager.invalidate("kanban_tasks")
    return {"status": "completed"}


# ── Subtasks ──────────────────────────────────────────────────

@router.post("/tasks/{task_id}/subtasks", status_code=status.HTTP_201_CREATED)
async def add_subtask(
    task_id: str, body: KanbanSubtaskCreate,
    user: Annotated[AuthUser, Depends(_require_admin_or_agent)],
):
    """Add a subtask to a task."""
    pool = get_pool()
    async with pool.acquire() as conn:
        max_pos = await conn.fetchval(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM kanban_subtasks WHERE task_id = $1",
            task_id,
        )
        sub_id = await conn.fetchval(
            "INSERT INTO kanban_subtasks (task_id, title, position) VALUES ($1, $2, $3) RETURNING id",
            task_id, body.title, max_pos,
        )
        # Fetch board_id for logging
        board_id = await conn.fetchval(
            "SELECT board_id FROM kanban_tasks WHERE id = $1", task_id
        )
        await conn.execute(
            "INSERT INTO kanban_agent_logs (user_id, task_id, board_id, action, details) VALUES ($1, $2, $3, 'subtask_added', $4)",
            user.user_id, task_id, board_id, body.title[:200],
        )
    cache_manager.invalidate("kanban_tasks")
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
    cache_manager.invalidate("kanban_tasks")
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
    cache_manager.invalidate("kanban_tasks")
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
    cache_manager.invalidate("kanban_tasks")
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
        # Log the comment
        await conn.execute(
            "INSERT INTO kanban_agent_logs (user_id, task_id, action, details) VALUES ($1, $2, 'comment_added', $3)",
            user.user_id, task_id, body.body[:200],
        )
    cache_manager.invalidate("kanban_tasks")
    return {"id": str(comment_id), "task_id": task_id, "body": body.body}
