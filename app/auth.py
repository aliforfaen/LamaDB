"""API key authentication with roles and scopes."""
import asyncio
import hashlib
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Annotated

security = HTTPBearer()


class AuthUser(BaseModel):
    """Authenticated user with role and scopes."""

    key_id: str
    name: str
    role: str
    scopes: list[str]
    user_id: str | None = None  # Linked users.id (None for legacy unlinked keys)


# ---------------------------------------------------------------------------
# Prefix-hash lookup: O(1) auth instead of O(N) bcrypt scan.
# ---------------------------------------------------------------------------
# We store SHA-256 of the first 16 characters of the raw key. This is NOT
# the secret — bcrypt still verifies the full key. The prefix is just a
# discriminator that lets us look up exactly one row in the DB before
# paying the bcrypt cost. 16 hex chars (64 bits) gives negligible collision
# risk with 81 active keys.
_PREFIX_LEN = 16


def _hash_prefix(token: str) -> str:
    """SHA-256 of the leading characters of an API key."""
    return hashlib.sha256(token[:_PREFIX_LEN].encode()).hexdigest()


async def _verify_key(key: str, salt: str, stored_hash: str) -> bool:
    """Verify an API key against a stored bcrypt hash.

    bcrypt.checkpw() is CPU-bound and synchronous; running it in a thread
    keeps the event loop responsive under concurrent auth checks.
    """
    return await asyncio.to_thread(
        bcrypt.checkpw,
        f"{salt}{key}".encode(),
        stored_hash.encode(),
    )


async def _touch_last_used(key_id: str):
    """Fire-and-forget: update last_used_at on key usage."""
    try:
        from app.db import get_pool
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE api_keys SET last_used_at = now() WHERE id = $1",
                key_id,
            )
    except Exception:
        pass  # Never fail a request because of tracking


async def _touch_last_active(user_id: str):
    """Fire-and-forget: update users.last_active_at on every auth."""
    try:
        from app.db import get_pool
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET last_active_at = now() WHERE id = $1",
                user_id,
            )
    except Exception:
        pass  # Never fail a request because of tracking


async def _authenticate(token: str) -> AuthUser:
    """Core auth logic: O(1) prefix lookup with O(N) fallback.

    Returns the AuthUser on success, raises HTTPException(401) on failure.
    Used by both get_current_user (Bearer) and verify_api_key (raw).
    """
    from app.config import settings
    from app.db import get_pool

    prefix_hash = _hash_prefix(token)

    pool = get_pool()
    async with pool.acquire() as conn:
        # Fast path: O(1) lookup by prefix hash.
        rows = await conn.fetch(
            """
            SELECT id, name, key_hash, role, scopes, user_id
            FROM api_keys
            WHERE key_prefix = $1 AND active = true
            """,
            prefix_hash,
        )

        for row in rows:
            if await _verify_key(token, settings.api_key_salt, row["key_hash"]):
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
                return user

        # Fallback for legacy keys without key_prefix populated.
        # On successful match, backfill the prefix so the next auth is O(1).
        # Skip the scan entirely if no legacy keys remain (uses partial index).
        legacy_count = await conn.fetchval(
            """
            SELECT 1 FROM api_keys
            WHERE (key_prefix IS NULL OR key_prefix = '') AND active = true
            LIMIT 1
            """,
        )
        if not legacy_count:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or inactive API key",
            )

        rows = await conn.fetch(
            """
            SELECT id, name, key_hash, role, scopes, user_id
            FROM api_keys
            WHERE (key_prefix IS NULL OR key_prefix = '') AND active = true
            """,
        )

        for row in rows:
            if await _verify_key(token, settings.api_key_salt, row["key_hash"]):
                await conn.execute(
                    "UPDATE api_keys SET key_prefix = $1 WHERE id = $2",
                    prefix_hash,
                    row["id"],
                )
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
                return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or inactive API key",
    )


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> AuthUser:
    """
    Validate the API key from Authorization: Bearer <key>.

    Uses O(1) prefix-hash lookup before the single bcrypt verification.
    Falls back to a linear scan over keys with no prefix for backward
    compatibility with keys created before the prefix column existed.
    """
    return await _authenticate(credentials.credentials)


async def verify_api_key(key: str) -> AuthUser | None:
    """
    Verify a raw API key against the database. Returns the AuthUser or None.

    Used for auth mechanisms that can't use Bearer headers (e.g. SSE via
    query param). Returns None on failure (doesn't raise) so callers can
    decide how to respond.
    """
    try:
        return await _authenticate(key)
    except HTTPException:
        return None


def require_scope(scope: str):
    """
    Dependency factory: require a specific scope.

    Admin role bypasses scope requirements.
    """
    async def scope_checker(
        user: Annotated[AuthUser, Depends(get_current_user)],
    ) -> AuthUser:
        if user.role == "admin":
            return user
        if scope not in user.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Scope '{scope}' required",
            )
        return user
    return scope_checker
