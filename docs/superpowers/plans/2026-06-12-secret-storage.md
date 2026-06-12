# Secret Storage Module — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Secret Storage module and Groups infrastructure for LamaDB: encrypted credential storage with pgcrypto, per-group/per-user access control, access request workflow, REST API + MCP tools, and full dashboard management UI.

**Architecture:** Two new modules — `groups` (core-ish, owns the groups + user_group_memberships tables) and `secrets` (encrypted storage with pgcrypto, 5 secret types, audit logging). Groups are a first-class LamaDB concept: AuthUser gains a `groups` field, and API key scopes support `group:<name>` filtering. Secrets are encrypted column-level in PostgreSQL; decryption is a SECURITY DEFINER function. Agents discover secrets via MCP (metadata only), request access, and reveal values once granted.

**Tech Stack:** Python 3.12 + FastAPI + asyncpg + pydantic. PostgreSQL 16 + pgcrypto extension. Vanilla JS dashboard (no new libraries).

**Spec:** `docs/superpowers/specs/2026-06-12-secret-storage-design.md`

**Existing migration ceiling:** 016 (dedup_cron.sql). New migrations start at 017.

---

### Task 1: Migration 017 — Groups core infrastructure

**Files:**
- Create: `migrations/017_groups_core.sql`

- [ ] **Step 1: Write the migration file**

```sql
-- 017_groups_core.sql
-- Groups as a first-class LamaDB concept.
-- Creates groups, user_group_memberships tables. Enables pgcrypto (needed by secrets module later).

-- Extension for column-level encryption (used by secrets module, migration 018)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Named collections of users
CREATE TABLE IF NOT EXISTS groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Many-to-many membership with roles
CREATE TABLE IF NOT EXISTS user_group_memberships (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    group_id UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'member',
    added_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (user_id, group_id)
);

-- Index for auth enrichment: fast lookup of groups for a user
CREATE INDEX IF NOT EXISTS idx_ugm_user_id ON user_group_memberships(user_id);

-- Index for listing members of a group
CREATE INDEX IF NOT EXISTS idx_ugm_group_id ON user_group_memberships(group_id);
```

- [ ] **Step 2: Verify migration is picked up by the runner**

```bash
# Check that the file exists and is in the sorted glob
ls -la migrations/017_groups_core.sql
```

- [ ] **Step 3: Commit**

```bash
git add migrations/017_groups_core.sql
git commit -m "feat: migration 017 — groups core infrastructure (groups + user_group_memberships + pgcrypto)"
```

---

### Task 2: Auth enrichment — populate AuthUser.groups

**Files:**
- Modify: `app/auth.py`

- [ ] **Step 1: Add `groups` field to AuthUser**

In `app/auth.py`, modify the `AuthUser` class (line 13-20) to add the `groups` field:

```python
class AuthUser(BaseModel):
    """Authenticated user with role and scopes."""

    key_id: str
    name: str
    role: str
    scopes: list[str]
    user_id: str | None = None  # Linked users.id (None for legacy unlinked keys)
    groups: list[str] = []       # Group names this user belongs to
```

- [ ] **Step 2: Populate `groups` in `_authenticate()`**

In `app/auth.py`, inside `_authenticate()`, after the user_id-based `_touch_last_active` call but BEFORE returning the `AuthUser`, add a group lookup. The best insertion point is right before the `return user` on line 115 (for the fast-path return) and before line 158 (for the fallback return).

Wrap the groups fetch in a helper function at the top of the file (after `_touch_last_active`):

```python
async def _fetch_user_groups(user_id: str) -> list[str]:
    """Fetch group names for a user. Returns empty list if no groups or no user_id."""
    if not user_id:
        return []
    try:
        from app.db import get_pool
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT g.name FROM groups g
                JOIN user_group_memberships ugm ON g.id = ugm.group_id
                WHERE ugm.user_id = $1
                ORDER BY g.name
                """,
                user_id,
            )
            return [r["name"] for r in rows]
    except Exception:
        return []  # Never fail auth because of groups query
```

Then in `_authenticate()`, modify both return points to populate groups. For the fast-path return (around line 110-115):

```python
                user = AuthUser(
                    key_id=str(row["id"]),
                    name=row["name"],
                    role=row["role"],
                    scopes=list(row["scopes"]) if row["scopes"] else [],
                    user_id=str(row["user_id"]) if row["user_id"] else None,
                )
                asyncio.create_task(_touch_last_used(user.key_id))
                if user.user_id:
                    asyncio.create_task(_touch_last_active(user.user_id))
                # Enrich with group membership
                user.groups = await _fetch_user_groups(user.user_id)
                return user
```

Apply the same change on the fallback path (around line 148-158), adding `user.groups = await _fetch_user_groups(user.user_id)` before the return.

- [ ] **Step 3: Commit**

```bash
git add app/auth.py
git commit -m "feat: enrich AuthUser with groups from user_group_memberships"
```

---

### Task 3: Groups module — models + REST routes

**Files:**
- Create: `modules/groups/__init__.py`
- Create: `modules/groups/models.py`
- Create: `modules/groups/routes.py`

- [ ] **Step 1: Write `modules/groups/__init__.py`**

```python
"""Groups module — user group management for LamaDB."""
MODULE_NAME = "groups"
MODULE_DESCRIPTION = "User group management — first-class LamaDB access primitive"
MODULE_VERSION = "0.1.0"
ENABLED = True

def get_router():
    from .routes import router
    return router
```

- [ ] **Step 2: Write `modules/groups/models.py`**

```python
"""Pydantic models for the groups module."""
from pydantic import BaseModel, Field
from typing import Optional


class GroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = ""


class GroupUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    description: Optional[str] = None


class GroupMember(BaseModel):
    user_id: str
    user_name: str
    role: str
    added_at: str


class GroupResponse(BaseModel):
    id: str
    name: str
    description: str
    member_count: int
    created_by: Optional[str] = None
    created_at: str
    updated_at: str


class GroupDetail(GroupResponse):
    members: list[GroupMember] = []


class MemberAdd(BaseModel):
    user_id: str
    role: str = "member"


class MemberUpdate(BaseModel):
    role: str
```

- [ ] **Step 3: Write `modules/groups/routes.py`**

```python
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


def _can_manage_group(user: AuthUser, group_created_by: str | None) -> bool:
    """Admins can manage any group; the group creator can manage their own."""
    if user.role == "admin":
        return True
    if group_created_by and user.user_id == group_created_by:
        return True
    # Group owners (users with 'owner' role in the group) can also manage
    return False


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
        return {
            "id": str(row["id"]),
            "name": row["name"],
            "description": row["description"],
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
```

- [ ] **Step 4: Verify module loads**

```bash
docker compose build api && docker compose up -d api
# Check logs for "Loaded module: groups"
docker logs lamadb_api --tail 5
```

- [ ] **Step 5: Commit**

```bash
git add modules/groups/
git commit -m "feat: groups module — CRUD + member management REST API"
```

---

### Task 4: Migration 018 — Secrets module tables

**Files:**
- Create: `migrations/018_secrets_module.sql`

- [ ] **Step 1: Write the migration**

```sql
-- 018_secrets_module.sql
-- Encrypted secret storage. Depends on pgcrypto (enabled in migration 017).

-- The secret store — values are encrypted BYTEA columns
CREATE TABLE IF NOT EXISTS secrets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    service TEXT NOT NULL,
    description TEXT DEFAULT '',
    secret_type TEXT NOT NULL,
    -- Encrypted value columns
    encrypted_value BYTEA NOT NULL,
    encrypted_extra_1 BYTEA,
    encrypted_extra_2 BYTEA,
    -- Metadata
    priority TEXT NOT NULL DEFAULT 'primary',
    tags TEXT[] DEFAULT '{}',
    owner_user_id UUID REFERENCES users(id),
    owner_group_id UUID REFERENCES groups(id),
    -- Lifecycle
    expires_at TIMESTAMPTZ,
    last_revealed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_secrets_service ON secrets(service);
CREATE INDEX IF NOT EXISTS idx_secrets_type ON secrets(secret_type);
CREATE INDEX IF NOT EXISTS idx_secrets_owner_user ON secrets(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_secrets_owner_group ON secrets(owner_group_id);
CREATE INDEX IF NOT EXISTS idx_secrets_tags ON secrets USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_secrets_expires ON secrets(expires_at) WHERE expires_at IS NOT NULL;

-- Explicit access grants (user or group)
CREATE TABLE IF NOT EXISTS secret_access (
    id BIGSERIAL PRIMARY KEY,
    secret_id UUID NOT NULL REFERENCES secrets(id) ON DELETE CASCADE,
    grantee_type TEXT NOT NULL,
    grantee_id UUID NOT NULL,
    access_level TEXT NOT NULL DEFAULT 'read',
    granted_by UUID REFERENCES users(id),
    granted_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (secret_id, grantee_type, grantee_id)
);
CREATE INDEX IF NOT EXISTS idx_secret_access_secret ON secret_access(secret_id);
CREATE INDEX IF NOT EXISTS idx_secret_access_grantee ON secret_access(grantee_type, grantee_id);

-- Access request workflow
CREATE TABLE IF NOT EXISTS secret_access_requests (
    id BIGSERIAL PRIMARY KEY,
    secret_id UUID NOT NULL REFERENCES secrets(id) ON DELETE CASCADE,
    requester_user_id UUID NOT NULL REFERENCES users(id),
    requested_level TEXT NOT NULL DEFAULT 'read',
    reason TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    reviewed_by UUID REFERENCES users(id),
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_secret_requests_secret ON secret_access_requests(secret_id);
CREATE INDEX IF NOT EXISTS idx_secret_requests_status ON secret_access_requests(status);

-- Audit log
CREATE TABLE IF NOT EXISTS secret_audit_log (
    id BIGSERIAL PRIMARY KEY,
    secret_id UUID NOT NULL REFERENCES secrets(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id),
    action TEXT NOT NULL,
    details TEXT DEFAULT '',
    ip_address TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_secret_audit_secret ON secret_audit_log(secret_id);
CREATE INDEX IF NOT EXISTS idx_secret_audit_user ON secret_audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_secret_audit_created ON secret_audit_log(created_at DESC);

-- ─── Master encryption key (server-side, never leaves PostgreSQL) ──────

DO $$
BEGIN
    IF current_setting('secrets.encryption_key', true) IS NULL THEN
        PERFORM set_config('secrets.encryption_key',
            encode(gen_random_bytes(32), 'hex'), false);
    END IF;
END $$;

-- ─── SECURITY DEFINER function for decryption ──────────────────────────

CREATE OR REPLACE FUNCTION reveal_secret_value(
    p_secret_id UUID,
    p_requesting_user_id UUID
) RETURNS TEXT AS $$
DECLARE
    raw_value TEXT;
BEGIN
    SELECT pgp_sym_decrypt(encrypted_value, current_setting('secrets.encryption_key'))
    INTO raw_value FROM secrets WHERE id = p_secret_id;

    IF raw_value IS NULL THEN
        RAISE EXCEPTION 'Decryption failed for secret %', p_secret_id;
    END IF;

    INSERT INTO secret_audit_log (secret_id, user_id, action, details)
    VALUES (p_secret_id, p_requesting_user_id, 'reveal', 'decrypted via reveal_secret_value()');

    UPDATE secrets SET last_revealed_at = now() WHERE id = p_secret_id;

    RETURN raw_value;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ─── SSE NOTIFY triggers ───────────────────────────────────────────────

CREATE OR REPLACE FUNCTION notify_secret_change() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('secret_updated', json_build_object(
        'id', COALESCE(NEW.id, OLD.id),
        'action', TG_OP
    )::text);
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS secret_notify_trigger ON secrets;
CREATE TRIGGER secret_notify_trigger
    AFTER INSERT OR UPDATE OR DELETE ON secrets
    FOR EACH ROW EXECUTE FUNCTION notify_secret_change();

CREATE OR REPLACE FUNCTION notify_secret_request_change() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('secret_request_updated', json_build_object(
        'id', COALESCE(NEW.id, OLD.id),
        'action', TG_OP
    )::text);
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS secret_request_notify_trigger ON secret_access_requests;
CREATE TRIGGER secret_request_notify_trigger
    AFTER INSERT OR UPDATE ON secret_access_requests
    FOR EACH ROW EXECUTE FUNCTION notify_secret_request_change();
```

