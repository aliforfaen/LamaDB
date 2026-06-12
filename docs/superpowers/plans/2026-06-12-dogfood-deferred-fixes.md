# Dogfood Deferred Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 11 deferred issues from the 2026-06-10 dogfood QA pass (7 high/medium + 4 low severity).

**Architecture:** All fixes are frontend-only (static/js/) except ISSUE-014 (backend dozzle sanitizer) and ISSUE-003 (backend dozzle route). Most are defensive checks, data-binding fixes, and missing UI wiring.

**Tech Stack:** Vanilla JS (no build tool), FastAPI (Python 3.12), asyncpg

---

## File Map

| File | Issues | What changes |
|------|--------|--------------|
| `static/js/app.js` | 002, 007, 011, 013, 016 | Header update, sidebar highlight, palette sync, badge refresh, console.error |
| `static/js/pages/overview.js` | 002, 010 | Header LED wiring, Promise.all parallelization |
| `static/js/pages/notflix.js` | 008 | Defensive data wrapper check |
| `static/js/pages/dozzle.js` | 003 | Guard against empty containers before log fetch |
| `static/js/pages/uptime.js` | 012 | Sparkline rendering fix |
| `static/js/pages/events.js` | 014 | Frontend ANSI strip (belt-and-suspenders) |
| `static/js/pages/search.js` | 015 | Add sidebar entry for search page |
| `static/js/lib/components.js` | 016 | Add console.error to showError |
| `modules/dozzle/collector.py` | 014 | Strip ANSI escape codes in _sanitize() |
| `modules/dozzle/routes.py` | 003 | Make container_id optional with default behavior |
| `static/index.html` | 015 | Add Search nav item to sidebar |

---

## Task 1: Fix Ticker Header LEDs (ISSUE-002)

**Problem:** Header LEDs (Services, Notifications, Dozzle, Agents, Uptime) permanently show 0/0 / 0 / 0 / 0 / — because `updateHeader()` is never called with real data.

**Files:**
- Modify: `static/js/pages/overview.js:30-31`
- Modify: `static/index.html:22-43` (verify LED element IDs)

- [ ] **Step 1: Define `window.updateHeader` in overview.js**

The overview page already calls `if (window.updateHeader) window.updateHeader();` but the function doesn't exist. Add it after the `loadTicker()` function:

```javascript
window.updateHeader = async function() {
  try {
    var [uptime, events, agents] = await Promise.all([
      window.api('/api/uptime/status').catch(function() { return []; }),
      window.api('/api/events?severity=error&limit=50').catch(function() { return []; }),
      window.api('/api/agent_board/tasks?status=pending').catch(function() { return []; })
    ]);

    // Services LED
    var up = (uptime || []).filter(function(m) { return m.status === 1; }).length;
    var total = (uptime || []).length;
    var servicesEl = document.getElementById('led-services');
    if (servicesEl) servicesEl.textContent = up + '/' + total;

    // Notifications LED (error events in last hour)
    var hourAgo = new Date(Date.now() - 3600000);
    var recentErrors = (events || []).filter(function(e) {
      return new Date(e.ts) > hourAgo;
    }).length;
    var notifEl = document.getElementById('led-notifications');
    if (notifEl) notifEl.textContent = recentErrors;

    // Agents LED
    var pending = (agents || []).length;
    var agentsEl = document.getElementById('led-agents');
    if (agentsEl) agentsEl.textContent = pending + ' pending';

    // Uptime LED (longest downtime or "all up")
    var downMonitors = (uptime || []).filter(function(m) { return m.status === 0; });
    var uptimeEl = document.getElementById('header-uptime');
    if (uptimeEl) {
      if (downMonitors.length > 0) {
        uptimeEl.textContent = downMonitors.length + ' DOWN';
        uptimeEl.style.color = 'var(--danger)';
      } else {
        uptimeEl.textContent = 'ALL UP';
        uptimeEl.style.color = 'var(--status-up)';
      }
    }
  } catch (e) {
    // Header not critical — silently ignore
  }
};
```

- [ ] **Step 2: Call updateHeader on SSE events**

In `static/js/app.js`, add SSE listeners that trigger `updateHeader`:

```javascript
// In the connectSSE function, add after existing listeners:
_sseSource.addEventListener('monitor_status', function(e) {
  try {
    if (window.updateHeader) window.updateHeader();
  } catch(ex) {}
});
```

- [ ] **Step 3: Verify LED element IDs match**

Check `static/index.html` lines 22-43 for element IDs: `led-services`, `led-notifications`, `led-dozzle`, `led-agents`, `header-uptime`. They should match the JS.

