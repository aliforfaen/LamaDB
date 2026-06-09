# LamaDB — Life Console Dashboard + Performance Hardening

> **Date:** 2026-06-09  
> **Session span:** 1 session (5 steps)  
> **Goal:** Redesign the dashboard overview into a "life console" blending system health with personal daily context. Fix a critical CPU saturation bug. Audit performance end-to-end. Dogfood test every page.  
> **Explicitly deferred:** New data-source modules, consumer Life-OS dashboard (separate app), list management CRUD, host topology map, time-series charts, knowledge graph explorer.

## Themes

| Theme | What | Steps |
|-------|------|-------|
| **P0 Fix** | CPU saturation diagnosis and fix | Step 1 |
| **Overview Redesign** | T-shaped life console with 7 draggable widgets | Steps 2–3 |
| **Performance Audit** | Endpoint + page load timing audit | Step 4 |
| **Dogfood QA** | Browser-driven test pass across all 14 pages | Step 5 |

---

## Step 1: CPU Saturation Diagnosis (P0)

### Problem

Container runs at **101% CPU** continuously after rebuild. Every API request takes 13–90 seconds regardless of endpoint complexity. The server responds correctly when it gets CPU time — the event loop is simply starved.

### What's Been Ruled Out

- Poller loops — all have proper `await asyncio.sleep()` intervals (5m–1h)
- SSE pg_listener — has `await asyncio.sleep(30)` in keep-alive loop
- Cache manager — simple in-memory dict, no loops
- Network connections — no stuck TCP queues visible in `/proc/net/tcp`
- Container healthcheck — `/health` responds, doesn't explain full core saturation
- Obvious code bugs — all collectors checked, no tight `while True` without await

### Diagnosis Approach

1. Install light profiling tools in the container: `py-spy` or use built-in `faulthandler` to dump Python thread stacks
2. Identify which thread/task is burning CPU
3. Trace root cause (likely: a background task not yielding, or blocking sync call in async context)
4. Fix the issue and verify CPU drops below 5% idle

### Success Criteria

- `docker stats` shows < 5% CPU at idle
- `GET /api/dashboard/overview` responds in < 500ms
- All other endpoints respond in < 1s

### Agent

`troubleshooter` (diagnosis) → `backend` (apply fix). Troubleshooter brings extended thinking and fresh perspective for deep debugging.

---

## Step 2: Backend — User Layout Persistence

### New Migration

`migrations/011_user_layouts.sql`:

```sql
CREATE TABLE IF NOT EXISTS user_layouts (
    user_id TEXT NOT NULL,
    page TEXT NOT NULL DEFAULT 'overview',
    layout JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (user_id, page)
);
```

### New Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/api/dashboard/user-layout?page=overview` | Bearer (any) | Returns saved widget order: `{"widgets": ["health", "modules", "activity", "rss", "agents", "scratchpad"]}` |
| `PUT` | `/api/dashboard/user-layout?page=overview` | Bearer (any) | Saves widget order. Body: `{"widgets": [...]}`. Validates widget IDs against known list. |

### Implementation

- Add to `app/core/dashboard.py` or new `app/core/user_layouts.py`
- `user_id` derived from API key name (from auth dependency) — no user accounts yet, but this lays the groundwork
- Simple JSON validation: reject unknown widget IDs
- Cache invalidation: invalidate tag `user_layouts` on PUT

### Agent

`backend` — migration, routes, validation.

---

## Step 3: Frontend — Overview Page Redesign

### Layout (T-Shaped)

