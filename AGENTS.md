# LamaDB — Agent Coding Guide

## What This Is

LamaDB is a self-hosted central data layer / Life OS. It stores documents, events, and relationships in PostgreSQL, exposes a FastAPI REST API, and serves RSS feeds generated from its data.

**Current phase: Phase 12 — Home Assistant Module + Bugfix Sprint.** 14 modules. ~67 commits, 263+ tests. New Home Assistant module: polls entity states every 5m, exposes REST API for status/config/service calls, dashboard page with entity cards grouped by domain, On/Off/Activate buttons for lights/switches/scenes. Bugfix sprint: fixed 7 frontend issues (Agent Board DOM ID mismatch, Ntfy conditional routing, Feeds placeholder flash, Overview flex-wrap CSS, Kanban delete UI + cleanup script), added 3s connect timeouts to Hermes/Dozzle for graceful degradation, switched to Tailscale IPs for Docker reachability, fixed Dozzle v10 grouped message parsing. Kanban boards with agent task orchestration (backported from LlamaBan), user identity profiles with API key management, MCP server (22 JSON-RPC tools), agent mailboxes (inbox/sent/thread/read), caching layer (in-memory, TTL + tag invalidation), per-module settings (settings.json overlay + dashboard forms), dashboard admin expansion (sidebar categories, document management table, module health, mobile responsive, theme toggle, command palette).

Hermes Agent integration live — polls session stats, token usage, system health, and gateway status from Hermes API (v0.16.0). Dashboard tab shows health, system metrics, session stats, and recent sessions table. Ingest pipeline for push-based lifecycle hooks. MCP server exposes LamaDB as callable tools for AI agents.

## Context
When a user asks about this project, a "llm-wiki" is kept for it in the folder `~/Basecamp/wiki/projects/lamadb/`. Read files in this folder if any context is needed. And keep them up to date with work and plans.

## Architecture

```
FastAPI app (app/main.py)
  ├── Core: documents, document_links, events tables
  ├── Module auto-discovery from modules/ directory
  ├── Users: identity profiles (api_keys.user_id → users table)
  ├── Role-based API key auth
  ├── SSE / WebSocket real-time
  └── PostgreSQL connection pool

Docker Compose
  ├── PostgreSQL 16 + pgvector + pg_trgm
  └── FastAPI app (Python 3.12)
```

## Tech Stack

- **Python 3.12** (Docker container)
- **FastAPI** + **uvicorn** (ASGI server)
- **asyncpg** (PostgreSQL async driver)
- **feedgen** (RSS/Atom XML generation)
- **pydantic** (data validation, comes with FastAPI)
- **PostgreSQL 16** with extensions: pgvector, pg_trgm

## Directory Structure

