"""Groups REST API — /api/groups/*"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import AuthUser, get_current_user
from app.db import get_pool
from .models import (
    GroupCreate, GroupUpdate, GroupResponse, GroupDetail,
    MemberAdd, MemberUpdate, GroupMember,
)

router = APIRouter(tags=["groups"])


def _require_admin(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


async def _is_group_owner(conn, group_id: str, user_id: str) -> bool:
    row = await conn.fetchrow(
        "SELECT 1 FROM user_group_memberships WHERE group_id = $1 AND user_id = $2 AND role = 'owner'",
        group_id, user_id,
    )
    return row is not None


# ─── POST /api/groups ───────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_group(
    body: GroupCreate,
    user: AuthUser = Depends(_require_admin),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO groups (name, description, created_by)
            VALUES ($1, $2, $3)
            RETURNING id, name, description, created_by, created_at, updated_at
            """,
            body.name, body.description, user.user_id,
        )
        return {
            "id": str(row["id"]),
            "name": row["name"],
            "description": row["description"],
            "member_count": 0,
            "created_by": str(row["created_by"]) if row["created_by"] else None,
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }


# ─── GET /api/groups ────────────────────────────────────────────────────

@router.get("")
async def list_groups(
    user: AuthUser = Depends(get_current_user),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                g.id, g.name, g.description, g.created_by, g.created_at, g.updated_at,
                COUNT(ugm.user_id) AS member_count
            FROM groups g
            LEFT JOIN user_group_memberships ugm ON g.id = ugm.group_id
            GROUP BY g.id
            ORDER BY g.name
            """
        )
        return [
            {
                "id": str(r["id"]),
                "name": r["name"],
                "description": r["description"],
                "member_count": r["member_count"],
                "created_by": str(r["created_by"]) if r["created_by"] else None,
                "created_at": str(r["created_at"]),
                "updated_at": str(r["updated_at"]),
            }
            for r in rows
        ]


# ─── GET /api/groups/{id} ───────────────────────────────────────────────

@router.get("/{group_id}")
async def get_group(
    group_id: str,
    user: AuthUser = Depends(get_current_user),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                g.id, g.name, g.description, g.created_by, g.created_at, g.updated_at,
                COUNT(ugm.user_id) AS member_count
            FROM groups g
            LEFT JOIN user_group_memberships ugm ON g.id = ugm.group_id
            WHERE g.id = $1
            GROUP BY g.id
            """,
            group_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Group not found")

        members = await conn.fetch(
            """
            SELECT ugm.user_id, u.name AS user_name, ugm.role, ugm.added_at
            FROM user_group_memberships ugm
            JOIN users u ON u.id = ugm.user_id
            WHERE ugm.group_id = $1
            ORDER BY ugm.role DESC, u.name
            """,
            group_id,
        )

        return {
            "id": str(row["id"]),
            "name": row["name"],
            "description": row["description"],
            "member_count": row["member_count"],
            "created_by": str(row["created_by"]) if row["created_by"] else None,
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "members": [
                {
                    "user_id": str(m["user_id"]),
                    "user_name": m["user_name"],
                    "role": m["role"],
                    "added_at": str(m["added_at"]),
                }
                for m in members
            ],
        }


# ─── PATCH /api/groups/{id} ─────────────────────────────────────────────

@router.patch("/{group_id}")
async def update_group(
    group_id: str,
    body: GroupUpdate,
    user: AuthUser = Depends(get_current_user),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT created_by FROM groups WHERE id = $1", group_id
        )
        if not existing:
            raise HTTPException(status_code=404, detail="Group not found")

        is_owner = await _is_group_owner(conn, group_id, user.user_id) if user.user_id else False
        if user.role != "admin" and str(existing["created_by"]) != user.user_id and not is_owner:
            raise HTTPException(status_code=403, detail="Only admins or group owners can update")

        sets = []
        args = [group_id]
        idx = 2
        if body.name is not None:
            sets.append(f"name = ${idx}"); args.append(body.name); idx += 1
        if body.description is not None:
            sets.append(f"description = ${idx}"); args.append(body.description); idx += 1
        sets.append(f"updated_at = now()")

        row = await conn.fetchrow(
            f"UPDATE groups SET {', '.join(sets)} WHERE id = $1 "
            f"RETURNING id, name, description, created_by, created_at, updated_at",
            *args,
        )
        member_count = await conn.fetchval(
            "SELECT COUNT(*) FROM user_group_memberships WHERE group_id = $1",
            group_id,
        )
        return {
            "id": str(row["id"]),
            "name": row["name"],
            "description": row["description"],
            "member_count": member_count,
            "created_by": str(row["created_by"]) if row["created_by"] else None,
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }


# ─── DELETE /api/groups/{id} ────────────────────────────────────────────

@router.delete("/{group_id}", status_code=204)
async def delete_group(
    group_id: str,
    user: AuthUser = Depends(_require_admin),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM groups WHERE id = $1", group_id
        )
        if result == "DELETE 0":
            raise HTTPException(status_code=404, detail="Group not found")


# ─── POST /api/groups/{id}/members ──────────────────────────────────────

@router.post("/{group_id}/members", status_code=201)
async def add_member(
    group_id: str,
    body: MemberAdd,
    user: AuthUser = Depends(get_current_user),
):
    if body.role not in ("member", "admin", "owner"):
        raise HTTPException(status_code=400, detail="Invalid role: must be member, admin, or owner")

    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT created_by FROM groups WHERE id = $1", group_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Group not found")

        is_owner = await _is_group_owner(conn, group_id, user.user_id) if user.user_id else False
        if user.role != "admin" and str(existing["created_by"]) != user.user_id and not is_owner:
            raise HTTPException(status_code=403, detail="Only admins or group owners can add members")

        user_exists = await conn.fetchval(
            "SELECT 1 FROM users WHERE id = $1", body.user_id
        )
        if not user_exists:
            raise HTTPException(status_code=400, detail="User not found")

        await conn.execute(
            """
            INSERT INTO user_group_memberships (user_id, group_id, role)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id, group_id) DO UPDATE SET role = $3
            """,
            body.user_id, group_id, body.role,
        )
        return {"status": "ok", "user_id": body.user_id, "role": body.role}