```
┌─────────────────────────────────────────────────────┐
│  Live Ticker (existing — keep as-is)                │
├─────────────────────────────────────────────────────┤
│  Health Bar (fixed, always visible)                 │
│  🟢 33/35 up │ 📊 87% cache │ 📝 1,247 docs │ ⚡ 12 events │ 🗄️ DB ok │
├───────────────────────────┬─────────────────────────┤
│  Module Status Cards      │  RSS Headlines          │
│  (3×3 draggable grid)     │  (latest 5 articles)    │
│                           │                         │
│  ┌──────┐ ┌──────┐ ┌─────┐│  📰 "AI writes its OS"  │
│  │uptime│ │hermes│ │frss ││  📰 "Rust 2026"         │
│  └──────┘ └──────┘ └─────┘│  📰 "LLM patterns"      │
│  ┌──────┐ ┌──────┐ ┌─────┐├─────────────────────────┤
│  │ ntfy │ │dozzle│ │ntflx││  Agent Status           │
│  └──────┘ └──────┘ └─────┘│  🤖 Hermes · 3 sessions │
│  ┌──────┐ ┌──────┐ ┌─────┐│  🤖 Muninn · offline    │
│  │ wiki │ │feeds │ │notif│├─────────────────────────┤
│  └──────┘ └──────┘ └─────┘│  Quick Capture           │
│                           │  [___________________]   │
│  Recent Activity Feed     │  [Save]                  │
│  18:20 hermes: session... │                         │
│  18:15 ⚠ dozzle: WARN...  │                         │
│  18:10 freshrss: 42 arts  │                         │
│  18:05 wiki: page update  │                         │
│  17:58 🔴 uptime: DOWN    │                         │
└───────────────────────────┴─────────────────────────┘
```

### Widgets (7 Total)

| # | Widget | Data Source | Refresh Strategy | States |
|---|--------|------------|------------------|--------|
| 1 | **Health Bar** | `GET /api/dashboard/overview` + `GET /api/uptime/status` | Poll 30s | Green (all ok), Yellow (degraded), Red (down) |
| 2 | **Module Cards** | `GET /api/dashboard/module-health` | Poll 60s | Green (fresh data), Yellow (stale >2x interval), Red (errors), Grey (disabled) |
| 3 | **Activity Feed** | `GET /api/events?limit=20` | SSE push | Scrollable, color-coded by severity |
| 4 | **RSS Headlines** | `GET /api/freshrss/articles?limit=5` | Poll 120s | Empty state: "No unread articles" |
| 5 | **Agent Status** | `GET /api/hermes/sessions/stats` + `GET /api/agent_board/inbox/count` | Poll 60s | Online/offline, session count, unread badge |
| 6 | **Quick Capture** | `POST /api/documents` (source_type=`scratchpad`) | On submit | Idle (placeholder text), Submitting (spinner), Success (toast + clear) |
| 7 | **Live Ticker** | Existing ticker code + SSE | Existing SSE | Keep as-is — no changes needed |

### Drag-and-Drop Implementation

- **Library:** SortableJS loaded via CDN (`<script src="https://cdn.jsdelivr.net/npm/sortablejs@1/Sortable.min.js">`)
- **Scope:** Module cards grid only (3×3). Other widgets (activity feed, RSS, agents, scratchpad) have fixed positions in the right column.
- **On drag end:** Call `PUT /api/dashboard/user-layout` with new widget order
- **On page load:** Call `GET /api/dashboard/user-layout` → apply saved order; fall back to default order
- **Visual feedback:** Drag ghost with opacity, drop placeholder highlight

### Empty / Error / Loading States

Every widget must handle three states:

| Widget | Loading | Empty | Error |
|--------|---------|-------|-------|
| Health Bar | Skeleton shimmer | "No data yet" | Greyed out with "Status unavailable" |
| Module Cards | Skeleton card grid | n/a (modules always exist) | Red dot + "Error loading" |
| Activity Feed | Skeleton lines | "No recent activity" | "Feed unavailable" |
| RSS Headlines | Skeleton lines | "No unread articles" | "RSS unavailable" |
| Agent Status | Skeleton lines | "No agents connected" | "Agent API unreachable" |
| Quick Capture | n/a | Placeholder text | Toast: "Failed to save" |

### Files

| Action | File | Description |
|--------|------|-------------|
| **Rewrite** | `static/js/pages/overview.js` | New widget-based renderer replacing old `loadOverview()` |
| **Create** | `static/js/lib/dragdrop.js` | SortableJS integration + layout save/load helpers |
| **Modify** | `static/index.html` | Replace overview section HTML, add CDN script + SortableJS init |
| **Modify** | `static/css/dashboard.css` | Widget card styles, health bar, grid layout, drag ghost, empty/error states |

