"""MCP tool handlers for the secrets module."""
from app.auth import AuthUser
from app.db import get_pool
from .crypto import reveal_decrypted, decrypt_extra
from .access import can_reveal


async def list_secrets(args: dict, auth_user: AuthUser) -> list[dict]:
    service = args.get("service")
    secret_type = args.get("secret_type")
    tag = args.get("tag")
    accessible_only = args.get("accessible", False)

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
        if accessible_only:
            if await can_reveal(secret, auth_user):
                secret["accessible"] = True
                results.append(secret)
        else:
            secret["accessible"] = await can_reveal(secret, auth_user)
            results.append(secret)

    return results


async def get_secret_metadata(args: dict, auth_user: AuthUser) -> dict:
    secret_id = args["id"]
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM secrets WHERE id = $1", secret_id)
        if not row:
            raise ValueError(f"Secret '{secret_id}' not found")

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
        secret["accessible"] = await can_reveal(secret, auth_user)
        return secret


async def reveal_secret(args: dict, auth_user: AuthUser) -> dict:
    secret_id = args["id"]
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM secrets WHERE id = $1", secret_id)
        if not row:
            raise ValueError(f"Secret '{secret_id}' not found")

    secret_data = {
        "id": str(row["id"]),
        "owner_user_id": str(row["owner_user_id"]) if row["owner_user_id"] else None,
        "owner_group_id": str(row["owner_group_id"]) if row["owner_group_id"] else None,
    }
    if not await can_reveal(secret_data, auth_user):
        raise PermissionError(
            f"You do not have access to reveal secret '{row['name']}'. "
            f"Use request_secret_access to ask for permission."
        )

    value = await reveal_decrypted(secret_id, auth_user.user_id)
    extra_1 = await decrypt_extra(secret_id, "encrypted_extra_1")
    extra_2 = await decrypt_extra(secret_id, "encrypted_extra_2")

    return {
        "id": secret_id, "value": value,
        "extra_1": extra_1, "extra_2": extra_2,
        "secret_type": row["secret_type"],
    }


async def request_secret_access(args: dict, auth_user: AuthUser) -> dict:
    secret_id = args["id"]
    reason = args.get("reason", "")

    if not auth_user.user_id:
        raise ValueError("User identity required to request access")

    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT name FROM secrets WHERE id = $1", secret_id)
        if not existing:
            raise ValueError(f"Secret '{secret_id}' not found")

        pending = await conn.fetchrow(
            "SELECT id FROM secret_access_requests WHERE secret_id = $1 AND requester_user_id = $2 AND status = 'pending'",
            secret_id, auth_user.user_id,
        )
        if pending:
            return {"status": "already_pending", "message": f"You already have a pending request for '{existing['name']}'"}

        row = await conn.fetchrow(
            "INSERT INTO secret_access_requests (secret_id, requester_user_id, reason) VALUES ($1, $2, $3) RETURNING id",
            secret_id, auth_user.user_id, reason,
        )
        return {
            "status": "pending", "request_id": row["id"],
            "message": f"Access request submitted for '{existing['name']}'. An admin will review it.",
        }
