# Life Console Dashboard + Performance Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Diagnose and fix CPU saturation, redesign overview page into a "life console" with 7 draggable widgets and server-side layout persistence, audit endpoint/page performance, and dogfood test all 14 dashboard pages.

**Architecture:** Five independent task groups. Task 1 (CPU diagnosis) is the P0 blocker — everything depends on it. Task 2 (user-layout backend) can run in parallel with Task 1. Task 3 (frontend overview) depends on Task 2. Tasks 4–5 (perf audit, dogfood) run after 1–3 complete. Uses existing FastAPI + asyncpg backend, vanilla JS frontend with SortableJS for drag-and-drop.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, PostgreSQL 16, vanilla JS, SortableJS (CDN), CSS custom properties, httpx (tests), agent-browser (dogfood)

---

### Task 1: CPU Saturation Diagnosis + Fix

**Files:**
- No new files (diagnostic investigation)
- May modify: any file identified as root cause

**Agents:** `troubleshooter` (diagnosis) → `backend` (apply fix)

- [ ] **Step 1: Install py-spy in the container for thread profiling**

```bash
docker exec lamadb_api pip install py-spy
```

- [ ] **Step 2: Dump Python thread stacks to find the busy loop**

```bash
docker exec lamadb_api py-spy dump --pid 1
```

Expected: Shows which Python function/thread is consuming CPU time. Look for any function without `await` calls in a loop, or sync IO called from async context.

- [ ] **Step 3: If py-spy unavailable, use faulthandler**

```bash
docker exec lamadb_api python3 -c "
import faulthandler, signal, time
faulthandler.register(signal.SIGUSR1)
print('faulthandler registered, send SIGUSR1 to dump stacks')
import time; time.sleep(300)
" &
# Then:
docker kill -s SIGUSR1 lamadb_api
docker logs lamadb_api --tail 200
```

- [ ] **Step 4: Check for sync-blocking in async context**

Common culprits in this codebase:
- `bcrypt.hashpw()` called without `run_in_executor` (in `app/auth.py` and `app/core/dashboard.py`)
- `uptime_kuma_api.UptimeKumaApi` login (synchronous) called in async task (in `modules/uptime/poller.py`)
- `pathlib.Path.read_text()` in migration runner (in `app/main.py`)

Check each: does it run in an async context without `await asyncio.to_thread()` or `loop.run_in_executor()`?

- [ ] **Step 5: Apply fix for identified root cause**

Example fixes depending on finding:

If `bcrypt.hashpw` blocking the event loop:
```python
# In app/auth.py, wrap bcrypt calls:
import asyncio
hash_result = await asyncio.to_thread(bcrypt.hashpw, key.encode(), salt)
```

If uptime poller blocking:
```python
# In modules/uptime/poller.py, wrap sync API calls:
api = await asyncio.to_thread(UptimeKumaApi, settings.uptime_kuma_url)
await asyncio.to_thread(api.login, settings.uptime_kuma_user, settings.uptime_kuma_password)
monitors = await asyncio.to_thread(api.get_monitors)
```

If poller_loop `__import__` causing repeated imports:
```python
# In app/main.py poller_loop, import once outside the loop:
mod = __import__(f"modules.{module_name}", fromlist=["collect"])
while True:
    result = await mod.collect()
    ...
```

- [ ] **Step 6: Rebuild container and verify CPU drops**

```bash
docker compose build api && docker compose up -d api
sleep 10
docker stats lamadb_api --no-stream
```

Expected: CPU < 5% at idle.

- [ ] **Step 7: Verify endpoint response times**

```bash
# Use the correct API key from frontend or .env
API_KEY=$(grep LAMADB_DASHBOARD_KEY .env 2>/dev/null | cut -d= -f2 || echo "YOUR_KEY")
time curl -s -o /dev/null -w "%{http_code}" \
  "http://localhost:8000/api/dashboard/overview" \
  -H "Authorization: Bearer $API_KEY"
```

Expected: 200 OK in < 500ms.

- [ ] **Step 8: Commit fix**

```bash
git add -A
git commit -m "fix(perf): resolve CPU saturation in container (root cause: [FILL])"
```

---

### Task 2: User Layout Backend

**Files:**
- Create: `migrations/011_user_layouts.sql`
- Modify: `app/core/dashboard.py` (append 2 new endpoints)
- Create: `tests/test_user_layouts.py`

**Agent:** `backend`

- [ ] **Step 1: Create migration file**

Write `migrations/011_user_layouts.sql`:

```sql
-- User layout persistence for drag-and-drop dashboard customization
CREATE TABLE IF NOT EXISTS user_layouts (
    user_id TEXT NOT NULL,
    page TEXT NOT NULL DEFAULT 'overview',
    layout JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (user_id, page)
);
```

- [ ] **Step 2: Rebuild to apply migration**

