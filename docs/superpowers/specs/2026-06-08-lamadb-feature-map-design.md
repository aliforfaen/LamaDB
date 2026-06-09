# LamaDB Feature Map — Design Spec

> **Date:** 2026-06-08  
> **Session span:** 4–5 sessions (S1 → S7)  
> **Goal:** Platform maturity (MCP, auth, mailboxes, module settings), quality/hardening (caching, testing), and dashboard admin expansion.  
> **Explicitly deferred:** New data-source modules (Notflix/Spotify poller, body/life tracking, list management CRUD), consumer-facing Life-OS dashboard.

## Themes

| Theme | What | Sessions |
|-------|------|----------|
| **Foundation** | Shared infrastructure that benefits everything | S1, S2 |
| **Platform Maturity** | MCP server, auth UX, agent mailboxes, per-module settings | S3, S4, S5, S6 |
| **Dashboard Admin** | UX expansion, live refresh, mobile, module health | S7 |

Sessions are dependency-ordered within each theme. Foundation comes first (caching and testing affect all later work), then platform maturity (auth enables MCP which enables mailboxes), then dashboard admin (built on top of the solid backend).

---

## S1: Caching Layer

**Problem:** Dashboard pages with heavy aggregate queries (overview stats, uptime status, events list) load slowly (2-5s). Polling multiplies the problem.

**Design:**

- `app/cache.py` — singleton `CacheManager` using an in-memory dict (no Redis — keep it simple for single-user deployment)
- Each cache entry: `key`, `value`, `expires_at` (TTL), `invalidate_tags` (list of strings)
- Decorator `@cached(ttl_seconds, invalidate_tags)` wrapping FastAPI route handlers
- Write-through invalidation: `POST/PUT/DELETE` endpoints call `cache.invalidate("uptime_status")` after successful writes
- Target endpoints for caching:
  - `GET /api/dashboard/overview` (TTL: 60s, tags: events, documents, monitors)
  - `GET /api/uptime/status` (TTL: 30s, tags: monitor_status)
  - `GET /api/uptime/history/recent` (TTL: 30s, tags: monitor_status)
  - `GET /api/hermes/health` (TTL: 120s, tags: hermes)
  - `GET /api/hermes/sessions/stats` (TTL: 120s, tags: hermes)
  - `GET /api/dashboard/modules` (TTL: 300s, tags: modules)
- Poll-based collectors auto-invalidate their cache tags on each poll cycle
- `GET /api/dashboard/cache-stats` — admin endpoint showing hit/miss counts and current entries (for debugging)

**Agents:** `backend` (build cache.py, wire decorators, add invalidation calls to write endpoints). `tester` (cache hit/miss/expiry/invalidation tests).

---

## S2: Testing Infrastructure (Lean)

**Problem:** 134 tests exist but no perf benchmarks, no frontend testing, no module audit. Hard to know if changes break things. Previous test over-engineering burned tokens and time. Keep it minimal.

**Design:**

- `benchmarks/` directory with targeted perf scripts:
  - `bench_overview.py` — time `GET /api/dashboard/overview` (10 iterations, report p50/p95)
  - `bench_uptime_status.py` — time `GET /api/uptime/status` with 35+ monitors
  - `bench_search.py` — time semantic + full-text search queries
  - All runnable via `docker exec lamadb_api python3 benchmarks/bench_*.py`
- Frontend smoke test: a single Python script that uses httpx to hit all 14 dashboard tab API endpoints, asserts 200 and non-empty body, reports failures
- Module audit checklist: `docs/module-audit.md` — table of each module, its endpoints, test coverage status, known issues. Maintained once by `researcher`, updated as needed by agents.
- `pytest.ini` additions: `timeout = 30`, default `-x` (stop on first failure)
- Rule: never create test infrastructure more complex than what's being tested. Tests live in `tests/`, run via `docker exec`, no CI pipelines.

**Agents:** `researcher` (audit existing test coverage per module, produce `docs/module-audit.md`). `tester` (write perf benchmarks and smoke test).

---

## S3: API Key & User Management UI

**Problem:** Creating keys requires `docker exec` + Python bcrypt script. Revoking is manual. No visibility into who has what access. Stale keys accumulate. The dashboard Settings page has basic CRUD but no UX polish.

**Design:**

