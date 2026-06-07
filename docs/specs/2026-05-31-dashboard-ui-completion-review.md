# Dashboard UI Completion — Implementation Review

**Date:** 2026-05-31
**Spec:** `docs/specs/2026-05-31-dashboard-ui-completion-spec.md`
**Tester:** `minimax` (implementation), `claude` (review)

## What was done

Completed three dashboard tabs (Ntfy, Dozzle, Agent Board) from basic renders to fully interactive pages, including 3 new backend endpoints, 13 new tests, and ~150 lines of frontend JS/HTML changes.

## Changes by file

| File | Lines | Change |
|------|-------|--------|
| `modules/ntfy/routes.py` | 178 (+60) | Added `GET /api/ntfy/events` endpoint; added `get_pool` import |
| `modules/agent_board/routes.py` | 489 (+70) | Added `POST /tasks/{id}/unclaim` and `POST /messages/{id}/read` |
| `tests/test_ntfy_events.py` | 208 (new) | 7 tests for ntfy events cache endpoint |
| `tests/test_agent_board.py` | 638 (+106) | 6 tests for unclaim and mark-read |
| `static/index.html` | 4386 (+166) | Frontend JS/HTML/CSS for all three tabs |

No migrations. No new dependencies. No new files beyond the test file.

## Backend endpoints

### `GET /api/ntfy/events`

Reads cached ntfy events from the `events` table (where `source='ntfy'`). Designed as an alternative to the live `/api/ntfy/messages` endpoint which requires a reachable ntfy server.

- **`priority` param** (`all|high|critical`) — maps to SQL `severity = ANY($1)`. Hardcoded severity_map, no raw input in WHERE.
- **`since` param** (`1h|6h|24h`) — maps to SQL `interval '{hardcoded}'`. No user input interpolation.
- **Response** — `{messages: [NtfyMessage], count: int}`. Same shape as `/api/ntfy/messages` so the renderer is shared.
- **Metadata coercion** — `json.loads()` fallback for JSONB columns that asyncpg returns as strings.

### `POST /api/agent_board/tasks/{id}/unclaim`

Resets a claimed task to pending. Validates:
1. Task exists (404)
2. Task is in `claimed` or `in_progress` state (400)
3. User has `admin` or `agent` role (403)

Follows the same pattern as `claim_task` and `complete_task` — check existing status, then UPDATE with RETURNING.

### `POST /api/agent_board/messages/{id}/read`

Sets `read=true` on `agent_messages`. No role restriction — any authenticated user can mark messages as read. Returns `MessageResponse`. The `read` column already existed in `004_agent_board.sql`.

## Test coverage

### ntfy/events (7 tests)
| Test | What it verifies |
|------|-----------------|
| `test_get_ntfy_events_empty` | Returns 200 with empty list |
| `test_get_ntfy_events_returns_events` | Inserted events appear in response |
| `test_get_ntfy_events_priority_critical` | Severity=critical filter works, info events excluded |
| `test_get_ntfy_events_priority_high` | Severity IN (critical, warn) filter works |
| `test_get_ntfy_events_since_param` | Since params (1h/6h/24h) all return 200 |
| `test_get_ntfy_events_read_role_allowed` | Read role can access (no scope restriction) |
| `test_get_ntfy_events_no_auth` | 401 without auth header |

### agent_board (6 new tests, 22 existing)
| Test | What it verifies |
|------|-----------------|
| `test_unclaim_task` | POST → status=pending, claimed_by/claimed_at cleared |
| `test_unclaim_non_claimed_task` | 400 for tasks not in claimed/in_progress |
| `test_unclaim_not_found` | 404 for fake IDs |
| `test_unclaim_forbidden_for_read_role` | 403 for read role |
| `test_mark_message_read` | POST → read=true |
| `test_mark_message_read_not_found` | 404 for fake message IDs |

All 13 pass isolated. One pre-existing test (`test_claim_task`) is intermittently flaky due to async pool state — this is not related to these changes (verified: passes when run alone, sometimes fails in a full suite run due to test isolation).

## Frontend changes

### Ntfy tab
- **Source toggle:** "Events" (reads from cache DB, default) / "Live" (hits ntfy server)
- **Priority filter:** All / High / Critical — filters client-side via query param
- **Auto-refresh:** 30-second interval toggle via checkbox
- **Detail expansion:** Click a row to expand full message body
- **Tab badge:** Shows pending event count from events cache
- **Functions:** `setNtfySource`, `setNtfyPriority`, `toggleNtfyAutoRefresh`, `_ntfyToggleDetail`

### Dozzle tab
- **Container dropdown:** Populated from `/api/dozzle/containers`, filters logs client-side
- **Error count badge:** Fetched from `/api/dozzle/errors?since=1h&limit=1`
- **Detail expansion:** Click a row to expand full log message
- **Functions:** `setDozzleContainer`, `_dozzleToggleDetail`

### Agent Board tab
- **"As:" input:** Configurable agent name for claiming tasks (replaces hardcoded `'muninn'`)
- **Release button:** Unclaims a claimed task via `POST /tasks/{id}/unclaim`
- **Result prompt:** `completeTaskPrompt` asks for optional result text before completing
- **Fixed message filter:** Removed hardcoded `from_agent=muninn`; now uses `_abMsgFilter` and `_abAgentName`
- **Mark as read:** Clicking an unread message row marks it read via `POST /messages/{id}/read`
- **Pending badge:** Shows count of pending tasks on the nav tab
- **Functions:** `setAbAgentName`, `unclaimTask`, `completeTaskPrompt`, `markMessageRead`

### CSS
- `.tab-badge` class added next to existing `.nav-item .badge-nav` styles
- Badge spans added to ntfy, dozzle, agentboard sidebar buttons

## Design notes

- **No new endpoints for Dozzle** — existing `/api/dozzle/containers`, `/api/dozzle/errors`, `/api/dozzle/logs` were sufficient. Container filter is client-side.
- **Events over ntfy live** — the spec called for events cache as the default source. The `/api/ntfy/events` endpoint queries the events table rather than requiring a live ntfy server, making the dashboard usable even when ntfy is down.
- **Interval mapping** — `INTERVAL_MAP` dict prevents SQL injection by mapping user-facing strings to hardcoded values, not interpolating raw user input.
- **Auth posture** — `unclaim` requires admin/agent (task mutation). `mark_read` allows any authenticated user (metadata update, low risk). `ntfy events` allows any authenticated user (no scope gate), which matches the existing pattern — `_require_auth` only checks for a valid key, not role.

## Issues found during review

1. **Minor: `_ntfyToggleDetail` accepts unused second parameter.** The onclick passes `(i, showDetail)` but the function only reads `idx`. Harmless — extra argument is silently ignored by JavaScript.
2. **Minor: `completeTaskPrompt` doesn't distinguish Cancel.** `prompt()` returns `null` on Cancel and `""` on empty-submit — both resolve to `{ result: {} }`. Users can't abort completion once they click the button. Not a regression (new function), but worth noting.
3. **Pre-existing: `escHtml` doesn't escape single quotes.** Task IDs used in onclick handlers are UUIDs (safe), but if the ID source ever changes, this could be an injection vector. Not introduced by this change.
4. **Pre-existing: `test_claim_task` flaky in full suite.** Runs fine in isolation. Caused by shared async pool state during test teardown. Not related to new code.

## Verification

- Build: `docker compose build api` — success
- Deploy: `docker compose up -d` — api and postgres healthy
- API smoke: All 3 new endpoints return correct responses
- Tests: 13/13 new tests pass, no regressions in existing suite
