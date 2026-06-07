# Test Suite Fix — Spec Sheet

> **For MiniMax-M2.7-highspeed via MiniMax:** Self-contained fix spec. All paths relative to `/home/messhias/LamaFiles/projects/lamadb/`.

**Goal:** Fix two bugs that make the test suite unusable:
1. Suite hangs forever (background poller tasks never cancelled)
2. Wiki DB tests fail with 409 Conflict (stale test data from previous runs)

**Repo:** `/home/messhias/LamaFiles/projects/lamadb/`
**Tech:** Python 3.12, FastAPI, asyncpg, pytest-asyncio
**Tests run inside Docker:** `docker exec lamadb_api python3 -m pytest tests/ -v`

---

## Bug 1: Suite Hangs — Background Tasks Never Cancelled

### Root Cause

`app/main.py` lifespan starts background poller tasks:

```python
# Line 78-85
for module_name, interval in [("freshrss", 900), ("ntfy", 300), ("dozzle", 300), ("notflix", 1800)]:
    asyncio.create_task(poller_loop(module_name, interval))
```

And the uptime poller (line 88-94). These tasks run `while True` loops. When the lifespan exits (`yield` returns), these tasks are **never cancelled**. They keep the event loop alive forever.

Every test file creates a new app via `make_app()` → enters lifespan → spawns new poller tasks → tasks never die → pytest hangs.

### Fix

