"""Access control logic for the secrets module."""
from app.auth import AuthUser
from app.db import get_pool


async def can_reveal(secret: dict, auth_user: AuthUser) -> bool:
    if auth_user.role == "admin":
        return True

    user_id = auth_user.user_id

    if user_id and secret.get("owner_user_id") == user_id:
        return True

    owner_group_id = secret.get("owner_group_id")
    if owner_group_id and user_id:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM user_group_memberships WHERE group_id = $1 AND user_id = $2",
                owner_group_id, user_id,
            )
            if row:
                return True

    if user_id:
        pool = get_pool()
        async with pool.acquire() as conn:
            grant = await conn.fetchrow(
                "SELECT 1 FROM secret_access WHERE secret_id = $1 AND grantee_type = 'user' AND grantee_id = $2",
                secret["id"], user_id,
            )
            if grant:
                return True

    if auth_user.groups:
        pool = get_pool()
        async with pool.acquire() as conn:
            for group_name in auth_user.groups:
                group_id = await _group_name_to_id(conn, group_name)
                if group_id:
                    grant = await conn.fetchrow(
                        "SELECT 1 FROM secret_access WHERE secret_id = $1 AND grantee_type = 'group' AND grantee_id = $2",
                        secret["id"], group_id,
                    )
                    if grant:
                        return True

    return False


async def can_manage(secret: dict, auth_user: AuthUser) -> bool:
    if auth_user.role == "admin":
        return True

    user_id = auth_user.user_id

    if user_id and secret.get("owner_user_id") == user_id:
        return True

    owner_group_id = secret.get("owner_group_id")
    if owner_group_id and user_id:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT role FROM user_group_memberships WHERE group_id = $1 AND user_id = $2 AND role IN ('owner', 'admin')",
                owner_group_id, user_id,
            )
            if row:
                return True

    if user_id:
        pool = get_pool()
        async with pool.acquire() as conn:
            grant = await conn.fetchrow(
                "SELECT 1 FROM secret_access WHERE secret_id = $1 AND grantee_type = 'user' AND grantee_id = $2 AND access_level = 'read_write'",
                secret["id"], user_id,
            )
            if grant:
                return True

    if auth_user.groups:
        pool = get_pool()
        async with pool.acquire() as conn:
            for group_name in auth_user.groups:
                group_id = await _group_name_to_id(conn, group_name)
                if group_id:
                    grant = await conn.fetchrow(
                        "SELECT 1 FROM secret_access WHERE secret_id = $1 AND grantee_type = 'group' AND grantee_id = $2 AND access_level = 'read_write'",
                        secret["id"], group_id,
                    )
                    if grant:
                        return True

    return False


async def _group_name_to_id(conn, group_name: str) -> str | None:
    row = await conn.fetchrow(
        "SELECT id FROM groups WHERE name = $1", group_name
    )
    return str(row["id"]) if row else None


async def grant_access(
    secret_id: str, grantee_type: str, grantee_id: str,
    access_level: str, granted_by: str | None,
) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO secret_access (secret_id, grantee_type, grantee_id, access_level, granted_by)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (secret_id, grantee_type, grantee_id)
            DO UPDATE SET access_level = $4, granted_by = $5, granted_at = now()""",
            secret_id, grantee_type, grantee_id, access_level, granted_by,
        )


async def revoke_access(grant_id: int) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM secret_access WHERE id = $1", grant_id)


async def log_audit(
    secret_id: str, user_id: str | None, action: str,
    details: str = "", ip_address: str | None = None,
) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO secret_audit_log (secret_id, user_id, action, details, ip_address)
            VALUES ($1, $2, $3, $4, $5)""",
            secret_id, user_id, action, details, ip_address,
        )
