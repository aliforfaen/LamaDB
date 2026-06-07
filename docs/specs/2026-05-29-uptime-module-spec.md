# LamaDB — Uptime Kuma Module Spec

**Created:** 2026-05-29  
**Phase:** 4 of PoC build  
**Status:** ✅ Implemented & Validated (10/10 tests pass)  
**Completed:** 2026-05-29 by MiniMax-M2.7-highspeed delegation worker  
**Spec version:** 1.0.0

## Context

LamaDB is a self-hosted central data layer (FastAPI + PostgreSQL 16 + pgvector/pg_trgm).  
The skeleton (Phases 1-2) is complete and committed. This spec covers Module 2: Uptime Kuma webhook integration.

**Project root:** `~/LamaFiles/projects/lamadb/`  
**AGENTS.md:** `~/LamaFiles/projects/lamadb/AGENTS.md` (full project guide, read it first)  
**Working skeleton:** `docker compose up` runs PG + API on port 8000. Swagger at `/docs`.

## What This Module Does

Receives Uptime Kuma webhook payloads, stores monitor status history in PostgreSQL, and exposes API endpoints for querying current status and history. Also writes events to the `events` table for the event bus.

### Uptime Kuma Webhook Payload Format

```json
{
  "heartbeat": {
    "status": 0,
    "msg": "connect ECONNREFUSED",
    "duration": 1523,
    "time": "2026-05-29T14:30:00+02:00"
  },
  "monitor": {
    "id": 42,
    "name": "Plex - Media Server",
    "url": "https://plex.notflix.no"
  }
}
```

**Status values:** `0` = DOWN, `1` = UP, `2` = pending, `3` = maintained (degraded)  
**All fields are present and required in the payload.**

## Data Model

Table already exists in `migrations/001_initial.sql`. Do NOT modify it. Schema:

```sql
CREATE TABLE monitor_status (
    id BIGSERIAL PRIMARY KEY,
    monitor_id TEXT NOT NULL,        -- from payload: monitor.id (the Kuma monitor ID as text)
    monitor_name TEXT NOT NULL,      -- from payload: monitor.name
    monitor_url TEXT,                -- from payload: monitor.url
    status INT NOT NULL,             -- from payload: heartbeat.status
    msg TEXT,                        -- from payload: heartbeat.msg
    duration_ms INT,                 -- from payload: heartbeat.duration
    received_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_monitor_received ON monitor_status (received_at DESC);
CREATE INDEX idx_monitor_id ON monitor_status (monitor_id);
```

## Required Deliverables

### 1. `modules/uptime/__init__.py` (update existing stub)

```python
MODULE_NAME = "uptime"
MODULE_DESCRIPTION = "Uptime Kuma webhook receiver and monitor status tracking"
MODULE_VERSION = "0.1.0"
ENABLED = True  # Change from False to True

def get_router():
    from .routes import router
    return router
```

### 2. `modules/uptime/models.py` (new file)

Pydantic models for request validation and API responses.

**Classes needed:**
- `MonitorStatus` — DB row model (output)
- `UptimeWebhookPayload` — validates the incoming webhook JSON
- `CurrentStatus` — latest status per monitor (output)

### 3. `modules/uptime/webhook.py` (new file)

Parse the webhook payload, insert into `monitor_status`, also write to `events` table.

**Logic:**
- Accept `UptimeWebhookPayload`
- INSERT into `monitor_status` (monitor_id, monitor_name, monitor_url, status, msg, duration_ms)
- INSERT into `events` (source='uptime_kuma', type='monitor_status', severity=derived from status, title='{monitor_name} is UP/DOWN', metadata with full payload)
- Severity mapping: status=0 → 'critical', status=1 → 'info', status=2 → 'warn', status=3 → 'warn'

### 4. `modules/uptime/routes.py` (replace stub)

