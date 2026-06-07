# LamaDB Phase 6+7: Uptime Webhook, Agent Board, and Dashboard Polish

> **For Hermes:** Use `subagent-driven-development` skill — delegate each phase as a single task to MiniMax-M2.7-highspeed worker. TDD for all backend work.
> **For Huginn/OpenCode:** This spec is self-contained. All file paths, data models, test patterns, and pitfalls are documented. Read AGENTS.md for codebase conventions.

**Goal:** Wire the real Uptime Kuma webhook into LamaDB, tag all monitors for topology auto-discovery, build an Agent Board MVP (PostgreSQL LISTEN/NOTIFY coordination layer), and polish the dashboard with ticker icons and mobile refinements.

**Architecture:** Four independent phases — execute in order. Phases 1+2 are config-heavy (no code). Phase 3 adds a new module. Phase 4 is frontend-only. All backend work follows TDD.

**Tech Stack:** FastAPI + asyncpg + PostgreSQL 16 (pgvector, pg_trgm) + Vanilla JS (IIFE, single `static/index.html`)

---

## Phase 1: Wire Uptime Kuma Webhook

**Objective:** Point Uptime Kuma's webhook at LamaDB so real monitor heartbeats flow into `monitor_status` and `events` tables.

**Background:** The webhook endpoint already exists at `POST /api/uptime/webhook` (no auth, public). It accepts Uptime Kuma's heartbeat payload format. The endpoint was tested with seed data but the real Kuma instance hasn't been pointed at it yet.

### Task 1.1: Configure Uptime Kuma Webhook URL

**Objective:** Set the webhook URL in Uptime Kuma to point at LamaDB.

**Details:**
1. Access Uptime Kuma admin panel (probook or valhalla, port 3001 typically)
2. Navigate to Settings → Notifications
3. Create/edit a Webhook notification type
4. Set URL to: `http://lamadb:8000/api/uptime/webhook`
5. Ensure JSON POST body format is the default Uptime Kuma format
6. Attach this webhook to ALL monitors (apply to all)

**Verification:**
```bash
# After ~60 seconds (heartbeat interval), check events table
curl -s -H "Authorization: Bearer test-agent-key" \
  "http://localhost:8000/api/events?limit=5" | python3 -m json.tool | grep uptime

# Check monitor_status table has real timestamps
curl -s -H "Authorization: Bearer test-agent-key" \
  "http://localhost:8000/api/uptime/status" | python3 -m json.tool | head -20
```

**Notes:**
- If Kuma is on a different Docker network, use the host IP: `http://<HOST_IP>:8000/api/uptime/webhook`
- The webhook is public (no auth header needed from Kuma)
- Uptime Kuma sends heartbeats every 60s by default — expect ~35 records per minute

---

## Phase 2: Tag Uptime Kuma Monitors

**Objective:** Apply the tag convention to all Uptime Kuma monitors so the topology host map auto-discovers hosts and services.

**Background:** The topology system works by tag convention (documented in `wiki/entities/uptime-kuma-topology.md`):
- Ping monitors on physical machines get the `host` tag
- Service monitors get a tag matching their host's slugified name
- Host key derivation: `name.lower().replace(" ", "-").replace("_", "-")`
- Any untagged/unmatched monitor appears as an orphan

**Current state:** All 35 monitors exist in Uptime Kuma but none are tagged. The topology shows 2 hosts + 5 services from seed data, with 13 orphans.

### Task 2.1: Identify Host Monitors

**Objective:** Find all ping/uptime checks on physical machines in Uptime Kuma.

1. In Uptime Kuma, look for monitors of type "HTTP(s)" or "Ping" that check whole machines
2. Known hosts: ProBook, Valhalla (maybe others — Dev VM, Plex Box, etc.)
3. For each host monitor, add tag: `host`

### Task 2.2: Tag Service Monitors by Host

**Objective:** For each service monitor, add a tag matching its host machine.

**Rules:**
- Host name → tag: lowercase, spaces → hyphens
- `"ProBook"` → `"probook"`, `"Valhalla"` → `"valhalla"`
- Service monitors on ProBook get the `probook` tag
- Service monitors on Valhalla get the `valhalla` tag
- Additional descriptive tags encouraged: `docker`, `web`, `database`, `media`

**Example mapping:**
| Monitor | Host | Tags |
|---------|------|------|
| ProBook (ping) | Self | `host` |
| Valhalla (ping) | Self | `host` |
| Dozzle | ProBook | `docker`, `probook` |
| LamaDB API | ProBook | `docker`, `probook`, `api` |
| FreshRSS | Valhalla | `docker`, `valhalla`, `rss` |
| Plex | ProBook | `probook`, `media` |
| Sonarr | ProBook | `probook`, `media` |

