# LamaDB — Dashboard UI Completion Spec

> **For Huginn/OpenCode:** This spec is self-contained. Read `AGENTS.md` for codebase conventions, module patterns, Docker workflow, and known pitfalls. All paths relative to repo root `~/LamaFiles/projects/lamadb/`.

**Goal:** Complete the three dashboard tabs that have backend APIs but placeholder UIs — Ntfy, Dozzle, and Agent Board — bringing them from "data renders" to fully browsable, filterable, interactive pages.

**Architecture:** Frontend-only improvements to `static/index.html` (~4,200 lines, single-file dashboard). No new backend endpoints needed — all APIs already exist. The work is JS rendering logic, HTML form elements, and CSS refinements inside the existing IIFE structure.

**Tech Stack:** Vanilla JS (IIFE, no framework), inline CSS (CSS custom properties on `:root`), FastAPI backend (already built). Docker Compose build + force-recreate for deployment.

---

## Current State vs Target

| Tab | Current | Target |
|-----|---------|--------|
| **Ntfy** | Table with priority badges, time filter, Refresh/Sync. Reads live from ntfy API (slow, dependent). | Read from LamaDB events table (fast, cached). Add priority filter, detail expansion, auto-refresh toggle, tab badge showing count. |
| **Dozzle** | Table with level/time filters, Refresh/Sync. Proxies live to Dozzle API. No per-container filter. | Add container filter dropdown, log detail expansion, error count badge on tab. Keep live proxy but add caching fallback. |
| **Agent Board** | Tasks grid with claim/complete/fail, messages table with compose. `claimed_by` hardcoded to 'muninn'. | Make claimed_by configurable, add unclaim button, add result input on complete, fix message filters, add task count badge, mark-as-read. |

---

## Phase 1: Ntfy Page — Read from Events + Filters + Polish

### Context

