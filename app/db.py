"""Async PostgreSQL connection pool using asyncpg."""
import asyncpg
from typing import AsyncGenerator
from contextlib import asynccontextmanager

from app.config import settings

# Global connection pool
_pool: asyncpg.Pool | None = None


async def create_pool() -> asyncpg.Pool:
    """Create the asyncpg connection pool."""
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=2,
        max_size=10,
        command_timeout=60,
    )
    return _pool


async def close_pool() -> None:
    """Close the connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    """Get the current connection pool."""
    if _pool is None:
        raise RuntimeError("Database pool not initialized. Call create_pool() first.")
    return _pool


async def get_connection() -> AsyncGenerator[asyncpg.Connection, None]:
    """Dependency that yields a connection from the pool."""
    pool = get_pool()
    async with pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def get_raw_connection():
    """Context manager for getting a raw connection (not as dependency)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        yield conn