### Task 2.3: Verify Topology

**Objective:** Confirm the topology endpoint reflects real tags.

```bash
# Check topology summary
curl -s -H "Authorization: Bearer test-agent-key" \
  "http://localhost:8000/api/uptime/topology" | python3 -m json.tool

# Expected: hosts > 2, services match tagged monitors, orphans < 5
```

**Acceptance criteria:**
- [ ] Every host ping monitor tagged `host`
- [ ] Every service monitor tagged with its host name
- [ ] Topology endpoint shows correct host→service mapping
- [ ] Orphans ≤ 3 (only truly untagged/unmatched)
- [ ] Dashboard topology tab shows real data (browser test)

---

## Phase 3: Agent Board MVP

**Objective:** Build a coordination layer where agents post tasks, query status, and get notified of new work via PostgreSQL LISTEN/NOTIFY.

**Background:** Currently agents are isolated — Muninn doesn't know what Rommie did, workers can't ask each other for help. The Agent Board solves this with:
- An `agent_tasks` table (task queue)
- An `agent_messages` table (agent-to-agent communication)
- PostgreSQL LISTEN/NOTIFY for real-time wake-up calls
- REST API for posting/querying/claiming tasks

**Design decisions:**
- Use PostgreSQL LISTEN/NOTIFY (not Redis, not WebSockets) — one less service to run
- Tasks have status: `pending`, `claimed`, `in_progress`, `completed`, `failed`
- Agents claim tasks by setting `claimed_by` + `status='claimed'`
- NOTIFY fires on INSERT into `agent_tasks` (so listeners wake up)
- Simple REST API — no streaming needed for MVP

### Task 3.1: Create Migration

**File:** `migrations/004_agent_board.sql`

```sql
-- Agent tasks (coordination queue)
CREATE TABLE IF NOT EXISTS agent_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    description TEXT,
    task_type TEXT NOT NULL DEFAULT 'general',
    priority TEXT NOT NULL DEFAULT 'normal',  -- low, normal, high, critical
    status TEXT NOT NULL DEFAULT 'pending',   -- pending, claimed, in_progress, completed, failed
    created_by TEXT,                           -- agent name that created the task
    claimed_by TEXT,                           -- agent name that claimed it
    assigned_to TEXT,                          -- specific agent (null = any)
    metadata JSONB DEFAULT '{}',
    result JSONB DEFAULT '{}',                 -- output on completion
    error TEXT,                                -- error message on failure
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    claimed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);
CREATE INDEX idx_tasks_status ON agent_tasks (status);
CREATE INDEX idx_tasks_priority ON agent_tasks (priority);
CREATE INDEX idx_tasks_claimed_by ON agent_tasks (claimed_by);

-- Agent messages (agent-to-agent communication)
CREATE TABLE IF NOT EXISTS agent_messages (
    id BIGSERIAL PRIMARY KEY,
    from_agent TEXT NOT NULL,
    to_agent TEXT,
    subject TEXT NOT NULL,
    body TEXT,
    message_type TEXT NOT NULL DEFAULT 'info',  -- info, question, alert, response
    parent_id BIGINT REFERENCES agent_messages(id),
    metadata JSONB DEFAULT '{}',
    read BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_messages_to ON agent_messages (to_agent);
CREATE INDEX idx_messages_unread ON agent_messages (to_agent) WHERE NOT read;

-- Notification function: NOTIFY on new task
CREATE OR REPLACE FUNCTION notify_agent_task()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify('agent_task', json_build_object(
        'id', NEW.id,
        'title', NEW.title,
        'priority', NEW.priority,
        'task_type', NEW.task_type
    )::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_agent_task_notify ON agent_tasks;
CREATE TRIGGER trg_agent_task_notify
    AFTER INSERT ON agent_tasks
    FOR EACH ROW
    EXECUTE FUNCTION notify_agent_task();
```

### Task 3.2: Create Agent Board Module

**Files to create:**

**`modules/agent_board/__init__.py`:**
```python
"""Agent Board — coordination layer for AI agents."""
MODULE_NAME = "agent_board"
MODULE_DESCRIPTION = "Agent task queue, messaging, and LISTEN/NOTIFY coordination"
MODULE_VERSION = "0.1.0"
ENABLED = True

def get_router():
    from .routes import router
    return router
```