- [ ] **Step 4: Commit**

```bash
git add static/js/pages/overview.js static/js/app.js
git commit -m "fix(header): wire updateHeader to real API data for ticker LEDs"
```

---

## Task 2: Parallelize Overview Fetches (ISSUE-010)

**Problem:** Overview page takes 5-10s because widget data is fetched sequentially.

**Files:**
- Modify: `static/js/pages/overview.js:21-35`

- [ ] **Step 1: Refactor loadOverview to use Promise.all**

Replace the sequential calls with parallel:

```javascript
window.loadOverview = async function() {
  // Fire all widget loaders in parallel — each handles its own errors
  await Promise.all([
    loadHealthBar(),
    loadModuleCards(),
    loadActivityFeed(),
    loadRSSHeadlines(),
    loadAgentStatus(),
    loadTicker()
  ]);

  if (window.updateFooter) window.updateFooter();
  if (window.updateHeader) window.updateHeader();
};
```

- [ ] **Step 2: Verify each loader has its own try/catch**

Each function (`loadHealthBar`, `loadModuleCards`, etc.) already has its own try/catch, so one failing won't break the others.

- [ ] **Step 3: Commit**

```bash
git add static/js/pages/overview.js
git commit -m "perf(overview): parallelize widget fetches with Promise.all"
```

---

## Task 3: Fix Dozzle 422 on Empty Containers (ISSUE-003)

**Problem:** When Dozzle is unreachable or returns no containers, the page tries to fetch logs without a valid container_id.

**Files:**
- Modify: `static/js/pages/dozzle.js:31-75`
- Modify: `modules/dozzle/routes.py:172-182`

- [ ] **Step 1: Make container_id optional in backend**

In `modules/dozzle/routes.py`, change `container_id` from required to optional:

```python
container_id: str | None = Query(default=None, description="Container ID (omit for all containers)"),
```

- [ ] **Step 2: Handle None container_id in backend**

Add logic to return recent logs from all containers when no container_id is specified:

```python
# After the container_id check, add:
if not container_id:
    # Return recent events from the database instead of live Dozzle logs
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT source, type, severity, title, body, metadata, ts
               FROM events WHERE source = 'dozzle'
               ORDER BY ts DESC LIMIT $1""",
            limit,
        )
    entries = []
    for row in rows:
        meta = row["metadata"]
        if isinstance(meta, str):
            meta = json.loads(meta)
        entries.append(LogEntry(
            container_name=meta.get("container", "unknown"),
            level=row["severity"],
            message=row["title"] or row["body"] or "",
            timestamp=row["ts"].isoformat() if row["ts"] else "",
        ))
    return {"logs": entries, "count": len(entries)}
```

- [ ] **Step 3: Add defensive check in frontend**

In `static/js/pages/dozzle.js`, add a guard before fetching logs:

```javascript
// In loadDozzlePage, after container selection:
if (!_selectedContainerId) {
  // No container selected — show message, don't fetch logs
  var contentEl = document.getElementById('dozzle-content');
  if (contentEl) {
    contentEl.innerHTML = '<div style="color:var(--muted);text-align:center;padding:30px;">Select a container to view logs.</div>';
  }
  return;
}
```

- [ ] **Step 4: Commit**

```bash
git add static/js/pages/dozzle.js modules/dozzle/routes.py
git commit -m "fix(dozzle): handle empty containers gracefully, make container_id optional"
```

---

## Task 4: Fix Notflix Data Wrapper (ISSUE-008)

**Problem:** API returns `{"data": {...}}` but frontend may read `data.sonarr` directly.

**Files:**
- Modify: `static/js/pages/notflix.js:85-93`

- [ ] **Step 1: Add defensive wrapper check**

In `renderNotflixSnapshot`, add a guard for the data wrapper:

```javascript
function renderNotflixSnapshot(status) {
  var el = document.getElementById('notflix-snapshot');
  if (!el) return;
  if (!status || status.status === 'no_data' || !status.data) {
    el.innerHTML = '<div style="color:var(--muted);padding:10px;">No library snapshot available yet.</div>';
    return;
  }

  // Handle both {data: {sonarr: ...}} and {sonarr: ...} shapes
  var data = status.data || status;
  var ts = status.ts ? window.relativeTime(status.ts) : '';
  // ... rest of function
```

- [ ] **Step 2: Verify activity endpoint shape**

The activity endpoint returns `{"events": [...]}` — verify the frontend reads `response.events` correctly (line 57 already does this).

- [ ] **Step 3: Commit**

```bash
git add static/js/pages/notflix.js
git commit -m "fix(notflix): handle data wrapper shape defensively"
```

