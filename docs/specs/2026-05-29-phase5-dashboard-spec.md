# LamaDB — Phase 5 Spec: Dashboard Wiring + Config/Management

**Date:** 2026-05-29
**Status:** Planning
**Depends on:** Phase 1-4 (skeleton, CRUD, feeds, uptime)

## Overview

Transform the static Open Design artifact (`open-design/index.html`) into a functional dashboard backed by live API data. Add a new Settings page for module management, API key management, and system health monitoring.

## Phase Breakdown

### Phase 5A: Dashboard Backend — Management API

New endpoints under `/api/dashboard/*` (admin-only).

#### System Overview

```
GET /api/dashboard/overview
```

Aggregated stats for the Overview page stat cards:

```json
{
  "documents": { "total": 1247, "today": 12 },
  "feeds": { "total": 3, "healthy": 3 },
  "monitors": { "up": 33, "down": 2, "unknown": 0 },
  "events": { "today": 89, "delta_yesterday": 5 }
}
```

SQL queries:
- `SELECT count(*) FROM documents` + `WHERE created_at > now() - interval '1 day'`
- `SELECT count(*) FROM feeds`
- `SELECT status, count(*) FROM (SELECT DISTINCT ON (monitor_id) status FROM monitor_status ORDER BY monitor_id, received_at DESC) GROUP BY status`
- `SELECT count(*) FROM events WHERE ts > now() - interval '1 day'` + delta

#### Module Management

```
GET /api/dashboard/modules
```

List all modules with metadata and runtime state:

```json
{
  "modules": [
    {
      "name": "feeds",
      "description": "RSS feed generator from LamaDB documents",
      "version": "0.1.0",
      "enabled": true,
      "routes": ["/api/feeds", "/feeds/{slug}.xml"],
      "tables": ["feeds"]
    },
    {
      "name": "uptime",
      "description": "Uptime Kuma webhook receiver",
      "version": "0.1.0",
      "enabled": true,
      "routes": ["/api/uptime/webhook", "/api/uptime/status", "/api/uptime/history"],
      "tables": ["monitor_status"]
    },
    {
      "name": "dashboard",
      "description": "Management dashboard for LamaDB",
      "version": "0.1.0",
      "enabled": true,
      "routes": ["/", "/api/dashboard/*"],
      "tables": []
    }
  ]
}
```

Implementation: scan `modules/` directory, read `__init__.py` attributes (MODULE_NAME, MODULE_DESCRIPTION, MODULE_VERSION, ENABLED), cross-reference with runtime state.

```
POST /api/dashboard/modules/{name}/toggle
Body: { "enabled": true|false }
```

Toggle a module on/off. Two approaches:

**Option A (Simple — PoC):** Write a `modules/{name}/.state` JSON file with `{"enabled": false}`. Module discovery checks this file alongside the `__init__.py` ENABLED flag. Requires app restart to take effect. Response includes `"restart_required": true`.

**Option B (Runtime):** Store module state in a `module_config` DB table. Module discovery queries this on startup. Toggle updates DB + triggers hot-reload. More complex, save for later.

**Decision: Option A for PoC.** Simple, no DB schema changes, state is visible in filesystem.

```
POST /api/dashboard/modules/{name}/restart
```

Trigger a graceful restart of the application (only works in Docker — sends SIGTERM to uvicorn). For PoC, return `{"message": "Restart required — restart the container manually"}`.

#### API Key Management

```
GET /api/dashboard/api-keys
```

List all API keys (key hash is NEVER returned):

```json
{
  "keys": [
    {
      "id": "uuid",
      "name": "Muninn Admin",
      "role": "admin",
      "scopes": [],
      "active": true,
      "created_at": "2026-05-29T12:00:00Z"
    }
  ]
}
```

```
POST /api/dashboard/api-keys
Body: { "name": "Worker Agent", "role": "agent", "scopes": ["feeds", "uptime"] }
```

Create a new API key. Returns the raw key ONCE:

```json
{
  "id": "uuid",
  "name": "Worker Agent",
  "role": "agent",
  "scopes": ["feeds", "uptime"],
  "key": "lamadb_live_abc123...",
  "message": "Save this key — it will not be shown again"
}
```