Modify `app/main.py` lifespan to track and cancel all background tasks:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: connect DB, run migrations, close DB."""
    logger.info("Starting LamaDB...")
    pool = await create_pool()
    await run_migrations(pool)

    # Track background tasks so we can cancel them on shutdown
    background_tasks: set[asyncio.Task] = set()

    for module_name, interval in [("freshrss", 900), ("ntfy", 300), ("dozzle", 300), ("notflix", 1800)]:
        try:
            mod = __import__(f"modules.{module_name}", fromlist=["ENABLED", "collect"])
            if getattr(mod, "ENABLED", False) and hasattr(mod, "collect"):
                task = asyncio.create_task(poller_loop(module_name, interval))
                background_tasks.add(task)
                task.add_done_callback(background_tasks.discard)
                logger.info(f"Started poller: {module_name} (every {interval}s)")
        except ImportError:
            pass

    # Uptime Kuma poller
    if settings.uptime_kuma_url and settings.uptime_kuma_api_key:
        try:
            from modules.uptime.poller import start_poller
            start_poller()
        except ImportError:
            pass

    # Notification rules seed
    try:
        from modules.notifications.engine import seed_default_rules
        await seed_default_rules()
    except (ImportError, Exception):
        pass

    yield

    # SHUTDOWN: Cancel all background tasks
    for task in background_tasks:
        task.cancel()
    # Wait for tasks to finish cancelling
    if background_tasks:
        await asyncio.gather(*background_tasks, return_exceptions=True)

    await close_pool()
    logger.info("Shutdown complete")
```

### Also fix: uptime poller needs cancellation

Check `modules/uptime/poller.py` — if it uses a `while True` loop with `asyncio.sleep`, the `start_poller()` function likely creates a task too. If it doesn't return the task handle, you may need to modify it to return the task so lifespan can track it.

If `start_poller()` uses `asyncio.create_task()` internally, modify it to return the task:

```python
# In modules/uptime/poller.py
def start_poller() -> asyncio.Task:
    task = asyncio.create_task(_poller_loop())
    return task
```

Then in lifespan:
```python
from modules.uptime.poller import start_poller
task = start_poller()
background_tasks.add(task)
task.add_done_callback(background_tasks.discard)
```

---

## Bug 2: Wiki DB Test Isolation — Stale Data Causes 409

### Root Cause

`cleanup_wiki_pages` fixture in `tests/test_wiki_db.py` requires tests to **manually register** page IDs:

```python
@pytest_asyncio.fixture(scope="function")
async def cleanup_wiki_pages(db_pool):
    created_ids = []
    async def register(page_id: str):
        created_ids.append(page_id)
    yield register
    for page_id in created_ids:
        # cleanup...
```

If a test crashes before `cleanup(data["id"])` runs, the page persists. Next run → 409 Conflict on duplicate path.

### Fix

Replace the manual cleanup with a **pre-test + post-test sweep** that deletes ALL wiki pages with test paths:

```python
@pytest_asyncio.fixture(scope="function", autouse=True)
async def cleanup_wiki_pages(db_pool):
    """Clean up ALL test wiki pages before and after each test."""
    async def _cleanup():
        async with db_pool.acquire() as conn:
            # Delete document links for test wiki pages
            await conn.execute(
                """DELETE FROM document_links
                   WHERE source_id IN (
                     SELECT id FROM documents
                     WHERE source_type = 'wiki_page'
                       AND metadata->>'path' LIKE 'test/%'
                   )"""
            )
            # Delete test wiki pages
            await conn.execute(
                """DELETE FROM documents
                   WHERE source_type = 'wiki_page'
                     AND metadata->>'path' LIKE 'test/%'"""
            )

    # Pre-test cleanup (handles leftover data from crashed previous runs)
    await _cleanup()

    yield

    # Post-test cleanup
    await _cleanup()
```

This way:
- Every test starts with a clean slate (no stale data)
- Every test ends with cleanup (no leaked data)
- No manual registration needed — `make_page()` helper no longer needs `cleanup=` parameter
- The `cleanup_wiki_pages` fixture parameter can be removed from test signatures

### Also clean up api_keys

The conftest `seed_test_api_key` fixture creates a key but never cleans it up. Since tests also create their own admin_key/agent_key/read_key, stale keys accumulate. Add cleanup:

```python
@pytest_asyncio.fixture(scope="function", autouse=True)
async def seed_test_api_key():
    conn = await asyncpg.connect(settings.database_url)
    try:
        await conn.execute(
            """INSERT INTO api_keys (name, key_hash, role, scopes, active)
               VALUES ($1, $2, $3, $4, true)
               ON CONFLICT (key_hash) DO NOTHING""",
            "test-agent",
            "$2b$12$oEdTQNnKaKXLHg9EkfoYkeOrQnQHYsbC06jjudpYZfmbnLfk90k8i",
            "admin",
            ["feeds", "uptime", "documents", "dashboard", "wiki", "agent_board", "ntfy", "dozzle", "freshrss", "notflix"],
        )
    finally:
        await conn.close()
```

This already uses `ON CONFLICT DO NOTHING` so it's idempotent. No change needed here, but the per-test-file admin_key/agent_key/read_key fixtures DO have cleanup (they delete by name). That's fine.

---

## Verification

After both fixes, run:

```bash
docker exec lamadb_api python3 -m pytest tests/ -v --timeout=30
```

Expected:
- All 187 tests complete (no hanging)
- No 409 Conflict errors
- Test run completes in under 2 minutes

If `--timeout` flag requires pytest-timeout package, install it first:
```bash
docker exec lamadb_api pip install pytest-timeout
```

---

## Pitfalls

- `asyncio.gather(*tasks, return_exceptions=True)` is critical — without `return_exceptions=True`, a `CancelledError` from one task would prevent waiting for others
- The `task.add_done_callback(background_tasks.discard)` prevents memory leaks from the set growing
- `test_` prefix path matching (`metadata->>'path' LIKE 'test/%'`) ensures we only delete test data, never real wiki pages
- Don't change the autouse `seed_test_api_key` fixture — it's fine as-is
- Some test files define their own `client` fixture (not from conftest). That's intentional — don't consolidate them

## Files to Modify

1. `app/main.py` — lifespan task tracking + cancellation
2. `modules/uptime/poller.py` — return task handle from `start_poller()`
3. `tests/test_wiki_db.py` — replace cleanup fixture, remove `cleanup_wiki_pages` param from test signatures
4. `tests/conftest.py` — optionally add wiki cleanup here if you want it shared across test files
