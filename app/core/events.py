""""Event CRUD routes."""
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict

from app.auth import AuthUser, get_current_user
from app.cache import cache_manager
from app.db import get_pool
from app.models.events import Event, EventCreate, EventPatch

router = APIRouter(prefix="/api/events", tags=["events"])
logger = logging.getLogger(__name__)


class ConsolidatedEvent(BaseModel):
    """Event row with a duplicate count for the last hour (consolidation view)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: str  # ISO string from asyncpg
    source: str
    type: str
    severity: str
    title: str
    body: str | None = None
    metadata: dict = {}
    processed: bool = False
    ticker: bool = False
    tags: list[str] = []
    count: int = 1


def _event_from_row(row) -> "Event":
    """Convert an asyncpg row to an Event, coercing JSONB metadata."""
    d = dict(row)
    meta = d.get("metadata")
    if meta is not None and not isinstance(meta, dict):
        if isinstance(meta, str):
            d["metadata"] = json.loads(meta)
        else:
            d["metadata"] = dict(meta) if meta else {}
    elif meta is None:
        d["metadata"] = {}
    # Ensure tags is a list (asyncpg returns Python list for TEXT[])
    if "tags" not in d:
        d["tags"] = []
    return Event(**d)


def _consolidated_from_row(row) -> "ConsolidatedEvent":
    """Convert an asyncpg row (with `count` column) to a ConsolidatedEvent."""
    d = dict(row)
    meta = d.get("metadata")
    if meta is not None and not isinstance(meta, dict):
        if isinstance(meta, str):
            d["metadata"] = json.loads(meta)
        else:
            d["metadata"] = dict(meta) if meta else {}
    elif meta is None:
        d["metadata"] = {}
    if "tags" not in d:
        d["tags"] = []
    # asyncpg returns timestamp as datetime; serialise to ISO for the response
    if hasattr(d.get("ts"), "isoformat"):
        d["ts"] = d["ts"].isoformat()
    return ConsolidatedEvent(**d)


@router.post("", response_model=Event, status_code=status.HTTP_201_CREATED)
async def create_event(
    event: EventCreate,
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> Event:
    """Create a new event."""
    if user.role not in ("admin", "agent"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO events (source, type, severity, title, body, metadata, ticker, tags)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id, ts, source, type, severity, title, body, metadata, processed, ticker, tags
            """,
            event.source,
            event.type,
            event.severity,
            event.title,
            event.body,
            json.dumps(event.metadata),
            event.ticker,
            event.tags,
        )
        result = _event_from_row(row)

    cache_manager.invalidate("events")

    # Fire notifications reactively (outside the transaction)
    try:
        from modules.notifications.engine import fire_event
        await fire_event({
            "id": result.id,
            "source": result.source,
            "type": result.type,
            "severity": result.severity,
            "title": result.title,
            "body": result.body,
            "tags": result.tags or [],
        })
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"Notification dispatch failed: {e}")

    return result


@router.get("", response_model=list[Event] | list[ConsolidatedEvent])
async def list_events(
    user: Annotated[AuthUser, Depends(get_current_user)],
    source: str | None = Query(default=None, description="Filter by source"),
    severity: str | None = Query(default=None, description="Filter by severity"),
    processed: bool | None = Query(default=None, description="Filter by processed status"),
    ticker: bool | None = Query(default=None, description="Filter by ticker flag"),
    consolidate: bool = Query(
        default=False,
        description="Group similar events (source+title) within the last 1 hour, returning the latest per group + a count.",
    ),
    limit: int = Query(default=50, ge=1, le=500, description="Max results"),
    offset: int = Query(default=0, ge=0, description="Skip first N results"),
) -> list:
    """List events with optional filters and pagination.

    When `consolidate=true`, groups events with the same `source`+`title` within
    the last hour and returns only the most recent row per group with a
    `count` field showing the number of duplicates collapsed.
    """
    pool = get_pool()

    if consolidate:
        async with pool.acquire() as conn:
            conditions = ["ts > now() - interval '1 hour'"]
            params: list = []
            param_idx = 1

            if source is not None:
                conditions.append(f"source = ${param_idx}")
                params.append(source)
                param_idx += 1

            if severity is not None:
                conditions.append(f"severity = ${param_idx}")
                params.append(severity)
                param_idx += 1

            if processed is not None:
                conditions.append(f"processed = ${param_idx}")
                params.append(processed)
                param_idx += 1

            if ticker is not None:
                conditions.append(f"ticker = ${param_idx}")
                params.append(ticker)
                param_idx += 1

            where_clause = "WHERE " + " AND ".join(conditions)

            query = f"""
                SELECT DISTINCT ON (source, title)
                    id, ts, source, type, severity, title, body, metadata, processed, ticker, tags,
                    COUNT(*) OVER (PARTITION BY source, title) AS count
                FROM events
                {where_clause}
                ORDER BY source, title, ts DESC
            """

            rows = await conn.fetch(query, *params)
            return [_consolidated_from_row(row) for row in rows]

    async with pool.acquire() as conn:
        conditions = []
        params = []
        param_idx = 1

        if source is not None:
            conditions.append(f"source = ${param_idx}")
            params.append(source)
            param_idx += 1

        if severity is not None:
            conditions.append(f"severity = ${param_idx}")
            params.append(severity)
            param_idx += 1

        if processed is not None:
            conditions.append(f"processed = ${param_idx}")
            params.append(processed)
            param_idx += 1

        if ticker is not None:
            conditions.append(f"ticker = ${param_idx}")
            params.append(ticker)
            param_idx += 1

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        query = f"""
            SELECT id, ts, source, type, severity, title, body, metadata, processed, ticker, tags
            FROM events
            {where_clause}
            ORDER BY ts DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """
        params.extend([limit, offset])

        rows = await conn.fetch(query, *params)
        return [_event_from_row(row) for row in rows]


@router.patch("/{event_id}", response_model=Event)
async def patch_event(
    event_id: int,
    patch: EventPatch,
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> Event:
    """Patch an event (e.g., mark as processed)."""
    if user.role not in ("admin", "agent"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE events
            SET processed = $1
            WHERE id = $2
            RETURNING id, ts, source, type, severity, title, body, metadata, processed, ticker, tags
            """,
            patch.processed,
            event_id,
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Event {event_id} not found",
            )
        return _event_from_row(row)