---

## Task 5: Fix Sidebar Active Highlight (ISSUE-007)

**Problem:** Clicking some nav items doesn't update the active highlight because `data-page` attribute doesn't match page ID.

**Files:**
- Modify: `static/index.html` (verify all nav items have correct data-page)
- Modify: `static/js/app.js:367-372`

- [ ] **Step 1: Audit all nav items for data-page consistency**

Check that every `<button class="nav-item" data-page="...">` matches the page IDs in `app.js:323-340`. The page IDs are: overview, feeds, uptime, events, wiki, documents, ntfy, dozzle, freshrss, agentboard, kanban, notflix, homeassistant, hermes, settings, notifications.

- [ ] **Step 2: Fix any mismatches**

If any nav items have `data-page="agent_board"` instead of `data-page="agentboard"`, fix them.

- [ ] **Step 3: Commit**

```bash
git add static/index.html
git commit -m "fix(sidebar): ensure data-page attributes match page IDs"
```

---

## Task 6: Sync Command Palette with Sidebar (ISSUE-011)

**Problem:** Command palette missing 6 of 14 pages.

**Files:**
- Verify: `static/js/app.js:182-210`

- [ ] **Step 1: Verify palette page list matches sidebar**

The palette in `app.js:184-201` already has 16 pages including all of them. Verify this matches the current sidebar. If pages are missing, add them.

- [ ] **Step 2: Commit if changes needed**

```bash
git add static/js/app.js
git commit -m "fix(palette): sync page list with sidebar"
```

---

## Task 7: Refresh Sidebar Badges on Navigation (ISSUE-013)

**Problem:** Sidebar badges show stale data because they're only updated once on bootstrap.

**Files:**
- Modify: `static/js/app.js:361-399`

- [ ] **Step 1: Call updateSidebarBadges on navigation**

In `window.navigateTo`, add a call to refresh badges:

```javascript
// After setting currentPage:
window.updateSidebarBadges && window.updateSidebarBadges();
```

- [ ] **Step 2: Commit**

```bash
git add static/js/app.js
git commit -m "fix(sidebar): refresh badges on page navigation"
```

---

## Task 8: Fix Uptime Sparklines (ISSUE-012)

**Problem:** Sparkline code exists but doesn't render because monitor cards lack the expected structure.

**Files:**
- Modify: `static/js/pages/uptime.js:84-94`

- [ ] **Step 1: Verify sparkline data shape**

The `renderSparklines` function expects `monitors[mid]` to be an array of points. Check that `/api/uptime/history/recent?limit=30` returns `{monitors: {monitor_id: [{status: 0|1, ...}]}}`.

- [ ] **Step 2: Add sparkline container div to monitor cards**

In `renderMonitorGrid`, add a div for the sparkline:

```javascript
// In the monitor card HTML, add after mon-meta:
'<div class="sparkline-container" data-monitor-id="' + m.monitor_id + '"></div>'
```

- [ ] **Step 3: Update renderSparklines to target the container**

```javascript
function renderSparklines(monitors) {
  var containers = document.querySelectorAll('#page-uptime .sparkline-container');
  containers.forEach(function(container) {
    var mid = container.dataset.monitorId;
    if (!mid || !monitors || !monitors[mid]) return;
    var svg = buildSparkline(monitors[mid]);
    container.innerHTML = svg;
  });
}
```

- [ ] **Step 4: Commit**

```bash
git add static/js/pages/uptime.js
git commit -m "fix(uptime): wire sparkline rendering to monitor cards"
```

---

## Task 9: Strip ANSI Escape Codes (ISSUE-014)

**Problem:** Dozzle log events contain raw ANSI escape codes that display as `[[32m` in the UI.

**Files:**
- Modify: `modules/dozzle/collector.py:18-21`
- Modify: `static/js/pages/events.js:27-47`

- [ ] **Step 1: Add ANSI stripping to backend _sanitize**

In `modules/dozzle/collector.py`, update the `_sanitize` function:

```python
import re

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

def _sanitize(text: str) -> str:
    """Strip ANSI escape codes, null bytes, and replace non-UTF8 sequences."""
    text = _ANSI_RE.sub('', text)
    text = text.replace("\x00", "")
    return text.encode("utf-8", errors="replace").decode("utf-8")
```

- [ ] **Step 2: Add frontend ANSI strip as belt-and-suspenders**

In `static/js/pages/events.js`, add a helper:

```javascript
function stripAnsi(str) {
  if (!str) return '';
  // Strip ANSI escape codes and their double-bracket variants
  return str.replace(/\x1b\[[0-9;]*m/g, '').replace(/\[\[[0-9;]*m/g, '');
}
```

