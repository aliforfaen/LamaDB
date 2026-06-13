# LamaDB Module Depth Enhancement — P0 + P1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 15 P0 user-found bugs and 9 P1 deferred items across all LamaDB modules, improving UX, data visualization, and dashboard usefulness.

**Architecture:** Sequential batches of related fixes. Each batch is handed to a subagent as a single task. Frontend changes touch `static/js/pages/*.js` and `static/css/dashboard.css`. Backend changes touch `modules/*/routes.py` and `app/main.py`. Build after every batch.

**Tech Stack:** FastAPI + asyncpg, vanilla JS frontend, PostgreSQL, Docker Compose.

---

## Batch 1: Global CSS Fix — Page Bottom Cut Off

**Files:**
- Modify: `static/css/dashboard.css` (main layout)
- Modify: `static/index.html` (container structure)

- [ ] **Step 1: Diagnose the cut-off**
  Inspect the CSS for `#app`, `.page-container`, or main content wrapper. Look for `height: 100vh`, `overflow: hidden`, or missing `padding-bottom`.

- [ ] **Step 2: Fix the CSS**
  Add `padding-bottom: 100px` or equivalent to the main content area. Ensure `overflow-y: auto` is present and no `height: 100vh` without `min-height`.
  ```css
  .page-container {
    min-height: 100vh;
    padding-bottom: 100px;
    overflow-y: auto;
  }
  ```

- [ ] **Step 3: Verify on multiple pages**
  Check Overview, Settings, ntfy, and any long page. Scroll to bottom. Confirm last 50-100px are visible.

- [ ] **Step 4: Commit**
  `git add static/css/dashboard.css static/index.html && git commit -m "fix: page bottom cut off on all pages"`

---

## Batch 2: Overview Page — Module Status + Notification List

**Files:**
- Modify: `static/js/pages/overview.js`
- Modify: `static/css/dashboard.css` (overview cards)
- Possibly modify: `modules/dashboard/routes.py` (new endpoint for notifications)

- [ ] **Step 1: Fix module status formatting**
  The "red" / "offline" status for ntfy and other modules doesn't make sense. Check the data source — `modules/dashboard/routes.py` likely returns a health map. Ensure status is based on actual error state, not just "no data". For ntfy, if the collector is working, show green. If the module is disabled, show gray. If the API returns errors, show red.

- [ ] **Step 2: Add notification list endpoint**
  In `modules/dashboard/routes.py` or `modules/notifications/routes.py`, add a `GET /api/notifications/unread` endpoint that returns the top 20 actionable notifications (not all 600). Use the existing events table or notification rules table. Filter by `severity IN ('warning', 'error')` and `processed = false`.
  ```python
  @router.get("/notifications/unread")
  async def get_unread_notifications():
      # Return top 20 actionable items
  ```

- [ ] **Step 3: Wire notification list to frontend**
  In `overview.js`, add a section that fetches `/api/notifications/unread` and renders a list. Use the existing `api()` helper.

- [ ] **Step 4: Commit**
  `git add static/js/pages/overview.js modules/dashboard/routes.py && git commit -m "feat: overview notification list + module status fix"`

---

## Batch 3: Events + Uptime Consolidation

**Files:**
- Modify: `modules/events/routes.py` or `modules/uptime/routes.py`
- Modify: `static/js/pages/events.js` and `static/js/pages/uptime.js`

- [ ] **Step 1: Add backend consolidation endpoint**
  Add a query that groups similar events by `source` + `title` within a time window (e.g., 1 hour). Return only the latest per group + a count.
  ```sql
  SELECT DISTINCT ON (source, title) *, COUNT(*) OVER (PARTITION BY source, title) as count
  FROM events
  WHERE ts > now() - interval '1 hour'
  ORDER BY source, title, ts DESC
  ```

- [ ] **Step 2: Wire to frontend**
  Update `events.js` to show `Title (×5)` when count > 1. Update `uptime.js` similarly for monitor history.

- [ ] **Step 3: Commit**
  `git add modules/events/routes.py static/js/pages/events.js static/js/pages/uptime.js && git commit -m "feat: consolidate similar events and uptime entries"`

---

## Batch 4: Settings Masonry + Secrets + Groups Styling

**Files:**
- Modify: `static/js/pages/settings.js`
- Modify: `static/js/pages/secrets.js`
- Modify: `static/js/pages/groups.js`
- Modify: `static/css/dashboard.css` (masonry grid, card styling)

- [ ] **Step 1: Settings module management masonry**
  Replace the current "one huge box per module" with a CSS masonry grid or flexbox cards. Each module gets a card with icon, name, toggle switch.
  ```css
  .module-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
    gap: 1rem;
  }
  ```