### Agent

`frontend` — all HTML/CSS/JS work. `backend` only for Step 2 (user-layout endpoint).

---

## Step 4: Performance Audit

### Goal

After CPU is unblocked (Step 1), verify everything is fast. Find and flag remaining bottlenecks.

### API Endpoint Audit

- Hit all 28+ API endpoints via timed curl/httpx
- Record p50, p95, p99 response times
- Flag any endpoint > 1s p95
- Check cache effectiveness: `GET /api/dashboard/cache-stats` → verify hit rate > 60% on cached endpoints
- Extend existing `benchmarks/` scripts if useful

### Page Load Audit

- Using `agent-browser`, load each of the 14 dashboard pages
- Measure: DOMContentLoaded, first contentful paint, time to interactive
- Flag any page > 3s to interactive
- Check for render-blocking resources, excessive API calls on page load

### Report

- Table: endpoint → p50/p95/p99 → notes
- Table: page → load metrics → notes
- Top 5 optimization targets with suggested fixes

### Agent

`tester` — all timing, benchmarking, and reporting.

---

## Step 5: Dogfood Testing Pass

### Goal

Systematic QA of every dashboard page. Find bugs, broken layouts, missing data, console errors.

### Test Plan

1. **Auth flow:** Login with valid key → sidebar appears. Invalid key → auth modal.
2. **All 14 pages:** Click each sidebar item. Verify:
   - Page renders without JS console errors
   - Data loads (or shows appropriate empty state)
   - No layout breakage
   - Screenshot each page at 1440px width
3. **Mobile (375×812):** Verify:
   - Sidebar collapses to bottom tab bar
   - Cards stack vertically
   - No horizontal overflow
   - Tables are readable (card view fallback)
4. **Command palette:** Cmd+K → type page name → navigates. `g d` → Documents. `?` → shortcut overlay.
5. **Theme toggle:** Light → Dark → System preference. CSS custom properties update correctly.
6. **SSE real-time:** POST new event via API → verify dashboard updates within 2 seconds.
7. **Settings page (post CPU fix):** Module config forms load, API keys tab works, cache stats display.

### Report

- List of issues found: severity (P0/P1/P2), page, description, repro steps, screenshot
- "All clear" if no issues found (expected after CPU fix)

### Agent

`tester` using `agent-browser` skill. Screenshots saved to `dogfood-screenshots/`.

---

## Execution Order

1. **Step 1** — CPU diagnosis (P0, blocks everything else)
2. **Step 2** — Backend user-layout endpoint (independent, can run in parallel with Step 1)
3. **Step 3** — Frontend overview redesign (depends on Step 2)
4. **Step 4** — Performance audit (depends on Step 1 — needs CPU unblocked)
5. **Step 5** — Dogfood pass (depends on Steps 1–3 — needs working dashboard)

## Agent Summary

| Step | Agent(s) | Type of Work |
|------|----------|--------------|
| 1 | `troubleshooter` → `backend` | Deep debug + fix |
| 2 | `backend` | Migration + 2 endpoints |
| 3 | `frontend` | HTML/CSS/JS (overview.js, dragdrop.js, CSS) |
| 4 | `tester` | API timing + page load benchmarking |
| 5 | `tester` (agent-browser) | Browser automation QA + screenshots |

## Rules

- Quality before speed. Troubleshooter runs first — no code changes before root cause is found.
- Steps 1 and 2 are independent — can run in parallel.
- Steps 4 and 5 run after 1–3 complete.
- Testing stays lean — targeted perf checks and browser smoke test, no test suite over-engineering.
- Keep the fun ratio high — this is a for-fun learning project.

## Non-Goals (explicitly out of scope)

- Host topology map, time-series charts, knowledge graph explorer, calendar heatmap (deferred to future phases)
- Consumer Life-OS dashboard as a separate application
- New data-source modules (Spotify, Home Assistant, body/health tracking)
- List management CRUD
- CI/CD pipelines, test coverage metrics
- Redis/external cache dependencies
- Changing API_KEY_SALT
- Rewriting existing modules (extend, don't replace)