```bash
docker compose build api && docker compose up -d api
docker exec lamadb_api python3 -c "
import asyncpg, asyncio, os
async def check():
    conn = await asyncpg.connect(os.environ['DATABASE_URL'])
    tables = await conn.fetch(\"SELECT table_name FROM information_schema.tables WHERE table_name='user_layouts'\")
    print('user_layouts table exists:', len(tables) > 0)
    await conn.close()
asyncio.run(check())
"
```

- [ ] **Step 3: Add GET and PUT endpoints to dashboard.py**

Append to `app/core/dashboard.py` (after line 812, before any module-level code):

```python
# ---------------------------------------------------------------------------
# GET /api/dashboard/user-layout — saved module card order
# ---------------------------------------------------------------------------

DEFAULT_MODULE_ORDER = ["uptime", "hermes", "freshrss", "ntfy", "dozzle",
                        "notflix", "wiki", "feeds", "notifications"]


@router.get("/user-layout")
async def get_user_layout(
    page: str = Query("overview"),
    user: AuthUser = Depends(get_current_user),
):
    """
    Return saved module card order for the overview page.
    Returns default order if no layout saved.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT layout FROM user_layouts WHERE user_id = $1 AND page = $2",
            user.name, page,
        )
        if row:
            layout = json.loads(row["layout"]) if isinstance(row["layout"], str) else row["layout"]
            return {"user_id": user.name, "page": page, "layout": layout}

        default = {"module_order": DEFAULT_MODULE_ORDER}
        return {"user_id": user.name, "page": page, "layout": default}


@router.put("/user-layout")
async def save_user_layout(
    body: dict,
    page: str = Query("overview"),
    user: AuthUser = Depends(get_current_user),
):
    """
    Save module card order for the overview page.
    The frontend sends module names in desired order.

    Body: {"module_order": ["uptime", "freshrss", "hermes", ...]}
    """
    module_order = body.get("module_order", [])
    if not isinstance(module_order, list):
        raise HTTPException(status_code=400, detail="'module_order' must be a list")

    layout = json.dumps({"module_order": module_order})
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_layouts (user_id, page, layout, updated_at)
            VALUES ($1, $2, $3, now())
            ON CONFLICT (user_id, page) DO UPDATE SET
                layout = EXCLUDED.layout,
                updated_at = now()
            """,
            user.name, page, layout,
        )

    return {"user_id": user.name, "page": page, "layout": {"module_order": module_order}}
```

- [ ] **Step 4: Write test file**

Write `tests/test_user_layouts.py`:

```python
"""Tests for user layout persistence endpoints."""
import os
import pytest
import pytest_asyncio
import httpx
from tests.conftest import container_required

BASE_URL = os.environ.get("LAMADB_TEST_URL", "http://localhost:8000")
AUTH_HEADERS = {"Authorization": "Bearer lamadb_test_key_2026"}


@pytest_asyncio.fixture
async def client():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as ac:
        yield ac


@pytest.mark.asyncio
@container_required
async def test_get_default_layout(client):
    """GET should return default module order when nothing saved."""
    resp = await client.get("/api/dashboard/user-layout?page=overview", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["page"] == "overview"
    assert "uptime" in data["layout"]["module_order"]


@pytest.mark.asyncio
@container_required
async def test_save_and_retrieve_layout(client):
    """PUT should save module order, GET should return it."""
    custom = {"module_order": ["uptime", "freshrss", "hermes", "ntfy", "dozzle", "notflix", "wiki", "feeds", "notifications"]}
    resp = await client.put("/api/dashboard/user-layout?page=overview", json=custom, headers=AUTH_HEADERS)
    assert resp.status_code == 200

    resp2 = await client.get("/api/dashboard/user-layout?page=overview", headers=AUTH_HEADERS)
    assert resp2.json()["layout"]["module_order"] == custom["module_order"]


@pytest.mark.asyncio
@container_required
async def test_requires_auth(client):
    """Endpoints should reject unauthenticated requests."""
    resp = await client.get("/api/dashboard/user-layout")
    assert resp.status_code in (401, 403)
```

- [ ] **Step 5: Run tests**

```bash
docker exec lamadb_api python3 -m pytest tests/test_user_layouts.py -v
```

Expected: 3 tests pass.

- [ ] **Step 6: Commit**

```bash
git add migrations/011_user_layouts.sql app/core/dashboard.py tests/test_user_layouts.py
git commit -m "feat(dashboard): add user-layout persistence for drag-and-drop widgets"
```

---

### Task 3: Frontend Overview Redesign

**Files:**
- Rewrite: `static/js/pages/overview.js`
- Create: `static/js/lib/dragdrop.js`
- Modify: `static/index.html` (replace overview section HTML, add SortableJS CDN)
- Modify: `static/css/dashboard.css` (append new widget styles)

**Agent:** `frontend`

- [ ] **Step 1: Add SortableJS CDN to index.html**

In `static/index.html`, after the last existing `<script src="...">` tag (around line 1490), add:

```html
<script src="https://cdn.jsdelivr.net/npm/sortablejs@1.15.6/Sortable.min.js"></script>
```

- [ ] **Step 2: Replace overview HTML section**

Replace lines 213–361 in `static/index.html` (the entire `<section id="page-overview">` block) with:

