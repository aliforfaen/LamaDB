# LamaDB Module Audit

> Last updated: 2026-06-08 | Maintained by: agents (update when adding endpoints)

## Module Status

| Module | Endpoints | Test Coverage | Known Issues |
|--------|-----------|---------------|--------------|
| Core (documents) | 5 (CRUD + links) | ✅ test_dashboard.py | None |
| Core (events) | 3 (POST/GET/PATCH) | ✅ test_dashboard.py | None |
| Core (search) | 2 (full-text, semantic) | ❌ no dedicated tests | None |
| Core (dashboard) | 12 (overview, modules, health, keys, etc.) | ✅ test_dashboard.py | SSE endpoint not in tests |
| Core (cache) | 1 (stats) | ✅ test_cache.py + test_dashboard_cache_stats.py | New — 11 tests passing |
| feeds | 6 (CRUD + public XML) | ✅ test_feeds.py | None |
| uptime | 7 (webhook, status, history, topology, recent, tags, ticker) | ✅ test_uptime.py | None |
| agent_board | 11 (tasks CRUD, messages, unclaim, read) | ❌ no dedicated tests | Inbox endpoints planned (S5) |
| freshrss | 4 (status, feeds, articles, sync) | ❌ no dedicated tests | Needs FRESHRSS_USERNAME + API_PASSWORD |
| ntfy | 1 (messages) | ❌ no dedicated tests | None |
| dozzle | 1 (containers) | ✅ test_dozzle_collector.py | Dozzle v10.6.5 migrated |
| notflix | 3 (status, activity, health) | ❌ no dedicated tests | Empty placeholders — needs keys |
| hermes | 7 (health, system, stats, sessions, ingest, costs, health-snapshot) | ✅ test_hermes_ingest.py | Hermes running: reachable |
| wiki | 4 (pages, page, log, scratchpad) | ❌ no dedicated tests | Read-only filesystem mount |
| notifications | 3 (rules CRUD) | ❌ no dedicated tests | None |

## Smoketest Coverage

Dashboard smoke test (`tests/smoke_test_dashboard.py`): 28 endpoints, 27 pass / 1 skip (dozzle)
