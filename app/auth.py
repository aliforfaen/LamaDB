"""API key authentication with roles and scopes."""
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


def _verify_key(key: str, salt: str, stored_hash: str) -> bool:
    """Verify an API key against a stored bcrypt hash."""
    return bcrypt.checkpw(f"{salt}{key}".encode(), stored_hash.encode())


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> AuthUser:
    """
    Validate the API key from Authorization: Bearer <key>.

    Looks up key hashes in api_keys table, verifies bcrypt hash,
    and returns the user's role and scopes. Admin role bypasses scope checks.
    """
    from app.config import settings
    from app.db import get_pool

    token = credentials.credentials

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, key_hash, role, scopes
            FROM api_keys
            WHERE active = true
            """,
        )

    # Verify token against each key hash
    for row in rows:
        if _verify_key(token, settings.api_key_salt, row["key_hash"]):
            return AuthUser(
                key_id=str(row["id"]),
                name=row["name"],
                role=row["role"],
                scopes=list(row["scopes"]) if row["scopes"] else [],
            )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or inactive API key",
    )


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
