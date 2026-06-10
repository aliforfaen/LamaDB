"""Agent Board routes — task queue and messaging for AI agents."""
import json
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import AuthUser, get_current_user
from app.db import get_pool
from app.models.events import EventCreate
from modules.agent_board.models import (
    MessageCreate,
    MessageResponse,
    TaskClaim,
    TaskComplete,
    TaskCreate,
    TaskResponse,
)

router = APIRouter(tags=["agent_board"])


def _task_from_row(row) -> "TaskResponse":
    """Convert asyncpg row to TaskResponse, coercing JSONB fields."""
    d = dict(row)
    # Convert UUID to string
    if "id" in d and hasattr(d["id"], "__str__"):
        d["id"] = str(d["id"])
    # Coerce metadata JSONB
    meta = d.get("metadata")
    if meta is not None and not isinstance(meta, dict):
        if isinstance(meta, str):
            d["metadata"] = json.loads(meta)
        else:
            d["metadata"] = dict(meta) if meta else {}
    elif meta is None:
        d["metadata"] = {}
    # Coerce result JSONB
    result = d.get("result")
    if result is not None and not isinstance(result, dict):
        if isinstance(result, str):
            d["result"] = json.loads(result)
        else:
            d["result"] = dict(result) if result else {}
    elif result is None:
        d["result"] = {}
    return TaskResponse(**d)


def _message_from_row(row) -> "MessageResponse":
    """Convert asyncpg row to MessageResponse, coercing JSONB."""
    d = dict(row)
    meta = d.get("metadata")
    if meta is not None and not isinstance(meta, dict):
        if isinstance(meta, str):
            d["metadata"] = json.loads(meta)
        else:
            d["metadata"] = dict(meta) if meta else {}
    elif meta is None:
        d["metadata"] = {}
    return MessageResponse(**d)


# ---------------------------------------------------------------------------
# POST /api/agent_board/tasks — Create a task
# ---------------------------------------------------------------------------