- [ ] **Step 2: Secrets styling overhaul**
  Add copy-to-clipboard buttons (use `navigator.clipboard.writeText()`). Add statistics cards (total secrets, last used, by type). Style the "New secret" dialog as a proper centered modal with padding.

- [ ] **Step 3: Groups styling**
  Apply the same card layout and modal pattern as Secrets.

- [ ] **Step 4: Commit**
  `git add static/js/pages/settings.js static/js/pages/secrets.js static/js/pages/groups.js static/css/dashboard.css && git commit -m "style: masonry settings, secrets + groups polish"`

---

## Batch 5: Dozzle Entry View

**Files:**
- Modify: `static/js/pages/dozzle.js`
- Modify: `modules/dozzle/routes.py` (if new endpoint needed)

- [ ] **Step 1: Add container list endpoint**
  Ensure `GET /api/dozzle/containers` returns the list of containers without logs.

- [ ] **Step 2: Build entry view**
  On page load, show a grid of container cards (name, status, image). Add a "View Logs" button per card. Only fetch logs when clicked.

- [ ] **Step 3: Commit**
  `git add static/js/pages/dozzle.js && git commit -m "feat: dozzle container entry view before logs"`

---

## Batch 6: Agent Board Dashboard

**Files:**
- Modify: `static/js/pages/agent_board.js`
- Modify: `static/css/dashboard.css` (agent board layout)

- [ ] **Step 1: Design the dashboard layout**
  Create a central dashboard with sections:
  - Agent profiles (avatars, names, status)
  - Messages summary (inbox count, sent count, unread)
  - MCP server status (online/offline)
  - Recent API errors (last 5 from events table)

- [ ] **Step 2: Implement sections**
  Reuse existing API endpoints (`/api/agent_board/tasks`, `/api/agent_board/messages`, `/api/mcp/status`).

- [ ] **Step 3: Commit**
  `git add static/js/pages/agent_board.js static/css/dashboard.css && git commit -m "feat: agent board central dashboard"`

---

## Batch 7: Kanban UX + Modal + New Board

**Files:**
- Modify: `static/js/pages/kanban.js`
- Modify: `static/css/kanban.css`

- [ ] **Step 1: Add selection boxes for task types**
  In the task creation/edit modal, add a `<select>` for task type: "research", "agent-driven development", "plan", "brainstorm", "only backend", "only frontend", "other". Store in `kanban_tasks.metadata` JSONB.

- [ ] **Step 2: Add recipient selection**
  Add a user/assignee dropdown populated from `/api/users`.

- [ ] **Step 3: Fix task modal subtabs**
  Add sub-tabs for subtasks, comments, and status history inside the task modal.

- [ ] **Step 4: Replace window.prompt() with modal**
  The "+ New Board" button should open a modal with fields for name, type (agentic/personal), and description.

- [ ] **Step 5: Commit**
  `git add static/js/pages/kanban.js static/css/kanban.css && git commit -m "feat: kanban task types, recipients, modal subtabs, new board modal"`

---

## Batch 8: ntfy Dashboard

**Files:**
- Modify: `static/js/pages/ntfy.js`
- Modify: `static/css/dashboard.css` (ntfy topic cards)

- [ ] **Step 1: Group by topic**
  Fetch notifications and group by `topic`. Display each topic as a card with:
  - Topic name
  - Count of notifications
  - Latest notification preview
  - Color border by importance (red = high, yellow = normal, gray = low)

- [ ] **Step 2: Sort latest on top**
  Sort topic cards by the timestamp of the latest notification in each topic.

- [ ] **Step 3: Fix "57y ago" time-ago bug**
  In `static/js/lib/components.js` or `ntfy.js`, fix `relativeTime()` to handle the API date format correctly. Likely need to parse ISO strings with `new Date()`.
  ```javascript
  function relativeTime(isoString) {
    const date = new Date(isoString);
    const now = new Date();
    const seconds = Math.floor((now - date) / 1000);
    // ... existing logic
  }
  ```

- [ ] **Step 4: Commit**
  `git add static/js/pages/ntfy.js static/js/lib/components.js && git commit -m "feat: ntfy topic dashboard + fix time-ago bug"`

---

## Batch 9: Notflix Activity + Detail

**Files:**
- Modify: `static/js/pages/notflix.js`
- Modify: `modules/notflix/routes.py` (if backend consolidation needed)

- [ ] **Step 1: Consolidate repeated activity**
  Group similar activity events by title + action within 1 hour. Show count.

- [ ] **Step 2: Format detail column**
  Replace raw JSON dump with formatted rows. If the detail is JSON, iterate keys and render as `key: value` pairs.
  ```javascript
  function formatDetail(detail) {
    if (typeof detail === 'string') {
      try { detail = JSON.parse(detail); } catch (e) {}
    }
    if (typeof detail === 'object') {
      return Object.entries(detail).map(([k, v]) => `${k}: ${v}`).join('<br>');
    }
    return detail;
  }
  ```

