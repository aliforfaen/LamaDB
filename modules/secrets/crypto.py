"""Thin wrappers around pgcrypto for encrypt/decrypt secret values."""
from app.db import get_pool


async def encrypt_value(raw: str) -> bytes:
    pool = get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT pgp_sym_encrypt($1, current_setting('secrets.encryption_key'))",
            raw,
        )


async def encrypt_optional(raw: str | None) -> bytes | None:
    if raw is None or raw == "":
        return None
    return await encrypt_value(raw)


async def reveal_decrypted(secret_id: str, user_id: str) -> str:
    pool = get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT reveal_secret_value($1, $2)",
            secret_id, user_id,
        )


async def decrypt_extra(secret_id: str, extra_column: str) -> str | None:
    if extra_column not in ("encrypted_extra_1", "encrypted_extra_2"):
        return None
    pool = get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            f"SELECT pgp_sym_decrypt({extra_column}, current_setting('secrets.encryption_key')) FROM secrets WHERE id = $1",
            secret_id,
        )
        return val.decode("utf-8") if isinstance(val, bytes) else val
