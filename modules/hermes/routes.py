"""Hermes Agent routes — analytics, health, ingest, and cost tracking."""
import json
import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import AuthUser, get_current_user
from app.cache import cached
from app.config import settings
from app.db import get_pool

from .models import (
    AgentHealthSnapshot,
    CostRollup,
    HermesHealth,
    IngestPayload,
    IngestResponse,
)
from .collector import _get_headers, _ensure_session_token

logger = logging.getLogger(__name__)
router = APIRouter(tags=["hermes"])
def _require_auth(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    return user


async def _hermes_get(path: str) -> dict | list | None:
    """GET from Hermes API, return None on error."""
    url = f"{settings.hermes_url.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient() as client:
            await _ensure_session_token(client)
            resp = await client.get(url, headers=_get_headers(), timeout=10)
            if resp.status_code == 200:
                return resp.json()
            return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# GET /api/hermes/health — check Hermes reachability
# ---------------------------------------------------------------------------

@router.get("/health", response_model=HermesHealth)
@cached(ttl_seconds=120, invalidate_tags=["hermes"], key_prefix="hermes_health")
async def check_health(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Check if Hermes is reachable and return basic status."""
    if not settings.hermes_url:
        return HermesHealth(reachable=False, url="", error="HERMES_URL not configured")

    status = await _hermes_get("/api/status")
    if status:
        return HermesHealth(
            reachable=True,
            url=settings.hermes_url,
            version=status.get("version"),
            gateway_running=status.get("gateway_running"),
        )
    return HermesHealth(reachable=False, url=settings.hermes_url, error="Connection failed")


# ---------------------------------------------------------------------------
# GET /api/hermes/status — full Hermes status
# ---------------------------------------------------------------------------

@router.get("/status")
async def get_status(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Return full Hermes status (version, gateway, platforms)."""
    status = await _hermes_get("/api/status")
    if not status:
        return {"error": "Hermes unreachable"}
    return status


# ---------------------------------------------------------------------------
# GET /api/hermes/sessions/stats — aggregate session statistics
# ---------------------------------------------------------------------------

@router.get("/sessions/stats")
@cached(ttl_seconds=120, invalidate_tags=["hermes"], key_prefix="hermes_sessions_stats")
async def get_session_stats(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Return aggregate session + message counts from Hermes."""
    stats = await _hermes_get("/api/sessions/stats")
    if not stats:
        return {"error": "Hermes unreachable"}
    return stats


# ---------------------------------------------------------------------------
# GET /api/hermes/sessions — recent sessions with token usage
# ---------------------------------------------------------------------------

@router.get("/sessions")
async def get_sessions(
    user: Annotated[AuthUser, Depends(_require_auth)],
    limit: int = Query(default=20, ge=1, le=100),
):
    """Return recent Hermes sessions with token and cost data."""
    data = await _hermes_get(f"/api/sessions?limit={limit}")
    if not data:
        return {"error": "Hermes unreachable"}
    return data


# ---------------------------------------------------------------------------
# GET /api/hermes/system — host system stats
# ---------------------------------------------------------------------------

@router.get("/system")
async def get_system_stats(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Return Hermes host system metrics (CPU, memory, disk)."""
    stats = await _hermes_get("/api/system/stats")
    if not stats:
        return {"error": "Hermes unreachable"}
    return stats


# ---------------------------------------------------------------------------
# GET /api/hermes/model — current model info
# ---------------------------------------------------------------------------

@router.get("/model")
async def get_model_info(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Return current model configuration and capabilities."""
    info = await _hermes_get("/api/model/info")
    if not info:
        return {"error": "Hermes unreachable"}
    return info


# ---------------------------------------------------------------------------
# GET /api/hermes/models — available models and providers
# ---------------------------------------------------------------------------

@router.get("/models")
async def get_model_options(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Return all available providers and their models."""
    opts = await _hermes_get("/api/model/options")
    if not opts:
        return {"error": "Hermes unreachable"}
    return opts


# ---------------------------------------------------------------------------
# GET /api/hermes/credentials — credential pool health
# ---------------------------------------------------------------------------

@router.get("/credentials")
async def get_credentials(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Return API key pool status per provider."""
    pool = await _hermes_get("/api/credentials/pool")
    if not pool:
        return {"error": "Hermes unreachable"}
    return pool


# ---------------------------------------------------------------------------
# GET /api/hermes/profiles — agent profiles
# ---------------------------------------------------------------------------

@router.get("/profiles")
async def get_profiles(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Return Hermes agent profiles with skill counts."""
    profiles = await _hermes_get("/api/profiles")
    if not profiles:
        return {"error": "Hermes unreachable"}
    return profiles


# ---------------------------------------------------------------------------
# GET /api/hermes/tools — available toolsets
# ---------------------------------------------------------------------------

@router.get("/tools")
async def get_tools(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Return available toolsets with enabled/configured state."""
    tools = await _hermes_get("/api/tools/toolsets")
    if not tools:
        return {"error": "Hermes unreachable"}
    return tools


# ---------------------------------------------------------------------------
# GET /api/hermes/mcp — MCP server connections
# ---------------------------------------------------------------------------

@router.get("/mcp")
async def get_mcp(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Return MCP server connections."""
    servers = await _hermes_get("/api/mcp/servers")
    if not servers:
        return {"error": "Hermes unreachable"}
    return servers


# ---------------------------------------------------------------------------
# GET /api/hermes/synced — read cached Hermes data from LamaDB
# ---------------------------------------------------------------------------

@router.get("/synced")
async def get_synced(
    user: Annotated[AuthUser, Depends(_require_auth)],
    limit: int = Query(default=20, ge=1, le=100),
):
    """Return Hermes sessions synced into LamaDB documents."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, content, metadata, tags, created_at
            FROM documents
            WHERE source_type = 'hermes_session'
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )

    sessions = []
    for row in rows:
        meta = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]
        sessions.append({
            "id": str(row["id"]),
            "title": row["title"],
            "preview": row["content"],
            "metadata": meta,
            "tags": list(row["tags"]) if row["tags"] else [],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        })

    return {"sessions": sessions, "count": len(sessions)}


# ---------------------------------------------------------------------------
# POST /api/hermes/sync — manual trigger sync
# ---------------------------------------------------------------------------

@router.post("/sync")
async def trigger_sync(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Manually trigger a Hermes data sync."""
    from .collector import collect
    result = await collect()
    return result


# ---------------------------------------------------------------------------
# POST /api/hermes/ingest — push ingest from Hermes lifecycle hooks
# ---------------------------------------------------------------------------

@router.post("/ingest", response_model=IngestResponse)
async def ingest_payload(
    payload: IngestPayload,
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Receive session finalize, LLM call, or health events from Hermes hooks.

    Hermes lifecycle hooks (on_session_finalize, post_llm_call, etc.) call this
    endpoint to push analytics data into LamaDB in near-real-time.
    """
    pool = get_pool()
    event_type = payload.event_type
    data = payload.data
    ts = payload.timestamp

    async with pool.acquire() as conn:
        if event_type == "session_finalize":
            return await _ingest_session_finalize(conn, data, ts)
        elif event_type == "llm_call":
            return await _ingest_llm_call(conn, data, ts)
        elif event_type == "credential_error":
            return await _ingest_credential_error(conn, data, ts)
        elif event_type == "gateway_status":
            return await _ingest_gateway_status(conn, data, ts)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown event_type: {event_type}")


async def _ingest_session_finalize(conn, data: dict, ts: float) -> IngestResponse:
    """Store a finalized session as a rich document + summary event."""
    sid = data.get("id", "")
    if not sid:
        return IngestResponse(accepted=False, detail="Missing session id")

    total_tokens = (
        data.get("input_tokens", 0)
        + data.get("output_tokens", 0)
        + data.get("reasoning_tokens", 0)
    )
    title = data.get("title") or data.get("preview", "")[:80] or f"Hermes session {sid}"

    # Upsert as document
    existing = await conn.fetchval(
        "SELECT id FROM documents WHERE metadata->>'hermes_session_id' = $1", sid
    )
    if existing:
        await conn.execute(
            """
            UPDATE documents SET
                title = $2, content = $3, metadata = $4, tags = $5, updated_at = now()
            WHERE id = $1
            """,
            existing,
            title,
            data.get("preview", ""),
            json.dumps({
                "hermes_session_id": sid,
                "source": data.get("source"),
                "model": data.get("model"),
                "message_count": data.get("message_count", 0),
                "tool_call_count": data.get("tool_call_count", 0),
                "input_tokens": data.get("input_tokens", 0),
                "output_tokens": data.get("output_tokens", 0),
                "cache_read_tokens": data.get("cache_read_tokens", 0),
                "cache_write_tokens": data.get("cache_write_tokens", 0),
                "reasoning_tokens": data.get("reasoning_tokens", 0),
                "total_tokens": total_tokens,
                "api_call_count": data.get("api_call_count", 0),
                "estimated_cost_usd": data.get("estimated_cost_usd"),
                "actual_cost_usd": data.get("actual_cost_usd"),
                "started_at": data.get("started_at"),
                "ended_at": data.get("ended_at"),
                "end_reason": data.get("end_reason"),
            }),
            ["hermes", data.get("source", "unknown")],
        )
        return IngestResponse(accepted=True, doc_id=str(existing), detail="updated")

    row = await conn.fetchrow(
        """
        INSERT INTO documents (source_type, title, content, metadata, tags)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
        """,
        "hermes_session",
        title,
        data.get("preview", ""),
        json.dumps({
            "hermes_session_id": sid,
            "source": data.get("source"),
            "model": data.get("model"),
            "message_count": data.get("message_count", 0),
            "tool_call_count": data.get("tool_call_count", 0),
            "input_tokens": data.get("input_tokens", 0),
            "output_tokens": data.get("output_tokens", 0),
            "cache_read_tokens": data.get("cache_read_tokens", 0),
            "cache_write_tokens": data.get("cache_write_tokens", 0),
            "reasoning_tokens": data.get("reasoning_tokens", 0),
            "total_tokens": total_tokens,
            "api_call_count": data.get("api_call_count", 0),
            "estimated_cost_usd": data.get("estimated_cost_usd"),
            "actual_cost_usd": data.get("actual_cost_usd"),
            "started_at": data.get("started_at"),
            "ended_at": data.get("ended_at"),
            "end_reason": data.get("end_reason"),
        }),
        ["hermes", data.get("source", "unknown")],
    )
    doc_id = str(row["id"])

    # Also create a summary event
    cost_str = f" ${data.get('estimated_cost_usd', 0):.4f}" if data.get("estimated_cost_usd") else ""
    await conn.execute(
        """
        INSERT INTO events (source, type, severity, title, body, metadata, ticker)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        "hermes",
        "hermes.session_end",
        "info",
        f"Hermes session: {title[:80]}",
        f"Model {data.get('model')}, {data.get('message_count', 0)} msgs, "
        f"{total_tokens} tokens{cost_str}",
        json.dumps({
            "session_id": sid,
            "source": data.get("source"),
            "model": data.get("model"),
            "total_tokens": total_tokens,
            "estimated_cost_usd": data.get("estimated_cost_usd"),
        }),
        True,
    )
    return IngestResponse(accepted=True, doc_id=doc_id, detail="created")


async def _ingest_llm_call(conn, data: dict, ts: float) -> IngestResponse:
    """Store a per-LLM-call event (token burn, latency, model)."""
    session_id = data.get("session_id", "unknown")
    model = data.get("model", "unknown")
    tokens = data.get("input_tokens", 0) + data.get("output_tokens", 0)

    row = await conn.fetchrow(
        """
        INSERT INTO events (source, type, severity, title, body, metadata)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        "hermes",
        "hermes.llm_call",
        "info",
        f"LLM call: {model} — {tokens} tokens",
        f"Session {session_id}, latency {data.get('latency_ms', 0)}ms",
        json.dumps(data),
    )
    return IngestResponse(accepted=True, event_id=row["id"])


async def _ingest_credential_error(conn, data: dict, ts: float) -> IngestResponse:
    """Store a credential/key failure event."""
    provider = data.get("provider", "unknown")
    row = await conn.fetchrow(
        """
        INSERT INTO events (source, type, severity, title, body, metadata, ticker, tags)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING id
        """,
        "hermes",
        "hermes.credential_error",
        "error",
        f"Credential failure: {provider}",
        data.get("error", "Unknown credential error"),
        json.dumps(data),
        True,
        ["hermes", "credential", "error"],
    )
    return IngestResponse(accepted=True, event_id=row["id"])


async def _ingest_gateway_status(conn, data: dict, ts: float) -> IngestResponse:
    """Store a gateway status change event."""
    state = data.get("state", "unknown")
    severity = "info" if state == "running" else "error"
    row = await conn.fetchrow(
        """
        INSERT INTO events (source, type, severity, title, body, metadata, ticker)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING id
        """,
        "hermes",
        "hermes.gateway_status",
        severity,
        f"Hermes gateway: {state}",
        f"Platforms: {json.dumps(data.get('platforms', {}))}",
        json.dumps(data),
        severity == "error",
    )
    return IngestResponse(accepted=True, event_id=row["id"])


# ---------------------------------------------------------------------------
# GET /api/hermes/costs — daily cost rollups from stored documents
# ---------------------------------------------------------------------------

@router.get("/costs")
async def get_costs(
    user: Annotated[AuthUser, Depends(_require_auth)],
    days: int = Query(default=7, ge=1, le=90),
):
    """Compute daily cost rollups from synced Hermes session documents."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                date_trunc('day', created_at)::date AS day,
                count(*) AS session_count,
                coalesce(sum((metadata->>'input_tokens')::bigint), 0) AS input_tokens,
                coalesce(sum((metadata->>'output_tokens')::bigint), 0) AS output_tokens,
                coalesce(sum((metadata->>'cache_read_tokens')::bigint), 0) AS cache_read_tokens,
                coalesce(sum((metadata->>'reasoning_tokens')::bigint), 0) AS reasoning_tokens,
                coalesce(sum((metadata->>'estimated_cost_usd')::float), 0) AS total_cost
            FROM documents
            WHERE source_type = 'hermes_session'
              AND created_at > now() - ($1 || ' days')::interval
            GROUP BY day
            ORDER BY day DESC
            """,
            str(days),
        )
        rollups = []
        for row in rows:
            # Per-model breakdown
            model_rows = await conn.fetch(
                """
                SELECT
                    metadata->>'model' AS model,
                    coalesce(sum((metadata->>'estimated_cost_usd')::float), 0) AS cost
                FROM documents
                WHERE source_type = 'hermes_session'
                  AND date_trunc('day', created_at)::date = $1
                GROUP BY metadata->>'model'
                """,
                row["day"],
            )
            by_model = {r["model"]: float(r["cost"]) for r in model_rows if r["model"]}

            rollups.append(CostRollup(
                date=str(row["day"]),
                total_cost_usd=float(row["total_cost"]),
                input_tokens=int(row["input_tokens"]),
                output_tokens=int(row["output_tokens"]),
                cache_read_tokens=int(row["cache_read_tokens"]),
                reasoning_tokens=int(row["reasoning_tokens"]),
                session_count=int(row["session_count"]),
                by_model=by_model,
            ))

    return {"rollups": rollups, "days": days}


# ---------------------------------------------------------------------------
# GET /api/hermes/health — agent health snapshot
# ---------------------------------------------------------------------------

@router.get("/health/snapshot")
async def get_health_snapshot(
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Compute agent health snapshot from stored events."""
    pool = get_pool()
    async with pool.acquire() as conn:
        # Recent errors (last 24h)
        error_count = await conn.fetchval(
            "SELECT count(*) FROM events WHERE source='hermes' AND severity='error' AND ts > now() - interval '24 hours'"
        ) or 0

        # Credential failures
        cred_failures = await conn.fetchval(
            "SELECT count(*) FROM events WHERE source='hermes' AND type='hermes.credential_error' AND ts > now() - interval '24 hours'"
        ) or 0

        # Gateway uptime: % of time gateway was "running" in last 24h
        gateway_events = await conn.fetch(
            "SELECT metadata->>'state' AS state, ts FROM events WHERE source='hermes' AND type='hermes.gateway_status' AND ts > now() - interval '24 hours' ORDER BY ts DESC LIMIT 50"
        )
        if gateway_events:
            running = sum(1 for r in gateway_events if r["state"] == "running")
            gateway_uptime = (running / len(gateway_events)) * 100
        else:
            gateway_uptime = 100.0  # assume up if no events

        # Session stats
        sessions_24h = await conn.fetchval(
            "SELECT count(*) FROM documents WHERE source_type='hermes_session' AND created_at > now() - interval '24 hours'"
        ) or 0

        active = await conn.fetchval(
            "SELECT count(*) FROM documents WHERE source_type='hermes_session' AND metadata->>'end_reason' IS NULL"
        ) or 0

        messages_24h = await conn.fetchval(
            "SELECT coalesce(sum((metadata->>'message_count')::bigint), 0) FROM documents WHERE source_type='hermes_session' AND created_at > now() - interval '24 hours'"
        ) or 0

        # By source
        source_rows = await conn.fetch(
            "SELECT metadata->>'source' AS src, count(*) FROM documents WHERE source_type='hermes_session' AND created_at > now() - interval '24 hours' GROUP BY metadata->>'source'"
        )
        by_source = {r["src"]: int(r["count"]) for r in source_rows if r["src"]}

    return AgentHealthSnapshot(
        gateway_uptime_pct=round(gateway_uptime, 1),
        recent_errors=int(error_count),
        credential_failures=int(cred_failures),
        active_sessions=int(active),
        total_sessions_24h=int(sessions_24h),
        messages_24h=int(messages_24h),
        by_source=by_source,
    )
