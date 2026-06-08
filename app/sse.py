"""SSE infrastructure for real-time dashboard updates.

Uses PostgreSQL LISTEN/NOTIFY + FastAPI StreamingResponse (Server-Sent Events).
A dedicated asyncpg connection (outside the pool) listens on trigger channels.
"""
import asyncio
import json
import logging
from typing import Callable, Any

logger = logging.getLogger(__name__)


class SSEManager:
    """Manages per-client asyncio.Queues for SSE broadcasting."""

    def __init__(self):
        self._queues: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        """Register a new client. Returns a queue that receives events."""
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Remove a client queue."""
        try:
            self._queues.remove(q)
        except ValueError:
            pass

    async def broadcast(self, data: dict) -> None:
        """Push data to all connected client queues. Drops silently on full queues."""
        for q in self._queues:
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                pass

    @property
    def client_count(self) -> int:
        return len(self._queues)


# Singleton instance
sse_manager = SSEManager()


async def pg_listener(
    dsn: str,
    channels: list[str],
    callback: Callable[[str, str], Any],
) -> None:
    """
    Long-lived asyncpg LISTEN loop on dedicated connection (NOT from pool).

    The pool strips listeners on connection release, so we use a standalone
    connection with an infinite loop.
    """
    import asyncpg

    conn = None
    while True:
        try:
            conn = await asyncpg.connect(dsn)
            logger.info("SSE pg_listener connected, channels=%s", channels)

            for channel in channels:
                await conn.add_listener(channel, callback)

            # Keep alive until connection drops
            while True:
                await asyncio.sleep(30)

        except (asyncio.CancelledError, KeyboardInterrupt):
            logger.info("SSE pg_listener cancelled")
            break
        except Exception as e:
            logger.warning("SSE pg_listener error, reconnecting in 5s: %s", e)
            await asyncio.sleep(5)
        finally:
            if conn is not None:
                try:
                    await conn.close()
                except Exception:
                    pass
                conn = None


def _make_notify_callback():
    """Create the asyncpg notification callback that forwards to sse_manager."""

    def on_notification(connection, pid, channel, payload):
        try:
            data = json.loads(payload) if payload else {}
            event = {
                "channel": channel,
                "data": data,
            }
            # Use call_soon to avoid blocking the asyncpg connection
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(sse_manager.broadcast(event))
            )
        except Exception:
            logger.debug("SSE callback failed for channel=%s", channel, exc_info=True)

    return on_notification