```
lamadb/
├── AGENTS.md              # This file
├── README.md              # Project overview
├── docker-compose.yml     # PostgreSQL + API server
├── Dockerfile             # Python 3.12 + app
├── requirements.txt       # Python dependencies
├── app/
│   ├── __init__.py
│   ├── main.py            # FastAPI app, module discovery, lifespan
│   ├── config.py          # Settings from env vars
│   ├── db.py              # asyncpg connection pool
│   ├── auth.py            # API key auth with roles (includes verify_api_key for SSE)
│   ├── cache.py           # In-memory TTL cache with tag invalidation
│   │   ├── embeddings.py      # Sentence-transformers (all-MiniLM-L6-v2, 384d)
│   ├── sse.py             # SSE infrastructure (SSEManager + pg_listener)
│   ├── mcp_server.py      # MCP JSON-RPC 2.0 handler
│   ├── mcp_registry.py    # Auto-discovers MCP tools from modules
│   ├── models/
│   │   ├── __init__.py
│   │   ├── documents.py   # Document + Link models
│   │   └── events.py      # Event model
│   └── core/
│       ├── __init__.py
│       ├── documents.py   # Document CRUD routes (/api/documents)
│       ├── events.py      # Event CRUD routes (/api/events)
│       ├── search.py      # Search routes (/api/search + /embeddings/backfill)
│       ├── dashboard.py   # Dashboard API + module health
│       ├── users.py       # User management endpoints
│       └── mcp.py         # Core MCP tools
├── modules/
│   ├── __init__.py        # Module registry
│   ├── feeds/             # RSS feed generator
│   │   ├── __init__.py
│   │   ├── routes.py      # /api/feeds/* + /feeds/{slug}.xml
│   │   ├── models.py
│   │   └── generator.py   # RSS XML generation
│   ├── uptime/            # Uptime Kuma webhook + registry poller
│   │   ├── __init__.py
│   │   ├── routes.py      # /api/uptime/*
│   │   ├── models.py
│   │   ├── webhook.py     # Webhook payload handler
│   │   ├── poller.py      # Registry poller (every 1h)
│   │   └── topology.py    # Host-zone topology grouping
│   ├── dashboard/         # Management dashboard
│   │   ├── __init__.py
│   │   └── routes.py      # Serves static files
│   ├── agent_board/       # Task queue + agent messaging
│   │   ├── __init__.py
│   │   ├── routes.py      # /api/agent_board/*
│   │   └── models.py
│   ├── kanban/            # Kanban boards with agent orchestration
│   │   ├── __init__.py    # MODULE_MCP_TOOLS (11 tools)
│   │   ├── routes.py      # /api/kanban/* (30 endpoints)
│   │   ├── models.py      # Pydantic models (29 classes)
│   │   └── mcp.py         # Agent-first MCP tools
│   ├── freshrss/          # FreshRSS feed scraper
│   │   ├── __init__.py
│   │   ├── routes.py
│   │   ├── models.py
│   │   └── collector.py   # Background poller (every 15m)
│   ├── ntfy/              # ntfy notification scraper
│   │   ├── __init__.py
│   │   ├── routes.py
│   │   ├── models.py
│   │   └── collector.py   # Background poller (every 5m)
│   ├── dozzle/            # Docker log scraper
│   │   ├── __init__.py
│   │   ├── routes.py
│   │   ├── models.py
│   │   ├── webhook.py
│   │   └── collector.py   # Background poller (every 5m)
│   ├── wiki/              # Wiki reader + CouchDB LiveSync collector
│   │   ├── __init__.py
│   │   ├── routes.py      # /api/wiki/*
│   │   ├── models.py
│   │   ├── wiki_db.py
│   │   ├── wiki_reader.py
│   │   ├── scratchpad.py
│   │   ├── couchdb_crypto.py  # LiveSync HKDF/AES-GCM decryption
│   │   ├── couchdb_client.py  # CouchDB HTTP client (Basic auth)
│   │   └── collector.py       # LiveSync _changes feed watcher + upsert
│   ├── hermes/            # Hermes Agent analytics
│   │   ├── __init__.py
│   │   ├── routes.py      # /api/hermes/*
│   │   ├── models.py
│   │   └── collector.py   # Background poller (every 5m)
│   ├── notflix/            # Sonarr/Radarr/Tautulli status
│   │   ├── __init__.py
│   │   ├── routes.py
│   │   ├── models.py
│   │   └── collector.py   # Background poller (every 30m)
│   └── notifications/     # Smart notification routing
│       ├── __init__.py
│       ├── routes.py
│       ├── models.py
│       └── engine.py
├── static/                # Dashboard frontend
│   ├── index.html
│   ├── css/
│   └── js/
├── migrations/
│   ├── 001_initial.sql    # Core tables + extensions
│   ├── 002_ticker.sql     # Ticker event support
│   ├── 002_wiki_scratchpad_seed.sql
│   ├── 003_uptime_tags.sql
│   ├── 003_freshrss.sql
│   ├── 004_agent_board.sql # Task queue + LISTEN/NOTIFY
│   ├── 005_monitor_registry.sql
│   ├── 006_notification_rules.sql
│   ├── 007_embedding_hnsw.sql # HNSW index for vector search
│   ├── 008_event_notify.sql  # NOTIFY triggers for SSE
│   ├── 009_api_key_last_used.sql
│   ├── 010_agent_mailboxes.sql
│   ├── 011_user_layouts.sql
│   ├── 012_dashboard_notify_triggers.sql
│   ├── 013_api_key_prefix.sql
│   ├── 014_kanban_core.sql   # Users + 7 kanban tables + NOTIFY triggers
│   ├── 015_user_theme.sql
│   ├── 016_dedup_cron.sql
│   ├── 017_groups_core.sql
│   ├── 018_secrets_module.sql
│   ├── 019_kanban_task_metadata.sql
│   ├── 019_migration_history.sql
│   ├── 020_local_embeddings_384.sql  # vector(1536)→vector(384), drop+recreate HNSW
│   └── 021_wiki_sync_state.sql       # Wiki collector CouchDB _changes seq tracker
├── benchmarks/
│   └── bench_all_endpoints.py
├── tests/
└── deploy/
    └── coolify.md         # Coolify deployment notes
```