Implementation:
- Generate random key with `secrets.token_urlsafe(32)`
- Hash with bcrypt using `API_KEY_SALT`
- Store hash in `api_keys` table
- Return raw key in response (only time it's visible)

```
DELETE /api/dashboard/api-keys/{id}
```

Revoke an API key (set `active = false`).

```
POST /api/dashboard/api-keys/{id}/rotate
```

Rotate a key — generates new key, invalidates old one. Returns new raw key once.

#### System Health

```
GET /api/dashboard/health
```

Detailed health check (admin-only, more than `/health`):

```json
{
  "status": "healthy",
  "database": {
    "connected": true,
    "version": "PostgreSQL 16.3",
    "extensions": {
      "vector": { "installed": true, "version": "0.7.0" },
      "pg_trgm": { "installed": true, "version": "1.6" },
      "pg_stat_statements": { "installed": true, "version": "1.10" },
      "pg_cron": { "installed": true, "version": "1.6" }
    },
    "tables": {
      "documents": { "rows": 1247, "size": "2.1 MB" },
      "document_links": { "rows": 342, "size": "156 KB" },
      "events": { "rows": 5678, "size": "3.4 MB" },
      "api_keys": { "rows": 4, "size": "32 KB" },
      "feeds": { "rows": 3, "size": "16 KB" },
      "monitor_status": { "rows": 12456, "size": "1.8 MB" }
    }
  },
  "pool": {
    "active": 2,
    "idle": 3,
    "max": 10
  },
  "uptime_seconds": 345678
}
```

SQL:
- `SELECT version()` for PG version
- `SELECT * FROM pg_available_extensions WHERE installed IS NOT NULL` for extensions
- `SELECT count(*) FROM {table}` for each table
- `SELECT pg_size_pretty(pg_total_relation_size('{table}'))` for sizes
- asyncpg pool stats for connection info

### Phase 5B: Dashboard Frontend — Wiring

Transform `open-design/index.html` from static to functional.

#### Architecture Decision

**Keep single-file HTML.** The Open Design artifact is a self-contained 73KB HTML file with inline CSS/JS. Rather than splitting into Vue components, we:

1. Add a lightweight data layer (`fetch` calls to `/api/dashboard/*`)
2. Add localStorage for API key storage
3. Replace hardcoded data with dynamic rendering
4. Keep the existing HTML structure and CSS

This preserves the design artifact's simplicity — no build step, no node_modules, just one HTML file served by FastAPI.

#### Auth Flow

1. On first visit, check `localStorage.getItem('lamadb_api_key')`
2. If missing → show a modal: "Enter your LamaDB admin API key"
3. Store key in localStorage
4. All fetch calls include `Authorization: Bearer ${key}`
5. On 401 → clear localStorage, show auth modal again

#### Data Loading Pattern

```javascript
// On page load and nav switch
async function loadPage(page) {
  showSkeleton(page);
  try {
    switch (page) {
      case 'overview':
        const stats = await api('/api/dashboard/overview');
        renderOverview(stats);
        break;
      case 'feeds':
        const feeds = await api('/api/feeds');
        renderFeeds(feeds);
        break;
      case 'uptime':
        const status = await api('/api/uptime/status');
        const history = await api('/api/uptime/history?limit=50');
        renderUptime(status, history);
        break;
      case 'events':
        const events = await api('/api/events?limit=50');
        renderEvents(events);
        break;
      case 'documents':
        // Documents uses search endpoint
        break;
      case 'settings':
        const modules = await api('/api/dashboard/modules');
        const keys = await api('/api/dashboard/api-keys');
        const health = await api('/api/dashboard/health');
        renderSettings(modules, keys, health);
        break;
    }
  } catch (err) {
    if (err.status === 401) showAuthModal();
    else showError(page, err);
  }
}
```

#### P0/P1 Fixes (from visual review)

1. **Dynamic footer** — Query `/api/uptime/status`, show "X up · Y down" with color
2. **URL contrast** — CSS fix: `.monitor-url { color: var(--fg-2); }`
3. **Event rows** — Default 20 rows, add "rows per page" dropdown
4. **Truncated descriptions** — Add `title` attribute to truncated cells
5. **Loading skeletons** — CSS skeleton animation while fetching
6. **Error states** — "API unreachable" banner with retry button

### Phase 5C: Settings Page (Config/Management)

New page in the sidebar: **Settings** (gear icon). Three sections.

#### Section 1: Module Management

Card grid showing each module:

```
┌─────────────────────────────────────────┐
│ 📡 Uptime Kuma              [ENABLED ●] │
│ Uptime Kuma webhook receiver            │
│ v0.1.0 · Routes: /api/uptime/*          │
│ Tables: monitor_status                  │
│                              [Restart]   │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│ 📰 Feeds                    [ENABLED ●] │
│ RSS feed generator from documents       │
│ v0.1.0 · Routes: /api/feeds/*           │
│ Tables: feeds                           │
│                              [Restart]   │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│ 📊 Dashboard                [ENABLED ●] │
│ Management dashboard for LamaDB         │
│ v0.1.0 · Routes: /, /api/dashboard/*    │
│ Tables: —                               │
│                              [Restart]   │
└─────────────────────────────────────────┘
```

Toggle switch calls `POST /api/dashboard/modules/{name}/toggle`.
Shows "Restart required" badge after toggle.

#### Section 2: API Keys

Table with create/revoke actions:

| Name | Role | Scopes | Active | Created | Actions |
|------|------|--------|--------|---------|---------|
| Muninn Admin | admin | * | ● | 2026-05-29 | — |
| Worker Agent | agent | feeds, uptime | ● | 2026-05-29 | [Rotate] [Revoke] |
| Dashboard Read | read | — | ● | 2026-05-29 | [Rotate] [Revoke] |

"+ Create Key" button opens form:
- Name (text)
- Role (dropdown: admin, agent, read)
- Scopes (multi-select checkboxes: documents, events, feeds, uptime, dashboard)
- Submit → shows raw key in a copy-to-clipboard modal (one-time view)

#### Section 3: System Health

Status cards:

- **Database:** Connected · PostgreSQL 16.3 · Pool: 2/10 active
- **Extensions:** vector ✓ · pg_trgm ✓ · pg_stat_statements ✓ · pg_cron ✓
- **Tables:** documents (1,247 rows, 2.1 MB) · events (5,678 rows, 3.4 MB) · ...
- **Uptime:** 3d 23h 45m

Green checkmarks for healthy, red X for issues.

## File Changes

### New Files

| File | Purpose |
|------|---------|
| `app/core/dashboard.py` | Dashboard API routes (/api/dashboard/*) |
| `modules/dashboard/routes.py` | Serve static files + dashboard API |
| `static/index.html` | Wired dashboard (copy from open-design, add JS) |
| `static/js/app.js` | Data fetching, rendering, auth logic |
| `tests/test_dashboard.py` | TDD tests for dashboard API |

### Modified Files

| File | Changes |
|------|---------|
| `modules/dashboard/__init__.py` | ENABLED=True, add get_router() |
| `app/main.py` | Register dashboard static mount at `/` |
| `migrations/` | Add `module_config` table (if Option B) or skip |
| `docker-compose.yml` | Mount static/ volume for dev |

### API Endpoint Summary

| Endpoint | Auth | Purpose |
|----------|------|---------|
| `GET /api/dashboard/overview` | admin | Aggregated stats |
| `GET /api/dashboard/modules` | admin | Module list + status |
| `POST /api/dashboard/modules/{name}/toggle` | admin | Enable/disable module |
| `GET /api/dashboard/health` | admin | System health detail |
| `GET /api/dashboard/api-keys` | admin | List API keys |
| `POST /api/dashboard/api-keys` | admin | Create API key |
| `DELETE /api/dashboard/api-keys/{id}` | admin | Revoke API key |
| `POST /api/dashboard/api-keys/{id}/rotate` | admin | Rotate API key |

## Implementation Order

1. **TDD: Dashboard API tests** (test_dashboard.py)
2. **Dashboard API routes** (app/core/dashboard.py)
3. **Static file serving** (modules/dashboard/routes.py + main.py)
4. **Wire frontend** (static/index.html — add fetch calls, auth, loading states)
5. **Settings page** (add to sidebar, module/key/health UI)
6. **P0/P1 fixes** (dynamic footer, contrast, event rows)
7. **Integration test** (docker compose up, verify all pages load with real data)

## Open Questions

| Question | Proposed Answer |
|----------|----------------|
| Module toggle: filesystem or DB? | Filesystem (.state file) for PoC. DB table later. |
| Dashboard static mount: `/` or `/dashboard`? | `/` — it's the primary UI. API is at `/api/*`. |
| API key rotation: keep old key valid for grace period? | No — instant revoke for PoC. Grace period later. |
| CORS: allow dashboard origin? | Already configured. Dashboard served from same origin. |
