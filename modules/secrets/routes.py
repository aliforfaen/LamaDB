"""Secrets REST API — /api/secrets/*"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth import AuthUser, get_current_user
from app.db import get_pool
from .models import (
    SecretCreate, SecretUpdate, SecretResponse, SecretRevealResponse,
    SecretAccessGrant, AccessGrantCreate,
    AccessRequestCreate, AccessRequestResponse, AccessRequestUpdate,
)
from .crypto import encrypt_value, encrypt_optional, reveal_decrypted, decrypt_extra
from .access import can_reveal, can_manage, grant_access, revoke_access, log_audit

router = APIRouter(tags=["secrets"])


def _secret_row_to_response(row) -> dict:
    return {
        "id": str(row["id"]), "name": row["name"], "service": row["service"],
        "description": row["description"] or "", "secret_type": row["secret_type"],
        "priority": row["priority"], "tags": list(row["tags"]) if row["tags"] else [],
        "owner_user_id": str(row["owner_user_id"]) if row["owner_user_id"] else None,
        "owner_group_id": str(row["owner_group_id"]) if row["owner_group_id"] else None,
        "expires_at": str(row["expires_at"]) if row["expires_at"] else None,
        "last_revealed_at": str(row["last_revealed_at"]) if row["last_revealed_at"] else None,
        "created_at": str(row["created_at"]), "updated_at": str(row["updated_at"]),
    }


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("", status_code=201)
async def create_secret(body: SecretCreate, request: Request, user: AuthUser = Depends(get_current_user)):
    pool = get_pool()
    encrypted_val = await encrypt_value(body.value)
    encrypted_e1 = await encrypt_optional(body.extra_1)
    encrypted_e2 = await encrypt_optional(body.extra_2)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO secrets (name, service, description, secret_type,
            encrypted_value, encrypted_extra_1, encrypted_extra_2,
            priority, tags, owner_user_id, owner_group_id, expires_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12) RETURNING *""",
            body.name, body.service, body.description, body.secret_type,
            encrypted_val, encrypted_e1, encrypted_e2,
            body.priority, body.tags, body.owner_user_id, body.owner_group_id,
            body.expires_at,
        )
        secret_data = _secret_row_to_response(row)
    await log_audit(str(row["id"]), user.user_id, "create",
                    f"Created secret '{body.name}' (type={body.secret_type}, service={body.service})",
                    _get_client_ip(request))
    return secret_data


@router.get("")
async def list_secrets(
    user: AuthUser = Depends(get_current_user),
    service: Optional[str] = Query(None), secret_type: Optional[str] = Query(None),
    priority: Optional[str] = Query(None), tag: Optional[str] = Query(None),
    accessible: bool = Query(False), expiring_soon: bool = Query(False),
    expired: bool = Query(False), group: Optional[str] = Query(None),
):
    pool = get_pool()
    conditions = []; args = []; idx = 1
    if service: conditions.append(f"service = ${idx}"); args.append(service); idx += 1
    if secret_type: conditions.append(f"secret_type = ${idx}"); args.append(secret_type); idx += 1
    if priority: conditions.append(f"priority = ${idx}"); args.append(priority); idx += 1
    if tag: conditions.append(f"${idx} = ANY(tags)"); args.append(tag); idx += 1
    if expiring_soon: conditions.append("expires_at IS NOT NULL AND expires_at <= now() + interval '30 days'")
    if expired: conditions.append("expires_at IS NOT NULL AND expires_at <= now()")
    if group: conditions.append(f"owner_group_id = (SELECT id FROM groups WHERE name = ${idx})"); args.append(group); idx += 1
    where = " AND ".join(conditions) if conditions else "TRUE"
    async with pool.acquire() as conn:
        rows = await conn.fetch(f"SELECT * FROM secrets WHERE {where} ORDER BY service, name", *args)
    results = []
    for r in rows:
        secret = _secret_row_to_response(r)
        if accessible:
            if await can_reveal(secret, user): results.append(secret)
        else:
            results.append(secret)
    return results


# NOTE: /requests routes are registered before /{secret_id} so the literal
# path matches first (FastAPI matches in declaration order; otherwise
# GET /requests would be caught by GET /{secret_id} with secret_id="requests").