```html
<section id="page-overview" class="page page-active" aria-label="Overview">

  <!-- ═══ Health Bar ═══ -->
  <div id="health-bar" class="health-bar">
    <div class="health-stat" data-metric="services">
      <span class="health-label">Services</span>
      <span class="health-value" id="hb-services">--</span>
      <span class="health-dot" id="hb-services-dot"></span>
    </div>
    <div class="health-stat" data-metric="cache">
      <span class="health-label">Cache</span>
      <span class="health-value" id="hb-cache">--</span>
      <span class="health-dot"></span>
    </div>
    <div class="health-stat" data-metric="documents">
      <span class="health-label">Documents</span>
      <span class="health-value" id="hb-documents">--</span>
    </div>
    <div class="health-stat" data-metric="events">
      <span class="health-label">Events Today</span>
      <span class="health-value" id="hb-events">--</span>
    </div>
    <div class="health-stat" data-metric="db">
      <span class="health-label">Database</span>
      <span class="health-value" id="hb-db">--</span>
      <span class="health-dot" id="hb-db-dot"></span>
    </div>
  </div>

  <!-- ═══ Main Overview Grid ═══ -->
  <div class="overview-main">
    <!-- Left Column -->
    <div class="overview-left">

      <!-- Module Status Cards (draggable) -->
      <div id="widget-modules" class="widget">
        <div class="widget-header">
          <h3>Module Status</h3>
          <span class="widget-badge" id="modules-count">9 modules</span>
        </div>
        <div id="modules-grid" class="modules-grid">
          <div class="module-card skeleton">Loading...</div>
        </div>
        <div class="widget-footer"><small>Drag cards to reorder &mdash; layout saved automatically</small></div>
      </div>

      <!-- Recent Activity Feed -->
      <div id="widget-activity" class="widget">
        <div class="widget-header">
          <h3>Recent Activity</h3>
        </div>
        <div id="activity-feed" class="activity-feed">
          <div class="activity-line skeleton">Loading...</div>
        </div>
      </div>
    </div>

    <!-- Right Column -->
    <div class="overview-right">

      <!-- RSS Headlines -->
      <div id="widget-rss" class="widget">
        <div class="widget-header">
          <h3>RSS Headlines</h3>
        </div>
        <div id="rss-list" class="rss-list">
          <div class="rss-item skeleton">Loading...</div>
        </div>
      </div>

      <!-- Agent Status -->
      <div id="widget-agents" class="widget">
        <div class="widget-header">
          <h3>Agent Status</h3>
        </div>
        <div id="agent-list" class="agent-list">
          <div class="agent-item skeleton">Loading...</div>
        </div>
      </div>

      <!-- Quick Capture -->
      <div id="widget-scratchpad" class="widget">
        <div class="widget-header">
          <h3>Quick Capture</h3>
        </div>
        <textarea id="scratchpad-input" class="scratchpad-input"
          placeholder="Capture a thought, idea, or reminder..."
          rows="3"></textarea>
        <button id="scratchpad-save" class="btn btn-primary btn-sm"
          onclick="window.submitScratchpad()">Save</button>
      </div>
    </div>
  </div>
</section>
```

- [ ] **Step 3: Write dragdrop.js**

Write `static/js/lib/dragdrop.js`:

```javascript
// Drag-and-drop initialization for overview module cards
(function() {
  'use strict';

  window.initDragDrop = function(moduleCards) {
    var grid = document.getElementById('modules-grid');
    if (!grid) return;

    // Clear existing content
    grid.innerHTML = '';
    moduleCards.forEach(function(card) {
      grid.appendChild(card);
    });

    // Initialize SortableJS
    if (typeof Sortable !== 'undefined') {
      var sortable = new Sortable(grid, {
        animation: 150,
        ghostClass: 'sortable-ghost',
        dragClass: 'sortable-drag',
        onEnd: function() {
          saveLayout();
        }
      });
    }
  };

  function saveLayout() {
    var grid = document.getElementById('modules-grid');
    if (!grid) return;
    var cards = grid.querySelectorAll('.module-card');
    var moduleOrder = [];
    cards.forEach(function(card) {
      moduleOrder.push(card.getAttribute('data-widget-id') || '');
    });

    window.api('/api/dashboard/user-layout?page=overview', {
      method: 'PUT',
      body: JSON.stringify({ module_order: moduleOrder })
    }).catch(function() { /* silent fail */ });
  }

  window.loadLayout = async function() {
    try {
      var data = await window.api('/api/dashboard/user-layout?page=overview');
      return data.layout.module_order || [];
    } catch (e) {
      return ['uptime', 'hermes', 'freshrss', 'ntfy', 'dozzle', 'notflix', 'wiki', 'feeds', 'notifications'];
    }
  };
})();
```

- [ ] **Step 4: Rewrite overview.js**

Write `static/js/pages/overview.js`:

```javascript
// Page: Overview — Life Console
(function() {
  'use strict';

  var POLL_INTERVALS = { health: 30000, modules: 60000, rss: 120000, agents: 60000 };

  window.loadOverview = async function() {
    loadHealthBar();
    loadModuleCards();
    loadActivityFeed();
    loadRSSHeadlines();
    loadAgentStatus();

    if (window.updateFooter) window.updateFooter();
  };

  // ─── Health Bar ───────────────────────────────────────────

  async function loadHealthBar() {
    try {
      var [overview, uptime] = await Promise.all([
        window.api('/api/dashboard/overview'),
        window.api('/api/uptime/status')
      ]);

      // Services
      if (uptime && uptime.length > 0) {
        var up = uptime.filter(function(m) { return m.status === 1; }).length;
        var down = uptime.length - up;
        var el = document.getElementById('hb-services');
        var dot = document.getElementById('hb-services-dot');
        if (el) el.textContent = up + '/' + uptime.length + ' up';
        if (dot) {
          dot.className = 'health-dot ' + (down > 0 ? 'health-dot-down' : 'health-dot-up');
        }
      }

      // Cache
      try {
        var cacheStats = await window.api('/api/dashboard/cache-stats?key=' + (window.getApiKey ? window.getApiKey() : ''));
        var total = (cacheStats.hits || 0) + (cacheStats.misses || 0);
        var rate = total > 0 ? Math.round(cacheStats.hits / total * 100) : 0;
        var el2 = document.getElementById('hb-cache');
        if (el2) el2.textContent = rate + '% hit';
      } catch(e) {}

      // Documents
      var el3 = document.getElementById('hb-documents');
      if (el3 && overview.documents) {
        el3.textContent = (overview.documents.total || 0).toLocaleString();
      }

      // Events
      var el4 = document.getElementById('hb-events');
      if (el4 && overview.events) {
        el4.textContent = (overview.events.today || 0);
      }

      // Database
      var el5 = document.getElementById('hb-db');
      var dot5 = document.getElementById('hb-db-dot');
      if (el5) el5.textContent = 'connected';
      if (dot5) dot5.className = 'health-dot health-dot-up';
    } catch (e) {
      markHealthError();
    }

    // Poll health bar periodically
    setTimeout(loadHealthBar, POLL_INTERVALS.health);
  }

  function markHealthError() {
    var bar = document.getElementById('health-bar');
    if (bar) bar.classList.add('health-bar-error');
  }

  // ─── Module Cards ─────────────────────────────────────────

  async function loadModuleCards() {
    var grid = document.getElementById('modules-grid');
    if (!grid) return;
    grid.innerHTML = '<div class="module-card skeleton">Loading modules...</div>';

    try {
      var health = await window.api('/api/dashboard/module-health');
      var modules = health.modules || [];
      var moduleOrder = await window.loadLayout();

      grid.innerHTML = '';

      // Sort modules to match saved layout order
      var orderedModules = [];
      moduleOrder.forEach(function(widgetId) {
        var m = modules.find(function(mod) { return mod.name === widgetId; });
        if (m) orderedModules.push(m);
      });
      // Add any modules not in the saved order
      modules.forEach(function(m) {
        if (!orderedModules.find(function(om) { return om.name === m.name; })) {
          orderedModules.push(m);
        }
      });

      orderedModules.forEach(function(m) {
        var statusClass = m.status === 'healthy' ? 'dot-up' :
          m.status === 'stale' ? 'dot-warn' :
          m.status === 'error' ? 'dot-down' : 'dot-off';

        var freshness = m.last_poll ? window.relativeTime(m.last_poll) : 'never';

        var card = document.createElement('div');
        card.className = 'module-card';
        card.setAttribute('data-widget-id', m.name);
        card.onclick = function() {
          var pageMap = {
            uptime: 'uptime', hermes: 'hermes', freshrss: 'freshrss',
            ntfy: 'ntfy', dozzle: 'dozzle', notflix: 'notflix',
            wiki: 'wiki', feeds: 'feeds', notifications: 'notifications'
          };
          var page = pageMap[m.name];
          if (page && window.navigateTo) window.navigateTo(page);
        };
        card.innerHTML =
          '<span class="status-dot-lg ' + statusClass + '"></span>' +
          '<div class="module-card-body">' +
            '<span class="module-card-name">' + (m.label || m.name) + '</span>' +
            '<span class="module-card-stats">' +
              (m.documents_count ? m.documents_count + ' docs &middot; ' : '') +
              freshness +
            '</span>' +
          '</div>' +
          (m.errors > 0 ? '<span class="module-card-errors">' + m.errors + '</span>' : '');
        grid.appendChild(card);
      });

      var countEl = document.getElementById('modules-count');
      if (countEl) countEl.textContent = orderedModules.length + ' modules';

      // Initialize drag-and-drop
      if (window.initDragDrop) {
        window.initDragDrop(grid.querySelectorAll('.module-card'));
      }
    } catch (e) {
      grid.innerHTML = '<div class="module-card error">Unable to load module status</div>';
    }

    setTimeout(loadModuleCards, POLL_INTERVALS.modules);
  }

  // ─── Activity Feed ────────────────────────────────────────

  async function loadActivityFeed() {
    var feed = document.getElementById('activity-feed');
    if (!feed) return;

    try {
      var events = await window.api('/api/events?limit=20');
      if (!events || events.length === 0) {
        feed.innerHTML = '<div class="activity-line empty">No recent activity</div>';
        return;
      }

      feed.innerHTML = events.map(function(ev) {
        var sevClass = ev.severity === 'critical' ? 'critical' :
          ev.severity === 'warn' ? 'warn' : 'info';
        var time = ev.ts ? new Date(ev.ts).toLocaleTimeString('en-US', {
          hour: '2-digit', minute: '2-digit', hour12: false
        }) : '';
        var icon = ev.severity === 'critical' ? '\u2717' :
          ev.severity === 'warn' ? '\u26A0' : '\u2713';
        return '<div class="activity-line activity-' + sevClass + '">' +
          '<code>' + time + '</code> ' +
          '<span class="activity-icon">' + icon + '</span> ' +
          '<span class="activity-source">' + (ev.source || '') + '</span>: ' +
          '<span class="activity-title">' + (ev.title || '') + '</span>' +
        '</div>';
      }).join('');
    } catch (e) {
      feed.innerHTML = '<div class="activity-line error">Activity feed unavailable</div>';
    }
  }

  // ─── RSS Headlines ────────────────────────────────────────

  async function loadRSSHeadlines() {
    var list = document.getElementById('rss-list');
    if (!list) return;

    try {
      var data = await window.api('/api/freshrss/articles?limit=5');
      var articles = data.articles || data || [];
      if (!Array.isArray(articles) || articles.length === 0) {
        list.innerHTML = '<div class="rss-item empty">No unread articles</div>';
        return;
      }

      list.innerHTML = articles.slice(0, 5).map(function(a) {
        return '<div class="rss-item">' +
          '<span class="rss-source">' + (a.feed_title || a.source || 'RSS') + '</span>' +
          '<span class="rss-title">' + (a.title || 'Untitled') + '</span>' +
        '</div>';
      }).join('');
    } catch (e) {
      list.innerHTML = '<div class="rss-item error">RSS unavailable</div>';
    }

    setTimeout(loadRSSHeadlines, POLL_INTERVALS.rss);
  }

  // ─── Agent Status ─────────────────────────────────────────

  async function loadAgentStatus() {
    var list = document.getElementById('agent-list');
    if (!list) return;

    try {
      var [stats, inboxCount] = await Promise.all([
        window.api('/api/hermes/sessions/stats').catch(function() { return null; }),
        window.api('/api/agent_board/inbox/count?agent=all').catch(function() { return { count: 0 }; })
      ]);

      list.innerHTML = '';

      // Hermes
      var hermesItem = document.createElement('div');
      hermesItem.className = 'agent-item';
      var isOnline = stats && stats.total > 0;
      hermesItem.innerHTML =
        '<span class="status-dot-sm ' + (isOnline ? 'dot-up' : 'dot-off') + '"></span>' +
        '<span class="agent-name">Hermes</span>' +
        '<span class="agent-info">' + (isOnline ? (stats.total || 0) + ' sessions' : 'offline') + '</span>';
      list.appendChild(hermesItem);

      // Agent Board
      var boardItem = document.createElement('div');
      boardItem.className = 'agent-item';
      boardItem.innerHTML =
        '<span class="status-dot-sm dot-up"></span>' +
        '<span class="agent-name">Agent Board</span>' +
        '<span class="agent-info">' + (inboxCount.count || 0) + ' unread</span>';
      list.appendChild(boardItem);
    } catch (e) {
      list.innerHTML = '<div class="agent-item error">Agent API unreachable</div>';
    }

    setTimeout(loadAgentStatus, POLL_INTERVALS.agents);
  }

  // ─── Quick Capture ────────────────────────────────────────

  window.submitScratchpad = async function() {
    var input = document.getElementById('scratchpad-input');
    var btn = document.getElementById('scratchpad-save');
    if (!input || !input.value.trim()) return;

    btn.disabled = true;
    btn.textContent = 'Saving...';
    try {
      await window.api('/api/documents', {
        method: 'POST',
        body: JSON.stringify({
          title: input.value.trim().substring(0, 80),
          content: input.value.trim(),
          source_type: 'scratchpad',
          tags: ['scratchpad']
        })
      });
      input.value = '';
      if (window.showToast) window.showToast('Saved to scratchpad', 'success');
    } catch (e) {
      if (window.showToast) window.showToast('Failed to save', 'error');
    }
    btn.disabled = false;
    btn.textContent = 'Save';
  };
})();
```