- [ ] **Step 2: Commit**

```bash
git add migrations/018_secrets_module.sql
git commit -m "feat: migration 018 — secrets module tables, pgcrypto encryption key, SECURITY DEFINER reveal function, SSE triggers"
```

---

### Task 5: Secrets module — models + crypto

**Files:**
- Create: `modules/secrets/__init__.py`
- Create: `modules/secrets/models.py`
- Create: `modules/secrets/crypto.py`

- [ ] **Step 1: Write `modules/secrets/__init__.py`**

```python
"""Secrets module — encrypted credential storage with access control."""
MODULE_NAME = "secrets"
MODULE_DESCRIPTION = "Encrypted secret, API key, and credential storage for agents"
MODULE_VERSION = "1.0.0"
ENABLED = True

MODULE_MCP_TOOLS = [
    {"name": "list_secrets", "description": "List all secrets visible to you (metadata only — no values). Filter by service, type, tags, accessibility.", "handler": "modules.secrets.mcp:list_secrets"},
    {"name": "get_secret_metadata", "description": "Get full metadata for a specific secret by ID.", "handler": "modules.secrets.mcp:get_secret_metadata"},
    {"name": "reveal_secret", "description": "Decrypt and return a secret value. Requires access grant or ownership. Audit logged.", "handler": "modules.secrets.mcp:reveal_secret"},
    {"name": "request_secret_access", "description": "Request access to a secret you can see but cannot reveal. Provide a reason for the request.", "handler": "modules.secrets.mcp:request_secret_access"},
]

def get_router():
    from .routes import router
    return router
```

- [ ] **Step 2: Write `modules/secrets/models.py`**

```python
"""Pydantic models for the secrets module."""
from pydantic import BaseModel, Field
from typing import Optional


# ─── Create / Update ────────────────────────────────────────────────────

class SecretCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    service: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    secret_type: str = Field(..., pattern="^(api_key|oauth|login|token|custom)$")
    value: str = Field(..., min_length=1)       # primary encrypted field
    extra_1: Optional[str] = None               # client_id / username / extra
    extra_2: Optional[str] = None               # overflow
    priority: str = "primary"
    tags: list[str] = []
    owner_user_id: Optional[str] = None
    owner_group_id: Optional[str] = None
    expires_at: Optional[str] = None            # ISO 8601


class SecretUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    service: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    secret_type: Optional[str] = Field(None, pattern="^(api_key|oauth|login|token|custom)$")
    value: Optional[str] = None                 # re-encrypt if provided
    extra_1: Optional[str] = None
    extra_2: Optional[str] = None
    priority: Optional[str] = None
    tags: Optional[list[str]] = None
    owner_user_id: Optional[str] = None
    owner_group_id: Optional[str] = None
    expires_at: Optional[str] = None


# ─── Responses ──────────────────────────────────────────────────────────

class SecretResponse(BaseModel):
    id: str
    name: str
    service: str
    description: str
    secret_type: str
    priority: str
    tags: list[str]
    owner_user_id: Optional[str] = None
    owner_group_id: Optional[str] = None
    expires_at: Optional[str] = None
    last_revealed_at: Optional[str] = None
    created_at: str
    updated_at: str


class SecretRevealResponse(BaseModel):
    id: str
    value: str
    extra_1: Optional[str] = None
    extra_2: Optional[str] = None
    secret_type: str


class SecretAccessGrant(BaseModel):
    id: int
    secret_id: str
    grantee_type: str
    grantee_id: str
    grantee_name: str = ""
    access_level: str
    granted_by: Optional[str] = None
    granted_at: str


class AccessGrantCreate(BaseModel):
    grantee_type: str = Field(..., pattern="^(user|group)$")
    grantee_id: str
    access_level: str = "read"


class AccessRequestCreate(BaseModel):
    reason: str = ""
    requested_level: str = "read"


class AccessRequestResponse(BaseModel):
    id: int
    secret_id: str
    secret_name: str = ""
    requester_user_id: str
    requester_name: str = ""
    requested_level: str
    reason: str
    status: str
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    created_at: str


class AccessRequestUpdate(BaseModel):
    status: str = Field(..., pattern="^(approved|rejected)$")
```

- [ ] **Step 3: Write `modules/secrets/crypto.py`**

```python
"""Thin wrappers around pgcrypto for encrypt/decrypt secret values."""
from app.db import get_pool


async def encrypt_value(raw: str) -> bytes:
    """Encrypt a plaintext string using the PostgreSQL server-side key.
    
    The value is encrypted INSIDE PostgreSQL — the raw text travels over
    the wire once as a bound parameter, but never appears in logs if
    prepared statements are used. Returns BYTEA suitable for the
    encrypted_* columns.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT pgp_sym_encrypt($1, current_setting('secrets.encryption_key'))",
            raw,
        )


async def encrypt_optional(raw: str | None) -> bytes | None:
    """Encrypt a value if non-None, return None otherwise."""
    if raw is None or raw == "":
        return None
    return await encrypt_value(raw)


async def reveal_decrypted(secret_id: str, user_id: str) -> str:
    """Decrypt a secret's primary value via the SECURITY DEFINER function.
    
    The function handles access audit logging and last_revealed_at update
    internally. Returns the plaintext value or raises if access denied or
    decryption fails.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT reveal_secret_value($1, $2)",
            secret_id, user_id,
        )


async def decrypt_extra(secret_id: str, extra_column: str) -> str | None:
    """Decrypt an extra field (extra_1 or extra_2) for a secret.
    
    This bypasses the SECURITY DEFINER function's audit logging (the main
    reveal_secret_value already logs the reveal). Only call this AFTER
    access has been verified and the primary value has been revealed.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            f"SELECT pgp_sym_decrypt({extra_column}, current_setting('secrets.encryption_key')) FROM secrets WHERE id = $1",
            secret_id,
        )
        return val.decode("utf-8") if isinstance(val, bytes) else val
```

- [ ] **Step 4: Commit**

```bash
git add modules/secrets/__init__.py modules/secrets/models.py modules/secrets/crypto.py
git commit -m "feat: secrets module — models, crypto wrappers, MCP tool declarations"
```

---

### Task 6: Secrets module — access control logic

**Files:**
- Create: `modules/secrets/access.py`

- [ ] **Step 1: Write `modules/secrets/access.py`**

```python
"""Access control logic for the secrets module.

Determines whether a user can reveal (read) or manage (write/delete) a secret.
Uses a three-tier check: ownership (user or group), explicit grants, admin bypass.
"""
from app.auth import AuthUser
from app.db import get_pool


async def can_reveal(secret: dict, auth_user: AuthUser) -> bool:
    """Check if a user can reveal (decrypt and read) a secret's value."""
    # Admin bypass
    if auth_user.role == "admin":
        return True

    user_id = auth_user.user_id

    # Direct user ownership
    if user_id and secret.get("owner_user_id") == user_id:
        return True

    # Group ownership — user must be a member
    owner_group_id = secret.get("owner_group_id")
    if owner_group_id and owner_group_id in (auth_user.groups or []):
        return True

    # Explicit access grant (user-level)
    if user_id:
        pool = get_pool()
        async with pool.acquire() as conn:
            grant = await conn.fetchrow(
                """
                SELECT 1 FROM secret_access
                WHERE secret_id = $1 AND grantee_type = 'user' AND grantee_id = $2
                """,
                secret["id"], user_id,
            )
            if grant:
                return True

    # Explicit access grant (group-level)
    if auth_user.groups:
        pool = get_pool()
        async with pool.acquire() as conn:
            for group_name in auth_user.groups:
                # We need group_id from group_name — groups are referenced by name
                # in the auth model but by UUID in secret_access
                group_id = await _group_name_to_id(conn, group_name)
                if group_id:
                    grant = await conn.fetchrow(
                        """
                        SELECT 1 FROM secret_access
                        WHERE secret_id = $1 AND grantee_type = 'group' AND grantee_id = $2
                        """,
                        secret["id"], group_id,
                    )
                    if grant:
                        return True

    return False


async def can_manage(secret: dict, auth_user: AuthUser) -> bool:
    """Check if a user can edit or delete a secret.
    
    Managers are: admins, the secret's owner, group owners/admins of the
    owning group, or users with explicit read_write grants.
    """
    # Admin bypass
    if auth_user.role == "admin":
        return True

    user_id = auth_user.user_id

    # Direct user ownership
    if user_id and secret.get("owner_user_id") == user_id:
        return True

    # Group ownership with elevated role
    owner_group_id = secret.get("owner_group_id")
    if owner_group_id and user_id:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT role FROM user_group_memberships
                WHERE group_id = $1 AND user_id = $2 AND role IN ('owner', 'admin')
                """,
                owner_group_id, user_id,
            )
            if row:
                return True

    # Explicit read_write grant
    if user_id:
        pool = get_pool()
        async with pool.acquire() as conn:
            grant = await conn.fetchrow(
                """
                SELECT 1 FROM secret_access
                WHERE secret_id = $1 AND grantee_type = 'user'
                  AND grantee_id = $2 AND access_level = 'read_write'
                """,
                secret["id"], user_id,
            )
            if grant:
                return True

    # Explicit read_write grant (group-level)
    if auth_user.groups:
        pool = get_pool()
        async with pool.acquire() as conn:
            for group_name in auth_user.groups:
                group_id = await _group_name_to_id(conn, group_name)
                if group_id:
                    grant = await conn.fetchrow(
                        """
                        SELECT 1 FROM secret_access
                        WHERE secret_id = $1 AND grantee_type = 'group'
                          AND grantee_id = $2 AND access_level = 'read_write'
                        """,
                        secret["id"], group_id,
                    )
                    if grant:
                        return True

    return False


async def _group_name_to_id(conn, group_name: str) -> str | None:
    """Convert a group name to its UUID. Cached per-connection."""
    row = await conn.fetchrow(
        "SELECT id FROM groups WHERE name = $1", group_name
    )
    return str(row["id"]) if row else None


async def grant_access(
    secret_id: str,
    grantee_type: str,
    grantee_id: str,
    access_level: str,
    granted_by: str | None,
) -> None:
    """Insert or update an access grant."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO secret_access (secret_id, grantee_type, grantee_id, access_level, granted_by)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (secret_id, grantee_type, grantee_id)
            DO UPDATE SET access_level = $4, granted_by = $5, granted_at = now()
            """,
            secret_id, grantee_type, grantee_id, access_level, granted_by,
        )


async def revoke_access(grant_id: int) -> None:
    """Delete an access grant by ID."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM secret_access WHERE id = $1", grant_id)


async def log_audit(
    secret_id: str,
    user_id: str | None,
    action: str,
    details: str = "",
    ip_address: str | None = None,
) -> None:
    """Insert an audit log entry."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO secret_audit_log (secret_id, user_id, action, details, ip_address)
            VALUES ($1, $2, $3, $4, $5)
            """,
            secret_id, user_id, action, details, ip_address,
        )
```

