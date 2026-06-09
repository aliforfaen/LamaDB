# Dashboard Frontend Bug Fix — 2026-06-09

> Sources: AI Agent session, 2026-06-09
> Raw: [Session Log](../../raw/lamadb/2026-06-09-dashboard-frontend-bugfix-session.md)

## Overview

Fixed multiple dashboard pages in LamaDB that were broken or degraded after an OpenCode refactoring split the frontend into separate page modules. The root cause was a missing `window.api` export — the `api()` function was defined inside an IIFE but never exposed globally. All 14 page modules call `window.api(...)` (~76 callsites), causing every authenticated page to silently fail.

## Changes

### Root Fix (1 line)
- `static/js/app.js`: Added `window.api = api;` after the function definition. Single-line fix that unblocks all page modules.

### Page-specific Fixes

| Page | Issues | Fixes |
|------|--------|-------|
| **Ntfy** | DOM ID mismatch, wrong CSS selector, 5 missing functions, wrong API response handling | `#ntfy-messages`→`#ntfy-content`, `.sub-tab-btn`→`[id^=]`, added `setNtfySource`/`setNtfyPriority`/`setNtfySince`/`toggleNtfyAutoRefresh`/`syncNtfy`, `data.messages \|\| data` |
| **Dozzle** | DOM ID mismatch, wrong CSS selector, 2 missing functions | `#dozzle-logs`→`#dozzle-content`, `.sub-tab-btn`→`[id^=]`, added `setDozzleSince`/`syncDozzle` |
| **Hermes** (HTML) | DOM IDs mismatched between HTML and JS | Changed `hermes-cards`→`hermes-sys-cards`, `hermes-session-stats`→`hermes-stats`, added `<tbody>` for sessions |

### Parallelization

Sequential API calls made parallel via `Promise.all` in 5 pages:

| Page | Endpoints | Before | After |
|------|-----------|--------|-------|
| Overview | events, uptime, feeds | 3 sequential calls (~3×RTT) | Parallel |
| Hermes | system, sessions/stats, sessions | 3 sequential | Parallel |
| FreshRSS | status, feeds | 2 sequential | Parallel |
| Notifications | rules, log | 2 sequential | Parallel |
| Notflix | status, activity | 2 sequential | Parallel |

### Pre-existing Issues (Not Fixed)

- **Dozzle `/logs` endpoint** requires `container_id` query param; frontend doesn't provide it → 422 error. Needs container discovery flow first.
- **Hermes API** is an external service not running in dev/CI → dashboard tab shows error states.

## Verification

- Docker build + restart successful; API healthy
- Overview page fully functional (stat cards, events, uptime, feeds)
- Settings page loads modules, API keys, health cards
- All `window.*` functions properly exported
- 47 backend tests passing (dashboard, cache, SSE, hermes)

## See Also

- [LamaDB Project Context](../../../AGENTS.md)