- [ ] **Step 5: Add widget CSS styles**

Append to `static/css/dashboard.css`:

```css
/* ─── Overview: Life Console ─────────────────────────────── */

/* Health Bar */
.health-bar {
  display: flex;
  gap: 0;
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  margin-bottom: 16px;
  background: var(--surface);
}
.health-stat {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border-right: 1px solid var(--border);
}
.health-stat:last-child { border-right: none; }
.health-label {
  font-size: 0.75rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.health-value {
  font-family: var(--font-mono);
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--text);
}
.health-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  margin-left: auto;
}
.health-dot-up { background: var(--success); box-shadow: 0 0 6px var(--success); }
.health-dot-down { background: var(--danger); box-shadow: 0 0 6px var(--danger); }
.health-bar-error .health-stat { opacity: 0.5; }

/* Overview Main Grid */
.overview-main {
  display: flex;
  gap: 16px;
}
.overview-left {
  flex: 2;
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}
.overview-right {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 240px;
}

/* Widget Frame */
.widget {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  overflow: hidden;
}
.widget-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}
.widget-header h3 {
  margin: 0;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--text);
}
.widget-badge {
  font-size: 0.7rem;
  font-family: var(--font-mono);
  color: var(--muted);
  background: var(--surface-alt);
  padding: 2px 8px;
  border-radius: 4px;
}
.widget-footer {
  padding: 8px 16px;
  border-top: 1px solid var(--border);
  background: var(--surface-alt);
}

/* Module Cards Grid */
.modules-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 4px;
  padding: 8px;
}
.module-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
  border: 1px solid transparent;
}
.module-card:hover {
  background: var(--surface-alt);
  border-color: var(--border);
}
.module-card.skeleton {
  grid-column: 1 / -1;
  text-align: center;
  color: var(--muted);
  cursor: default;
}
.module-card.error {
  grid-column: 1 / -1;
  text-align: center;
  color: var(--danger);
}
.module-card-body {
  flex: 1;
  min-width: 0;
}
.module-card-name {
  display: block;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.module-card-stats {
  font-size: 0.7rem;
  color: var(--muted);
  font-family: var(--font-mono);
}
.module-card-errors {
  font-size: 0.7rem;
  font-weight: 700;
  color: var(--danger);
  background: rgba(255,0,50,0.1);
  padding: 2px 6px;
  border-radius: 4px;
}

/* SortableJS drag states */
.sortable-ghost { opacity: 0.3; }
.sortable-drag { opacity: 0.8; box-shadow: 0 4px 16px rgba(0,0,0,0.3); }

/* Activity Feed */
.activity-feed {
  padding: 4px 0;
  max-height: 320px;
  overflow-y: auto;
}
.activity-line {
  padding: 6px 16px;
  font-size: 0.8rem;
  font-family: var(--font-mono);
  border-bottom: 1px solid rgba(255,255,255,0.03);
  display: flex;
  gap: 6px;
  align-items: baseline;
}
.activity-line code {
  color: var(--muted);
  font-size: 0.75rem;
}
.activity-icon { font-size: 0.75rem; }
.activity-source { color: var(--accent2); font-weight: 500; }
.activity-title { color: var(--text); flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.activity-critical .activity-icon { color: var(--danger); }
.activity-warn .activity-icon { color: var(--warn); }
.activity-info .activity-icon { color: var(--success); }
.activity-line.empty,
.activity-line.error { color: var(--muted); padding: 12px 16px; justify-content: center; border: none; }
.activity-line.error { color: var(--danger); }

/* RSS List */
.rss-list { padding: 4px 0; }
.rss-item {
  padding: 10px 16px;
  border-bottom: 1px solid rgba(255,255,255,0.03);
}
.rss-source {
  display: block;
  font-size: 0.65rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 2px;
}
.rss-title {
  font-size: 0.82rem;
  color: var(--text);
  line-height: 1.3;
}
.rss-item.empty { color: var(--muted); text-align: center; padding: 20px 16px; border: none; }
.rss-item.error { color: var(--danger); text-align: center; padding: 20px 16px; border: none; }

/* Agent List */
.agent-list { padding: 4px 0; }
.agent-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border-bottom: 1px solid rgba(255,255,255,0.03);
}
.agent-name { font-size: 0.85rem; font-weight: 500; color: var(--text); }
.agent-info { font-size: 0.75rem; color: var(--muted); margin-left: auto; font-family: var(--font-mono); }
.agent-item.error { color: var(--danger); text-align: center; justify-content: center; padding: 20px 16px; border: none; }

/* Quick Capture */
.scratchpad-input {
  width: 100%;
  border: none;
  border-bottom: 1px solid var(--border);
  background: transparent;
  color: var(--text);
  font-family: var(--font-mono);
  font-size: 0.8rem;
  padding: 12px 16px;
  resize: vertical;
  box-sizing: border-box;
  outline: none;
}
.scratchpad-input:focus { border-color: var(--accent2); }
.scratchpad-input::placeholder { color: var(--muted); }
#scratchpad-save {
  display: block;
  margin: 8px 16px 12px auto;
}

/* Status dots */
.status-dot-lg {
  width: 10px; height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}
.status-dot-sm {
  width: 8px; height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.dot-up { background: var(--success); box-shadow: 0 0 6px var(--success); }
.dot-down { background: var(--danger); box-shadow: 0 0 6px var(--danger); }
.dot-warn { background: var(--warn); box-shadow: 0 0 6px var(--warn); }
.dot-off { background: var(--muted); }

/* Skeleton loading */
.skeleton {
  color: var(--muted) !important;
  animation: skeleton-pulse 1.5s ease-in-out infinite;
}
@keyframes skeleton-pulse {
  0%, 100% { opacity: 0.4; }
  50% { opacity: 0.7; }
}

/* Mobile */
@media (max-width: 768px) {
  .overview-main { flex-direction: column; }
  .overview-right { min-width: 0; }
  .health-bar { flex-wrap: wrap; }
  .health-stat { flex: 1 1 calc(50% - 1px); padding: 8px 12px; border-bottom: 1px solid var(--border); }
  .health-stat:nth-child(4),
  .health-stat:nth-child(5) { border-bottom: none; }
  .modules-grid { grid-template-columns: repeat(2, 1fr); }
  .activity-feed { max-height: 200px; }
}
```