- [ ] **Step 2: Commit**

```bash
git add modules/secrets/access.py
git commit -m "feat: secrets access control — can_reveal, can_manage, grant, revoke, audit logging"
```

---

### Task 7: Secrets module — REST routes

**Files:**
- Create: `modules/secrets/routes.py`

- [ ] **Step 1: Write `modules/secrets/routes.py`**

```python
"""Secrets REST API — /api/secrets/*"""
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

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
    """Convert a database row to a secret response dict (no values)."""
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "service": row["service"],
        "description": row["description"] or "",
        "secret_type": row["secret_type"],
        "priority": row["priority"],
        "tags": list(row["tags"]) if row["tags"] else [],
        "owner_user_id": str(row["owner_user_id"]) if row["owner_user_id"] else None,
        "owner_group_id": str(row["owner_group_id"]) if row["owner_group_id"] else None,
        "expires_at": str(row["expires_at"]) if row["expires_at"] else None,
        "last_revealed_at": str(row["last_revealed_at"]) if row["last_revealed_at"] else None,
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def _get_client_ip(request: Request) -> str:
    """Extract client IP from request headers."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ─── POST /api/secrets ──────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_secret(
    body: SecretCreate,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    pool = get_pool()
    encrypted_val = await encrypt_value(body.value)
    encrypted_e1 = await encrypt_optional(body.extra_1)
    encrypted_e2 = await encrypt_optional(body.extra_2)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO secrets (name, service, description, secret_type,
                encrypted_value, encrypted_extra_1, encrypted_extra_2,
                priority, tags, owner_user_id, owner_group_id, expires_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
            RETURNING *
            """,
            body.name, body.service, body.description, body.secret_type,
            encrypted_val, encrypted_e1, encrypted_e2,
            body.priority, body.tags, body.owner_user_id, body.owner_group_id,
            body.expires_at,
        )
        secret_data = _secret_row_to_response(row)

    await log_audit(
        str(row["id"]), user.user_id, "create",
        f"Created secret '{body.name}' (type={body.secret_type}, service={body.service})",
        _get_client_ip(request),
    )
    return secret_data


# ─── GET /api/secrets ───────────────────────────────────────────────────

@router.get("")
async def list_secrets(
    user: AuthUser = Depends(get_current_user),
    service: Optional[str] = Query(None),
    secret_type: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    accessible: bool = Query(False),
    expiring_soon: bool = Query(False),
    expired: bool = Query(False),
    group: Optional[str] = Query(None),
):
    pool = get_pool()
    conditions = []
    args = []
    idx = 1

    if service:
        conditions.append(f"service = ${idx}"); args.append(service); idx += 1
    if secret_type:
        conditions.append(f"secret_type = ${idx}"); args.append(secret_type); idx += 1
    if priority:
        conditions.append(f"priority = ${idx}"); args.append(priority); idx += 1
    if tag:
        conditions.append(f"${idx} = ANY(tags)"); args.append(tag); idx += 1
    if expiring_soon:
        conditions.append(f"expires_at IS NOT NULL AND expires_at <= now() + interval '30 days'")
    if expired:
        conditions.append(f"expires_at IS NOT NULL AND expires_at <= now()")
    if group:
        conditions.append(f"owner_group_id = (SELECT id FROM groups WHERE name = ${idx})")
        args.append(group); idx += 1

    where = " AND ".join(conditions) if conditions else "TRUE"

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM secrets WHERE {where} ORDER BY service, name",
            *args,
        )

    results = []
    for r in rows:
        secret = _secret_row_to_response(r)
        if accessible:
            # Filter: only include secrets the user can reveal
            if await can_reveal(secret, user):
                results.append(secret)
        else:
            results.append(secret)

    return results


# ─── GET /api/secrets/{id} ──────────────────────────────────────────────

@router.get("/{secret_id}")
async def get_secret(
    secret_id: str,
    user: AuthUser = Depends(get_current_user),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM secrets WHERE id = $1", secret_id)
        if not row:
            raise HTTPException(status_code=404, detail="Secret not found")
        return _secret_row_to_response(row)


# ─── PATCH /api/secrets/{id} ────────────────────────────────────────────

@router.patch("/{secret_id}")
async def update_secret(
    secret_id: str,
    body: SecretUpdate,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT * FROM secrets WHERE id = $1", secret_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Secret not found")

        secret_data = _secret_row_to_response(existing)
        if not await can_manage(secret_data, user):
            raise HTTPException(status_code=403, detail="You do not have permission to edit this secret")

        sets = [f"updated_at = now()"]
        args = []
        idx = 1

        for field in ["name", "service", "description", "secret_type", "priority"]:
            val = getattr(body, field, None)
            if val is not None:
                sets.append(f"{field} = ${idx}"); args.append(val); idx += 1

        if body.value is not None:
            sets.append(f"encrypted_value = ${idx}"); args.append(await encrypt_value(body.value)); idx += 1
        if body.extra_1 is not None:
            sets.append(f"encrypted_extra_1 = ${idx}"); args.append(await encrypt_optional(body.extra_1)); idx += 1
        if body.extra_2 is not None:
            sets.append(f"encrypted_extra_2 = ${idx}"); args.append(await encrypt_optional(body.extra_2)); idx += 1
        if body.tags is not None:
            sets.append(f"tags = ${idx}"); args.append(body.tags); idx += 1
        if body.owner_user_id is not None:
            sets.append(f"owner_user_id = ${idx}"); args.append(body.owner_user_id); idx += 1
        if body.owner_group_id is not None:
            sets.append(f"owner_group_id = ${idx}"); args.append(body.owner_group_id); idx += 1
        if body.expires_at is not None:
            sets.append(f"expires_at = ${idx}"); args.append(body.expires_at); idx += 1

        args.append(secret_id)
        row = await conn.fetchrow(
            f"UPDATE secrets SET {', '.join(sets)} WHERE id = ${idx} RETURNING *",
            *args,
        )
        result = _secret_row_to_response(row)

    await log_audit(secret_id, user.user_id, "update", f"Updated secret", _get_client_ip(request))
    return result


# ─── DELETE /api/secrets/{id} ───────────────────────────────────────────

@router.delete("/{secret_id}", status_code=204)
async def delete_secret(
    secret_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT * FROM secrets WHERE id = $1", secret_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Secret not found")

        secret_data = _secret_row_to_response(existing)
        if not await can_manage(secret_data, user):
            raise HTTPException(status_code=403, detail="You do not have permission to delete this secret")

        await conn.execute("DELETE FROM secrets WHERE id = $1", secret_id)

    await log_audit(secret_id, user.user_id, "delete", f"Deleted secret", _get_client_ip(request))


# ─── GET /api/secrets/{id}/reveal ───────────────────────────────────────

@router.get("/{secret_id}/reveal")
async def reveal_secret(
    secret_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT * FROM secrets WHERE id = $1", secret_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Secret not found")

        secret_data = _secret_row_to_response(existing)
        if not await can_reveal(secret_data, user):
            raise HTTPException(status_code=403, detail="You do not have permission to reveal this secret. Use /request to ask for access.")

    # Decrypt primary value via SECURITY DEFINER function (also logs audit + updates last_revealed_at)
    plaintext = await reveal_decrypted(secret_id, user.user_id)

    # Decrypt extras
    extra_1 = await decrypt_extra(secret_id, "encrypted_extra_1")
    extra_2 = await decrypt_extra(secret_id, "encrypted_extra_2")

    return {
        "id": secret_id,
        "value": plaintext,
        "extra_1": extra_1,
        "extra_2": extra_2,
        "secret_type": existing["secret_type"],
    }


# ─── POST /api/secrets/{id}/access ──────────────────────────────────────

@router.post("/{secret_id}/access", status_code=201)
async def create_access_grant(
    secret_id: str,
    body: AccessGrantCreate,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT * FROM secrets WHERE id = $1", secret_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Secret not found")

        secret_data = _secret_row_to_response(existing)
        if not await can_manage(secret_data, user):
            raise HTTPException(status_code=403, detail="You do not have permission to manage access for this secret")

    await grant_access(secret_id, body.grantee_type, body.grantee_id, body.access_level, user.user_id)
    await log_audit(secret_id, user.user_id, "grant",
                    f"Granted {body.access_level} access to {body.grantee_type}:{body.grantee_id}",
                    _get_client_ip(request))
    return {"status": "ok"}


# ─── GET /api/secrets/{id}/access ───────────────────────────────────────

@router.get("/{secret_id}/access")
async def list_access_grants(
    secret_id: str,
    user: AuthUser = Depends(get_current_user),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT * FROM secrets WHERE id = $1", secret_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Secret not found")

        rows = await conn.fetch(
            """
            SELECT sa.*,
              CASE WHEN sa.grantee_type = 'user' THEN u.name
                   WHEN sa.grantee_type = 'group' THEN g.name
              END AS grantee_name
            FROM secret_access sa
            LEFT JOIN users u ON sa.grantee_type = 'user' AND sa.grantee_id = u.id::text
            LEFT JOIN groups g ON sa.grantee_type = 'group' AND sa.grantee_id = g.id::text
            WHERE sa.secret_id = $1
            ORDER BY sa.granted_at DESC
            """,
            secret_id,
        )
        return [
            {
                "id": r["id"],
                "secret_id": str(r["secret_id"]),
                "grantee_type": r["grantee_type"],
                "grantee_id": r["grantee_id"],
                "grantee_name": r["grantee_name"] or "",
                "access_level": r["access_level"],
                "granted_by": str(r["granted_by"]) if r["granted_by"] else None,
                "granted_at": str(r["granted_at"]),
            }
            for r in rows
        ]


# ─── DELETE /api/secrets/{id}/access/{grant_id} ─────────────────────────

@router.delete("/{secret_id}/access/{grant_id}", status_code=204)
async def delete_access_grant(
    secret_id: str,
    grant_id: int,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT * FROM secrets WHERE id = $1", secret_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Secret not found")

        secret_data = _secret_row_to_response(existing)
        if not await can_manage(secret_data, user):
            raise HTTPException(status_code=403, detail="You do not have permission to manage access for this secret")

        await revoke_access(grant_id)

    await log_audit(secret_id, user.user_id, "revoke",
                    f"Revoked access grant #{grant_id}",
                    _get_client_ip(request))


# ─── POST /api/secrets/{id}/request ─────────────────────────────────────

@router.post("/{secret_id}/request", status_code=201)
async def create_access_request(
    secret_id: str,
    body: AccessRequestCreate,
    user: AuthUser = Depends(get_current_user),
):
    if not user.user_id:
        raise HTTPException(status_code=400, detail="User identity required for access requests")

    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT id FROM secrets WHERE id = $1", secret_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Secret not found")

        # Check if already has a pending request
        pending = await conn.fetchrow(
            "SELECT id FROM secret_access_requests WHERE secret_id = $1 AND requester_user_id = $2 AND status = 'pending'",
            secret_id, user.user_id,
        )
        if pending:
            raise HTTPException(status_code=409, detail="You already have a pending request for this secret")

        row = await conn.fetchrow(
            """
            INSERT INTO secret_access_requests (secret_id, requester_user_id, requested_level, reason)
            VALUES ($1, $2, $3, $4)
            RETURNING id, created_at
            """,
            secret_id, user.user_id, body.requested_level, body.reason,
        )
        return {
            "id": row["id"],
            "status": "pending",
            "created_at": str(row["created_at"]),
        }


# ─── GET /api/secrets/requests ──────────────────────────────────────────

@router.get("/requests")
async def list_access_requests(
    user: AuthUser = Depends(get_current_user),
    status_filter: Optional[str] = Query(None, alias="status"),
):
    pool = get_pool()
    conditions = []
    args = []
    idx = 1

    if status_filter:
        conditions.append(f"sar.status = ${idx}"); args.append(status_filter); idx += 1

    where = " AND ".join(conditions) if conditions else "TRUE"

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT sar.*, s.name AS secret_name, u.name AS requester_name
            FROM secret_access_requests sar
            JOIN secrets s ON s.id = sar.secret_id
            JOIN users u ON u.id = sar.requester_user_id
            WHERE {where}
            ORDER BY sar.created_at DESC
            LIMIT 100
            """,
            *args,
        )
        return [
            {
                "id": r["id"],
                "secret_id": str(r["secret_id"]),
                "secret_name": r["secret_name"],
                "requester_user_id": str(r["requester_user_id"]),
                "requester_name": r["requester_name"],
                "requested_level": r["requested_level"],
                "reason": r["reason"] or "",
                "status": r["status"],
                "reviewed_by": str(r["reviewed_by"]) if r["reviewed_by"] else None,
                "reviewed_at": str(r["reviewed_at"]) if r["reviewed_at"] else None,
                "created_at": str(r["created_at"]),
            }
            for r in rows
        ]


# ─── PATCH /api/secrets/requests/{req_id} ───────────────────────────────

@router.patch("/requests/{request_id}")
async def review_access_request(
    request_id: int,
    body: AccessRequestUpdate,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    if user.role not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin role required to review access requests")

    pool = get_pool()
    async with pool.acquire() as conn:
        req = await conn.fetchrow(
            "SELECT * FROM secret_access_requests WHERE id = $1", request_id
        )
        if not req:
            raise HTTPException(status_code=404, detail="Request not found")
        if req["status"] != "pending":
            raise HTTPException(status_code=400, detail=f"Request is already {req['status']}")

        new_status = body.status
        await conn.execute(
            """
            UPDATE secret_access_requests
            SET status = $1, reviewed_by = $2, reviewed_at = now()
            WHERE id = $3
            """,
            new_status, user.user_id, request_id,
        )

        if new_status == "approved":
            await grant_access(
                str(req["secret_id"]), "user", str(req["requester_user_id"]),
                req["requested_level"], user.user_id,
            )

        action = "approve" if new_status == "approved" else "reject"
        await log_audit(
            str(req["secret_id"]), user.user_id, action,
            f"{'Approved' if new_status == 'approved' else 'Rejected'} access request #{request_id} from {req['requester_user_id']}",
            _get_client_ip(request),
        )

    return {"status": new_status}
```