Use it when rendering title and body:

```javascript
'<td class="truncate-cell" title="' + stripAnsi(ev.title || '') + '">' + stripAnsi(ev.title || '') + '</td>' +
'<td class="truncate-cell" title="' + stripAnsi(bodyPreview) + '">' + stripAnsi(bodyPreview) + '</td>' +
```

- [ ] **Step 3: Commit**

```bash
git add modules/dozzle/collector.py static/js/pages/events.js
git commit -m "fix(dozzle): strip ANSI escape codes in sanitizer and frontend"
```

---

## Task 10: Add Search to Desktop Sidebar (ISSUE-015)

**Problem:** Search page has no desktop sidebar entry.

**Files:**
- Modify: `static/index.html` (add Search nav item)
- Modify: `static/js/app.js:323-340` (add search to pages map)

- [ ] **Step 1: Add Search page to sidebar**

In the Core category section of `index.html`, add after Documents:

```html
<button class="nav-item" data-page="search">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
  <span>Search</span>
</button>
```

- [ ] **Step 2: Add search to pages map in app.js**

In `app.js:323-340`, add:

```javascript
'search': document.getElementById('page-search'),
```

And add to `titles`:

```javascript
'search': 'Search',
```

- [ ] **Step 3: Add keyboard shortcut**

In the `pageMap` for `g` shortcuts (app.js:578-591), add:

```javascript
'q': 'search',
```

- [ ] **Step 4: Commit**

```bash
git add static/index.html static/js/app.js
git commit -m "feat(search): add Search page to desktop sidebar"
```

---

## Task 11: Log Errors to Console (ISSUE-016)

**Problem:** Errors caught in try/catch are displayed in-page but not logged to console for debugging.

**Files:**
- Modify: `static/js/lib/components.js:429-437`

- [ ] **Step 1: Add console.error to showError**

In `window.showError`, add console logging:

```javascript
window.showError = function(message) {
  console.error('[LamaDB]', message);  // <-- Add this line
  var existing = document.querySelector('.error-banner');
  // ... rest of function
```

- [ ] **Step 2: Add console.error to page-level catch blocks**

In each page loader that has a catch block, add `console.error`:

```javascript
// Example pattern for each page:
catch (e) {
  console.error('[LamaDB] Page load error:', e);
  // ... existing error display
}
```

Apply to: overview.js, notflix.js, dozzle.js, uptime.js, events.js, hermes.js, freshrss.js, agent_board.js

- [ ] **Step 3: Commit**

```bash
git add static/js/lib/components.js static/js/pages/*.js
git commit -m "fix(errors): log caught errors to console for debugging"
```

---

## Execution Order

Execute tasks in this order (dependencies noted):

1. **Task 1** (Header LEDs) — standalone
2. **Task 2** (Overview parallelization) — standalone
3. **Task 3** (Dozzle 422) — standalone
4. **Task 4** (Notflix wrapper) — standalone
5. **Task 5** (Sidebar highlight) — standalone
6. **Task 6** (Palette sync) — verify, likely already fixed
7. **Task 7** (Badge refresh) — standalone
8. **Task 8** (Sparklines) — standalone
9. **Task 9** (ANSI codes) — backend + frontend
10. **Task 10** (Search sidebar) — standalone
11. **Task 11** (Console errors) — standalone, do last (touches many files)

**Total estimated effort:** 2-3 hours for a skilled agent.

**Verification:** After all tasks, rebuild and test:
```bash
docker compose build api && docker compose up -d api
# Test each fixed page in browser
```

---

## Success Criteria

| Issue | Before | After |
|-------|--------|-------|
| ISSUE-002 | Ticker shows 0/0 | Ticker shows real counts |
| ISSUE-003 | Dozzle 422 error | Graceful fallback or working logs |
| ISSUE-004 | Hermes crash | Already fixed in 08e90e2 |
| ISSUE-008 | Notflix loading forever | Data renders correctly |
| ISSUE-010 | 5-10s overview load | <2s with parallel fetches |
| ISSUE-007 | Sidebar highlight wrong | Correct highlight on all pages |
| ISSUE-011 | Palette missing pages | All pages in palette |
| ISSUE-013 | Stale badges | Badges refresh on navigation |
| ISSUE-012 | No sparklines | SVG sparklines on monitor cards |
| ISSUE-014 | ANSI codes in events | Clean text |
| ISSUE-015 | No search sidebar | Search in sidebar |
| ISSUE-016 | Errors swallowed | Errors in console |