- [ ] **Step 6: Rebuild and verify overview page loads**

```bash
docker compose build api && docker compose up -d api
```

Open dashboard → Overview page should show:
- Health bar with live data
- Module status cards in 3-column grid
- Recent activity feed
- RSS headlines
- Agent status
- Quick capture textarea

- [ ] **Step 7: Verify drag-and-drop works**

1. Grab a module card and drag to new position
2. Refresh page → verify position persisted
3. Check `GET /api/dashboard/user-layout` returns saved order

- [ ] **Step 8: Commit**

```bash
git add static/js/pages/overview.js static/js/lib/dragdrop.js static/index.html static/css/dashboard.css
git commit -m "feat(dashboard): redesign overview as life console with 7 draggable widgets"
```

---

### Task 4: Performance Audit

**Files:**
- Modify: `benchmarks/bench_overview.py` (extend with more endpoints)
- Create: `benchmarks/bench_all_endpoints.py`

**Agent:** `tester`

- [ ] **Step 1: Write comprehensive endpoint timing script**

Write `benchmarks/bench_all_endpoints.py`:

```python
"""Time all dashboard API endpoints, report p50/p95."""
import os, time, json, httpx

BASE_URL = os.environ.get("LAMADB_TEST_URL", "http://localhost:8000")
API_KEY = os.environ.get("LAMADB_TEST_KEY", "lamadb_test_key_2026")
HEADERS = {"Authorization": f"Bearer {API_KEY}"}
ITERATIONS = 5

ENDPOINTS = [
    "/api/dashboard/overview",
    "/api/dashboard/modules",
    "/api/dashboard/health",
    "/api/dashboard/module-health",
    "/api/dashboard/module-settings",
    "/api/dashboard/api-keys",
    "/api/dashboard/api-keys/stats",
    "/api/dashboard/cache-stats?key=" + API_KEY,
    "/api/uptime/status",
    "/api/uptime/history/recent?limit=10",
    "/api/events?limit=10",
    "/api/documents?limit=10",
    "/api/search?q=test",
    "/api/feeds",
    "/api/freshrss/status",
    "/api/hermes/health",
    "/api/hermes/sessions/stats",
    "/api/wiki/pages",
    "/api/agent_board/tasks?limit=10",
    "/api/notifications/rules",
]

def percentile(values, p):
    k = (len(values) - 1) * p / 100
    f = int(k)
    c = k - f
    if f + 1 < len(values):
        return values[f] + c * (values[f + 1] - values[f])
    return values[f]

def main():
    client = httpx.Client(base_url=BASE_URL, timeout=30)
    results = []

    for ep in ENDPOINTS:
        times = []
        errors = 0
        for _ in range(ITERATIONS):
            try:
                start = time.monotonic()
                resp = client.get(ep, headers=HEADERS)
                elapsed = (time.monotonic() - start) * 1000
                if resp.status_code == 200:
                    times.append(elapsed)
                else:
                    errors += 1
            except Exception:
                errors += 1
        if times:
            times.sort()
            results.append({
                "endpoint": ep,
                "p50_ms": round(percentile(times, 50), 1),
                "p95_ms": round(percentile(times, 95), 1),
                "min_ms": round(min(times), 1),
                "max_ms": round(max(times), 1),
                "errors": errors,
            })
        else:
            results.append({"endpoint": ep, "p50_ms": None, "p95_ms": None, "errors": errors})

    # Print table
    print(f"{'Endpoint':<55} {'p50':>8} {'p95':>8} {'min':>8} {'max':>8} {'errs':>5}")
    print("-" * 95)
    slow = []
    for r in results:
        p50 = f"{r['p50_ms']:.0f}ms" if r['p50_ms'] else "FAIL"
        p95 = f"{r['p95_ms']:.0f}ms" if r['p95_ms'] else "FAIL"
        mn = f"{r['min_ms']:.0f}ms" if r['min_ms'] else "-"
        mx = f"{r['max_ms']:.0f}ms" if r['max_ms'] else "-"
        print(f"{r['endpoint']:<55} {p50:>8} {p95:>8} {mn:>8} {mx:>8} {r['errors']:>5}")
        if r['p95_ms'] and r['p95_ms'] > 1000:
            slow.append(r)

    print(f"\n--- Slow endpoints (>1s p95): {len(slow)} ---")
    for r in slow:
        print(f"  {r['endpoint']}: p95={r['p95_ms']:.0f}ms")

    client.close()

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run timing benchmark**

```bash
docker exec lamadb_api python3 benchmarks/bench_all_endpoints.py
```

Expected: All endpoints respond. p95 < 500ms for cached endpoints, < 1s for uncached. Flag any > 1s.

- [ ] **Step 3: Run cache stats check**

```bash
curl -s "http://localhost:8000/api/dashboard/cache-stats?key=lamadb_test_key_2026"
```

Expected: `hits` > `misses` after multiple page loads. If hits are low, cache isn't effective — flag for investigation.

- [ ] **Step 4: Document findings in plan output**

No commit needed — results are reported back for review.

---

### Task 5: Dogfood Testing Pass

**Files:**
- No code files changed
- Screenshots saved to: `dogfood-screenshots/`

**Agent:** `tester` using `agent-browser` skill

- [ ] **Step 1: Launch agent-browser and login**

Navigate to `http://localhost:8000/`. Enter API key `lamadb_test_key_2026`. Verify sidebar appears and overview page loads with the new life console layout.