The Ntfy collector (`modules/ntfy/collector.py`) already polls ntfy and writes to the `events` table (source='ntfy'). The frontend currently ignores this cache and proxies live to the ntfy JSON API via `/api/ntfy/messages`. This is slow (depends on ntfy being up), inconsistent (sync button creates events but page doesn't show them), and misses the persistence benefit.

**Fix:** Add a backend endpoint that reads ntfy messages from the events table (fast, cached), and switch the frontend to use it. Keep the live `/api/ntfy/messages` as a fallback "Live" toggle.

### Backend Changes

**Add endpoint: `GET /api/ntfy/events`** — reads from `events` table where `source = 'ntfy'`.

```python
# In modules/ntfy/routes.py, add:

from app.db import get_pool

@router.get("/events")
async def get_ntfy_events(
    user: Annotated[AuthUser, Depends(_require_auth)],
    priority: str = Query(default="all", description="Filter: all, high (≥4), critical (5)"),
    since: str = Query(default="24h", description="Time window"),
    limit: int = Query(default=100, ge=1, le=200),
):
    """Get ntfy messages from the events cache (fast, offline-safe)."""
    pool = get_pool()
    
    # Build interval from 'since' string: 1h → interval '1 hour', 6h → '6 hours', etc.
    interval_map = {"1h": "1 hour", "6h": "6 hours", "24h": "24 hours"}
    interval = interval_map.get(since, "24 hours")
    
    priority_clause = ""
    params = [interval, limit]
    if priority == "high":
        priority_clause = "AND (metadata->>'priority')::int >= 4"
    elif priority == "critical":
        priority_clause = "AND (metadata->>'priority')::int >= 5"
    
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT id, ts, title, body, metadata, severity
            FROM events
            WHERE source = 'ntfy'
              AND ts > now() - $1::interval
              {priority_clause}
            ORDER BY ts DESC
            LIMIT $2
            """,
            *params,
        )
    
    messages = []
    for row in rows:
        meta = row["metadata"]
        if isinstance(meta, str):
            meta = json.loads(meta)
        messages.append({
            "id": row["id"],
            "time": row["ts"].isoformat() if row["ts"] else None,
            "title": row["title"],
            "message": row["body"],
            "priority": meta.get("priority", 3) if meta else 3,
            "tags": meta.get("tags", []) if meta else [],
            "severity": row["severity"],
        })
    
    return {"messages": messages, "count": len(messages)}
```

**⚠️ Pitfall:** The `since` parameter uses human strings ('1h', '6h'). The SQL needs interval casting. Use the interval_map pattern above — don't try to parse arbitrary strings into Postgres intervals.

### Frontend Changes — Ntfy JS

**1a. Add a "Source" toggle: Events (default) vs Live**

Add to the filter bar HTML (around line 2037):

```html
<span class="filter-label">Source</span>
<button class="btn btn-sm btn-secondary active" id="ntfy-src-events" onclick="window.setNtfySource('events')">Events</button>
<button class="btn btn-sm btn-secondary" id="ntfy-src-live" onclick="window.setNtfySource('live')">Live</button>
```

**1b. Add priority filter**

```html
<span class="filter-label" style="margin-left:8px;">Priority</span>
<button class="btn btn-sm btn-secondary active" id="ntfy-pri-all" onclick="window.setNtfyPriority('all')">All</button>
<button class="btn btn-sm btn-secondary" id="ntfy-pri-high" onclick="window.setNtfyPriority('high')">High</button>
<button class="btn btn-sm btn-secondary" id="ntfy-pri-critical" onclick="window.setNtfyPriority('critical')">Critical</button>
```

**1c. JS variables and setters** (replace ~line 3764)

```javascript
var _ntfySince = '24h';
var _ntfyPriority = 'all';
var _ntfySource = 'events';  // 'events' | 'live'

window.setNtfySince = function(since) { ... };  // existing — keep
window.setNtfyPriority = function(pri) {
  _ntfyPriority = pri;
  document.querySelectorAll('[id^="ntfy-pri-"]').forEach(function(b) { b.classList.remove('active'); });
  document.getElementById('ntfy-pri-' + pri).classList.add('active');
  loadNtfyPage();
};
window.setNtfySource = function(src) {
  _ntfySource = src;
  document.querySelectorAll('[id^="ntfy-src-"]').forEach(function(b) { b.classList.remove('active'); });
  document.getElementById('ntfy-src-' + src).classList.add('active');
  loadNtfyPage();
};
```

**1d. Rewrite `loadNtfyPage()`** — use events cache by default

```javascript
async function loadNtfyPage() {
  var el = document.getElementById('ntfy-content');
  el.innerHTML = '<p class="loading">Loading…</p>';

  if (_ntfySource === 'events') {
    try {
      var data = await api('/api/ntfy/events?since=' + _ntfySince + '&priority=' + _ntfyPriority + '&limit=200');
      renderNtfyMessages(data.messages || []);
      // Update count badge on tab
      var badge = document.getElementById('ntfy-tab-count');
      if (badge) badge.textContent = data.count || 0;
    } catch(e) {
      el.innerHTML = '<p class="error">Failed to load ntfy events.</p>';
    }
  } else {
    // Live fallback — keep existing logic
    try {
      var health = await api('/api/ntfy/health');
      var hEl = document.getElementById('ntfy-health-status');
      if (hEl) {
        var dot = health.reachable
          ? '<span class="status-dot-lg status-up"></span> Reachable'
          : '<span class="status-dot-lg status-down"></span> Unreachable';
        hEl.innerHTML = dot + ' <span style="font-family:var(--font-mono);">' + (health.message_count || 0) + ' msgs</span>';
      }
    } catch(e) {}
    try {
      var data = await api('/api/ntfy/messages?since=' + _ntfySince + '&limit=200');
      renderNtfyMessages(data.messages || []);
    } catch(e) {
      el.innerHTML = '<p class="error">Failed to load ntfy messages.</p>';
    }
  }
}
```

**1e. Add message detail expansion to `renderNtfyMessages()`** — click row to expand

Add a click handler on each row that toggles a detail row beneath it showing full message body. Pattern:

```javascript
// Inside renderNtfyMessages, after building each row:
var msgId = 'ntfy-msg-' + (m.id || Math.random());
html += '<tr class="ntfy-row" id="' + msgId + '" onclick="window.toggleNtfyDetail(\'' + msgId + '\')" style="cursor:pointer;">' +
  // ... existing cells ...
  '</tr>';
html += '<tr id="' + msgId + '-detail" class="ntfy-detail" style="display:none;">' +
  '<td colspan="5"><div style="padding:12px 16px;background:var(--surface-2);border-radius:var(--radius-sm);font-size:13px;line-height:1.6;white-space:pre-wrap;word-break:break-word;">' + escHtml(m.message || m.body || '') + '</div></td>' +
  '</tr>';
```

Add the toggle function (export to window):

```javascript
window.toggleNtfyDetail = function(msgId) {
  var detail = document.getElementById(msgId + '-detail');
  if (detail) detail.style.display = detail.style.display === 'none' ? '' : 'none';
};
```

**1f. Auto-refresh toggle** — add a checkbox in filter bar:

```html
<label style="display:flex;align-items:center;gap:4px;font-size:12px;color:var(--muted);cursor:pointer;">
  <input type="checkbox" id="ntfy-auto-refresh" onchange="window.toggleNtfyAutoRefresh()" /> Auto
</label>
```

```javascript
var _ntfyAutoRefresh = false;
var _ntfyRefreshTimer = null;

window.toggleNtfyAutoRefresh = function() {
  _ntfyAutoRefresh = !_ntfyAutoRefresh;
  if (_ntfyAutoRefresh) {
    _ntfyRefreshTimer = setInterval(loadNtfyPage, 30000); // 30s
  } else {
    clearInterval(_ntfyRefreshTimer);
  }
};
```

### Acceptance Criteria — Phase 1

- [ ] Ntfy tab loads from events table (fast, works offline if ntfy is down)
- [ ] "Live" toggle switches back to ntfy API proxy (shows health status)
- [ ] Priority filter: All / High (≥4) / Critical (5) works correctly
- [ ] Click a message row → detail expands showing full body
- [ ] Time filter (1h/6h/24h) works with events endpoint
- [ ] Auto-refresh checkbox starts/stops 30s polling
- [ ] Tab button shows message count badge
- [ ] Sync button still triggers collector (no change needed)
- [ ] No JS console errors
- [ ] Docker rebuild + force-recreate picks up changes

---

## Phase 2: Dozzle Page — Container Filter + Detail Expansion

### Context

The Dozzle backend proxies live to Dozzle API for `/logs` and `/containers`. The frontend shows all logs mixed together. Adding a container selector lets users filter to one container's logs.

### Frontend Changes — Dozzle JS

**2a. Add container filter dropdown to HTML** (around line 2051)

```html
<span class="filter-label">Container</span>
<select id="dozzle-container-select" onchange="window.setDozzleContainer(this.value)" style="background:var(--surface-2);color:var(--fg);border:1px solid var(--border);border-radius:var(--radius-sm);padding:4px 8px;font-size:12px;max-width:200px;">
  <option value="all">All Containers</option>
</select>
```

**2b. Populate container dropdown from `/api/dozzle/containers`**

In `loadDozzlePage()`, after fetching containers:

```javascript
try {
  var containers = await api('/api/dozzle/containers');
  var ccEl = document.getElementById('dozzle-container-count');
  if (ccEl) ccEl.textContent = (containers.length || 0) + ' containers';

  // Populate dropdown
  var select = document.getElementById('dozzle-container-select');
  if (select && containers.length) {
    var options = '<option value="all">All Containers</option>';
    containers.forEach(function(c) {
      var name = c.name || c.id || 'unknown';
      options += '<option value="' + escHtml(name) + '">' + escHtml(name) + '</option>';
    });
    // Preserve current selection
    select.innerHTML = options;
    if (_dozzleContainer) select.value = _dozzleContainer;
  }
} catch(e) {}
```

**2c. JS variable and setter**

```javascript
var _dozzleContainer = 'all';

window.setDozzleContainer = function(container) {
  _dozzleContainer = container;
  loadDozzlePage();
};
```

**2d. Filter logs client-side in `renderDozzleLogs()`**

After rendering the table, if `_dozzleContainer !== 'all'`, show only matching rows. Better approach: filter before rendering:

```javascript
function renderDozzleLogs(logs) {
  var el = document.getElementById('dozzle-content');

  // Apply container filter
  var filtered = _dozzleContainer === 'all'
    ? logs
    : logs.filter(function(l) {
        return (l.container || '').toLowerCase() === _dozzleContainer.toLowerCase();
      });

  if (!filtered || filtered.length === 0) {
    el.innerHTML = '<div class="col-card" style="text-align:center;padding:32px;color:var(--muted);">No log entries found</div>';
    return;
  }
  // ... rest of rendering with 'filtered' instead of 'logs'
```

**2e. Add log detail expansion** — click row to see full message

Same pattern as Ntfy: add onclick to rows, toggle detail row with full message body. Use `logId = 'dozzle-log-' + index`:

```javascript
window.toggleDozzleDetail = function(logId) {
  var detail = document.getElementById(logId + '-detail');
  if (detail) detail.style.display = detail.style.display === 'none' ? '' : 'none';
};
```

**2f. Error count badge on tab button**

In `loadDozzlePage()`, fetch `/api/dozzle/errors` and update badge:

```javascript
try {
  var errData = await api('/api/dozzle/errors?limit=5&since=1h');
  var badge = document.getElementById('dozzle-tab-count');
  if (badge) badge.textContent = errData.count || 0;
} catch(e) {}
```

### Acceptance Criteria — Phase 2

- [ ] Container dropdown populates from /api/dozzle/containers on page load
- [ ] Selecting a container filters logs to that container only
- [ ] "All Containers" restores full view
- [ ] Click a log row → detail expands showing full message
- [ ] Existing level/time filters still work
- [ ] Tab button shows error count badge (from /errors endpoint)
- [ ] Sync/Refresh buttons still functional
- [ ] No JS console errors

---

## Phase 3: Agent Board — Configurable Claim + Unclaim + Polish

### Context

The Agent Board has the most complete UI of the three, but has hardcoded values and missing workflow steps. Key issues: `claimed_by` is hardcoded to 'muninn', no unclaim, complete passes empty result.

### Frontend Changes — Agent Board JS

**3a. Configurable `claimed_by`**

Currently (line 4048-4056):
```javascript
window.claimTask = async function(taskId) {
  await api('/api/agent_board/tasks/' + taskId + '/claim', {
    method: 'POST',
    body: JSON.stringify({ claimed_by: 'muninn' })  // HARDCODED
  });
};
```

**Fix:** Add a text input in the Agent Board header for the active agent name. Default to 'muninn' but make it editable. Store in a variable:

```html
<!-- In filter bar, next to "+ New Task" button: -->
<span style="font-size:12px;color:var(--muted);display:flex;align-items:center;gap:4px;">
  As:
  <input type="text" id="ab-agent-name" value="muninn"
    style="width:100px;background:var(--surface-2);color:var(--fg);border:1px solid var(--border);border-radius:var(--radius-sm);padding:2px 6px;font-size:12px;"
    onchange="window.setAbAgentName(this.value)" />
</span>
```

```javascript
var _abAgentName = 'muninn';

window.setAbAgentName = function(name) {
  _abAgentName = name || 'muninn';
};
```

Then in `claimTask`:
```javascript
body: JSON.stringify({ claimed_by: _abAgentName })
```

**3b. Add Unclaim/Release button**

Add a new function and button for claimed tasks:

```javascript
window.unclaimTask = async function(taskId) {
  try {
    // Reset task to pending — POST to /claim with no claimed_by, or use a separate endpoint
    // The backend doesn't have an unclaim endpoint, so we fake it by claiming with empty
    await api('/api/agent_board/tasks/' + taskId + '/claim', {
      method: 'POST',
      body: JSON.stringify({ claimed_by: null })
    });
    loadAgentBoardTasks();
  } catch(e) {
    // Fallback: if null doesn't work, just refresh
    loadAgentBoardTasks();
  }
};
```

**⚠️ Backend note:** The claim endpoint may reject `null` claimed_by. If so, add a backend route: `POST /api/agent_board/tasks/{id}/unclaim` that resets status to 'pending' and clears claimed_by. This is a 5-line route — pattern-copy from the claim route but set status='pending', claimed_by=None.

In `renderAbTasks()`, add the Unclaim button for claimed tasks:

```javascript
if (t.status === 'claimed' || t.status === 'in_progress') {
  html += '<button class="btn btn-sm btn-secondary" onclick="window.unclaimTask(\'' + escHtml(t.id || '') + '\')">Release</button>';
}
```

**3c. Result input on Complete**

Currently `completeTask` passes `{ result: {} }`. Add a prompt or form for result text:

```javascript
window.completeTask = async function(taskId) {
  var resultText = prompt('Result / notes (optional):');
  var result = resultText ? { notes: resultText } : {};
  try {
    await api('/api/agent_board/tasks/' + taskId + '/complete', {
      method: 'POST',
      body: JSON.stringify({ result: result })
    });
    loadAgentBoardTasks();
  } catch(e) { alert('Failed to complete task'); }
};
```

**3d. Fix messages filter**

Currently `loadAgentBoardMessages()` always includes `from_agent=muninn` in the query. The filter should respect selected tab:

```javascript
async function loadAgentBoardMessages() {
  var el = document.getElementById('ab-messages-content');
  el.innerHTML = '<p class="loading">Loading…</p>';
  try {
    var params = '';
    if (_abMsgFilter === 'unread') params = '&unread=true';
    else if (_abMsgFilter === 'to_me') params = '&to_agent=' + _abAgentName;
    // 'all' = no filter, shows everything
    
    var msgs = await api('/api/agent_board/messages?limit=100' + params);
    _abAllMessages = Array.isArray(msgs) ? msgs : (msgs.messages || []);
    renderAbMessages(_abAllMessages);
  } catch(e) {
    el.innerHTML = '<p class="error">Failed to load messages.</p>';
  }
}
```

**3e. Mark message as read on click**

Add a click handler to message rows:

```javascript
window.markMessageRead = async function(msgId) {
  try {
    await api('/api/agent_board/messages/' + msgId + '/read', { method: 'POST' });
    // Re-render to update NEW badge
    loadAgentBoardMessages();
  } catch(e) {}
};
```

**⚠️ Backend note:** If `POST /api/agent_board/messages/{id}/read` doesn't exist, add it. Pattern:
```python
@router.post("/messages/{msg_id}/read")
async def mark_read(msg_id: int, user: Annotated[AuthUser, Depends(_require_auth)]):
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE agent_messages SET read = true WHERE id = $1", msg_id)
    return {"ok": True}
```

**3f. Auto-refresh and pending count badge**

Add auto-refresh toggle (same pattern as Ntfy). Add pending count badge on tab button:

```javascript
// In loadAgentBoardTasks, after fetching:
var pending = tasks.filter(function(t) { return t.status === 'pending'; }).length;
var badge = document.getElementById('ab-tab-count');
if (badge) badge.textContent = pending || '';
```

### Acceptance Criteria — Phase 3

- [ ] Agent name input editable — claim/complete/fail use that name
- [ ] Unclaim/Release button visible for claimed tasks, resets to pending
- [ ] Complete task prompts for result notes, passes them to backend
- [ ] Messages filter: All / Unread / Sent to me — correct backend queries
- [ ] Click message marks it read (NEW badge disappears)
- [ ] Pending task count badge on tab button
- [ ] Auto-refresh toggle for tasks list
- [ ] No JS console errors
- [ ] All existing functionality preserved (create task, send message, claim, complete, fail)

---

## Backend Changes Summary

| Endpoint | Method | Module | Purpose |
|----------|--------|--------|---------|
| `/api/ntfy/events` | GET | ntfy | Read ntfy messages from events table |
| `/api/agent_board/tasks/{id}/unclaim` | POST | agent_board | Reset task to pending |
| `/api/agent_board/messages/{id}/read` | POST | agent_board | Mark message as read |

**All three are simple pass-through to existing tables.** No new tables, no migrations, no config changes.

### Unclaim route template

```python
# In modules/agent_board/routes.py, add after fail endpoint:

@router.post("/tasks/{task_id}/unclaim")
async def unclaim_task(
    task_id: str,
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Release a claimed task back to pending."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE agent_tasks
               SET status = 'pending', claimed_by = NULL, claimed_at = NULL, updated_at = now()
               WHERE id = $1 AND status IN ('claimed', 'in_progress')
               RETURNING id, title, status""",
            task_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Task not found or not claimed")
        return {"id": row["id"], "title": row["title"], "status": row["status"]}
```

### Read message route template

```python
# In modules/agent_board/routes.py:

@router.post("/messages/{msg_id}/read")
async def mark_message_read(
    msg_id: int,
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Mark an agent message as read."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE agent_messages SET read = true WHERE id = $1", msg_id
        )
        if result == "UPDATE 0":
            raise HTTPException(status_code=404, detail="Message not found")
        return {"ok": True}
```

---

## Common Patterns for All Three Pages

### Auto-refresh pattern (reuse on all tabs)

```javascript
var _autoRefresh = false;
var _refreshTimer = null;
var _pageLoadFn = null;  // set to loadNtfyPage, loadDozzlePage, etc.

window.toggleAutoRefresh = function() {
  _autoRefresh = !_autoRefresh;
  if (_autoRefresh) {
    _refreshTimer = setInterval(_pageLoadFn, 30000);
  } else {
    clearInterval(_refreshTimer);
  }
};
```

Each page gets its own auto-refresh variable: `_ntfyAutoRefresh`, `_dozzleAutoRefresh`, `_abAutoRefresh`.

### Tab badge pattern

Add a `<span>` inside each tab button for the count:

```html
<button class="..." onclick="switchTab('ntfy')">Ntfy <span id="ntfy-tab-count" class="tab-badge"></span></button>
```

CSS for badge:
```css
.tab-badge {
  background: var(--accent);
  color: #fff;
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 8px;
  margin-left: 4px;
  display: none;
}
.tab-badge:not(:empty) { display: inline; }
```

### Detail expansion pattern (reuse on Ntfy and Dozzle)

```javascript
window.toggleDetail = function(rowId) {
  var detail = document.getElementById(rowId + '-detail');
  if (detail) detail.style.display = detail.style.display === 'none' ? '' : 'none';
};
```

---

## Execution Order

1. **Phase 1 (Ntfy)** — ~30 min. Backend endpoint (5 min) + frontend (25 min). Most impactful — fixes the read-from-cache problem.
2. **Phase 2 (Dozzle)** — ~20 min. Frontend only. Container filter + detail expansion + badge.
3. **Phase 3 (Agent Board)** — ~30 min. 2 small backend routes (5 min) + frontend workflow polish (25 min).

**Total:** ~80 min.

---

## Docker Build & Deploy

After ALL changes are complete (not per-phase — build once at end):

```bash
cd /home/messhias/LamaFiles/projects/lamadb
docker compose build api && docker compose up -d --force-recreate api
sleep 3
docker exec lamadb_api python3 -m pytest tests/ --tb=no -q
```

**⚠️ Never use `docker compose restart`** — it doesn't pick up code changes. Always `build` + `up -d --force-recreate`.

---

## Verification

After build, verify each page:

```bash
# API checks
curl -s -H "Authorization: Bearer test-agent-key" "http://localhost:8000/api/ntfy/events?since=24h" | python3 -m json.tool | head -20
curl -s -H "Authorization: Bearer test-agent-key" "http://localhost:8000/api/dozzle/containers" | python3 -m json.tool | head -10
curl -s -H "Authorization: Bearer test-agent-key" "http://localhost:8000/api/agent_board/tasks" | python3 -m json.tool | head -10
```

Then browser test:
1. Ntfy tab → events load, priority filter works, click message expands, Live toggle works
2. Dozzle tab → container dropdown populates, select filters logs, click expands detail
3. Agent Board → change agent name, claim a task, unclaim it, complete with result, mark message read
4. Check all tab badges show counts
5. Check browser console for JS errors

---

## Known Pitfalls

| # | Pitfall | Prevention |
|---|---------|------------|
| 1 | `since` parameter needs interval casting in SQL | Use the interval_map dict — don't interpolate user strings directly |
| 2 | `json.loads()` on metadata that's already a dict | Check `isinstance(meta, str)` before parsing |
| 3 | onclick handlers not on `window` | Every new function called from HTML MUST be exported: `window.fnName = fnName;` |
| 4 | `escHtml()` produces HTML entities that break onclick | Don't use `escHtml()` inside `onclick="..."` attribute values — use the raw ID or a data attribute |
| 5 | Container filter breaks when container names have special chars | Use `toLowerCase()` comparison, not exact match |
| 6 | Auto-refresh timers leak on tab switch | Clear timer in the tab switch handler when leaving the page |
| 7 | Static files stale after build | Use `--force-recreate`, never `restart` |
| 8 | `claimed_by: null` may fail if backend expects non-null | Add the explicit `/unclaim` endpoint (Phase 3) |
| 9 | The `messages` endpoint `ts` field vs `created_at` | The backend model uses `created_at` but the frontend render accesses `m.ts` — check and align |
| 10 | `prompt()` for complete result is crude | Use `prompt()` as v1 — it works. A form modal is v2. |

---

## Spec Metadata

- **Created:** 2026-05-31
- **For:** Huginn/OpenCode orchestrator
- **Repo:** `/home/messhias/LamaFiles/projects/lamadb/`
- **Branch:** `master` (28 commits)
- **Prerequisite specs:** `docs/specs/2026-05-30-webhook-agentboard-polish-spec.md` (all backend APIs already built)