**Endpoints:**

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/uptime/webhook` | None (public) | Receive Kuma webhook |
| GET | `/api/uptime/status` | Bearer (any role) | Current status of all monitors |
| GET | `/api/uptime/history` | Bearer (any role) | Recent status changes (limit 100) |
| GET | `/api/uptime/history/{monitor_id}` | Bearer (any role) | History for a specific monitor |

**GET /api/uptime/status** — uses `DISTINCT ON (monitor_id) ... ORDER BY monitor_id, received_at DESC` to get latest per monitor.

**GET /api/uptime/history** — accepts `?limit=50&offset=0&monitor_id=42` query params.

**POST /api/uptime/webhook** — NO auth dependency. This is called by Uptime Kuma which can't send API keys. Returns `{"received": true}` on success.

### 5. `tests/test_uptime.py` (new file)

**TDD ENFORCED.** Write tests BEFORE implementation code. Test file uses pytest + httpx (or FastAPI TestClient).

**Test cases required:**
1. `test_webhook_creates_monitor_status` — POST valid payload, verify row in monitor_status
2. `test_webhook_creates_event` — POST valid payload, verify event created in events table
3. `test_webhook_down_status_critical_severity` — status=0 → event severity='critical'
4. `test_webhook_up_status_info_severity` — status=1 → event severity='info'
5. `test_get_status_returns_latest_per_monitor` — insert 2 statuses for same monitor, GET /status returns 1 row (latest)
6. `test_get_status_multiple_monitors` — insert 2 monitors, GET /status returns 2 rows
7. `test_get_history_filters_by_monitor_id` — insert 2 monitors, GET /history?monitor_id=X returns only that monitor's entries
8. `test_get_history_pagination` — insert 5 records, GET /history?limit=3 returns 3
9. `test_webhook_no_auth_required` — POST without auth header succeeds (201)
10. `test_status_endpoint_requires_auth` — GET /status without auth returns 401

**Test setup:** Tests use the real database. Run migrations before tests. Use httpx ASGITransport to test the FastAPI app directly (no HTTP server needed).

## Non-Functional Requirements

- **Async throughout** — asyncpg queries, async FastAPI routes
- **No ORM** — raw SQL with asyncpg
- **Type hints** on all public functions
- **Docstrings** on public functions (Google style)
- **Pydantic** for all request/response validation
- **Error handling** — HTTPException with proper status codes
- **No .env modifications needed**

## Existing Code to Reference

- `app/main.py` — how module auto-discovery works (lines 97-121)
- `app/db.py` — get_pool() for DB access
- `app/auth.py` — AuthUser, get_current_user (reference for protected endpoints)
- `app/core/events.py` — pattern for INSERT + RETURNING
- `app/models/events.py` — EventCreate model shape
- `modules/feeds/__init__.py` — module metadata pattern

## Running Tests

```bash
# After docker compose up -d
cd ~/LamaFiles/projects/lamadb
pip install pytest httpx

# Run specific test
pytest tests/test_uptime.py::test_webhook_creates_monitor_status -v

# Run all uptime tests
pytest tests/test_uptime.py -v
```

## Acceptance Criteria

1. `docker compose up -d` starts clean
2. `curl -X POST http://localhost:8000/api/uptime/webhook -H 'Content-Type: application/json' -d '<valid_payload>'` returns `{"received": true}`
3. `curl http://localhost:8000/api/uptime/status -H 'Authorization: Bearer <key>'` returns monitor statuses
4. All 10 tests pass
5. Swagger at `/docs` shows all uptime endpoints
6. Module loads automatically (ENABLED=True in __init__.py)

## Session Log (Crash Recovery)

**Date:** 2026-05-29  
**Session goal:** Build Uptime Kuma module as first LamaDB PoC module.

**Decisions made:**
- Uptime Kuma module built first as PoC test
- All coding delegated to MiniMax-M2.7-highspeed workers
- Spec written as crash-safe artifact
- Skeleton validated before module build
- No Coolify until local PoC is solid

**User preferences:**
- Always delegate coding to MiniMax workers (infinite tokens)
- Write logs for crash recovery
- TDD-style development
- RSS feeds filtered through LLM for summaries (not raw logs)
- Dashboard: framework-based (Vue 3 CDN)