- [ ] **Step 2: Verify module loads**

```bash
docker compose build api && docker compose up -d api
docker logs lamadb_api --tail 5
# Should see: "Loaded module: groups" and "Loaded module: secrets"
```

- [ ] **Step 3: Commit**

```bash
git add modules/secrets/routes.py
git commit -m "feat: secrets REST API — CRUD, reveal, access grants, request workflow (17 endpoints)"
```

---

### Task 8: Secrets module — MCP tools

**Files:**
- Create: `modules/secrets/mcp.py`

- [ ] **Step 1: Write `modules/secrets/mcp.py`**

```python
"""MCP tool handlers for the secrets module."""
from app.auth import AuthUser
from app.db import get_pool
from .crypto import reveal_decrypted, decrypt_extra
from .access import can_reveal


async def list_secrets(args: dict, auth_user: AuthUser) -> list[dict]:
    """List all secrets visible to the agent (metadata only, no values)."""
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
            "id": str(r["id"]),
            "name": r["name"],
            "service": r["service"],
            "secret_type": r["secret_type"],
            "priority": r["priority"],
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
    """Get full metadata for a specific secret by ID."""
    secret_id = args["id"]

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM secrets WHERE id = $1", secret_id
        )
        if not row:
            raise ValueError(f"Secret '{secret_id}' not found")

        secret = {
            "id": str(row["id"]),
            "name": row["name"],
            "service": row["service"],
            "description": row["description"] or "",
            "secret_type": row["secret_type"],
            "priority": row["priority"],
            "tags": list(row["tags"]) if row["tags"] else [],
            "owner_user_id": str(row["owner_user_id"]) if row["owner_user_id"] else None,
            "owner_group_id": str(row["owner_group_id"]) if row["owner_group_id"] else None,
            "expires_at": str(row["expires_at"]) if row["expires_at"] else None,
            "last_revealed_at": str(row["last_revealed_at"]) if row["last_revealed_at"] else None,
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }
        secret["accessible"] = await can_reveal(secret, auth_user)
        return secret


async def reveal_secret(args: dict, auth_user: AuthUser) -> dict:
    """Decrypt and return a secret value. Requires access grant or ownership."""
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
        "id": secret_id,
        "value": value,
        "extra_1": extra_1,
        "extra_2": extra_2,
        "secret_type": row["secret_type"],
    }


async def request_secret_access(args: dict, auth_user: AuthUser) -> dict:
    """Request access to a secret that is visible but not accessible."""
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
            "SELECT id FROM secret_access_requests "
            "WHERE secret_id = $1 AND requester_user_id = $2 AND status = 'pending'",
            secret_id, auth_user.user_id,
        )
        if pending:
            return {"status": "already_pending", "message": f"You already have a pending request for '{existing['name']}'"}

        row = await conn.fetchrow(
            """
            INSERT INTO secret_access_requests (secret_id, requester_user_id, reason)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            secret_id, auth_user.user_id, reason,
        )
        return {
            "status": "pending",
            "request_id": row["id"],
            "message": f"Access request submitted for '{existing['name']}'. An admin will review it.",
        }
```

- [ ] **Step 2: Commit**

```bash
git add modules/secrets/mcp.py
git commit -m "feat: secrets MCP tools — list_secrets, get_secret_metadata, reveal_secret, request_secret_access"
```

---

### Task 9: Dashboard pages — JavaScript

**Files:**
- Create: `static/js/pages/groups.js`
- Create: `static/js/pages/secrets.js`
- Create: `static/js/pages/access_requests.js`

- [ ] **Step 1: Write `static/js/pages/groups.js`**