- [ ] **Step 2: Click through all 14 sidebar pages**

For each page, verify:
- Content renders without console errors
- No layout breakage at 1440px width
- Take screenshot: `dogfood-screenshots/page-{name}.png`

Pages: Overview, Documents, Events, Search, Uptime, Feeds, FreshRSS, ntfy, Dozzle, Notflix, Hermes, Agent Board, Wiki, Notifications, Settings.

- [ ] **Step 3: Test mobile layout**

Resize viewport to 375×812. Verify:
- Sidebar → bottom tab bar
- Cards stack vertically
- Tables collapse to card view
- No horizontal overflow
- Take screenshot: `dogfood-screenshots/mobile-overview.png`

- [ ] **Step 4: Test command palette**

Press Cmd+K (or Ctrl+K). Type "documents". Verify navigates to Documents page.

- [ ] **Step 5: Test keyboard shortcuts**

Press `g d` → navigates to Documents. Press `?` → shortcut overlay appears.

- [ ] **Step 6: Test theme toggle**

Click theme toggle. Verify light/dark modes switch correctly. CSS custom properties update.

- [ ] **Step 7: Test SSE real-time updates**

```bash
curl -X POST http://localhost:8000/api/events \
  -H "Authorization: Bearer lamadb_test_key_2026" \
  -H "Content-Type: application/json" \
  -d '{"source":"dogfood","type":"test","severity":"info","title":"Dogfood test event"}'
```

