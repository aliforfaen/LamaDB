# Test Suite Overhaul — Spec Sheet

> **For the coding agent:** Fix the LamaDB test suite. Two approaches tried, lessons learned below. The goal: all 187 tests pass, run in under 60 seconds.

## Context

**Repo:** `/home/messhias/LamaFiles/projects/lamadb/`
**Tests run inside Docker:** `docker exec lamadb_api python3 -m pytest tests/ -q`
**Build/restart cycle:** `docker compose build api` then `docker compose create api && docker compose start api`
**IMPORTANT:** Terminal tool blocks `docker compose up` — use `create` + `start` separately.

## Current State

We tried session-scoped fixtures to make tests fast. Two problems:
1. asyncpg pool created in session event loop can't be used from function-scoped test loops
2. Fixture-stripping regex accidentally removed test-specific fixtures (sample_task, sample_feed, etc.)

## The Right Approach

**Keep function-scoped fixtures** but make them fast:

### Step 1: Revert pytest.ini
```ini
[pytest]
asyncio_mode = auto
asyncio_default_fixture_loop_scope = function
```

### Step 2: Restore test files from git
```bash
cd /home/messhias/LamaFiles/projects/lamadb
git checkout HEAD~1 -- tests/
```
This restores all test files to the committed state (with per-file fixtures).

### Step 3: Re-apply only the wiki_db.py fixes
The committed test_wiki_db.py still has the old cleanup fixture. Re-apply:
1. Replace `cleanup_wiki_pages` fixture with autouse version that sweeps `test/%` paths
2. Remove `cleanup=cleanup_wiki_pages` from `make_page()` calls
3. Remove `cleanup_wiki_pages` from test function signatures

### Step 4: Add LAMADB_SKIP_POLLERS to conftest.py
The conftest.py already has `os.environ["LAMADB_SKIP_POLLERS"] = "1"` — keep that.

### Step 5: Verify tests pass
```bash
docker compose build api
# restart container
docker exec lamadb_api python3 -m pytest tests/ -q --tb=line 2>&1 | tail -5
```

### Step 6: Also apply LAMADB_SKIP_POLLERS to each test file's client fixture
Each test file creates its own `client` fixture which enters the lifespan. Add `os.environ["LAMADB_SKIP_POLLERS"] = "1"` before `make_app()` in each file's client fixture, OR rely on conftest setting it at import time (it's set module-level, so it should work).

Actually, since conftest.py sets `os.environ["LAMADB_SKIP_POLLERS"] = "1"` at module level (before any test imports), the lifespan will see it. No per-file changes needed for this.

## Expected Result
- All 187 tests pass
- Run time under 60 seconds (with LAMADB_SKIP_POLLERS)
- No event loop mismatches
- No missing fixtures

## Pitfalls
- `docker compose up` is blocked by terminal tool — use `create` + `start`
- Static files are COPY'd into image — must rebuild after any file change
- Migration warnings about PL/pgSQL syntax are non-fatal — ignore them
- The `admin_key` fixture creates a unique key per test using `uuid4().hex` — don't use fixed key names or cleanup will collide
