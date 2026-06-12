"""MCP tool handlers for the secrets module."""
from app.db import get_pool
from .crypto import reveal_decrypted, decrypt_extra


async def _get_user_groups(user_id: str) -> list[str]:
    """Fetch group names for a user (mirrors _fetch_user_groups in auth.py)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT g.name FROM groups g
               JOIN user_group_memberships ugm ON g.id = ugm.group_id
               WHERE ugm.user_id = $1 ORDER BY g.name""",
            user_id,
        )
        return [r["name"] for r in rows]


async def _user_is_admin(user_id: str) -> bool:
    """Check if a user has admin role."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT ak.role FROM api_keys ak WHERE ak.user_id = $1 AND ak.active = true LIMIT 1""",
            user_id,
        )
        return row is not None and row["role"] == "admin"


async def _can_reveal(secret: dict, user_id: str, user_groups: list[str]) -> bool:
    """Check if user can reveal a secret (adapted from access.py for MCP context)."""
    # Admin bypass
    if await _user_is_admin(user_id):
        return True

    # Direct ownership
    if secret.get("owner_user_id") == user_id:
        return True

    # Group ownership
    owner_group_id = secret.get("owner_group_id")
    if owner_group_id and user_groups:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM user_group_memberships WHERE group_id = $1 AND user_id = $2",
                owner_group_id, user_id,
            )
            if row:
                return True

    # Explicit grants (user-level)
    pool = get_pool()
    async with pool.acquire() as conn:
        grant = await conn.fetchrow(
            "SELECT 1 FROM secret_access WHERE secret_id = $1 AND grantee_type = 'user' AND grantee_id = $2",
            secret["id"], user_id,
        )
        if grant:
            return True

    # Explicit grants (group-level)
    if user_groups:
        async with pool.acquire() as conn:
            for group_name in user_groups:
                row = await conn.fetchrow("SELECT id FROM groups WHERE name = $1", group_name)
                if row:
                    grant = await conn.fetchrow(
                        "SELECT 1 FROM secret_access WHERE secret_id = $1 AND grantee_type = 'group' AND grantee_id = $2",
                        secret["id"], str(row["id"]),
                    )
                    if grant:
                        return True

    return False


async def list_secrets(user_id: str, service: str | None = None,
                       secret_type: str | None = None, tag: str | None = None,
                       accessible: bool = False) -> list[dict]:
    """List all secrets visible to the agent (metadata only, no values)."""
    pool = get_pool()
    conditions = []
    params = []
    idx = 1

    if service:
        conditions.append(f"service = ${idx}"); params.append(service); idx += 1
    if secret_type:
        conditions.append(f"secret_type = ${idx}"); params.append(secret_type); idx += 1
    if tag:
        conditions.append(f"${idx} = ANY(tags)"); params.append(tag); idx += 1

    where = " AND ".join(conditions) if conditions else "TRUE"

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT id, name, service, secret_type, priority, tags, "
            f"owner_user_id, owner_group_id, expires_at, last_revealed_at "
            f"FROM secrets WHERE {where} ORDER BY service, name",
            *params,
        )

    user_groups = await _get_user_groups(user_id)
    results = []
    for r in rows:
        secret = {
            "id": str(r["id"]), "name": r["name"], "service": r["service"],
            "secret_type": r["secret_type"], "priority": r["priority"],
            "tags": list(r["tags"]) if r["tags"] else [],
            "owner_user_id": str(r["owner_user_id"]) if r["owner_user_id"] else None,
            "owner_group_id": str(r["owner_group_id"]) if r["owner_group_id"] else None,
            "expires_at": str(r["expires_at"]) if r["expires_at"] else None,
            "last_revealed_at": str(r["last_revealed_at"]) if r["last_revealed_at"] else None,
        }
        can = await _can_reveal(secret, user_id, user_groups)
        if accessible:
            if can:
                secret["accessible"] = True
                results.append(secret)
        else:
            secret["accessible"] = can
            results.append(secret)

    return results


async def get_secret_metadata(id: str, user_id: str) -> dict:
    """Get full metadata for a specific secret by ID."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM secrets WHERE id = $1", id)
        if not row:
            raise ValueError(f"Secret '{id}' not found")

        user_groups = await _get_user_groups(user_id)
        secret = {
            "id": str(row["id"]), "name": row["name"], "service": row["service"],
            "description": row["description"] or "", "secret_type": row["secret_type"],
            "priority": row["priority"], "tags": list(row["tags"]) if row["tags"] else [],
            "owner_user_id": str(row["owner_user_id"]) if row["owner_user_id"] else None,
            "owner_group_id": str(row["owner_group_id"]) if row["owner_group_id"] else None,
            "expires_at": str(row["expires_at"]) if row["expires_at"] else None,
            "last_revealed_at": str(row["last_revealed_at"]) if row["last_revealed_at"] else None,
            "created_at": str(row["created_at"]), "updated_at": str(row["updated_at"]),
        }
        secret["accessible"] = await _can_reveal(secret, user_id, user_groups)
        return secret


async def reveal_secret(id: str, user_id: str) -> dict:
    """Decrypt and return a secret value. Requires access grant or ownership."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM secrets WHERE id = $1", id)
        if not row:
            raise ValueError(f"Secret '{id}' not found")

    user_groups = await _get_user_groups(user_id)
    secret_data = {
        "id": str(row["id"]),
        "owner_user_id": str(row["owner_user_id"]) if row["owner_user_id"] else None,
        "owner_group_id": str(row["owner_group_id"]) if row["owner_group_id"] else None,
    }
    if not await _can_reveal(secret_data, user_id, user_groups):
        raise PermissionError(
            f"You do not have access to reveal secret '{row['name']}'. "
            f"Use request_secret_access to ask for permission."
        )

    value = await reveal_decrypted(id, user_id)
    extra_1 = await decrypt_extra(id, "encrypted_extra_1")
    extra_2 = await decrypt_extra(id, "encrypted_extra_2")

    return {
        "id": id, "value": value,
        "extra_1": extra_1, "extra_2": extra_2,
        "secret_type": row["secret_type"],
    }


async def request_secret_access(id: str, user_id: str, reason: str = "") -> dict:
    """Request access to a secret that is visible but not accessible."""
    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT name FROM secrets WHERE id = $1", id)
        if not existing:
            raise ValueError(f"Secret '{id}' not found")

        pending = await conn.fetchrow(
            "SELECT sr.id FROM secret_access_requests sr WHERE sr.secret_id = $1 AND sr.requester_user_id = $2 AND sr.status = 'pending'",
            id, user_id,
        )
        if pending:
            return {"status": "already_pending", "message": f"You already have a pending request for '{existing['name']}'"}

        row = await conn.fetchrow(
            "INSERT INTO secret_access_requests (secret_id, requester_user_id, reason) VALUES ($1, $2, $3) RETURNING id",
            id, user_id, reason,
        )
        return {
            "status": "pending", "request_id": row["id"],
            "message": f"Access request submitted for '{existing['name']}'. An admin will review it.",
        }