## Data Model

### Core Tables (migrations/001_initial.sql)

```sql
-- Extensions
CREATE EXTENSION IF NOT EXISTS pgvector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Universal document store
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    metadata JSONB DEFAULT '{}',
    tags TEXT[] DEFAULT '{}',
    embedding vector(1536),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_documents_tags ON documents USING GIN (tags);
CREATE INDEX idx_documents_source_type ON documents (source_type);
CREATE INDEX idx_documents_created ON documents (created_at DESC);

-- Typed relationships between documents
CREATE TABLE document_links (
    id BIGSERIAL PRIMARY KEY,
    source_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    target_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    link_type TEXT NOT NULL,
    context TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Event bus (replaces events.jsonl)
CREATE TABLE events (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ DEFAULT now(),
    source TEXT NOT NULL,
    type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    title TEXT NOT NULL,
    body TEXT,
    metadata JSONB DEFAULT '{}',
    processed BOOLEAN DEFAULT false
);

-- Feeds (module: feeds)
CREATE TABLE feeds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    description TEXT,
    filter_tags TEXT[] DEFAULT '{}',
    filter_source_types TEXT[] DEFAULT '{}',
    max_items INT DEFAULT 50,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Monitor status (module: uptime)
CREATE TABLE monitor_status (
    id BIGSERIAL PRIMARY KEY,
    monitor_id TEXT NOT NULL,
    monitor_name TEXT NOT NULL,
    monitor_url TEXT,
    status INT NOT NULL,
    msg TEXT,
    duration_ms INT,
    received_at TIMESTAMPTZ DEFAULT now()
);
```

### User Identity Tables (migration 014)

```sql
-- User profiles (sits alongside api_keys)
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL DEFAULT 'agent',  -- 'human' | 'agent'
    status TEXT NOT NULL DEFAULT 'active',
    instructions TEXT,                    -- per-agent onboarding
    last_active_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- api_keys gets user_id FK for attribution
ALTER TABLE api_keys ADD COLUMN user_id UUID REFERENCES users(id);
```

### Kanban Tables (migration 014)

```sql
kanban_boards      — type: agentic|personal, owner_id → users
kanban_columns     — status: backlog|in_progress|review|done
kanban_tasks        — task_number (per-board), priority, assignee, help_wanted, deps
kanban_subtasks     — per-task checklist
kanban_task_dependencies — auto-start dependents on completion
kanban_comments     — user-attributed task discussion
kanban_agent_logs   — action audit trail (task_claimed, task_completed, etc.)
```

### API Key Table

```sql
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    key_prefix TEXT NOT NULL,     -- SHA-256 of first 16 chars for O(1) lookup
    role TEXT NOT NULL DEFAULT 'read',
    scopes TEXT[] DEFAULT '{}',
    active BOOLEAN DEFAULT true,
    user_id UUID REFERENCES users(id),
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

## Auth Model

Role-based API keys. Three roles:

| Role | Access | Example |
|------|--------|---------|
| `admin` | Full read/write on all modules + core | Muninn |
| `agent` | Read/write on scoped modules + events | Worker agents |
| `read` | Read-only on public endpoints | Dashboards, external |

API key sent via `Authorization: Bearer <key>` header. Keys stored as bcrypt hashes. O(1) prefix hash lookup (migration 013).

Scopes are module names: `['kanban', 'feeds', 'uptime', 'documents']`. Empty scopes = access to nothing (must be explicitly granted). Admin role ignores scopes.

AuthUser populates `user_id` from `api_keys.user_id`, enabling per-user identity for task assignment, agent attribution, and profile lookups.

## Module Pattern

Each module is a self-contained package in `modules/`:

```python
# modules/feeds/__init__.py
MODULE_NAME = "feeds"
MODULE_DESCRIPTION = "RSS feed generator from LamaDB documents"
MODULE_VERSION = "0.1.0"
ENABLED = True

