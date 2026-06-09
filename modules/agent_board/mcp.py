"""MCP tools for the Agent Board module."""
import json
from app.db import get_pool


async def get_agent_tasks(status: str = None, priority: str = None,
                          limit: int = 50) -> dict:
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
            LIMIT ${param_idx}
        """
        params.append(limit)

        rows = await conn.fetch(query, *params)

    tasks = []
    for row in rows:
        meta = row["metadata"]
        if meta is not None and not isinstance(meta, dict):
            if isinstance(meta, str):
                meta = json.loads(meta)
            else:
                meta = dict(meta) if meta else {}
        elif meta is None:
            meta = {}

        result = row["result"]
        if result is not None and not isinstance(result, dict):
            if isinstance(result, str):
                result = json.loads(result)
            else:
                result = dict(result) if result else {}
        elif result is None:
            result = {}

        tasks.append({
            "id": str(row["id"]),
            "title": row["title"],
            "description": row["description"],
            "task_type": row["task_type"],
            "priority": row["priority"],
            "status": row["status"],
            "created_by": row["created_by"],
            "claimed_by": row["claimed_by"],
            "assigned_to": row["assigned_to"],
            "metadata": meta,
            "result": result,
            "error": row["error"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        })

    return {"tasks": tasks, "count": len(tasks)}


async def send_agent_message(to_agent: str, subject: str, body: str = "",
                             message_type: str = "info",
                             metadata: dict = None) -> dict:
    """Send an agent-to-agent message."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO agent_messages (from_agent, to_agent, subject, body, message_type, metadata)
            VALUES ('mcp', $1, $2, $3, $4, $5)
            RETURNING id, from_agent, to_agent, subject, body, message_type, metadata, read, created_at
            """,
            to_agent,
            subject,
            body,
            message_type,
            json.dumps(metadata or {}),
        )

    meta = row["metadata"]
    if meta is not None and not isinstance(meta, dict):
        if isinstance(meta, str):
            meta = json.loads(meta)
        else:
            meta = dict(meta) if meta else {}
    elif meta is None:
        meta = {}

    return {
        "id": row["id"],
        "from_agent": row["from_agent"],
        "to_agent": row["to_agent"],
        "subject": row["subject"],
        "body": row["body"],
        "message_type": row["message_type"],
        "metadata": meta,
        "read": row["read"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }
