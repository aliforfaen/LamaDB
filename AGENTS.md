# LamaDB — Agent Coding Guide

## What This Is

LamaDB is a self-hosted central data layer / Life OS. It stores documents, events, and relationships in PostgreSQL, exposes a FastAPI REST API, and serves RSS feeds generated from its data.

**Current phase: Active development.** 11 modules (feeds, uptime, dashboard, agent_board, freshrss, ntfy, dozzle, wiki, hermes, notflix, notifications). 30+ commits, 134 tests. Dashboard with real-time SSE, uptime sparklines, document detail modals, Hermes analytics, and topology host map.

Hermes Agent integration live — polls session stats, token usage, system health, and gateway status from Hermes API (v0.16.0). Dashboard tab shows health, system metrics, session stats, and recent sessions table.

## Architecture

```
FastAPI app (app/main.py)
  ├── Core: documents, document_links, events tables
  ├── Module auto-discovery from modules/ directory
  ├── Role-based API key auth
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
│   ├── embeddings.py      # OpenAI embedding service (text-embedding-3-small, 1536d)
│   ├── sse.py             # SSE infrastructure (SSEManager + pg_listener)
│   ├── models/
│   │   ├── __init__.py
│   │   ├── documents.py   # Document + Link models
│   │   └── events.py      # Event model
│   └── core/
│       ├── __init__.py
│       ├── documents.py   # Document CRUD routes (/api/documents)
│       ├── events.py      # Event CRUD routes (/api/events)
│       └── search.py      # Search routes (/api/search + /embeddings/backfill)
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
│   ├── wiki/              # Wiki reader (Karakeep API)
│   │   ├── __init__.py
│   │   ├── routes.py      # /api/wiki/*
│   │   ├── models.py
│   │   ├── wiki_db.py
│   │   ├── wiki_reader.py
│   │   └── scratchpad.py
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
│   └── 008_event_notify.sql  # NOTIFY triggers for SSE
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
CREATE INDEX idx_links_source ON document_links (source_id);
CREATE INDEX idx_links_target ON document_links (target_id);
CREATE INDEX idx_links_type ON document_links (link_type);

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
CREATE INDEX idx_events_ts ON events (ts DESC);
CREATE INDEX idx_events_source ON events (source);
CREATE INDEX idx_events_severity ON events (severity);
CREATE INDEX idx_events_processed ON events (processed) WHERE NOT processed;

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
CREATE INDEX idx_monitor_received ON monitor_status (received_at DESC);
CREATE INDEX idx_monitor_id ON monitor_status (monitor_id);
```

### API Key Table