Verify overview event counter increments within 2 seconds.

- [ ] **Step 8: Compile report**

Document any issues found with: severity (P0/P1/P2), page, description, repro steps. If no issues, report "All clear — 14 pages, mobile, SSE, theme toggle all working."

---

## Execution Order & Dependencies

```
Task 1 (CPU) ──┐
               ├──> Task 4 (Perf) ──> Task 5 (Dogfood)
Task 2 (Layout)┤
               └──> Task 3 (Frontend)
```

- Task 1 and Task 2 can run in **parallel** (independent)
- Task 3 depends on Task 2 (needs `user-layout` endpoint)
- Tasks 4–5 depend on Task 1 (need CPU unblocked) and Tasks 2–3 (need working dashboard)

## Agent Dispatch Strategy

| Run | Agents | Tasks | Parallel? |
|-----|--------|-------|-----------|
| Wave 1 | `troubleshooter` → `backend` | Task 1 (diagnose + fix CPU) | Yes — dispatch both |
| Wave 1 | `backend` | Task 2 (user-layout backend + test) | simultaneously |
| Wave 2 | `frontend` | Task 3 (overview redesign) | After Task 2 completes |
| Wave 3 | `tester` | Task 4 (perf audit) | After Tasks 1–3 complete |
| Wave 3 | `tester` (agent-browser) | Task 5 (dogfood) | After Tasks 1–3 complete |

## Verification Checklist

- [ ] CPU < 5% idle in `docker stats`
- [ ] `GET /api/dashboard/overview` < 500ms
- [ ] `GET /api/dashboard/user-layout` returns default module order (200)
- [ ] `PUT /api/dashboard/user-layout` saves + persists across reload
- [ ] Overview page: health bar, 9 module cards, activity feed, RSS, agents, scratchpad all render
- [ ] Module cards are draggable, order persists after refresh
- [ ] Quick capture: type text → Save → appears in documents
- [ ] Mobile layout: sidebar → tab bar, cards stack, no overflow
- [ ] Command palette + keyboard shortcuts work
- [ ] Theme toggle cycles light/dark
- [ ] SSE pushes events to dashboard within 2s
- [ ] All 14 pages load without console errors
- [ ] Endpoint timing: p95 < 1s for all endpoints
- [ ] Cache hit rate > 60%