```javascript
// ─── Groups Management Page ─────────────────────────────────────────────
(function() {
  'use strict';

  function formatDate(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    return d.toLocaleDateString();
  }

  async function loadGroups() {
    var list = document.getElementById('groups-table-body');
    if (!list) return;
    try {
      var groups = await window.api('/api/groups');
      list.innerHTML = '';
      if (!groups.length) {
        list.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--fg-muted);padding:2rem;">No groups yet. Create one above.</td></tr>';
        return;
      }
      groups.forEach(function(g) {
        var tr = document.createElement('tr');
        tr.className = 'clickable-row';
        tr.onclick = function() { showGroupDetail(g.id); };
        tr.innerHTML =
          '<td><strong>' + window.escHtml(g.name) + '</strong></td>' +
          '<td>' + window.escHtml(g.description || '') + '</td>' +
          '<td>' + g.member_count + '</td>' +
          '<td>' + formatDate(g.created_at) + '</td>';
        list.appendChild(tr);
      });
    } catch (e) { console.error('loadGroups:', e); }
  }

  async function showGroupDetail(groupId) {
    var detail = document.getElementById('groups-detail');
    if (!detail) return;
    try {
      var g = await window.api('/api/groups/' + groupId);
      var users = await window.api('/api/users');
      var membersHtml = '';
      if (g.members && g.members.length) {
        g.members.forEach(function(m) {
          membersHtml +=
            '<div class="member-row" style="display:flex;align-items:center;gap:0.5rem;padding:0.35rem 0;border-bottom:1px solid var(--border);">' +
            '<span style="flex:1"><strong>' + window.escHtml(m.user_name) + '</strong></span>' +
            '<span class="badge" style="font-size:0.75rem">' + m.role + '</span>' +
            '<button class="btn btn-sm btn-ghost" onclick="event.stopPropagation();window.removeGroupMember(\'' + groupId + '\',\'' + m.user_id + '\')" title="Remove member" style="color:var(--danger)">&times;</button>' +
            '</div>';
        });
      } else {
        membersHtml = '<p style="color:var(--fg-muted)">No members yet.</p>';
      }

      detail.innerHTML =
        '<div class="detail-header" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;">' +
        '<h3 style="margin:0">' + window.escHtml(g.name) + '</h3>' +
        '<button class="btn btn-sm btn-ghost" onclick="document.getElementById(\'groups-detail\').innerHTML=\'\'">&times;</button>' +
        '</div>' +
        '<p style="color:var(--fg-muted);margin-bottom:1rem;">' + window.escHtml(g.description || 'No description') + '</p>' +
        '<h4 style="margin-bottom:0.5rem">Members (' + (g.members ? g.members.length : 0) + ')</h4>' +
        '<div style="margin-bottom:0.75rem;display:flex;gap:0.5rem">' +
        '<select id="new-member-select" style="flex:1;padding:0.3rem">' +
        '<option value="">Add member...</option>' +
        (users || []).map(function(u) {
          return '<option value="' + u.id + '">' + window.escHtml(u.name) + '</option>';
        }).join('') +
        '</select>' +
        '<select id="new-member-role" style="padding:0.3rem"><option value="member">Member</option><option value="admin">Admin</option><option value="owner">Owner</option></select>' +
        '<button class="btn btn-sm btn-primary" onclick="window.addGroupMember(\'' + groupId + '\')">Add</button>' +
        '</div>' +
        '<div id="group-members-list">' + membersHtml + '</div>' +
        '<div style="margin-top:1rem">' +
        '<button class="btn btn-sm btn-danger" onclick="window.deleteGroup(\'' + groupId + '\')">Delete Group</button>' +
        '</div>';

      window._currentGroupId = groupId;
    } catch (e) { console.error('showGroupDetail:', e); }
  }

  async function createGroup() {
    var name = document.getElementById('new-group-name').value.trim();
    var desc = document.getElementById('new-group-desc').value.trim();
    if (!name) return;
    try {
      await window.api('/api/groups', {
        method: 'POST',
        body: JSON.stringify({ name: name, description: desc })
      });
      document.getElementById('new-group-name').value = '';
      document.getElementById('new-group-desc').value = '';
      loadGroups();
    } catch (e) { window.showError('Failed to create group: ' + e.message); }
  }

  window.addGroupMember = async function(groupId) {
    var userId = document.getElementById('new-member-select').value;
    var role = document.getElementById('new-member-role').value;
    if (!userId) return;
    try {
      await window.api('/api/groups/' + groupId + '/members', {
        method: 'POST',
        body: JSON.stringify({ user_id: userId, role: role })
      });
      showGroupDetail(groupId);
    } catch (e) { window.showError('Failed to add member: ' + e.message); }
  };

  window.removeGroupMember = async function(groupId, userId) {
    if (!confirm('Remove this member?')) return;
    try {
      await window.api('/api/groups/' + groupId + '/members/' + userId, { method: 'DELETE' });
      showGroupDetail(groupId);
    } catch (e) { window.showError('Failed to remove member: ' + e.message); }
  };

  window.deleteGroup = async function(groupId) {
    if (!confirm('Delete this group? This cannot be undone.')) return;
    try {
      await window.api('/api/groups/' + groupId, { method: 'DELETE' });
      document.getElementById('groups-detail').innerHTML = '';
      loadGroups();
    } catch (e) { window.showError('Failed to delete group: ' + e.message); }
  };

  window.loadGroups = loadGroups;
})();
```

- [ ] **Step 2: Write `static/js/pages/secrets.js`**