# ─── DELETE /api/groups/{id}/members/{user_id} ──────────────────────────

@router.delete("/{group_id}/members/{user_id}", status_code=204)
async def remove_member(
    group_id: str,
    user_id: str,
    user: AuthUser = Depends(get_current_user),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT created_by FROM groups WHERE id = $1", group_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Group not found")

        is_owner = await _is_group_owner(conn, group_id, user.user_id) if user.user_id else False
        if user.role != "admin" and str(existing["created_by"]) != user.user_id and not is_owner:
            raise HTTPException(status_code=403, detail="Only admins or group owners can remove members")

        member_exists = await conn.fetchrow(
            "SELECT 1 FROM user_group_memberships WHERE group_id = $1 AND user_id = $2",
            group_id, user_id,
        )
        if not member_exists:
            raise HTTPException(status_code=404, detail="Member not found in group")

        await conn.execute(
            "DELETE FROM user_group_memberships WHERE group_id = $1 AND user_id = $2",
            group_id, user_id,
        )


# ─── PATCH /api/groups/{id}/members/{user_id} ───────────────────────────

@router.patch("/{group_id}/members/{user_id}")
async def update_member_role(
    group_id: str,
    user_id: str,
    body: MemberUpdate,
    user: AuthUser = Depends(get_current_user),
):
    if body.role not in ("member", "admin", "owner"):
        raise HTTPException(status_code=400, detail="Invalid role")

    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT created_by FROM groups WHERE id = $1", group_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Group not found")

        is_owner = await _is_group_owner(conn, group_id, user.user_id) if user.user_id else False
        if user.role != "admin" and str(existing["created_by"]) != user.user_id and not is_owner:
            raise HTTPException(status_code=403, detail="Only admins or group owners can change roles")

        await conn.execute(
            "UPDATE user_group_memberships SET role = $3 WHERE group_id = $1 AND user_id = $2",
            group_id, user_id, body.role,
        )
        return {"status": "ok", "user_id": user_id, "role": body.role}