### Backend Extensions (`app/core/api_keys.py`)
- `last_used_at` column — updated on every authenticated request (lightweight: `UPDATE api_keys SET last_used_at = now() WHERE id = $1` — async, no await on the response path)
- `PATCH /api/dashboard/api-keys/{id}` — update name, scopes, role
- Soft-deactivate: `active` boolean toggle (keep the row, don't orphan foreign references)
- Scope validation: reject scopes for module names that don't exist in the module registry
- `GET /api/dashboard/api-keys/stats` — count active/inactive/stale (no usage in 30 days)

### Frontend (Dashboard → Settings → API Keys)
- Table: name, role badge, scopes as tag chips, created date, last used (relative: "3 days ago"), active toggle
- "Create Key" flow: name input → role dropdown (admin/agent/read) → scope multi-select with checkboxes grouped by module → "Generate" button → one-time reveal modal with copy button
- "Rotate" button: confirmation dialog → new key displayed once → old key deactivated
- "Revoke" button: confirmation → soft-deactivate → undo available for 5 seconds
- Filter: show all / active only / inactive / stale

**Agents:** `backend` (route extensions, `last_used_at` tracking, scope validation). `frontend` (Settings UI rebuild).

---

## S4: MCP Server

**Problem:** Agents (Hermes, Muninn, Rommie) can't natively call LamaDB APIs. They'd need HTTP clients, auth handling, JSON parsing, pagination logic. An MCP server exposes LamaDB as callable tools with JSON-RPC — agents say "search documents for X" and get structured results.

**Design:**

### Transport
- Primary: streamable HTTP (MCP 2024-11-05 spec) — POST-based with optional SSE streaming for tool results
- Reuses existing SSE infrastructure from `app/sse.py`
- Endpoint: `POST /mcp` (or configurable path)
- Auth: Bearer token (same API key system), scoped by key's role and scopes

### Tool Discovery
- `tools/list` returns all registered tools with JSON Schema parameter definitions
- Tools auto-discover from modules — each module can declare `MODULE_MCP_TOOLS` in `__init__.py`:
  ```python
  MODULE_MCP_TOOLS = [
      {"name": "uptime_status", "handler": "modules.uptime.mcp:get_status", 
       "description": "Get current status of all monitored services", ...}
  ]
  ```

### Initial Tool Set (12 tools)
| Tool | Module | Description |
|------|--------|-------------|
| `search_documents` | Core | Full-text + semantic search across documents |
| `get_document` | Core | Single document with metadata, tags, links |
| `create_document` | Core | Create a new document |
| `update_document` | Core | Update title, content, tags, metadata |
| `create_event` | Core | Log an event to the event bus |
| `get_events` | Core | Filtered event feed (source, type, severity, limit) |
| `get_uptime_status` | Uptime | Current status of all monitors |
| `get_uptime_history` | Uptime | History for a specific monitor |
| `get_agent_tasks` | Agent Board | Filtered task queue (status, agent) |
| `send_agent_message` | Agent Board | Send message to agent or broadcast |
| `wiki_search` | Wiki | Search mounted wiki filesystem |
| `scratchpad_capture` | Wiki | Quick-capture note to scratchpad |

### Implementation
- `app/mcp_server.py` — MCP protocol handler (JSON-RPC 2.0, tool registry, auth middleware)
- `app/mcp_registry.py` — tool auto-discovery from module `MODULE_MCP_TOOLS` declarations
- Each module's `mcp.py` — tool handler functions (optional; inline in routes.py for simple tools)
- MCP connection status visible in dashboard → Settings → MCP Server (tools list, recent calls, errors)

**Agents:** `researcher` (study existing MCP Python implementations — FastMCP, mcp-python-sdk — for patterns and pitfall avoidance). `backend` (build server, transport, tool registry, 12 tool handlers). `tester` (tool call validation, auth rejection, parameter validation errors).

---

## S5: Agent Mailboxes

**Problem:** `agent_board` has a flat `agent_messages` table — no inbox/sent concept, no threading, no read state. Agents can't check "what's for me."

**Design:**

### Schema Extension
```sql
ALTER TABLE agent_messages
  ADD COLUMN inbox_for TEXT,          -- agent name, or NULL for broadcast
  ADD COLUMN reply_to BIGINT REFERENCES agent_messages(id),
  ADD COLUMN read BOOLEAN DEFAULT false;
CREATE INDEX idx_messages_inbox ON agent_messages (inbox_for, read, created_at DESC);
```

### New Endpoints
| Endpoint | Description |
|----------|-------------|
| `GET /api/agent_board/inbox?agent=` | Messages addressed to agent, unread first, paginated |
| `GET /api/agent_board/sent?agent=` | Messages sent by agent |
| `GET /api/agent_board/inbox/count?agent=` | Unread count (for badge) |
| `PATCH /api/agent_board/messages/{id}/read` | Mark single message as read |
| `PATCH /api/agent_board/messages/read-all?agent=` | Mark all as read |
| `GET /api/agent_board/thread/{id}` | Full thread via recursive CTE on reply_to |

### Dashboard UI (Agent Board → Inbox tab)
- Left panel: message list (sender, subject, preview, relative time), unread bolded, unread count badge on tab
- Right panel: selected message with full body, reply form (textarea + send button)
- Thread view: messages grouped by thread, indented by depth
- Agent Board overview card updated to show unread message count per agent

### MCP Tool
- `get_my_inbox(agent_name)` → first tool an agent calls after connecting to MCP

**Agents:** `backend` (migration + routes + recursive CTE thread query). `frontend` (inbox UI — split pane, reply form, thread view).

---

## S6: Per-Module Settings

**Problem:** Module configuration is scattered across `.env`, `docker-compose.yml`, and `config.py`. Adding a setting means touching 3 files. No runtime visibility. No validation. No way to see what's configured without SSHing into the host.

**Design:**

### Schema Declaration Pattern
Each module's `__init__.py` declares its config schema:

```python
MODULE_CONFIG_SCHEMA = {
    "freshrss_url": {
        "type": "str", "default": "", "env": "FRESHRSS_URL",
        "label": "FreshRSS URL", "description": "GReader API base URL",
        "required": True, "placeholder": "http://valhalla:8780/api"
    },
    "freshrss_username": {
        "type": "str", "default": "", "env": "FRESHRSS_USERNAME",
        "label": "Username", "required": False
    },
    "freshrss_password": {
        "type": "secret", "default": "", "env": "FRESHRSS_API_PASSWORD",
        "label": "API Password", "required": False
    },
}
```

### Config Engine (`app/config.py` extension)
- `discover_module_configs()` — walks module registry, collects all `MODULE_CONFIG_SCHEMA` dicts
- Settings stored in a `settings.json` file (overlay on top of env vars). Env vars take priority if set, `settings.json` otherwise. This avoids editing `.env` programmatically.
- `GET /api/dashboard/module-settings` — returns all modules + their config schemas + current resolved values (secrets masked as `***`)
- `PUT /api/dashboard/module-settings/{module_name}` — updates `settings.json`, triggers cache invalidation, returns "restart required" flag if the setting requires restart
- Validation per type: `str`, `int`, `bool`, `secret`, `url` — bad values rejected with error message

### Frontend (Dashboard → Settings → Module Config)
- List of modules with gear icon → click to open config form
- Form per module: label, input field (text/password/checkbox), description, current value
- Secrets: masked by default, toggle eye icon to reveal
- Save button → PUT to API → green toast "Settings saved" or yellow "Restart required for changes to take effect"
- Module status indicator: green (configured + running), yellow (configured, restart needed), grey (not configured — defaults only)

**Agents:** `backend` (schema declaration pattern, config engine, routes, settings.json writer, validation). `frontend` (per-module settings form UI).

---

## S7: Dashboard Admin Expansion

Five independent sub-items. All primarily frontend, with minor backend work for NOTIFY triggers and WebSocket.

### S7a: Sidebar & Navigation Redesign

- Group the 14 sidebar items into 4 collapsible categories:
  - **Core** — Documents, Events, Search
  - **Monitoring** — Uptime, Dozzle, Hermes, Agent Board
  - **Data Sources** — Feeds, FreshRSS, Ntfy, Notflix, Wiki
  - **Admin** — Settings, Notifications
- Category headers: click to expand/collapse, chevron indicator, persist state in localStorage
- Alert badges on categories (e.g., "3" next to Monitoring when 3 services down)
- Keyboard shortcuts: `g d` → Documents, `g e` → Events, `g s` → Settings, `?` → shortcut help overlay
- Quick search bar in sidebar header — searches across all module data via `GET /api/search`

### S7b: Document Management UI

- Replace current document list with a proper data table:
  - Sortable columns: title, source_type, tags, created date
  - Client-side text filter (filters by title)
  - Pagination (server-side via API)
- Inline editing: click title, tags, or content → inline input → auto-save on blur with debounce
- Bulk operations: checkboxes on rows → "Tag selected", "Delete selected", "Change source_type" toolbar appears
- Drag-and-drop linking: grab one document row, drop on another → "Create Link" modal opens with link_type selector
- Detail modal (already built in Phase 8) stays; add "Edit" button that opens inline editor or modal editor

### S7c: Module Health Page

- New tab or Overview card section: "Module Health"
- Per-module card showing:
  - Status dot: green (active, data fresh), yellow (stale >2x poll interval), red (collector errors), grey (ENABLED=False)
  - Last poll/collection timestamp ("3 minutes ago" or "Never")
  - Documents contributed / events contributed count
  - Recent errors (last 5 events with severity=error for this module's source_type)
- "Force Poll" button per poller module (calls existing poll endpoints)
- Backend: `GET /api/dashboard/module-health` — aggregate query joining module registry, events table, and per-module stats

### S7d: Live Refresh Upgrade

- Extend SSE NOTIFY triggers to: `documents` table (INSERT, UPDATE, DELETE), `monitor_status` (INSERT)
- Frontend: EventSource listener on new document/monitor channels → shows toast "New document: {title}" or refreshes relevant panels
- WebSocket endpoint `WS /api/dashboard/ws` — thin wrapper for bidirectional needs:
  - Live document editing broadcasts changes to all viewers (collaboration awareness — shows "document being edited by...")
  - Optional: REPL-like SQL console for admin (read-only queries against the DB)
- Connection status indicator in sidebar footer: green dot + latency (ping/pong via SSE heartbeat)

### S7e: Mobile & Polish

- Responsive redesign:
  - <768px: sidebar collapses to bottom tab bar (icons only, 5 tabs: Home, Monitor, Data, Search, Settings)
  - Tables become stacked cards with key/values
  - Modals go fullscreen with close button
- Loading skeletons everywhere: replace "flash of empty table" with shimmer placeholder cards
- Light/dark theme toggle: persisted to localStorage, CSS custom properties, system preference detection
- Command palette (Cmd+K / Ctrl+K): type to navigate to any page, search documents, run quick actions

**Agents:** `frontend` (all five sub-items). `backend` (NOTIFY triggers on documents + monitor_status tables, WebSocket endpoint setup, module-health aggregate endpoint).

---

## Agent Summary

| Session | Primary Agent(s) | Type of Work |
|---------|-----------------|--------------|
| S1 | backend, tester | New file (cache.py) + test file |
| S2 | researcher, tester | Research (audit) + test files |
| S3 | backend, frontend | Backend route extensions + frontend UI rebuild |
| S4 | researcher, backend, tester | Research MCP patterns → build server + 12 tools → validate |
| S5 | backend, frontend | DB migration + routes + frontend inbox UI |
| S6 | backend, frontend | Backend config engine + frontend settings forms |
| S7 | frontend (primary), backend | UI expansion (5 sub-items) + minor backend (NOTIFY triggers, WebSocket) |

**Rules:**
- Quality before speed — run `researcher` before spinning up coding agents
- Independent sub-items within a session can run in parallel with `dispatching-parallel-agents`
- Never deploy incomplete work — each session ends with a working, tested increment
- Testing stays lean — targeted, per-feature tests only, no test suite over-engineering
- Keep the fun ratio high — this is a for-fun learning project

---

## Explicit Non-Goals (for this spec)

- New data-source modules (Notflix poller, Spotify, Home Assistant, body/life tracking)
- Consumer-facing Life-OS dashboard (separate from admin dashboard)
- List management CRUD (groceries, todos, plans — deferred to post-platform-maturity)
- CI/CD pipelines, elaborate test infrastructure, test coverage metrics
- Redis or external cache dependencies (in-memory only for single-user deployment)
- Changing the `API_KEY_SALT` (never touch it)
- Rewriting existing modules (extend, don't replace)