```javascript
// ─── Secrets Management Page ────────────────────────────────────────────
(function() {
  'use strict';

  var SECRET_TYPES = ['api_key', 'oauth', 'login', 'token', 'custom'];

  function formatDate(iso) { if (!iso) return '—'; var d = new Date(iso); return d.toLocaleDateString(); }

  function statusBadge(expiresAt, lastRevealedAt) {
    if (!expiresAt) return '<span style="color:var(--fg-muted);font-size:0.8rem">—</span>';
    var exp = new Date(expiresAt);
    var now = new Date();
    if (exp < now) return '<span class="badge" style="background:var(--danger);color:#fff">Expired</span>';
    var days = Math.ceil((exp - now) / (1000 * 60 * 60 * 24));
    if (days <= 7) return '<span class="badge" style="background:#f59e0b;color:#000">Expires in ' + days + 'd</span>';
    return '<span style="color:var(--fg-muted);font-size:0.8rem">' + formatDate(expiresAt) + '</span>';
  }

  async function loadSecrets(filters) {
    filters = filters || {};
    var table = document.getElementById('secrets-table-body');
    if (!table) return;
    try {
      var params = [];
      if (filters.service) params.push('service=' + encodeURIComponent(filters.service));
      if (filters.type) params.push('secret_type=' + encodeURIComponent(filters.type));
      if (filters.priority) params.push('priority=' + encodeURIComponent(filters.priority));
      if (filters.tag) params.push('tag=' + encodeURIComponent(filters.tag));
      var qs = params.length ? '?' + params.join('&') : '';
      var secrets = await window.api('/api/secrets' + qs);
      table.innerHTML = '';
      if (!secrets.length) {
        table.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--fg-muted);padding:2rem;">No secrets found.</td></tr>';
        return;
      }
      secrets.forEach(function(s) {
        var tr = document.createElement('tr');
        tr.className = 'clickable-row';
        tr.onclick = function() { showSecretDetail(s.id); };
        tr.innerHTML =
          '<td><strong>' + window.escHtml(s.name) + '</strong></td>' +
          '<td>' + window.escHtml(s.service) + '</td>' +
          '<td><span class="badge" style="font-size:0.75rem">' + s.secret_type + '</span></td>' +
          '<td>' + (s.priority === 'primary' ? '⭐' : s.priority === 'secondary' ? '🔄' : '⬇️') + ' ' + s.priority + '</td>' +
          '<td>' + (s.tags || []).map(function(t) { return '<span class="badge" style="font-size:0.7rem;background:var(--surface-2)">' + window.escHtml(t) + '</span>'; }).join(' ') + '</td>' +
          '<td>' + statusBadge(s.expires_at, s.last_revealed_at) + '</td>' +
          '<td>' + (s.last_revealed_at ? formatDate(s.last_revealed_at) : '<span style="color:var(--fg-muted)">Never used</span>') + '</td>';
        table.appendChild(tr);
      });
    } catch (e) { console.error('loadSecrets:', e); }
  }

  async function showSecretDetail(secretId) {
    var detail = document.getElementById('secrets-detail');
    if (!detail) return;
    try {
      var s = await window.api('/api/secrets/' + secretId);
      var accessGrants = await window.api('/api/secrets/' + secretId + '/access');

      var grantsHtml = '';
      if (accessGrants.length) {
        accessGrants.forEach(function(g) {
          grantsHtml +=
            '<div style="display:flex;align-items:center;gap:0.5rem;padding:0.35rem 0;border-bottom:1px solid var(--border)">' +
            '<span style="flex:1">' + window.escHtml(g.grantee_name || g.grantee_id) + ' <span class="badge" style="font-size:0.7rem">' + g.grantee_type + '</span></span>' +
            '<span class="badge" style="font-size:0.7rem">' + g.access_level + '</span>' +
            '<button class="btn btn-sm btn-ghost" onclick="event.stopPropagation();window.revokeSecretAccess(\'' + secretId + '\',' + g.id + ')" style="color:var(--danger)">&times;</button>' +
            '</div>';
        });
      } else {
        grantsHtml = '<p style="color:var(--fg-muted)">No access grants.</p>';
      }

      detail.innerHTML =
        '<div class="detail-header" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">' +
        '<h3 style="margin:0">' + window.escHtml(s.name) + '</h3>' +
        '<button class="btn btn-sm btn-ghost" onclick="document.getElementById(\'secrets-detail\').innerHTML=\'\'">&times;</button>' +
        '</div>' +
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:0.5rem;margin-bottom:1rem">' +
        '<div><strong>Service:</strong> ' + window.escHtml(s.service) + '</div>' +
        '<div><strong>Type:</strong> ' + s.secret_type + '</div>' +
        '<div><strong>Priority:</strong> ' + s.priority + '</div>' +
        '<div><strong>Expires:</strong> ' + (s.expires_at ? formatDate(s.expires_at) : 'Never') + '</div>' +
        '<div><strong>Last Used:</strong> ' + (s.last_revealed_at ? formatDate(s.last_revealed_at) : 'Never') + '</div>' +
        '<div><strong>Tags:</strong> ' + (s.tags || []).join(', ') + '</div>' +
        '</div>' +
        '<p style="color:var(--fg-muted)">' + window.escHtml(s.description || 'No description') + '</p>' +

        // Reveal section
        '<div style="margin:1rem 0;padding:0.75rem;border:1px solid var(--border);border-radius:var(--radius)">' +
        '<strong>Secret Value</strong>' +
        '<div style="display:flex;gap:0.5rem;margin-top:0.5rem">' +
        '<input type="text" id="reveal-field" readonly style="flex:1;padding:0.4rem;font-family:monospace;font-size:0.85rem;background:var(--surface-1);border:1px solid var(--border);border-radius:4px" value="••••••••••••" />' +
        '<button class="btn btn-sm btn-primary" id="reveal-btn" onclick="window.revealSecretValue(\'' + secretId + '\')">Reveal</button>' +
        '<button class="btn btn-sm" id="copy-btn" onclick="window.copyRevealedSecret()" style="display:none">Copy</button>' +
        '</div>' +
        '<div id="reveal-timer" style="font-size:0.75rem;color:var(--fg-muted);margin-top:0.25rem"></div>' +
        '</div>' +

        // Access grants
        '<h4 style="margin-top:1rem">Access Grants</h4>' +
        '<div style="margin-bottom:0.5rem;display:flex;gap:0.5rem">' +
        '<select id="grant-type-select"><option value="user">User</option><option value="group">Group</option></select>' +
        '<input type="text" id="grant-id-input" placeholder="User/Group ID" style="flex:1;padding:0.3rem">' +
        '<button class="btn btn-sm btn-primary" onclick="window.grantSecretAccess(\'' + secretId + '\')">Grant Access</button>' +
        '</div>' +
        '<div>' + grantsHtml + '</div>' +

        '<div style="margin-top:1.5rem;display:flex;gap:0.5rem">' +
        '<button class="btn btn-sm btn-primary" onclick="window.editSecret(\'' + secretId + '\')">Edit</button>' +
        '<button class="btn btn-sm btn-danger" onclick="window.deleteSecretConfirm(\'' + secretId + '\')">Delete</button>' +
        '</div>';

      window._currentSecretId = secretId;
    } catch (e) { console.error('showSecretDetail:', e); }
  }

  var _revealTimer = null;
  var _revealedValue = '';

  window.revealSecretValue = async function(secretId) {
    try {
      var result = await window.api('/api/secrets/' + secretId + '/reveal');
      _revealedValue = result.value;
      document.getElementById('reveal-field').value = result.value;
      document.getElementById('reveal-btn').style.display = 'none';
      document.getElementById('copy-btn').style.display = 'inline-block';

      var seconds = 30;
      var timerEl = document.getElementById('reveal-timer');
      timerEl.textContent = 'Auto-masking in ' + seconds + 's';
      if (_revealTimer) clearInterval(_revealTimer);
      _revealTimer = setInterval(function() {
        seconds--;
        if (seconds <= 0) {
          clearInterval(_revealTimer);
          document.getElementById('reveal-field').value = '••••••••••••';
          document.getElementById('reveal-btn').style.display = 'inline-block';
          document.getElementById('copy-btn').style.display = 'none';
          timerEl.textContent = '';
          _revealedValue = '';
        } else {
          timerEl.textContent = 'Auto-masking in ' + seconds + 's';
        }
      }, 1000);
    } catch (e) { window.showError('Reveal failed: ' + e.message); }
  };

  window.copyRevealedSecret = function() {
    if (!_revealedValue) return;
    navigator.clipboard.writeText(_revealedValue).then(function() {
      window.showToast('Copied!');
    }).catch(function() {
      window.showError('Copy failed');
    });
  };

  window.revokeSecretAccess = async function(secretId, grantId) {
    if (!confirm('Revoke this access grant?')) return;
    try {
      await window.api('/api/secrets/' + secretId + '/access/' + grantId, { method: 'DELETE' });
      showSecretDetail(secretId);
    } catch (e) { window.showError('Revoke failed: ' + e.message); }
  };

  window.grantSecretAccess = async function(secretId) {
    var type = document.getElementById('grant-type-select').value;
    var id = document.getElementById('grant-id-input').value.trim();
    if (!id) return;
    try {
      await window.api('/api/secrets/' + secretId + '/access', {
        method: 'POST',
        body: JSON.stringify({ grantee_type: type, grantee_id: id, access_level: 'read' })
      });
      showSecretDetail(secretId);
    } catch (e) { window.showError('Grant failed: ' + e.message); }
  };

  window.deleteSecretConfirm = async function(secretId) {
    if (!confirm('Delete this secret? This cannot be undone.')) return;
    try {
      await window.api('/api/secrets/' + secretId, { method: 'DELETE' });
      document.getElementById('secrets-detail').innerHTML = '';
      loadSecrets();
    } catch (e) { window.showError('Delete failed: ' + e.message); }
  };

  window.showNewSecretForm = function() {
    var detail = document.getElementById('secrets-detail');
    if (!detail) return;
    var typeFields = {
      'api_key': '<div class="form-group"><label>API Key</label><input type="text" id="new-secret-value" class="form-input" placeholder="sk-..." required></div>',
      'oauth': '<div class="form-group"><label>Client ID</label><input type="text" id="new-secret-extra1" class="form-input" placeholder="client_..."></div><div class="form-group"><label>Client Secret</label><input type="text" id="new-secret-value" class="form-input" placeholder="secret_..." required></div>',
      'login': '<div class="form-group"><label>Username</label><input type="text" id="new-secret-extra1" class="form-input" placeholder="username"></div><div class="form-group"><label>Password</label><input type="password" id="new-secret-value" class="form-input" required></div>',
      'token': '<div class="form-group"><label>Token</label><input type="text" id="new-secret-value" class="form-input" placeholder="eyJ..." required></div><div class="form-group"><label>Token Type</label><select id="new-secret-extra1" class="form-input"><option>Bearer</option><option>Basic</option><option>Custom</option></select></div>',
      'custom': '<div class="form-group"><label>Value</label><input type="text" id="new-secret-value" class="form-input" required></div><div class="form-group"><label>Extra 1</label><input type="text" id="new-secret-extra1" class="form-input"></div><div class="form-group"><label>Extra 2</label><input type="text" id="new-secret-extra2" class="form-input"></div>'
    };

    function renderFields() {
      var t = document.getElementById('new-secret-type').value;
      document.getElementById('type-fields-container').innerHTML = typeFields[t] || typeFields['custom'];
    }

    detail.innerHTML =
      '<h3>New Secret</h3>' +
      '<div class="form-group"><label>Name</label><input type="text" id="new-secret-name" class="form-input" placeholder="My API Key" required></div>' +
      '<div class="form-group"><label>Service</label><input type="text" id="new-secret-service" class="form-input" placeholder="openai" required></div>' +
      '<div class="form-group"><label>Description</label><input type="text" id="new-secret-desc" class="form-input" placeholder="Optional"></div>' +
      '<div class="form-group"><label>Type</label><select id="new-secret-type" class="form-input" onchange="document.getElementById(\'type-fields-container\').innerHTML = window._secretTypeFields[this.value] || window._secretTypeFields[\'custom\']">' +
      SECRET_TYPES.map(function(t) { return '<option value="' + t + '">' + t + '</option>'; }).join('') +
      '</select></div>' +
      '<div id="type-fields-container">' + typeFields['api_key'] + '</div>' +
      '<div class="form-group"><label>Priority</label><select id="new-secret-priority" class="form-input"><option value="primary">Primary</option><option value="secondary">Secondary</option><option value="fallback">Fallback</option></select></div>' +
      '<div class="form-group"><label>Tags (comma-separated)</label><input type="text" id="new-secret-tags" class="form-input" placeholder="production, paid"></div>' +
      '<div style="display:flex;gap:0.5rem;margin-top:1rem">' +
      '<button class="btn btn-primary" onclick="window.createSecret()">Create</button>' +
      '<button class="btn btn-ghost" onclick="document.getElementById(\'secrets-detail\').innerHTML=\'\'">Cancel</button>' +
      '</div>';

    // Store type fields for the onchange handler
    window._secretTypeFields = typeFields;
  };

  window.createSecret = async function() {
    var name = document.getElementById('new-secret-name').value.trim();
    var service = document.getElementById('new-secret-service').value.trim();
    var desc = document.getElementById('new-secret-desc').value.trim();
    var type = document.getElementById('new-secret-type').value;
    var value = document.getElementById('new-secret-value').value;
    var extra1 = document.getElementById('new-secret-extra1');
    var extra2 = document.getElementById('new-secret-extra2');
    var priority = document.getElementById('new-secret-priority').value;
    var tagsRaw = document.getElementById('new-secret-tags').value;

    if (!name || !service || !value) { window.showError('Name, service, and value are required'); return; }

    var body = {
      name: name, service: service, description: desc,
      secret_type: type, value: value, priority: priority,
      tags: tagsRaw ? tagsRaw.split(',').map(function(t) { return t.trim(); }).filter(Boolean) : [],
      extra_1: extra1 ? extra1.value.trim() || null : null,
      extra_2: extra2 ? extra2.value.trim() || null : null,
    };

    try {
      await window.api('/api/secrets', { method: 'POST', body: JSON.stringify(body) });
      document.getElementById('secrets-detail').innerHTML = '';
      loadSecrets();
    } catch (e) { window.showError('Create failed: ' + e.message); }
  };

  window.loadSecrets = loadSecrets;
})();
```

- [ ] **Step 3: Write `static/js/pages/access_requests.js`**

```javascript
// ─── Access Requests Page ───────────────────────────────────────────────
(function() {
  'use strict';

  function formatDate(iso) { if (!iso) return ''; var d = new Date(iso); return d.toLocaleString(); }

  var currentFilter = 'pending';

  window.loadAccessRequests = async function(filter) {
    if (filter) currentFilter = filter;
    var table = document.getElementById('requests-table-body');
    if (!table) return;

    // Update filter tab styling
    document.querySelectorAll('#requests-filter-bar .filter-tab').forEach(function(el) {
      el.classList.toggle('active', el.dataset.status === currentFilter);
    });

    try {
      var qs = currentFilter ? '?status=' + currentFilter : '';
      var requests = await window.api('/api/secrets/requests' + qs);
      table.innerHTML = '';
      if (!requests.length) {
        table.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--fg-muted);padding:2rem;">No ' + currentFilter + ' requests.</td></tr>';
        return;
      }
      requests.forEach(function(r) {
        var tr = document.createElement('tr');
        var actionsHtml = '';
        if (r.status === 'pending') {
          actionsHtml =
            '<button class="btn btn-sm btn-primary" onclick="event.stopPropagation();window.approveRequest(' + r.id + ')" style="margin-right:0.25rem">Approve</button>' +
            '<button class="btn btn-sm btn-ghost" onclick="event.stopPropagation();window.rejectRequest(' + r.id + ')" style="color:var(--danger)">Reject</button>';
        } else {
          actionsHtml = '<span style="color:var(--fg-muted);font-size:0.8rem">' +
            (r.status === 'approved' ? '✓ Approved' : '✗ Rejected') + '</span>';
        }
        tr.innerHTML =
          '<td><strong>' + window.escHtml(r.requester_name) + '</strong></td>' +
          '<td>' + window.escHtml(r.secret_name) + '</td>' +
          '<td>' + window.escHtml(r.reason || '—') + '</td>' +
          '<td>' + formatDate(r.created_at) + '</td>' +
          '<td><span class="badge" style="font-size:0.75rem;background:' + (r.status === 'pending' ? '#f59e0b' : r.status === 'approved' ? '#10b981' : '#ef4444') + ';color:#fff">' + r.status + '</span></td>' +
          '<td>' + actionsHtml + '</td>';
        table.appendChild(tr);
      });
    } catch (e) { console.error('loadAccessRequests:', e); }
  };

  window.approveRequest = async function(requestId) {
    try {
      await window.api('/api/secrets/requests/' + requestId, {
        method: 'PATCH',
        body: JSON.stringify({ status: 'approved' })
      });
      loadAccessRequests();
    } catch (e) { window.showError('Approve failed: ' + e.message); }
  };

  window.rejectRequest = async function(requestId) {
    try {
      await window.api('/api/secrets/requests/' + requestId, {
        method: 'PATCH',
        body: JSON.stringify({ status: 'rejected' })
      });
      loadAccessRequests();
    } catch (e) { window.showError('Reject failed: ' + e.message); }
  };

  window.loadAccessRequestsPage = function() { loadAccessRequests(); };

  // Initial load
  if (document.getElementById('requests-table-body')) {
    setTimeout(function() { loadAccessRequests(); }, 100);
  }
})();
```

- [ ] **Step 4: Commit**