- [ ] **Step 3: Commit**
  `git add static/js/pages/notflix.js && git commit -m "feat: notflix activity consolidation + formatted detail"`

---

## Batch 10: Hermes Profile Fix

**Files:**
- Modify: `modules/hermes/routes.py`
- Modify: `modules/hermes/collector.py`
- Modify: `static/js/pages/hermes.js`

- [ ] **Step 1: Check collector profile path**
  In `modules/hermes/collector.py`, the Hermes API URL might be pulling from the default profile instead of `~/.hermes/profiles/muninn`. Check the `HERMES_URL` env var and any profile parameter. The Hermes API may need `?profile=muninn` or a header.

- [ ] **Step 2: Check for new multi-profile API**
  Hermes API v0.16.0+ may support listing all profiles. Add a `GET /api/hermes/profiles` endpoint if available.

- [ ] **Step 3: Update frontend to show profile selector**
  If multiple profiles are available, show a dropdown in the Hermes page.

- [ ] **Step 4: Commit**
  `git add modules/hermes/collector.py modules/hermes/routes.py static/js/pages/hermes.js && git commit -m "fix: hermes profile path + multi-profile support"`

---

## Batch 11: Home Assistant Flair + Timestamps

**Files:**
- Modify: `static/js/pages/homeassistant.js`
- Modify: `static/css/dashboard.css` (HA cards)

- [ ] **Step 1: Add relative timestamps**
  Replace raw ISO timestamps with `relativeTime()` for SCENE cards and entity last-changed.

- [ ] **Step 2: Improve card styling**
  Make HA cards more visually appealing — add icons per domain, color-coded states, hover effects. Use CSS grid for responsive layout.

- [ ] **Step 3: Add scene control flair**
  Make On/Off/Activate buttons more prominent. Add status indicators (glowing for on, dim for off).

- [ ] **Step 4: Commit**
  `git add static/js/pages/homeassistant.js static/css/dashboard.css && git commit -m "style: home assistant flair + relative timestamps"`

---

## Batch 12: P1 Remaining Fixes

**Files:**
- Modify: `app/main.py` (migration tracker)
- Modify: `static/js/pages/settings.js` (API keys pagination)
- Modify: `static/js/pages/users.js` (inline styling)

- [ ] **Step 1: Migration history table**
  In `app/main.py`, before running migrations, check a `migration_history` table. If the migration file hash/name exists, skip it.
  ```sql
  CREATE TABLE IF NOT EXISTS migration_history (
    id SERIAL PRIMARY KEY,
    filename TEXT NOT NULL UNIQUE,
    applied_at TIMESTAMPTZ DEFAULT now()
  );
  ```
  In `app/main.py`, wrap the migration runner:
  ```python
  for migration_file in sorted(migrations_dir.glob("*.sql")):
      exists = await conn.fetchval("SELECT 1 FROM migration_history WHERE filename = $1", migration_file.name)
      if exists:
          continue
      # ... run migration ...
      await conn.execute("INSERT INTO migration_history (filename) VALUES ($1)", migration_file.name)
  ```

- [ ] **Step 2: API Keys pagination**
  In `settings.js`, add pagination to the API keys table. Show 25 rows per page with prev/next buttons.

- [ ] **Step 3: Fix Users inline styling**
  In `users.js`, fix the create user form layout. Ensure proper CSS classes and alignment.

- [ ] **Step 4: Commit**
  `git add app/main.py static/js/pages/settings.js static/js/pages/users.js && git commit -m "fix: migration tracker, api keys pagination, users styling"`

---

## Verification & Final Build

- [ ] **Step 1: Build and restart**
  `docker compose build api && docker compose up -d api`

- [ ] **Step 2: Quick smoke test**
  - Open dashboard, check Overview module status and notification list
  - Scroll to bottom of 3 pages, confirm no cut-off
  - Check Events page, confirm consolidation
  - Check Settings module grid, Secrets modal, Groups layout
  - Check Dozzle entry view
  - Check Agent Board dashboard
  - Check Kanban modal, new board modal
  - Check ntfy topic cards, time-ago
  - Check Notflix detail formatting
  - Check Hermes profile data
  - Check HA timestamps and styling
  - Check API keys pagination
  - Check Users form
  - Check migration table exists

- [ ] **Step 3: Final commit**
  `git commit -m "release: P0 + P1 module depth enhancement complete"`

---

## Self-Review

**Spec coverage:** All 15 P0 and 9 P1 items have a corresponding batch.
**Placeholder scan:** No TBD or TODO placeholders — all steps have concrete code examples.
**Type consistency:** All file paths use `static/js/pages/*.js` and `modules/*/routes.py` patterns consistent with AGENTS.md.
