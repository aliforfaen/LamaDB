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
