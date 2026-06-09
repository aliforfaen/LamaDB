# Life Console Dashboard + Performance Hardening — 2026-06-09

> Sources: AI Agent session, 2026-06-09
> Raw: [Spec](../../docs/superpowers/specs/2026-06-09-life-console-dashboard-design.md), [Plan](../../docs/superpowers/plans/2026-06-09-life-console-dashboard-plan.md)

## Overview

Major session overhauling LamaDB's dashboard overview into a "Life Console" — a T-shaped widget dashboard blending system health with personal daily context. Fixed two critical performance bottlenecks (CPU saturation, O(N) auth) that made the dashboard unusable. Deployed server-side layout persistence and drag-and-drop module reordering.

## Performance Fixes (P0)

### CPU Saturation (101% → 0.10%)

**Root cause:** Dozzle collector fetched all log levels (info, debug, warn, error) from all 40 containers every 5 minutes, generating 3000+ events per cycle with zero deduplication. Each event INSERT fired a NOTIFY trigger, flooding the SSE listener with 3000+ coroutine schedules. Secondary: synchronous bcrypt/pathlib/UptimeKumaApi calls blocked the async event loop.

**Fixes:**
- `modules/dozzle/collector.py` — SHA-256 content dedup keys, error/warn-only filtering, 50-event per-container cap, `asyncio.to_thread()` for JSON parsing
- `app/auth.py`, `app/main.py`, `app/core/dashboard.py`, `app/config.py` — all synchronous calls (bcrypt, pathlib reads) wrapped in `asyncio.to_thread()`
- `modules/uptime/poller.py` — UptimeKumaApi sync calls wrapped in `asyncio.to_thread()`
- `app/sse.py` — simplified SSE callback from double-scheduling to `run_coroutine_threadsafe()`
- `app/main.py` — poller error exponential backoff, cached module imports

### O(N) Auth Bottleneck (13s → 230ms)

**Root cause:** `get_current_user()` in `app/auth.py` performed a linear scan over all 62 active API keys, running bcrypt verification (217ms each) on every request. Every authed endpoint took 7-13s regardless of handler complexity.

**Fix:** Added `key_prefix` column to `api_keys` table (SHA-256 hash of first 16 key characters). Auth now does O(1) DB lookup via prefix index before single bcrypt verification. Backward-compatible: existing keys auto-backfill on first successful auth.

| Metric | Before | After |
|--------|--------|-------|
| CPU idle | 101% | 0.10% |
| Auth time | 7–13s | 230ms |
| `/health` endpoint | 13–90s | 3ms |
| Overview page | 90s | 230ms |

## Overview Redesign ("Life Console")

### Layout

T-shaped: fixed health bar at top, two-column grid below.

| Column | Content |
|--------|---------|
| **Health Bar** (top, fixed) | Services up/down, cache hit rate, document count, events today, DB status — polls 30s |
| **Left (2/3)** | Module Status Cards (3×3 draggable grid, 60s poll), Recent Activity Feed (20 events, 60s poll) |
| **Right (1/3)** | RSS Headlines (5 articles, 120s poll), Agent Status (Hermes + Agent Board, 60s poll), Quick Capture (scratchpad textarea) |

Live ticker bar retained unchanged at very top.

### Drag-and-Drop

Module cards are draggable via SortableJS (CDN). On drag end → `PUT /api/dashboard/user-layout` saves card order. On page load → `GET /api/dashboard/user-layout` restores. Layout persisted server-side in `user_layouts` table (per API key user).

### Files Changed

| File | Change |
|------|--------|
| `static/js/pages/overview.js` | Rewritten (104→286 lines): 7 widget renderers with polling, error/empty/skeleton states |
| `static/js/lib/dragdrop.js` | New: SortableJS init, layout save/load, instance tracking |
| `static/index.html` | Overview HTML section replaced, SortableJS CDN added |
| `static/css/dashboard.css` | ~280 lines of new widget styles (scoped to `#page-overview`) |
| `app/core/dashboard.py` | `GET/PUT /api/dashboard/user-layout` endpoints |
| `migrations/012_user_layouts.sql` | New table with `(user_id, page)` PK and JSONB layout |

## Dogfood QA Results

33 screenshots, 0 console errors across all 15 pages. 8 bugs found:

**P0 (1):** Notifications page title displays `[object HTMLElement]` — one-line fix in `app.js:311`
**P1 (4):** Agent Board tasks stuck (ID mismatch), FreshRSS articles stuck (`.map()` on object), Dozzle 422 (missing query param), Hermes unreachable (upstream down)
**P2 (3):** Uptime sparklines regression (Phase 8B, endpoint returns `[]`), Overview render race on first auth (recovers on F5), Settings sidebar paint on scroll

Working great: SSE real-time (2s latency), command palette, keyboard shortcuts, theme toggle, mobile layout, auth flow.

## Key Decisions

- **Drag-drop scope:** Module cards only. Other widgets have fixed positions. Layout saved per-user via API key name.
- **Cache stats:** Removed from health bar (query-param auth not available from Bearer-authenticated pages). Shows `--` gracefully.
- **Auth prefix:** SHA-256 over first 16 key chars. 64-bit discriminator space, negligible collision risk for 81 keys.
- **Migration numbering:** `012_` used (011_ was already taken by dashboard notify triggers).

## Commits (8 total)

```
e2a21ea perf(auth): O(1) key lookup via prefix hash
0ceca0a fix(dashboard): timer leak, closure bug, CSS scoping, SortableJS re-init
b0f822c fix(dashboard): match module-health API fields and add activity feed polling
0b635f9 feat(dashboard): redesign overview as life console with 7 draggable widgets
84ecab4 fix(migration): rename 011_user_layouts → 012
061498c feat(dashboard): add user-layout persistence for drag-and-drop
8d8b326 fix(perf): wrap remaining sync calls (bcrypt, pathlib) in asyncio.to_thread
5361dea fix(perf): resolve CPU saturation with poller optimizations and dozzle dedup
```

## See Also

- [Dashboard Frontend Bug Fix](dashboard-frontend-bugfix-2026-06-09.md) — previous session fixing pages after JS refactoring
- [AGENTS.md](../../AGENTS.md) — project architecture and feature map