def get_router():
    from .routes import router
    return router
```

Module discovery in `app/main.py`:
1. Scan `modules/` for subdirectories with `__init__.py`
2. Check `ENABLED` flag
3. Call `get_router()` to get the FastAPI router
4. Include router with prefix `/api/{module_name}`

Modules can define their own database tables. Migration files for modules go in `migrations/` with the module name prefix.

MCP tools are declared via `MODULE_MCP_TOOLS` list in `__init__.py` and auto-registered by `app/mcp_registry.py`.

## Development Workflow

**This is a for-fun learning project. Keep it simple.**

```bash
# Start
docker compose up -d

# Develop — edit code, then rebuild
docker compose build api && docker compose restart api

# Test — use Swagger UI
# Open http://localhost:8000/docs in browser

# Run a specific test (only when needed)
docker exec lamadb_api python3 -m pytest tests/test_feeds.py -q

# Check logs
docker logs lamadb_api --tail 20
```

**Don't:** Run the full test suite after every change. Don't build elaborate test infrastructure. Don't spend more time testing than building.

**Do:** Use Swagger UI (`/docs`) for manual testing. Write a test only when verifying something complex. Keep the fun ratio high.

## What to Build — Completed Phases

### Phase 1: Skeleton ✅ (2026-05-29)
- [x] docker-compose.yml, Dockerfile, requirements.txt
- [x] app/main.py — FastAPI + module auto-discovery + CORS
- [x] app/config.py, app/db.py, app/auth.py
- [x] migrations/001_initial.sql — all core tables
- [x] Health endpoint, auto-run migrations

### Phase 2: Core Endpoints ✅ (2026-05-29)
- [x] Documents CRUD, Events CRUD, Search (pg_trgm)

### Phase 3: Feeds Module ✅ (2026-05-29)
- [x] RSS XML generator, feed CRUD, public endpoints

### Phase 4: Uptime Module ✅ (2026-05-29)
- [x] Webhook receiver, registry poller, topology host map

### Phase 5: Dashboard + Config ✅ (2026-05-29)
- [x] Backend API (8 endpoints), frontend wiring, settings page

### Phase 6: Core Enhancements ✅ (2026-06-07)
- [x] Semantic search (pgvector), document graph traversal, Hermes dashboard

### Phase 7: Embeddings, FreshRSS, SSE ✅ (2026-06-07)
- [x] OpenAI embeddings, HNSW index, SSE real-time events, migration runner fix

### Phase 8: Dashboard Polish & Test Suite Rebuild ✅ (2026-06-08)
- [x] Document detail modal, uptime sparklines, SSE bugfixes, 14 new tests

### Phase 9: Platform Maturity ✅ (2026-06-08)
- [x] Caching layer, MCP server (12 tools), agent mailboxes, per-module settings
- [x] Dashboard admin expansion, user layout persistence, performance hardening
- [x] CPU saturation fixed (101% → 0.09%), O(1) auth lookup

### Phase 10: Kanban Module ✅ (2026-06-10)
- [x] Users table + identity profiles with API key management
- [x] Kanban boards (agentic + personal types), columns, task state machine
- [x] Subtasks, task dependencies (auto-start on completion)
- [x] Agent log audit trail, MCP tools (11 kanban tools)
- [x] Dashboard kanban board with drag-drop (SortableJS)
- [x] User management frontend (create, rotate, deactivate)
- [x] SSE real-time updates, caching on read endpoints
- [x] Backported from LlamaBan (`~/LamaFiles/projects/kanban/`)

### Phase 14: Local Embeddings + CouchDB Wiki ✅ (2026-06-14)
- [x] Swap OpenAI text-embedding-3-small (1536d) for sentence-transformers
  all-MiniLM-L6-v2 (384d, CPU-only)
- [x] Migration 020: vector(1536)→vector(384) + HNSW index
- [x] LiveSync V2 HKDF+AES-GCM decryption
- [x] CouchDB `_changes` feed watcher + poller, only syncs `wiki/` folder
- [x] 107/108 wiki pages synced, semantic search returns results

### Phase 15: Notification Dedupe + Aggregation ✅ (2026-06-15)
- [x] Dozzle collector: strip ISO/slash/RFC-2822 timestamps + hex ids from
  dedup_key fingerprint (was unique per timestamp, blocking all dedup)
- [x] Migration 022: re-hash existing dedup_keys for events with old
  fingerprints (collapsed 445,427 dozzle dupes in one run)
- [x] Migration 023: backfill dedup_key for dozzle events that had
  container_id but no key (pre-collector events)
- [x] `/api/notifications/unread?aggregate=true`: GROUP BY (source, type,
  severity, normalized_title) with count, first_seen, last_seen, event_ids
- [x] Frontend notifications widget: shows `×N` count badge, dismiss
  marks all event_ids in group processed
- [x] `/api/events?exclude_source=dozzle` filter for non-noisy sources
- [x] Agent Board "Recent API Errors" widget renamed to "Recent System
  Errors" and excludes dozzle container logs
- [x] Result: 501k unread dozzle events → 11.6k distinct events

## Known Pitfalls

| Pitfall | Fix |
|---------|-----|
| `pgvector/pgvector:pg16` uses extension name `vector`, not `pgvector` | `CREATE EXTENSION IF NOT EXISTS vector;` |
| asyncpg returns JSONB as string `'{}'` | Use `_coerce_jsonb()` helper that json.loads() strings before Pydantic init |
| `dict(row)` on asyncpg Record doesn't handle JSONB | Build Document explicitly from `row["field"]` with coercion |
| Module router prefix doubled | Module routers must NOT define their own `/api/` prefix — main.py adds `/api/{module_name}` |
| Hermes security.redact_secrets replaces passwords in tool output | Read secrets from `os.environ` inside the container, never embed in commands |
| Module `__init__.py` imports `from .routes import router` | Module auto-discovery calls `get_router()` which imports routes; use lazy import pattern |
| Migration runner splits on `;` before stripping comments | Strip `--` comment lines first, THEN split on `;` |
| `openWikiPage` not found (onclick fails silently) | IIFE scoping: functions used in `onclick` must be exported as `window.fnName = fnName;`. Same bug hit `openWikiPage` and `switchUptimeTab`. |
| Static file changes don't appear | Static files are COPY'd into the image, not volume-mounted. Rebuild: `docker compose build api && docker compose up -d api` |
| Docker healthcheck fails | curl not installed in python:3.12-slim. Added `apt-get install curl` to Dockerfile. |
| Migration runner splits inside `$$` dollar-quoted blocks | Use `_split_sql()` state machine in `app/main.py` — only splits on `;` outside `$$` blocks. Also avoid nested `$$` in DO blocks — use bare `CREATE OR REPLACE FUNCTION` instead. |
| Page loader functions inside inner IIFE can't access `api()` | Define page loaders in the outer IIFE scope (before `(function() {` at `// ─── HEADER + TICKER`), alongside `loadOverview`, `loadFeeds`, etc. Export to `window` for `onclick` handlers. |
| API_KEY_SALT must be set BEFORE creating keys | Keys hashed with wrong salt return 401 forever. Salt is in `.env` — do not change after keys exist. |
| Tests not found in container (`file or directory not found`) | Dockerfile must `COPY tests/` and `COPY pytest.ini .` — tests aren't volume-mounted. |
| `IngestResponse.doc_id` rejects UUID from `fetchval` | `doc_id` expects `str`, but asyncpg returns `UUID`. Use `str(existing)`. |
| Hermes ingest tests slow (30s each) | Notification dispatch to ntfy blocks each POST. Set `LAMADB_SKIP_NOTIFICATIONS=1` or add ntfy guard in `fire_event()`. |
| JSONB metadata in tests is a string, not dict | asyncpg returns JSONB as string. Use `json.loads(row["metadata"])` before accessing keys. |
| `@cached` decorator returns `no-request` key for handlers without `request: Request` param | The decorator extracts the Starlette `Request` from `kwargs["request"]`. Route handlers that don't declare `request: Request` as a parameter share one cache key. For endpoints with query params, declare the request parameter. |
| Cache invalidation uses tags — misspelled tags silently do nothing | Double-check tag names. `cache_manager.invalidate("documents")` must match the `invalidate_tags=["documents"]` on the `@cached` decorator. |
| `docker compose build --no-cache api` doesn't always invalidate COPY layers | Use `docker build -t lamadb-api:latest -f Dockerfile . && docker compose up -d api --force-recreate` for guaranteed fresh builds. |
| MCP tools in MODULE_MCP_TOOLS use `handler` key with dotted path `module.path:func_name` | The `_import_handler()` function splits on `:` and imports. Double-check the module path and function name. |
| `inbox_for` defaults to `to_agent` when not provided | In `send_message()`, `message.inbox_for or message.to_agent` ensures backward compatibility for old code that doesn't set inbox_for. |
| `settings.json` overlay sits alongside `.env` — env vars take priority | `discover_module_configs()` checks `settings` (env) first, then `settings_overlay` (file), then `field["default"]`. Don't delete the file manually — use the API. |
| WebSocket auth uses first-message pattern | `dashboard_websocket()` accepts the connection, then reads the first JSON message for `{"key": "..."}`. Invalid keys get code 4001. |
| `AuthUser` has optional `user_id: str | None` | Populated in `_authenticate()` from `api_keys.user_id` (added by migration 014). `None` for legacy keys not yet linked. Use for self-vs-other authorization checks. |
| New `api_keys` inserts MUST populate `key_prefix` | O(1) auth (migration 013) won't find keys without it. Compute via `app.auth._hash_prefix(raw_key)` (SHA-256 of first 16 chars). |
| Kanban board types determine default columns | Agentic: Backlog/In Progress/Review/Done. Personal: Inbox/In Progress/Review/Done. Board creation auto-populates columns from `DEFAULT_COLUMNS_AGENTIC` / `DEFAULT_COLUMNS_PERSONAL` tuples. |
| Completing a task must move it to Done column | `complete_task` route finds the Done column via `status = 'done'` and updates `column_id` BEFORE auto-starting dependents. |
| Kanban SSE channel is `kanban_task_updated` | NOTIFY triggers fire on INSERT/UPDATE/DELETE of `kanban_tasks`. Frontend registers callback via `window._sseCallbacks['kanban_task_updated']`. pg_listener subscribes in app/main.py. |
| User creation auto-generates API key with user_id link | `POST /api/users` creates both a `users` row and an `api_keys` row with `user_id` FK. New keys MUST include `key_prefix` for O(1) lookup. Legacy keys in migration get user_id backfilled from name matching. |
| Embeddings now use local `sentence-transformers/all-MiniLM-L6-v2` (384-dim) | No more OpenAI dependency. Model loads lazily on first `generate_embedding()` call. First call takes ~5-10s. Backfill after migration: trigger `POST /api/search/embeddings/backfill` with admin key. |
| HNSW index recreated after vector dim change (migration 020) | Migration drops HNSW, clears embeddings, alters `vector(1536)` → `vector(384)`, recreates index. All existing embeddings are cleared and must be regenerated via backfill endpoint. |
| Wiki collector uses CouchDB `_changes` feed with longpoll | Runs continuously via `watch_wiki_changes()` asyncio task. Advances sequence per batch. On errors, backs off exponentially (10s → 300s max). |
| Wiki sync state persisted in `wiki_sync_state` table | Tracks last processed CouchDB sequence. Reset to `'0'` to trigger full re-sync: `UPDATE wiki_sync_state SET last_seq = '0';` |
| Wiki collector only syncs `wiki/` folder pages | Files outside `wiki/` are skipped via path prefix check. Set `WIKI_COUCHDB_URL`, `WIKI_COUCHDB_DB`, `WIKI_COUCHDB_USER`, `WIKI_COUCHDB_PASSWORD`, `WIKI_COUCHDB_ENCRYPTION_KEY` env vars. |
| LiveSync chunk IDs contain `+` which decodes to space in URLs | CouchDB client URL-encodes path segments via `urllib.parse.quote`. Raw `+` in doc IDs (e.g., `h:+abc`) must be encoded as `%2B` in HTTP requests. |
| `decrypt_meta` expects `/\\:` prefix on path fields | LiveSync V2 uses `/\\:` prefix (forward slash, backslash, colon). In Python source, check as `path_field.startswith("/\\\\:")` (escape backslashes). |
| Both `%=` (sync-salt) and `%$` (ephemeral-salt) encryption prefixes are supported | `%=` uses the global `pbkdf2salt` from sync parameters; `%$` embeds its own pbkdf2 salt. Both produce AES-256-GCM ciphertext. Verified against live `obsidiannotes` CouchDB. |
| Gapped SQL placeholders cause `IndeterminateDatatypeError` | UPDATE/INSERT queries must use sequential placeholders `$1, $2, $3...` starting at `$1`. Gaps like `$2, $3, $4, $5, $6` (skipping $1) cause asyncpg to fail. The error message is misleading — the actual issue is the missing $1 in the SQL syntax. |
| Dozzle dedup_key includes message timestamps → every recurring error unique | `_event_dedup_key()` must call `_normalize_for_dedup()` (strips ISO/slash dates, RFC-2822 dates, hex ids, ANSI codes) before hashing. Without this, `agregarr cookie 'agregarr.sid' required` (logged 1×/min) becomes 1 unique event per minute. Migrations 022/023 backfill existing rows; `dedup_dozzle_events()` then collapses 500k+ → 1. |
| `/api/notifications/unread` returns 1 row per event (no aggregation) → unread count grows unbounded | Use `?aggregate=true` (default) which `GROUP BY (source, type, severity, regexp_replace(title, '\\d{4}-...-?', 'TS', 'g'))`. Returns count, first_seen, last_seen, event_ids. Frontend widget shows `×N` count badge; dismiss marks all event_ids processed. |
| Migration runner applies migration but doesn't record it in `migration_history` | The migration_history INSERT is in the same try-block as the statements; if any statement errors and the runner logs it as a warning, the file is still marked applied. If INSERT itself fails, the row is lost. Check `SELECT * FROM migration_history` after a migration with non-trivial statements. |

## Important Notes

- The `/feeds/{slug}.xml` endpoint is PUBLIC (no auth). It's RSS — readers can't send API keys.
- The `/api/uptime/webhook` endpoint is semi-public. We'll validate by source IP later, but for PoC it's open.
- Module tables are created by module-specific migrations. The feeds and uptime tables are in 001_initial.sql for PoC simplicity.
```
DATABASE_URL=postgresql://lamadb:lamadb@postgres:5432/lamadb
API_KEY_SALT=<random-string-for-hashing>
CORS_ORIGINS=http://localhost:3000,http://localhost:8080
# Local embeddings: see app/embeddings.py (no OpenAI key required)
WIKI_COUCHDB_URL=http://valhalla:5984
WIKI_COUCHDB_DB=obsidiannotes
WIKI_COUCHDB_USER=
WIKI_COUCHDB_PASSWORD=
WIKI_COUCHDB_ENCRYPTION_KEY=
FRESHRSS_URL=http://valhalla:8780 # FreshRSS GReader API base URL
HERMES_URL=http://dev-vm:9119     # Hermes Agent API
UPTIME_KUMA_URL=...               # Uptime Kuma API URL
DOZZLE_URL=...                    # Dozzle API URL
SONARR_URL=... / RADARR_URL=... / TAUTULLI_URL=...
```
API_KEY_SALT=<random-string-for-hashing>
CORS_ORIGINS=http://localhost:3000,http://localhost:8080
OPENAI_API_KEY=sk-...            # Optional — embeddings silently skipped if empty
FRESHRSS_URL=http://valhalla:8780 # FreshRSS GReader API base URL
HERMES_URL=http://dev-vm:9119     # Hermes Agent API
UPTIME_KUMA_URL=...               # Uptime Kuma API URL
DOZZLE_URL=...                    # Dozzle API URL
SONARR_URL=... / RADARR_URL=... / TAUTULLI_URL=...
```

## Known Pitfalls (Legacy — preserved from Phase 1-9)

| Pitfall | Fix |
|---------|-----|
| `pgvector/pgvector:pg16` uses extension name `vector` | `CREATE EXTENSION IF NOT EXISTS vector;` |
| Migration runner splits on `;` before stripping comments | Strip comments first then split |
| Static files are COPY'd, not mounted | Rebuild after static/ changes |
| API_KEY_SALT must be set BEFORE creating keys | Don't change salt after keys exist |