```bash
git add static/js/pages/groups.js static/js/pages/secrets.js static/js/pages/access_requests.js
git commit -m "feat: dashboard pages — groups management, secrets management, access request queue"
```

---

### Task 10: HTML integration — sidebar, pages, script imports

**Files:**
- Modify: `static/index.html` (sidebar nav + page containers + script imports)

- [ ] **Step 1: Add page containers to index.html**

Find the existing page containers section (search for `id="page-homeassistant"` or similar) in `index.html`. After the last `page-*` div and before the closing `</main>` tag, add the three new page containers:

```html
        <!-- ─── Security ─── -->
        <div id="page-groups" class="page">
          <div class="page-header">
            <h2>Groups</h2>
            <p class="page-subtitle">Manage user groups for access control</p>
          </div>
          <div class="card">
            <div style="display:flex;gap:0.5rem;margin-bottom:1rem">
              <input type="text" id="new-group-name" placeholder="Group name" class="form-input" style="flex:1">
              <input type="text" id="new-group-desc" placeholder="Description" class="form-input" style="flex:2">
              <button class="btn btn-primary" onclick="window.createGroup()">Create Group</button>
            </div>
            <div style="display:grid;grid-template-columns:2fr 1fr;gap:1rem">
              <table class="table">
                <thead><tr><th>Name</th><th>Description</th><th>Members</th><th>Created</th></tr></thead>
                <tbody id="groups-table-body"></tbody>
              </table>
              <div id="groups-detail" class="card" style="background:var(--surface-2)"></div>
            </div>
          </div>
        </div>

        <div id="page-secrets" class="page">
          <div class="page-header">
            <h2>Secrets</h2>
            <p class="page-subtitle">Encrypted credentials, API keys, and logins</p>
          </div>
          <div class="card">
            <div style="display:flex;gap:0.5rem;margin-bottom:1rem;flex-wrap:wrap">
              <button class="btn btn-primary" onclick="window.showNewSecretForm()">+ New Secret</button>
              <input type="text" id="secret-filter-service" placeholder="Filter service..." class="form-input" style="width:150px" onchange="window.loadSecrets({service: this.value})">
              <select id="secret-filter-type" class="form-input" style="width:120px" onchange="window.loadSecrets({type: this.value})">
                <option value="">All types</option>
                <option value="api_key">API Key</option>
                <option value="oauth">OAuth</option>
                <option value="login">Login</option>
                <option value="token">Token</option>
                <option value="custom">Custom</option>
              </select>
            </div>
            <div style="display:grid;grid-template-columns:2fr 1fr;gap:1rem">
              <table class="table">
                <thead><tr><th>Name</th><th>Service</th><th>Type</th><th>Priority</th><th>Tags</th><th>Expires</th><th>Last Used</th></tr></thead>
                <tbody id="secrets-table-body"></tbody>
              </table>
              <div id="secrets-detail" class="card" style="background:var(--surface-2)"></div>
            </div>
          </div>
        </div>

        <div id="page-access-requests" class="page">
          <div class="page-header">
            <h2>Access Requests</h2>
            <p class="page-subtitle">Review and manage secret access requests</p>
          </div>
          <div class="card">
            <div id="requests-filter-bar" style="display:flex;gap:0.5rem;margin-bottom:1rem">
              <button class="btn btn-sm filter-tab active" data-status="pending" onclick="window.loadAccessRequests('pending')">Pending</button>
              <button class="btn btn-sm filter-tab" data-status="approved" onclick="window.loadAccessRequests('approved')">Approved</button>
              <button class="btn btn-sm filter-tab" data-status="rejected" onclick="window.loadAccessRequests('rejected')">Rejected</button>
            </div>
            <table class="table">
              <thead><tr><th>Requester</th><th>Secret</th><th>Reason</th><th>Requested</th><th>Status</th><th>Actions</th></tr></thead>
              <tbody id="requests-table-body"></tbody>
            </table>
          </div>
        </div>
```

- [ ] **Step 2: Add Security sidebar category**

In `index.html`, find the closing `</div>` of the admin sidebar category (around line 197, after the Notifications nav-item). After `</div>` (closing `items-admin`) and `</div>` (closing `sidebar-category admin`), insert the new Security category:

```html
      <!-- ─── Security ─── -->
      <div class="sidebar-category" data-category="security">
        <button class="sidebar-category-header" onclick="window.toggleSidebarCategory('security')">
          <span class="chevron" id="chevron-security">&#9654;</span>
          Security
          <span class="cat-badge" id="badge-security"></span>
        </button>
        <div class="sidebar-category-items" id="items-security">
          <button class="nav-item" data-page="secrets">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
            <span>Secrets</span>
          </button>
          <button class="nav-item" data-page="access-requests">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg>
            <span>Access Requests</span>
          </button>
          <button class="nav-item" data-page="groups">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
            <span>Groups</span>
          </button>
        </div>
      </div>
```

- [ ] **Step 3: Add script imports**

In `index.html`, find the existing script imports near the bottom (after `settings.js` and the other page imports). Add the new scripts:

```html
  <script src="/js/pages/groups.js"></script>
  <script src="/js/pages/secrets.js"></script>
  <script src="/js/pages/access_requests.js"></script>
```

- [ ] **Step 4: Add toast container for copy feedback (if not exists)**

Search for `id="toast-container"` in index.html. If it doesn't exist, add after `<body>`:

```html
  <div id="toast-container" style="position:fixed;bottom:1rem;right:1rem;z-index:9999;display:flex;flex-direction:column;gap:0.5rem"></div>
```

If it already exists, skip this step.

- [ ] **Step 5: Commit**

```bash
git add static/index.html
git commit -m "feat: HTML integration — Security sidebar category, secrets/groups/requests page containers, script imports"
```

---

### Task 11: App.js integration — navigation, page loaders, SSE

**Files:**
- Modify: `static/js/app.js`

- [ ] **Step 1: Add pages and titles entries**

In `app.js`, find the `pages` object (around line 357) and add:

```javascript
    'secrets':    document.getElementById('page-secrets'),
    'access-requests': document.getElementById('page-access-requests'),
    'groups':     document.getElementById('page-groups'),
```

In the `titles` object (around line 376), add:

```javascript
    'secrets': 'Secrets',
    'access-requests': 'Access Requests',
    'groups': 'Groups',
```

- [ ] **Step 2: Add navigation routing**

In the `navigateTo` function (around line 416+), inside the big if/else chain, add:

```javascript
    else if (pageId === 'secrets') window.loadSecrets && window.loadSecrets();
    else if (pageId === 'access-requests') window.loadAccessRequestsPage && window.loadAccessRequestsPage();
    else if (pageId === 'groups') window.loadGroups && window.loadGroups();
```

- [ ] **Step 3: Add SSE callbacks**

In `app.js`, find the SSE callback setup (search for `_sseCallbacks` or `kanban_task_updated`). Add the new channels. If using a centralized callback dispatcher pattern, add:

```javascript
  window._sseCallbacks = window._sseCallbacks || {};
  window._sseCallbacks['secret_updated'] = function(data) {
    if (window._currentPage === 'secrets') window.loadSecrets && window.loadSecrets();
  };
  window._sseCallbacks['secret_request_updated'] = function(data) {
    if (window._currentPage === 'access-requests') window.loadAccessRequests && window.loadAccessRequests();
  };
```

- [ ] **Step 4: Add toast helper (if not exists)**

If `window.showToast` doesn't exist in app.js, add it (before the end of the IIFE):

```javascript
  window.showToast = function(message) {
    var container = document.getElementById('toast-container');
    if (!container) return;
    var toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;
    toast.style.cssText = 'background:var(--surface-2);color:var(--fg);padding:0.5rem 1rem;border-radius:var(--radius);box-shadow:0 2px 8px rgba(0,0,0,0.2);animation:fadeIn 0.2s ease;font-size:0.875rem';
    container.appendChild(toast);
    setTimeout(function() { toast.remove(); }, 2500);
  };
```

- [ ] **Step 5: Commit**

```bash
git add static/js/app.js
git commit -m "feat: app.js — navigation, page loaders, SSE callbacks for secrets/groups/requests"
```

---

### Task 12: SSE channels in main.py + module verification

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: Add SSE channels to pg_listener**

In `app/main.py`, find the `pg_listener` call (line 188-195). The current channels list is:

```python
["event_created", "task_update", "document_created", "monitor_status", "kanban_task_updated"],
```

Add the two new channels:

```python
["event_created", "task_update", "document_created", "monitor_status", "kanban_task_updated", "secret_updated", "secret_request_updated"],
```

- [ ] **Step 2: Build and restart**

```bash
docker compose build api && docker compose up -d api
```

- [ ] **Step 3: Verify everything loads**

```bash
docker logs lamadb_api --tail 20
```

Expected output should include:
- "Running migration: 017_groups_core.sql"
- "Running migration: 018_secrets_module.sql"  
- "Loaded module: groups"
- "Loaded module: secrets"
- SSE listener channels include "secret_updated" and "secret_request_updated"
- MCP server registers 26 tools (22 existing + 4 new)

- [ ] **Step 4: Quick smoke test via Swagger UI**

Visit `http://localhost:8000/docs` and verify:
- `/api/groups` endpoints appear in the docs
- `/api/secrets` endpoints appear in the docs

- [ ] **Step 5: Commit**

```bash
git add app/main.py
git commit -m "feat: add secret_updated and secret_request_updated SSE channels to pg_listener"
```

---

### Task 13: Tests — test_groups.py

**Files:**
- Create: `tests/test_groups.py`

- [ ] **Step 1: Verify test infrastructure exists**

```bash
ls tests/conftest.py tests/test_kanban.py  # Check for patterns
```

Read `tests/conftest.py` for the auth fixture pattern and any test utilities. Assume fixtures like `client` (httpx.AsyncClient), `auth_headers` (admin API key), etc. exist.

- [ ] **Step 2: Write tests**