@router.get("/requests")
async def list_access_requests(user: AuthUser = Depends(get_current_user), status_filter: Optional[str] = Query(None, alias="status")):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    pool = get_pool()
    conditions = []; args = []; idx = 1
    if status_filter: conditions.append(f"sar.status = ${idx}"); args.append(status_filter); idx += 1
    where = " AND ".join(conditions) if conditions else "TRUE"
    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""SELECT sar.*, s.name AS secret_name, u.name AS requester_name
            FROM secret_access_requests sar JOIN secrets s ON s.id = sar.secret_id JOIN users u ON u.id = sar.requester_user_id
            WHERE {where} ORDER BY sar.created_at DESC LIMIT 100""", *args)
        return [{"id": r["id"], "secret_id": str(r["secret_id"]), "secret_name": r["secret_name"], "requester_user_id": str(r["requester_user_id"]), "requester_name": r["requester_name"], "requested_level": r["requested_level"], "reason": r["reason"] or "", "status": r["status"], "reviewed_by": str(r["reviewed_by"]) if r["reviewed_by"] else None, "reviewed_at": str(r["reviewed_at"]) if r["reviewed_at"] else None, "created_at": str(r["created_at"])} for r in rows]


@router.patch("/requests/{request_id}")
async def review_access_request(request_id: int, body: AccessRequestUpdate, request: Request, user: AuthUser = Depends(get_current_user)):
    if user.role not in ("admin",): raise HTTPException(status_code=403, detail="Admin role required to review access requests")
    pool = get_pool()
    async with pool.acquire() as conn:
        req = await conn.fetchrow("SELECT * FROM secret_access_requests WHERE id = $1", request_id)
        if not req: raise HTTPException(status_code=404, detail="Request not found")
        if req["status"] != "pending": raise HTTPException(status_code=400, detail=f"Request is already {req['status']}")
        new_status = body.status
        await conn.execute("UPDATE secret_access_requests SET status = $1, reviewed_by = $2, reviewed_at = now() WHERE id = $3", new_status, user.user_id, request_id)
        if new_status == "approved":
            await grant_access(str(req["secret_id"]), "user", str(req["requester_user_id"]), req["requested_level"], user.user_id)
        action = "approve" if new_status == "approved" else "reject"
        await log_audit(str(req["secret_id"]), user.user_id, action, f"{'Approved' if new_status == 'approved' else 'Rejected'} access request #{request_id} from {req['requester_user_id']}", _get_client_ip(request))
    return {"status": new_status}


@router.get("/{secret_id}")
async def get_secret(secret_id: str, user: AuthUser = Depends(get_current_user)):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM secrets WHERE id = $1", secret_id)
        if not row: raise HTTPException(status_code=404, detail="Secret not found")
        return _secret_row_to_response(row)


@router.patch("/{secret_id}")
async def update_secret(secret_id: str, body: SecretUpdate, request: Request, user: AuthUser = Depends(get_current_user)):
    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT * FROM secrets WHERE id = $1", secret_id)
        if not existing: raise HTTPException(status_code=404, detail="Secret not found")
        secret_data = _secret_row_to_response(existing)
        if not await can_manage(secret_data, user):
            raise HTTPException(status_code=403, detail="You do not have permission to edit this secret")
        sets = ["updated_at = now()"]; args = []; idx = 1
        for field in ["name", "service", "description", "secret_type", "priority"]:
            val = getattr(body, field, None)
            if val is not None: sets.append(f"{field} = ${idx}"); args.append(val); idx += 1
        if body.value is not None: sets.append(f"encrypted_value = ${idx}"); args.append(await encrypt_value(body.value)); idx += 1
        if body.extra_1 is not None: sets.append(f"encrypted_extra_1 = ${idx}"); args.append(await encrypt_optional(body.extra_1)); idx += 1
        if body.extra_2 is not None: sets.append(f"encrypted_extra_2 = ${idx}"); args.append(await encrypt_optional(body.extra_2)); idx += 1
        if body.tags is not None: sets.append(f"tags = ${idx}"); args.append(body.tags); idx += 1
        if body.owner_user_id is not None: sets.append(f"owner_user_id = ${idx}"); args.append(body.owner_user_id); idx += 1
        if body.owner_group_id is not None: sets.append(f"owner_group_id = ${idx}"); args.append(body.owner_group_id); idx += 1
        if body.expires_at is not None: sets.append(f"expires_at = ${idx}"); args.append(body.expires_at); idx += 1
        args.append(secret_id)
        row = await conn.fetchrow(f"UPDATE secrets SET {', '.join(sets)} WHERE id = ${idx} RETURNING *", *args)
        result = _secret_row_to_response(row)
    await log_audit(secret_id, user.user_id, "update", "Updated secret", _get_client_ip(request))
    return result


@router.delete("/{secret_id}", status_code=204)
async def delete_secret(secret_id: str, request: Request, user: AuthUser = Depends(get_current_user)):
    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT * FROM secrets WHERE id = $1", secret_id)
        if not existing: raise HTTPException(status_code=404, detail="Secret not found")
        secret_data = _secret_row_to_response(existing)
        if not await can_manage(secret_data, user):
            raise HTTPException(status_code=403, detail="You do not have permission to delete this secret")
        await conn.execute("DELETE FROM secrets WHERE id = $1", secret_id)
    await log_audit(secret_id, user.user_id, "delete", "Deleted secret", _get_client_ip(request))


@router.get("/{secret_id}/reveal")
async def reveal_secret(secret_id: str, request: Request, user: AuthUser = Depends(get_current_user)):
    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT * FROM secrets WHERE id = $1", secret_id)
        if not existing: raise HTTPException(status_code=404, detail="Secret not found")
        secret_data = _secret_row_to_response(existing)
        if not await can_reveal(secret_data, user):
            raise HTTPException(status_code=403, detail="You do not have permission to reveal this secret. Use /request to ask for access.")
    plaintext = await reveal_decrypted(secret_id, user.user_id)
    extra_1 = await decrypt_extra(secret_id, "encrypted_extra_1")
    extra_2 = await decrypt_extra(secret_id, "encrypted_extra_2")
    return {"id": secret_id, "value": plaintext, "extra_1": extra_1, "extra_2": extra_2, "secret_type": existing["secret_type"]}


@router.post("/{secret_id}/access", status_code=201)
async def create_access_grant(secret_id: str, body: AccessGrantCreate, request: Request, user: AuthUser = Depends(get_current_user)):
    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT * FROM secrets WHERE id = $1", secret_id)
        if not existing: raise HTTPException(status_code=404, detail="Secret not found")
        secret_data = _secret_row_to_response(existing)
        if not await can_manage(secret_data, user):
            raise HTTPException(status_code=403, detail="You do not have permission to manage access for this secret")
    await grant_access(secret_id, body.grantee_type, body.grantee_id, body.access_level, user.user_id)
    await log_audit(secret_id, user.user_id, "grant", f"Granted {body.access_level} access to {body.grantee_type}:{body.grantee_id}", _get_client_ip(request))
    return {"status": "ok"}


@router.get("/{secret_id}/access")
async def list_access_grants(secret_id: str, user: AuthUser = Depends(get_current_user)):
    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT * FROM secrets WHERE id = $1", secret_id)
        if not existing: raise HTTPException(status_code=404, detail="Secret not found")
        rows = await conn.fetch(
            """SELECT sa.*, CASE WHEN sa.grantee_type = 'user' THEN u.name WHEN sa.grantee_type = 'group' THEN g.name END AS grantee_name
            FROM secret_access sa LEFT JOIN users u ON sa.grantee_type = 'user' AND sa.grantee_id = u.id::text
            LEFT JOIN groups g ON sa.grantee_type = 'group' AND sa.grantee_id = g.id::text
            WHERE sa.secret_id = $1 ORDER BY sa.granted_at DESC""", secret_id)
        return [{"id": r["id"], "secret_id": str(r["secret_id"]), "grantee_type": r["grantee_type"], "grantee_id": r["grantee_id"], "grantee_name": r["grantee_name"] or "", "access_level": r["access_level"], "granted_by": str(r["granted_by"]) if r["granted_by"] else None, "granted_at": str(r["granted_at"])} for r in rows]


@router.delete("/{secret_id}/access/{grant_id}", status_code=204)
async def delete_access_grant(secret_id: str, grant_id: int, request: Request, user: AuthUser = Depends(get_current_user)):
    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT * FROM secrets WHERE id = $1", secret_id)
        if not existing: raise HTTPException(status_code=404, detail="Secret not found")
        secret_data = _secret_row_to_response(existing)
        if not await can_manage(secret_data, user):
            raise HTTPException(status_code=403, detail="You do not have permission to manage access for this secret")
        await revoke_access(grant_id)
    await log_audit(secret_id, user.user_id, "revoke", f"Revoked access grant #{grant_id}", _get_client_ip(request))


@router.post("/{secret_id}/request", status_code=201)
async def create_access_request(secret_id: str, body: AccessRequestCreate, user: AuthUser = Depends(get_current_user)):
    if not user.user_id: raise HTTPException(status_code=400, detail="User identity required for access requests")
    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT id FROM secrets WHERE id = $1", secret_id)
        if not existing: raise HTTPException(status_code=404, detail="Secret not found")
        pending = await conn.fetchrow("SELECT id FROM secret_access_requests WHERE secret_id = $1 AND requester_user_id = $2 AND status = 'pending'", secret_id, user.user_id)
        if pending: raise HTTPException(status_code=409, detail="You already have a pending request for this secret")
        row = await conn.fetchrow("INSERT INTO secret_access_requests (secret_id, requester_user_id, requested_level, reason) VALUES ($1, $2, $3, $4) RETURNING id, created_at", secret_id, user.user_id, body.requested_level, body.reason)
        return {"id": row["id"], "status": "pending", "created_at": str(row["created_at"])}