@router.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    task: TaskCreate,
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> TaskResponse:
    """Create a new agent task."""
    if user.role not in ("admin", "agent"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO agent_tasks (title, description, task_type, priority, assigned_to, created_by, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id, title, description, task_type, priority, status,
                      created_by, claimed_by, assigned_to, metadata, result,
                      error, created_at, updated_at, claimed_at, completed_at
            """,
            task.title,
            task.description,
            task.task_type,
            task.priority,
            task.assigned_to,
            task.created_by or user.role,  # Use role as default creator
            json.dumps(task.metadata),
        )
        return _task_from_row(row)


# ---------------------------------------------------------------------------
# GET /api/agent_board/tasks — List tasks
# ---------------------------------------------------------------------------

@router.get("/tasks", response_model=list[TaskResponse])
async def list_tasks(
    user: Annotated[AuthUser, Depends(get_current_user)],
    status: Optional[str] = Query(default=None, description="Filter by status"),
    priority: Optional[str] = Query(default=None, description="Filter by priority"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[TaskResponse]:
    """List agent tasks with optional filters."""
    pool = get_pool()
    async with pool.acquire() as conn:
        conditions = []
        params = []
        param_idx = 1

        if status is not None:
            conditions.append(f"status = ${param_idx}")
            params.append(status)
            param_idx += 1

        if priority is not None:
            conditions.append(f"priority = ${param_idx}")
            params.append(priority)
            param_idx += 1

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        query = f"""
            SELECT id, title, description, task_type, priority, status,
                   created_by, claimed_by, assigned_to, metadata, result,
                   error, created_at, updated_at, claimed_at, completed_at
            FROM agent_tasks
            {where_clause}
            ORDER BY
                CASE priority
                    WHEN 'critical' THEN 0
                    WHEN 'high' THEN 1
                    WHEN 'normal' THEN 2
                    WHEN 'low' THEN 3
                    ELSE 4
                END,
                created_at DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """
        params.extend([limit, offset])

        rows = await conn.fetch(query, *params)
        return [_task_from_row(row) for row in rows]


# ---------------------------------------------------------------------------
# GET /api/agent_board/tasks/{id} — Get task by ID
# ---------------------------------------------------------------------------

@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> TaskResponse:
    """Get a specific task by ID."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, title, description, task_type, priority, status,
                   created_by, claimed_by, assigned_to, metadata, result,
                   error, created_at, updated_at, claimed_at, completed_at
            FROM agent_tasks
            WHERE id = $1
            """,
            task_id,
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task {task_id} not found",
            )
        return _task_from_row(row)


# ---------------------------------------------------------------------------
# POST /api/agent_board/tasks/{id}/claim — Claim a task
# ---------------------------------------------------------------------------

@router.post("/tasks/{task_id}/claim", response_model=TaskResponse)
async def claim_task(
    task_id: str,
    claim: TaskClaim,
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> TaskResponse:
    """Claim a pending task (sets status='claimed', claimed_by)."""
    if user.role not in ("admin", "agent"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    pool = get_pool()
    async with pool.acquire() as conn:
        # Check current status
        existing = await conn.fetchrow(
            "SELECT id, status FROM agent_tasks WHERE id = $1",
            task_id,
        )
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task {task_id} not found",
            )
        if existing["status"] != "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Task is already {existing['status']}, cannot claim",
            )

        row = await conn.fetchrow(
            """
            UPDATE agent_tasks
            SET status = 'claimed',
                claimed_by = $1,
                claimed_at = now(),
                updated_at = now()
            WHERE id = $2
            RETURNING id, title, description, task_type, priority, status,
                      created_by, claimed_by, assigned_to, metadata, result,
                      error, created_at, updated_at, claimed_at, completed_at
            """,
            claim.claimed_by,
            task_id,
        )
        return _task_from_row(row)


# ---------------------------------------------------------------------------
# POST /api/agent_board/tasks/{id}/complete — Mark complete
# ---------------------------------------------------------------------------

@router.post("/tasks/{task_id}/complete", response_model=TaskResponse)
async def complete_task(
    task_id: str,
    complete: TaskComplete,
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> TaskResponse:
    """Mark a claimed task as completed."""
    if user.role not in ("admin", "agent"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    pool = get_pool()
    async with pool.acquire() as conn:
        # Check current status
        existing = await conn.fetchrow(
            "SELECT id, status FROM agent_tasks WHERE id = $1",
            task_id,
        )
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task {task_id} not found",
            )
        if existing["status"] not in ("claimed", "in_progress"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Task must be claimed first (current: {existing['status']})",
            )

        row = await conn.fetchrow(
            """
            UPDATE agent_tasks
            SET status = 'completed',
                result = $1,
                completed_at = now(),
                updated_at = now()
            WHERE id = $2
            RETURNING id, title, description, task_type, priority, status,
                      created_by, claimed_by, assigned_to, metadata, result,
                      error, created_at, updated_at, claimed_at, completed_at
            """,
            json.dumps(complete.result) if complete.result else "{}",
            task_id,
        )
        return _task_from_row(row)


# ---------------------------------------------------------------------------
# POST /api/agent_board/tasks/{id}/fail — Mark failed
# ---------------------------------------------------------------------------

@router.post("/tasks/{task_id}/fail", response_model=TaskResponse)
async def fail_task(
    task_id: str,
    fail: TaskComplete,
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> TaskResponse:
    """Mark a claimed task as failed."""
    if user.role not in ("admin", "agent"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    pool = get_pool()
    async with pool.acquire() as conn:
        # Check current status
        existing = await conn.fetchrow(
            "SELECT id, status FROM agent_tasks WHERE id = $1",
            task_id,
        )
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task {task_id} not found",
            )
        if existing["status"] not in ("claimed", "in_progress"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Task must be claimed first (current: {existing['status']})",
            )

        row = await conn.fetchrow(
            """
            UPDATE agent_tasks
            SET status = 'failed',
                error = $1,
                completed_at = now(),
                updated_at = now()
            WHERE id = $2
            RETURNING id, title, description, task_type, priority, status,
                      created_by, claimed_by, assigned_to, metadata, result,
                      error, created_at, updated_at, claimed_at, completed_at
            """,
            fail.error,
            task_id,
        )
        return _task_from_row(row)
# ---------------------------------------------------------------------------
# POST /api/agent_board/tasks/{id}/unclaim — Release a claimed task
# ---------------------------------------------------------------------------
@router.post("/tasks/{task_id}/unclaim", response_model=TaskResponse)
async def unclaim_task(
    task_id: str,
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> TaskResponse:
    """Release a claimed task back to pending (clears claimed_by/claimed_at)."""
    if user.role not in ("admin", "agent"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id, status FROM agent_tasks WHERE id = $1",
            task_id,
        )
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task {task_id} not found",
            )
        if existing["status"] not in ("claimed", "in_progress"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Task must be claimed to release (current: {existing['status']})",
            )
        row = await conn.fetchrow(
            """
            UPDATE agent_tasks
            SET status = 'pending',
                claimed_by = NULL,
                claimed_at = NULL,
                updated_at = now()
            WHERE id = $1
            RETURNING id, title, description, task_type, priority, status,
                      created_by, claimed_by, assigned_to, metadata, result,
                      error, created_at, updated_at, claimed_at, completed_at
            """,
            task_id,
        )
        return _task_from_row(row)
# ---------------------------------------------------------------------------
# PATCH /api/agent_board/messages/{id}/read — Mark message as read
# ---------------------------------------------------------------------------
@router.patch("/messages/{msg_id}/read")
async def mark_message_read(
    msg_id: int,
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> MessageResponse:
    """Mark a message as read. Any authenticated user can do this."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE agent_messages SET read = true
            WHERE id = $1
            RETURNING id, from_agent, to_agent, inbox_for, subject, body, message_type,
                      parent_id, reply_to, metadata, read, created_at
            """,
            msg_id,
        )
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
        return _message_from_row(row)


# ---------------------------------------------------------------------------
# PATCH /api/agent_board/messages/read-all — Mark all as read for an agent
# ---------------------------------------------------------------------------
@router.patch("/messages/read-all")
async def mark_all_read(
    user: Annotated[AuthUser, Depends(get_current_user)],
    agent: str = Query(...),
):
    """Mark all unread messages in an agent's inbox as read."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE agent_messages SET read = true
            WHERE (inbox_for = $1 OR (inbox_for IS NULL AND to_agent = $1))
              AND read = false
            """,
            agent,
        )
        updated = int(result.split()[-1]) if result else 0
        return {"agent": agent, "marked_read": updated}


# ---------------------------------------------------------------------------
# GET /api/agent_board/inbox — Messages addressed to agent, unread first
# ---------------------------------------------------------------------------
@router.get("/inbox", response_model=list[MessageResponse])
async def get_inbox(
    user: Annotated[AuthUser, Depends(get_current_user)],
    agent: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Get inbox for an agent — unread messages first, then by date descending.

    If `agent` is None, returns ALL inbox messages (no filter).
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        if agent is None:
            rows = await conn.fetch(
                """
                SELECT id, from_agent, to_agent, inbox_for, subject, body, message_type,
                       parent_id, reply_to, metadata, read, created_at
                FROM agent_messages
                ORDER BY read ASC, created_at DESC
                LIMIT $1 OFFSET $2
                """,
                limit, offset,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, from_agent, to_agent, inbox_for, subject, body, message_type,
                       parent_id, reply_to, metadata, read, created_at
                FROM agent_messages
                WHERE inbox_for = $1 OR (inbox_for IS NULL AND to_agent = $1)
                ORDER BY read ASC, created_at DESC
                LIMIT $2 OFFSET $3
                """,
                agent, limit, offset,
            )
        return [_message_from_row(r) for r in rows]


# ---------------------------------------------------------------------------
# GET /api/agent_board/sent — Messages sent by agent
# ---------------------------------------------------------------------------
@router.get("/sent", response_model=list[MessageResponse])
async def get_sent(
    user: Annotated[AuthUser, Depends(get_current_user)],
    agent: str = Query(...),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Get messages sent by a specific agent."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, from_agent, to_agent, inbox_for, subject, body, message_type,
                   parent_id, reply_to, metadata, read, created_at
            FROM agent_messages
            WHERE from_agent = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            agent, limit, offset,
        )
        return [_message_from_row(r) for r in rows]


# ---------------------------------------------------------------------------
# GET /api/agent_board/inbox/count — Unread count for badge
# ---------------------------------------------------------------------------
@router.get("/inbox/count")
async def inbox_unread_count(
    user: Annotated[AuthUser, Depends(get_current_user)],
    agent: Optional[str] = Query(default=None),
):
    """Get unread message count for an agent's inbox (or all agents if None)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        if agent is None:
            count = await conn.fetchval(
                """
                SELECT count(*) FROM agent_messages
                WHERE read = false
                """,
            )
        else:
            count = await conn.fetchval(
                """
                SELECT count(*) FROM agent_messages
                WHERE (inbox_for = $1 OR (inbox_for IS NULL AND to_agent = $1))
                  AND read = false
                """,
                agent,
            )
        return {"agent": agent, "unread": count or 0}


# ---------------------------------------------------------------------------
# GET /api/agent_board/thread/{msg_id} — Full thread via recursive CTE
# ---------------------------------------------------------------------------
@router.get("/thread/{msg_id}")
async def get_thread(
    msg_id: int,
    user: Annotated[AuthUser, Depends(get_current_user)],
):
    """Get full message thread by walking reply_to up to root, then recursing down."""
    pool = get_pool()
    async with pool.acquire() as conn:
        # Walk up to the root message
        root = msg_id
        current = msg_id
        while True:
            row = await conn.fetchrow(
                "SELECT reply_to FROM agent_messages WHERE id = $1", current
            )
            if not row or not row["reply_to"]:
                break
            current = row["reply_to"]
            root = current

        rows = await conn.fetch(
            """
            WITH RECURSIVE thread AS (
                SELECT id, from_agent, to_agent, inbox_for, subject, body, message_type,
                       parent_id, reply_to, metadata, read, created_at, 0 AS depth
                FROM agent_messages
                WHERE id = $1
                UNION ALL
                SELECT m.id, m.from_agent, m.to_agent, m.inbox_for, m.subject, m.body,
                       m.message_type, m.parent_id, m.reply_to, m.metadata,
                       m.read, m.created_at, t.depth + 1
                FROM agent_messages m
                JOIN thread t ON m.reply_to = t.id
            )
            SELECT * FROM thread ORDER BY depth, created_at
            """,
            root,
        )
        if not rows:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Message not found"
            )
        return {"thread": [_message_from_row(r) for r in rows]}

# ---------------------------------------------------------------------------
# POST /api/agent_board/messages — Send a message
# ---------------------------------------------------------------------------

@router.post("/messages", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def send_message(
    message: MessageCreate,
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> MessageResponse:
    """Send an agent-to-agent message."""
    if user.role not in ("admin", "agent"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO agent_messages (from_agent, to_agent, inbox_for, subject, body, message_type, parent_id, reply_to, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id, from_agent, to_agent, inbox_for, subject, body, message_type,
                      parent_id, reply_to, metadata, read, created_at
            """,
            user.name,  # Use API key name as from_agent (e.g. "muninn", "ali")
            message.to_agent,
            message.inbox_for or message.to_agent,  # default inbox_for = to_agent
            message.subject,
            message.body,
            message.message_type,
            message.parent_id,
            message.reply_to,
            json.dumps(message.metadata),
        )
        return _message_from_row(row)


# ---------------------------------------------------------------------------
# GET /api/agent_board/messages — List messages
# ---------------------------------------------------------------------------

@router.get("/messages", response_model=list[MessageResponse])
async def list_messages(
    user: Annotated[AuthUser, Depends(get_current_user)],
    to_agent: Optional[str] = Query(default=None),
    unread: Optional[bool] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[MessageResponse]:
    """List agent messages with optional filters."""
    pool = get_pool()
    async with pool.acquire() as conn:
        conditions = []
        params = []
        param_idx = 1

        if to_agent is not None:
            conditions.append(f"to_agent = ${param_idx}")
            params.append(to_agent)
            param_idx += 1

        if unread is not None:
            conditions.append(f"read = ${param_idx}")
            params.append(not unread)  # unread=true means read=false
            param_idx += 1

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        query = f"""
            SELECT id, from_agent, to_agent, inbox_for, subject, body, message_type,
                   parent_id, reply_to, metadata, read, created_at
            FROM agent_messages
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """
        params.extend([limit, offset])

        rows = await conn.fetch(query, *params)
        return [_message_from_row(row) for row in rows]