```python
"""Tests for the groups module."""
import pytest


@pytest.mark.asyncio
async def test_create_group(client, auth_headers):
    """Admin can create a group."""
    resp = await client.post("/api/groups", json={
        "name": "test-group-1",
        "description": "A test group"
    }, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "test-group-1"
    assert data["member_count"] == 0


@pytest.mark.asyncio
async def test_list_groups(client, auth_headers):
    """List groups returns all groups."""
    # Create one first
    await client.post("/api/groups", json={"name": "list-test"}, headers=auth_headers)
    resp = await client.get("/api/groups", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_add_member(client, auth_headers, test_user_id):
    """Add a member to a group."""
    # Create group
    r = await client.post("/api/groups", json={"name": "member-test"}, headers=auth_headers)
    group_id = r.json()["id"]

    # Add member
    resp = await client.post(f"/api/groups/{group_id}/members", json={
        "user_id": test_user_id,
        "role": "member"
    }, headers=auth_headers)
    assert resp.status_code == 201

    # Verify group detail shows member
    detail = await client.get(f"/api/groups/{group_id}", headers=auth_headers)
    assert detail.status_code == 200
    members = detail.json()["members"]
    assert len(members) == 1
    assert members[0]["user_id"] == test_user_id
    assert members[0]["role"] == "member"


@pytest.mark.asyncio
async def test_remove_member(client, auth_headers, test_user_id):
    """Remove a member from a group."""
    r = await client.post("/api/groups", json={"name": "remove-test"}, headers=auth_headers)
    group_id = r.json()["id"]
    await client.post(f"/api/groups/{group_id}/members", json={
        "user_id": test_user_id, "role": "member"
    }, headers=auth_headers)

    resp = await client.delete(f"/api/groups/{group_id}/members/{test_user_id}", headers=auth_headers)
    assert resp.status_code == 204

    detail = await client.get(f"/api/groups/{group_id}", headers=auth_headers)
    assert len(detail.json()["members"]) == 0


@pytest.mark.asyncio
async def test_delete_group(client, auth_headers):
    """Delete a group."""
    r = await client.post("/api/groups", json={"name": "delete-test"}, headers=auth_headers)
    group_id = r.json()["id"]
    resp = await client.delete(f"/api/groups/{group_id}", headers=auth_headers)
    assert resp.status_code == 204
    # Verify it's gone
    r2 = await client.get(f"/api/groups/{group_id}", headers=auth_headers)
    assert r2.status_code == 404
```

- [ ] **Step 3: Run tests**

```bash
docker exec lamadb_api python3 -m pytest tests/test_groups.py -v
```

Expected: All 5 tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_groups.py
git commit -m "test: groups module — CRUD, member add/remove, cascade delete"
```

---

### Task 14: Tests — test_secrets.py

**Files:**
- Create: `tests/test_secrets.py`

- [ ] **Step 1: Write tests**

```python
"""Tests for the secrets module."""
import pytest


SECRET_PAYLOAD = {
    "name": "Test API Key",
    "service": "openai",
    "description": "Test key for CI",
    "secret_type": "api_key",
    "value": "sk-test-key-12345",
    "priority": "primary",
    "tags": ["test", "ci"],
}


@pytest.mark.asyncio
async def test_create_secret_api_key(client, auth_headers):
    """Create an api_key type secret."""
    resp = await client.post("/api/secrets", json=SECRET_PAYLOAD, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Test API Key"
    assert data["service"] == "openai"
    assert data["secret_type"] == "api_key"
    # Value must NOT be in the response
    assert "value" not in data
    assert "encrypted_value" not in data


@pytest.mark.asyncio
async def test_create_secret_oauth(client, auth_headers):
    """Create an oauth type secret with extra fields."""
    resp = await client.post("/api/secrets", json={
        "name": "OAuth App",
        "service": "github",
        "secret_type": "oauth",
        "value": "gh_secret_abc",
        "extra_1": "gh_client_id_123",
    }, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["secret_type"] == "oauth"


@pytest.mark.asyncio
async def test_list_secrets_metadata_only(client, auth_headers):
    """List endpoint returns no values."""
    await client.post("/api/secrets", json=SECRET_PAYLOAD, headers=auth_headers)
    resp = await client.get("/api/secrets", headers=auth_headers)
    assert resp.status_code == 200
    secrets = resp.json()
    assert len(secrets) >= 1
    for s in secrets:
        assert "value" not in s
        assert "encrypted_value" not in s


@pytest.mark.asyncio
async def test_reveal_secret_as_owner(client, auth_headers):
    """Owner can reveal their secret's value."""
    r = await client.post("/api/secrets", json=SECRET_PAYLOAD, headers=auth_headers)
    secret_id = r.json()["id"]

    resp = await client.get(f"/api/secrets/{secret_id}/reveal", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["value"] == "sk-test-key-12345"
    assert data["secret_type"] == "api_key"


@pytest.mark.asyncio
async def test_list_secrets_filter_service(client, auth_headers):
    """Filter secrets by service."""
    await client.post("/api/secrets", json={**SECRET_PAYLOAD, "service": "openai"}, headers=auth_headers)
    await client.post("/api/secrets", json={**SECRET_PAYLOAD, "service": "github", "value": "gh-token"}, headers=auth_headers)

    resp = await client.get("/api/secrets?service=openai", headers=auth_headers)
    secrets = resp.json()
    assert all(s["service"] == "openai" for s in secrets)


@pytest.mark.asyncio
async def test_list_secrets_filter_tags(client, auth_headers):
    """Filter secrets by tag."""
    await client.post("/api/secrets", json={**SECRET_PAYLOAD, "tags": ["production"]}, headers=auth_headers)
    await client.post("/api/secrets", json={**SECRET_PAYLOAD, "tags": ["staging"], "value": "staging-key"}, headers=auth_headers)

    resp = await client.get("/api/secrets?tag=production", headers=auth_headers)
    secrets = resp.json()
    assert all("production" in s["tags"] for s in secrets)


@pytest.mark.asyncio
async def test_update_secret(client, auth_headers):
    """Update secret metadata."""
    r = await client.post("/api/secrets", json=SECRET_PAYLOAD, headers=auth_headers)
    secret_id = r.json()["id"]

    resp = await client.patch(f"/api/secrets/{secret_id}", json={
        "name": "Updated Key Name",
        "priority": "secondary",
    }, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Updated Key Name"
    assert data["priority"] == "secondary"


@pytest.mark.asyncio
async def test_update_secret_re_encrypt(client, auth_headers):
    """Updating the value re-encrypts and the new value is correct."""
    r = await client.post("/api/secrets", json=SECRET_PAYLOAD, headers=auth_headers)
    secret_id = r.json()["id"]

    await client.patch(f"/api/secrets/{secret_id}", json={
        "value": "new-secret-value-xyz"
    }, headers=auth_headers)

    reveal = await client.get(f"/api/secrets/{secret_id}/reveal", headers=auth_headers)
    assert reveal.json()["value"] == "new-secret-value-xyz"


@pytest.mark.asyncio
async def test_delete_secret_cascade(client, auth_headers):
    """Deleting a secret cascades to access, requests, audit log."""
    r = await client.post("/api/secrets", json=SECRET_PAYLOAD, headers=auth_headers)
    secret_id = r.json()["id"]

    # Delete
    resp = await client.delete(f"/api/secrets/{secret_id}", headers=auth_headers)
    assert resp.status_code == 204

    # Verify gone
    r2 = await client.get(f"/api/secrets/{secret_id}", headers=auth_headers)
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_access_request_submit(client, auth_headers, agent_auth_headers):
    """An agent can submit an access request."""
    r = await client.post("/api/secrets", json=SECRET_PAYLOAD, headers=auth_headers)
    secret_id = r.json()["id"]

    resp = await client.post(f"/api/secrets/{secret_id}/request", json={
        "reason": "Need this for building features"
    }, headers=agent_auth_headers)
    assert resp.status_code == 201
    assert resp.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_access_request_approve(client, auth_headers, agent_auth_headers, test_agent_user_id):
    """Admin approves an access request — grant is created."""
    r = await client.post("/api/secrets", json=SECRET_PAYLOAD, headers=auth_headers)
    secret_id = r.json()["id"]

    # Agent requests access
    req = await client.post(f"/api/secrets/{secret_id}/request", json={
        "reason": "Need access"
    }, headers=agent_auth_headers)
    req_id = req.json()["id"]

    # Admin approves
    resp = await client.patch(f"/api/secrets/requests/{req_id}", json={
        "status": "approved"
    }, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"

    # Verify grant was created
    grants = await client.get(f"/api/secrets/{secret_id}/access", headers=auth_headers)
    grant_user_ids = [g["grantee_id"] for g in grants.json()]
    assert test_agent_user_id in grant_user_ids


@pytest.mark.asyncio
async def test_access_request_reject(client, auth_headers, agent_auth_headers):
    """Admin rejects an access request."""
    r = await client.post("/api/secrets", json=SECRET_PAYLOAD, headers=auth_headers)
    secret_id = r.json()["id"]

    req = await client.post(f"/api/secrets/{secret_id}/request", json={
        "reason": "Need access"
    }, headers=agent_auth_headers)
    req_id = req.json()["id"]

    resp = await client.patch(f"/api/secrets/requests/{req_id}", json={
        "status": "rejected"
    }, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_priority_filtering(client, auth_headers):
    """Filter secrets by priority."""
    await client.post("/api/secrets", json={**SECRET_PAYLOAD, "priority": "primary", "value": "key1"}, headers=auth_headers)
    await client.post("/api/secrets", json={**SECRET_PAYLOAD, "priority": "fallback", "value": "key2"}, headers=auth_headers)

    resp = await client.get("/api/secrets?priority=fallback", headers=auth_headers)
    secrets = resp.json()
    assert all(s["priority"] == "fallback" for s in secrets)


@pytest.mark.asyncio
async def test_last_revealed_updated(client, auth_headers):
    """revel_secret updates last_revealed_at."""
    r = await client.post("/api/secrets", json=SECRET_PAYLOAD, headers=auth_headers)
    secret_id = r.json()["id"]

    # Initially null
    detail = await client.get(f"/api/secrets/{secret_id}", headers=auth_headers)
    assert detail.json()["last_revealed_at"] is None

    # Reveal
    await client.get(f"/api/secrets/{secret_id}/reveal", headers=auth_headers)

    # Now populated
    detail2 = await client.get(f"/api/secrets/{secret_id}", headers=auth_headers)
    assert detail2.json()["last_revealed_at"] is not None
```

- [ ] **Step 2: Check conftest for required fixtures**

Before running, verify these fixtures exist in `tests/conftest.py`:

```python
# Expected fixtures:
# - client: httpx.AsyncClient connected to the app
# - auth_headers: dict with Authorization header for admin key
# - agent_auth_headers: dict with Authorization header for agent key
# - test_user_id: str UUID of a test user
# - test_agent_user_id: str UUID of the test agent user
```

If `agent_auth_headers` or `test_agent_user_id` don't exist, add them to `conftest.py` or use the admin headers for those tests (simplify the test to not rely on a separate agent key).

- [ ] **Step 3: Run tests**

```bash
docker exec lamadb_api python3 -m pytest tests/test_secrets.py -v
```

Expected: All 14 tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_secrets.py
git commit -m "test: secrets module — CRUD, reveal, encryption, access requests, filtering, audit"
```

---

## Execution Completed

After all tasks, verify the full test suite:

```bash
docker exec lamadb_api python3 -m pytest tests/test_groups.py tests/test_secrets.py -v
```

And check the dashboard loads correctly:

```bash
curl -s http://localhost:8000/ | head -20
```