**`modules/agent_board/models.py`:**
```python
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    task_type: str = "general"
    priority: str = "normal"  # low, normal, high, critical
    assigned_to: Optional[str] = None
    created_by: Optional[str] = None
    metadata: dict = {}

class TaskResponse(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    task_type: str
    priority: str
    status: str
    created_by: Optional[str] = None
    claimed_by: Optional[str] = None
    assigned_to: Optional[str] = None
    metadata: dict
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    claimed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

class TaskClaim(BaseModel):
    claimed_by: str

class TaskComplete(BaseModel):
    result: Optional[dict] = None
    error: Optional[str] = None

class MessageCreate(BaseModel):
    to_agent: Optional[str] = None
    subject: str
    body: Optional[str] = None
    message_type: str = "info"
    parent_id: Optional[int] = None
    metadata: dict = {}

class MessageResponse(BaseModel):
    id: int
    from_agent: str
    to_agent: Optional[str] = None
    subject: str
    body: Optional[str] = None
    message_type: str
    parent_id: Optional[int] = None
    metadata: dict
    read: bool
    created_at: datetime
```

**`modules/agent_board/routes.py`:** (core — 8 endpoints)

Endpoints to implement:

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/agent_board/tasks` | admin/agent | Create a task |
| GET | `/api/agent_board/tasks` | any | List tasks (filterable: ?status=pending&priority=high) |
| GET | `/api/agent_board/tasks/{id}` | any | Get task by ID |
| POST | `/api/agent_board/tasks/{id}/claim` | admin/agent | Claim a task (body: `{"claimed_by": "muninn"}`) |
| POST | `/api/agent_board/tasks/{id}/complete` | admin/agent | Mark complete (body: `{"result": {...}}`) |
| POST | `/api/agent_board/tasks/{id}/fail` | admin/agent | Mark failed (body: `{"error": "reason"}`) |
| POST | `/api/agent_board/messages` | admin/agent | Send a message |
| GET | `/api/agent_board/messages` | any | List messages (filterable: ?to_agent=muninn&unread=true) |

**Reference pattern:** Copy the pattern from `app/core/events.py` — same auth flow, same asyncpg patterns, same `_from_row()` coercion helper.

### Task 3.3: Write Tests

**File:** `tests/test_agent_board.py`

Test cases (TDD order):
1. `test_create_task` — POST /api/agent_board/tasks → 201, task in response
2. `test_list_tasks` — GET /api/agent_board/tasks → returns array
3. `test_filter_tasks_by_status` — GET ?status=pending → only pending
4. `test_filter_tasks_by_priority` — GET ?priority=high → only high priority
5. `test_claim_task` — POST /tasks/{id}/claim → status='claimed', claimed_by set
6. `test_claim_already_claimed_task` — claim claimed task → 409 Conflict
7. `test_complete_task` — POST /tasks/{id}/complete → status='completed', result set
8. `test_fail_task` — POST /tasks/{id}/fail → status='failed', error set
9. `test_complete_unclaimed_task` — complete without claim → 400 or 409
10. `test_send_message` — POST /api/agent_board/messages → 201
11. `test_list_messages_filtered` — GET ?to_agent=muninn&unread=true → filtered
12. `test_unauthorized_create` — read role → 403
13. `test_create_task_with_metadata` — JSONB round-trips correctly

**Auth note:** The `test-agent-key` in conftest.py is role='admin'. Tests that check 403 need a 'read' role key. Either seed one or skip those tests if seeding is complex.

### Task 3.4: Wire to Dashboard Overview

**Objective:** Show agent task counts on the Overview page.

Add a summary card to the Overview section:
- "AGENT TASKS" — total count from `agent_tasks`
- Breakdown: "3 pending · 1 claimed · 2 completed"
- Use existing `SOURCE_ICONS` pattern from `app/core/dashboard.py`

**Dashboard API change:** Update `GET /api/dashboard/overview` to include agent task counts.

### Task 3.5: Build & Deploy

```bash
docker compose build api && docker compose up -d --force-recreate api
sleep 3 && docker exec lamadb_api python3 -m pytest tests/test_agent_board.py -v
```

**Acceptance criteria:**
- [ ] All agent tasks endpoints return correct HTTP codes
- [ ] Claim flow enforced: pending → claimed → completed/failed
- [ ] Concurrent claim returns 409
- [ ] Agent messages CRUD works
- [ ] LISTEN/NOTIFY trigger fires (test by manually inserting and checking with `LISTEN agent_task`)
- [ ] 12+ tests passing
- [ ] Dashboard overview shows agent task counts

---

## Phase 4: Dashboard Polish

**Objective:** Add source icons to the ticker marquee, clean up orphan styling, and add mobile-friendly refinements.

**Background:** The ticker already has CSS classes for icons (`.ti-icon`, `.ti-ok`, `.ti-warn`, `.ti-err`, `.ti-breaking`) but the JS renderer doesn't populate them. The orphan section works but could use better visual treatment.

### Task 4.1: Add Source Icons to Ticker

**Objective:** Each ticker item shows a source icon (e.g., ⚡ for uptime, 📰 for RSS, 🤖 for agent).

**Implementation:**
In the ticker render function (JS in `static/index.html`), add `source_icon` mappings and prepend icons to each item:

```javascript
const SOURCE_ICONS = {
  uptime_kuma: '⚡', freshrss: '📰', rss: '📰',
  agent: '🤖', system: '◉', test: '◉',
  dozzle: '📋', ntfy: '🔔', github: '⬡',
  feed_processor: '📡', doc_indexer: '📑'
};