```sql
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL DEFAULT 'read',
    scopes TEXT[] DEFAULT '{}',
    active BOOLEAN DEFAULT true,
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

API key sent via `Authorization: Bearer <key>` header. Keys stored as bcrypt hashes.

Scopes are module names: `['feeds', 'uptime', 'documents']`. Empty scopes = access to nothing (must be explicitly granted). Admin role ignores scopes.

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

Modules can define their own database tables (like `feeds`, `monitor_status`). Migration files for modules go in `migrations/` with the module name prefix.



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

## What to Build (PoC Scope)

### Phase 1: Skeleton ✅ (Completed 2026-05-29)
- [x] `docker-compose.yml` with PostgreSQL 16 (use pgvector/pgvector:pg16 image) + API server
- [x] `Dockerfile` for Python 3.12 app
- [x] `requirements.txt` with all dependencies (+ httpx, pytest, pytest-asyncio for tests)
- [x] `app/main.py` — FastAPI app with lifespan (connect/disconnect DB), module auto-discovery, CORS
- [x] `app/config.py` — pydantic Settings from env vars (DATABASE_URL, API_KEY_SALT, etc.)
- [x] `app/db.py` — asyncpg connection pool (create on startup, close on shutdown)
- [x] `app/auth.py` — API key dependency (check header, verify hash, return role + scopes)
- [x] `migrations/001_initial.sql` — all core tables above
- [x] Health endpoint: `GET /health` returns `{"status": "ok"}`
- [x] Auto-run migrations on startup (read SQL file, execute)

### Phase 2: Core Endpoints ✅ (Completed 2026-05-29)
- [x] `app/models/documents.py` — Pydantic models for Document, DocumentCreate, DocumentLink
- [x] `app/models/events.py` — Pydantic models for Event, EventCreate, EventPatch
- [x] `app/core/documents.py` — CRUD: POST/GET/PUT/DELETE /api/documents, GET /api/documents/{id}, typed links
- [x] `app/core/events.py` — CRUD: POST /api/events, GET /api/events (with filters: source, severity, processed), PATCH
- [x] `app/core/search.py` — GET /api/search?q=term (full-text on documents using pg_trgm similarity)

### Phase 3: Module 1 — Feeds ✅ (Completed 2026-05-29)
- [x] `modules/feeds/__init__.py` — module metadata + ENABLED=True + get_public_router()
- [x] `modules/feeds/models.py` — Feed, FeedCreate, FeedUpdate pydantic models
- [x] `modules/feeds/routes.py`:
  - `POST /api/feeds` — create feed (name, slug, filter criteria)
  - `GET /api/feeds` — list feeds
  - `GET /api/feeds/{slug}` — feed details
  - `PUT /api/feeds/{slug}` — update feed
  - `DELETE /api/feeds/{slug}` — delete feed
  - `GET /feeds/{slug}.xml` — RSS XML output (public, no auth)
- [x] `modules/feeds/generator.py` — query documents matching feed filters, generate RSS XML using feedgen
- Feed filtering: by tags (ANY match), by source_type, ordered by created_at DESC, limited to max_items
- **RSS content rule:** Feeds serve SUMMARIES, not raw logs. Raw agent output has source_type='agent_output'. Summaries have source_type='summary'. The feed generator filters for summaries by default. This keeps RSS readable — dense logs are unreadable in feed readers, but summaries are great.
- Each summary document should link to its raw source(s) via document_links (link_type='derived_from')
- [x] `tests/test_feeds.py` — 15 TDD tests (CRUD, RSS output, filtering, public access, validation) — ALL PASSING

### Phase 4: Module 2 — Uptime ✅ (Completed 2026-05-29)
- [x] `modules/uptime/__init__.py` — module metadata + ENABLED=True
- [x] `modules/uptime/models.py` — UptimeWebhookPayload, MonitorStatus, CurrentStatus, WebhookResponse
- [x] `modules/uptime/routes.py`:
  - `POST /api/uptime/webhook` — receive Kuma webhook payload (no auth, validated by tailnet)
  - `GET /api/uptime/status` — current status of all monitors (DISTINCT ON monitor_id)
  - `GET /api/uptime/history` — recent status changes (paginated, filterable)
  - `GET /api/uptime/history/{monitor_id}` — history for specific monitor
- [x] `modules/uptime/webhook.py` — parse Kuma webhook, insert into monitor_status, also write to events
- [x] Uptime Kuma webhook format: `{"heartbeat": {"status": 0|1|2|3, "msg": "...", "duration": ..., "time": "..."}, "monitor": {"id": ..., "name": "...", "url": "..."}}`
- [x] `tests/test_uptime.py` — 10 TDD tests (webhook creation, severity mapping, status querying, auth, pagination) — ALL PASSING

### Phase 5: Dashboard + Config 🔧 (Design done → Wiring next)

**Spec:** `docs/specs/2026-05-29-phase5-dashboard-spec.md`

#### 5A: Dashboard Backend (Management API) ✅ (2026-05-29)
- [x] `app/core/dashboard.py` — Dashboard API routes (/api/dashboard/*)
  - `GET /api/dashboard/overview` — aggregated stats (doc count, feed count, monitor up/down, events today)
  - `GET /api/dashboard/modules` — list all modules with metadata + runtime state
  - `POST /api/dashboard/modules/{name}/toggle` — enable/disable module (writes .state file, requires restart)
  - `GET /api/dashboard/health` — system health (DB version, extensions, table sizes, pool stats)
  - `GET /api/dashboard/api-keys` — list API keys (hashes never returned)
  - `POST /api/dashboard/api-keys` — create API key (returns raw key once)
  - `DELETE /api/dashboard/api-keys/{id}` — revoke API key
  - `POST /api/dashboard/api-keys/{id}/rotate` — rotate API key
- [x] `tests/test_dashboard.py` — 13 TDD tests, ALL PASSING
- [x] `modules/dashboard/__init__.py` — ENABLED=True, get_router() returns dashboard router
- [x] `modules/dashboard/routes.py` — static file serving at /
- [x] `static/index.html` — copied from Open Design artifact

#### 5B: Dashboard Frontend (Wiring) ✅ (2026-05-29)
- [x] `open-design/index.html` — design artifact (73KB, 5 pages, Tech Utility aesthetic)
- [x] `open-design/brand-spec.md` — color tokens + typography
- [x] `modules/dashboard/__init__.py` — ENABLED=True, get_router()
- [x] `modules/dashboard/routes.py` — serve static files at /
- [x] `static/index.html` — wired dashboard (fetch calls, auth, loading/error states)
- [x] Auth flow: localStorage API key, 401 → auth modal
- [x] P0 fix: dynamic footer (reflect actual uptime status)
- [x] P1 fixes: URL contrast, event row count, description tooltips, loading skeletons

#### 5C: Settings Page (Config/Management) ✅ (2026-05-29)
- [x] Sidebar: "Settings" nav item (gear icon)
- [x] Module Management section: card grid with toggle switches, metadata display, restart prompt
- [x] API Keys section: table with create/revoke/rotate, one-time key display modal
- [x] System Health section: DB status, extensions, table sizes, pool stats

### Phase 6: Core Enhancements ✅ (Completed 2026-06-07)

#### 6A: Semantic Search
- [x] `GET /api/search/semantic?q=term&limit=N` — pgvector cosine similarity endpoint
- [x] Deterministic hash-based pseudo-embedding generator (SHA-256 → 1536-dim L2-normalized vector)
- [x] Uses pgvector `<=>` operator for cosine distance ranking
- [x] Returns empty when no embeddings stored — placeholder until real embedding model is connected

#### 6B: Document Graph Traversal
- [x] `GET /api/documents/{id}/graph?depth=N&link_type=X` — recursive CTE graph traversal
- [x] Cycle detection via ARRAY path tracking in recursive CTE
- [x] Returns `{root_id, nodes: [{id, title, source_type}], edges: [{source_id, target_id, link_type, context, level}]}`
- [x] Depth limited to 1–5, optional link_type filter

#### 6C: Hermes Dashboard Tab
- [x] Added Hermes nav item to sidebar (between Notflix and Settings)
- [x] Page section with health badge, system stats cards, session statistics, and recent sessions table
- [x] Fetches from `/api/hermes/health`, `/api/hermes/system`, `/api/hermes/sessions/stats`, `/api/hermes/sessions`
- [x] Shows gateway connectivity, host metrics, token usage summary, and session list with cost estimates
- [x] Exported `loadHermesPage` to window for onclick handler (IIFE scoping)

### Phase 7: Embeddings, FreshRSS, SSE, Dashboard Polish ✅ (Completed 2026-06-07)

#### 7A: FreshRSS Polling Activation
- [x] Added `FRESHRSS_URL`, `FRESHRSS_USERNAME`, `FRESHRSS_API_PASSWORD` env vars to `docker-compose.yml`
- [x] Deduplicated auth helper: `routes.py` now imports `AuthToken` from `collector.py`
- [x] Added FreshRSS dashboard tab (nav item + page section with status cards, feed list, articles, Sync Now button)

#### 7B: Vector Embeddings Pipeline
- [x] Added `openai>=1.0.0` dependency + `OPENAI_API_KEY` / `embedding_model` config
- [x] Created `app/embeddings.py` — `generate_embedding()`, `generate_embeddings_batch()`, `embed_document_async()` fire-and-forget
- [x] `POST /api/embeddings/backfill` — admin-only batch backfill for existing documents
- [x] `GET /api/search/semantic` upgraded: real OpenAI embeddings with pseudo-embedding fallback (no API key → no embeddings stored)
- [x] `migrations/007_embedding_hnsw.sql` — HNSW index on `documents.embedding vector_cosine_ops`
- [x] Fire-and-forget embedding hooked into `POST /api/documents` (create) and `PUT /api/documents/{id}` (update)

#### 7C: Real-Time Dashboard (SSE)
- [x] `migrations/008_event_notify.sql` — NOTIFY triggers on `events` INSERT and `agent_tasks` UPDATE
- [x] Created `app/sse.py` — `SSEManager` (per-client `asyncio.Queue`) + `pg_listener` (dedicated asyncpg connection outside pool)
- [x] `GET /api/dashboard/stream?key=<api_key>` — SSE endpoint with query-param auth + 15s heartbeat
- [x] `app/auth.py` — added `verify_api_key()` for non-Bearer auth mechanisms
- [x] Frontend `connectSSE()` EventSource client, connected after auth success
- [x] Dashboard polling interval reduced from 30s → 120s (SSE covers real-time)

#### 7C.5: Migration Runner Fix
- [x] Rewrote `_split_sql()` from naive `split(";")` to character-by-character state machine that preserves `$$` dollar-quoted blocks
- [x] Rewrote `migrations/008_event_notify.sql` to avoid nested `$$` blocks (bare `CREATE OR REPLACE FUNCTION` instead of `DO $$` wrappers)

#### 7D/7E: Verification & Dogfood
- [x] All 14 dashboard sidebar items present and navigable
- [x] Triggers `trg_event_created_notify`, `trg_task_updated_notify` verified active
- [x] HNSW index `idx_documents_embedding_hnsw` created
- [x] SSE pg_listener connected on `event_created`, `task_update` channels
- [x] NOTIFY end-to-end: inserting into `events` table fires notification received by listener
- [x] 1,247 documents, 33/35 monitors up, 89 events today (verified via dashboard overview)
- [x] Hermes tab: health green, version 0.16.0, gateway running, 189 sessions


### Phase 8: Dashboard Polish & Test Suite Rebuild ✅ (Completed 2026-06-08)

#### 8A: Document Detail Modal
- [x] Rewrote `openDocDetail()` from DOM-scraping to async API fetch (parallel document + links calls)
- [x] Loading state, 404 handling, real timestamps from API
- [x] Linked documents rendered as clickable chips instead of static SVG placeholder
- [x] Removed 6 hard-coded stub cards — `loadDocuments()` populates dynamically

#### 8B: Uptime Sparklines
- [x] `GET /api/uptime/history/recent?limit=30` — batch endpoint grouped by monitor_id using `ROW_NUMBER() OVER (PARTITION BY)`
- [x] Inline SVG sparklines (stepped polylines, 120×24px) injected into each monitor card
- [x] Color-coded by latest status: green=UP, red=DOWN, grey=pending

#### 8C: SSE Bugfixes
- [x] `app/sse.py`: Fixed `NameError` when `asyncpg.connect()` fails — `conn` initialized to `None` before try, guarded `finally`
- [x] Frontend `connectSSE()`: Removed manual `setTimeout(connectSSE, 5000)` retry that raced with EventSource auto-reconnect

#### 8D: Test Suite Rebuild
- [x] `tests/test_hermes_ingest.py` — 6 tests: session_finalize, upsert, llm_call, credential_error, gateway_status, unknown_type
- [x] `tests/test_dozzle_collector.py` — 4 tests: sanitize null bytes, invalid UTF-8, SSE parsing, JSONL parsing
- [x] `tests/test_sse.py` — 4 tests: auth rejection, SSEManager broadcast/subscribe/unsubscribe lifecycle
- [x] `Dockerfile`: Added `COPY tests/` and `COPY pytest.ini` so tests run in container
- [x] Bugfix: `modules/hermes/routes.py` — `str(existing)` conversion for UUID→str in upsert `IngestResponse.doc_id`
- [x] All 14 new tests pass (152s, in-process via httpx ASGITransport, no docker exec)

- **Async everywhere.** asyncpg, async FastAPI routes, no sync blocking.
- **Pydantic for all models.** Request/response validation.
- **No ORMs.** Raw SQL with asyncpg. Keep it simple, keep it readable.
- **Type hints everywhere.** Python 3.12 syntax.
- **Docstrings on public functions.** Google style.
- **Error handling:** Use FastAPI HTTPException with proper status codes.
- **JSONB for flexible data.** Don't add columns for module-specific fields — use metadata.
- **UUIDs for document IDs.** SERIAL/BIGSERIAL for internal tables (events, monitor_status).
- **TIMESTAMPTZ always.** Never naive timestamps.

## Environment Variables


```
DATABASE_URL=postgresql://lamadb:lamadb@postgres:5432/lamadb
API_KEY_SALT=<random-string-for-hashing>
CORS_ORIGINS=http://localhost:3000,http://localhost:8080
OPENAI_API_KEY=sk-...            # Optional — embeddings silently skipped if empty
FRESHRSS_URL=http://valhalla:8780 # FreshRSS GReader API base URL
FRESHRSS_USERNAME=lamadb          # FreshRSS login username
FRESHRSS_API_PASSWORD=...         # FreshRSS API password
HERMES_URL=http://dev-vm:9119     # Hermes Agent API
HERMES_DASHBOARD_SESSION_TOKEN=.. # Fallback auth for Hermes API
UPTIME_KUMA_URL=...               # Uptime Kuma API URL
UPTIME_KUMA_API_KEY=...           # Uptime Kuma API key
```

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

## Important Notes

- The `/feeds/{slug}.xml` endpoint is PUBLIC (no auth). It's RSS — readers can't send API keys.
- The `/api/uptime/webhook` endpoint is semi-public. We'll validate by source IP later, but for PoC it's open.
- Module tables are created by module-specific migrations. The feeds and uptime tables are in 001_initial.sql for PoC simplicity.
