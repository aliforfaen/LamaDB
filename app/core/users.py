"""User management endpoints — identity profiles for agents and humans."""
import asyncio
import secrets
from typing import Annotated

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import AuthUser, get_current_user
from app.core.dashboard import require_admin
from app.db import get_pool
from app.config import settings

router = APIRouter(tags=["users"])

USER_KEY_PREFIX = "lamadb_user_"


def _generate_api_key() -> str:
    """Generate a human-readable API key."""
    return USER_KEY_PREFIX + secrets.token_urlsafe(24)


def _key_prefix_hash(raw_key: str) -> str:
    """SHA-256 of the first 16 chars — mirrors app.auth._hash_prefix.

    Required by the O(1) auth lookup (migration 013): without key_prefix
    populated, the new key won't be found on the fast path and the legacy
    fallback is unavailable once legacy keys are gone.
    """
    from app.auth import _hash_prefix
    return _hash_prefix(raw_key)


async def _hash_key(raw_key: str) -> str:
    """Hash an API key with the configured salt."""
    salt = settings.api_key_salt.encode()
    return await asyncio.to_thread(
        lambda: bcrypt.hashpw(salt + raw_key.encode(), bcrypt.gensalt()).decode()
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
    key_prefix = _key_prefix_hash(raw_key)

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

        user_type = body.get("type", "agent")
        role = "admin" if user_type == "human" else "agent"
        scopes = ["kanban", "documents", "events"] if role == "agent" else []

        key_id = await conn.fetchval(
            """INSERT INTO api_keys (name, key_hash, key_prefix, role, scopes, active, user_id)
               VALUES ($1, $2, $3, $4, $5, true, $6) RETURNING id""",
            name, key_hash, key_prefix, role, scopes, user_id,
        )

    return {
        "user": {"id": str(user_id), "name": name, "type": user_type, "status": "active"},
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

    key_masked = USER_KEY_PREFIX + "****" if row["active_key_hash"] else None

    return {
        "id": str(row["id"]), "name": row["name"], "type": row["type"],
        "status": row["status"], "instructions": row["instructions"],
        "last_active_at": row["last_active_at"],
        "api_key_masked": key_masked,
        "api_key_id": str(row["active_key_id"]) if row["active_key_id"] else None,
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
            updates.append("updated_at = now()")
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
        key_prefix = _key_prefix_hash(raw_key)

        await conn.execute(
            "UPDATE api_keys SET active = false WHERE user_id = $1 AND active = true",
            user_id,
        )

        user_type = existing["type"]
        role = "admin" if user_type == "human" else "agent"
        scopes = ["kanban", "documents", "events"] if role == "agent" else []

        key_id = await conn.fetchval(
            """INSERT INTO api_keys (name, key_hash, key_prefix, role, scopes, active, user_id)
               VALUES ($1, $2, $3, $4, $5, true, $6) RETURNING id""",
            existing["name"],
            key_hash,
            key_prefix,
            role,
            scopes,
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