// In ticker item render:
const icon = SOURCE_ICONS[item.source] || '●';
const sevClass = item.severity === 'critical' ? 'ti-err' :
                 item.severity === 'warn' ? 'ti-warn' : 'ti-ok';
html += `<span class="ticker-item">
  <span class="ti-icon ${sevClass}">${icon}</span>${escHtml(item.title)}
</span>`;
```

**Files:** `static/index.html` — modify the `loadTicker()` or equivalent JS function.

### Task 4.2: Add Breaking News Badge to Ticker

**Objective:** Critical-severity items get a pulsing "BREAKING" badge after them.

Already partially styled (`.ti-breaking`, `.ti-breaking-badge` in CSS). Wire it up:

```javascript
if (item.severity === 'critical') {
  html += `<span class="ti-breaking"><span class="ti-breaking-badge">BREAKING</span></span>`;
}
```

### Task 4.3: Improve Orphan Section Styling

**Objective:** The orphan services section in the topology tab needs visual polish.

**Current state:** Orphans render in a basic list. 

**Desired:**
- Orphan chips with tag badges showing unmatched tags
- Lighter background (dimmed) to distinguish from active host cards
- Tooltip: "This monitor isn't assigned to any host. Add a host-name tag in Uptime Kuma."
- Count badge: "13 orphans" with muted styling

**Files:** `static/index.html` — modify `renderTopology()` HTML generation.

### Task 4.4: Mobile Refinements

**Objective:** Basic responsive fixes for phone/tablet.

**Changes:**
1. Sidebar collapses to icon-only on screens < 768px (already in CSS? check)
2. Host cards stack vertically on small screens (`flex-direction: column` in topology grid)
3. Ticker font-size scales down on mobile
4. Auth modal is scrollable on short screens

**Files:** `static/index.html` — add/refine `@media` queries.

### Task 4.5: Build & Verify

```bash
docker compose build api && docker compose up -d --force-recreate api
# Browser test: localhost:8000 → verify ticker icons, orphan styling, mobile layout
```

**Acceptance criteria:**
- [ ] Ticker shows source icons for all item types
- [ ] Critical items show BREAKING badge
- [ ] Orphan section has tag chips and tooltips
- [ ] Mobile layout doesn't break (test at 375px width)
- [ ] No JS errors in browser console

---

## Execution Order

Execute phases in order — each builds on the previous:

1. **Phase 1** (Webhook) — 10 min, config only
2. **Phase 2** (Tags) — 15 min, config only  
3. **Phase 3** (Agent Board) — delegate to MiniMax worker, ~5 min delegation + 5 min verify
4. **Phase 4** (Polish) — delegate to MiniMax worker, ~5 min delegation + 3 min verify

**Total estimated:** 40-50 min

---

## Known Pitfalls

| # | Pitfall | Prevention |
|---|---------|------------|
| 1 | Uptime Kuma webhook can't reach LamaDB (Docker network) | Use host IP or `host.docker.internal` if on same machine |
| 2 | `monitor_status.tags` column doesn't exist | Migration `003_uptime_tags.sql` must have run. Check: `docker exec lamadb_postgres psql -U lamadb -c "\d monitor_status"` |
| 3 | Agent Board migration fails (table exists) | Use `IF NOT EXISTS` |
| 4 | TDD tests break without seed data | Use conftest.py pattern — autouse fixture inserts test data |
| 5 | Dashboard JS: onclick handlers not on `window` | Any new function called from HTML `onclick` MUST be exported: `window.fnName = fnName;` |
| 6 | Static files stale after build | Use `--force-recreate`, never `restart` |
| 7 | Test API key doesn't have admin role | conftest.py seeds `test-agent-key` as admin — verify with `docker exec lamadb_api python3 -c "from app.auth import verify_key; ..."` |

---

## Spec Sheet Metadata

- **Created:** 2026-05-30
- **For:** Huginn (OpenCode orchestrator) + MiniMax-M2.7-highspeed workers
- **Repo:** `~/LamaFiles/projects/lamadb/`
- **Wiki ref:** `entities/uptime-kuma-topology.md`
- **AGENTS.md:** Read for codebase conventions BEFORE coding
