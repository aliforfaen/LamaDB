"""LamaDB FastAPI application with module auto-discovery."""
import asyncio
import hashlib
import logging
import time
import faulthandler
import signal
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.cache import cache_manager
from app.config import settings
from app.db import create_pool, close_pool, get_pool
from app.sse import pg_listener, _make_notify_callback, sse_manager

# Enable faulthandler for on-demand stack dumps (SIGUSR1)
faulthandler.register(signal.SIGUSR1, all_threads=True)

# Import core routers
from app.core.documents import router as documents_router
from app.core.events import router as events_router
from app.core.search import router as search_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


async def run_migrations(pool) -> None:
    """Execute pending migration files, tracking each in migration_history.

    Contract:
      * A migration is recorded in ``migration_history`` only after every
        statement in its file succeeds. If any statement raises a
        non-idempotent error, the entire file is rolled back and no row is
        inserted (so the next startup will retry it).
      * Idempotent failures (``already exists`` / ``duplicate ...``) are
        tolerated and logged at INFO — they do not roll back the file.
      * Already-applied files are skipped via the ``migration_history``
        primary key.
      * On a legacy database that predates ``migration_history`` (table
        empty but legacy tables present), every existing migration file is
        backfilled into ``migration_history`` with a NULL checksum so the
        files are not re-executed.
    """
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))

    async with pool.acquire() as conn:
        # Ensure tracking table exists (bootstraps itself)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS migration_history (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ DEFAULT now(),
                checksum TEXT,
                execution_ms INT
            )
        """)

        # Fetch already-applied filenames
        rows = await conn.fetch("SELECT filename FROM migration_history")
        applied = {row["filename"] for row in rows}

        # Backfill legacy databases: if the tracking table is empty but a
        # core legacy table exists, mark every current migration file as
        # already-applied so we don't re-run their statements. Backfilled
        # rows get checksum=NULL and execution_ms=0 to distinguish them
        # from real runs.
        if not applied:
            legacy_exists = await conn.fetchval(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables "
                "  WHERE table_schema = 'public' AND table_name = 'documents'"
                ")"
            )
            if legacy_exists and migration_files:
                logger.info(
                    "Backfilling migration_history for legacy database "
                    f"({len(migration_files)} files)"
                )
                async with conn.transaction():
                    for mf in migration_files:
                        await conn.execute(
                            "INSERT INTO migration_history "
                            "(filename, checksum, execution_ms) "
                            "VALUES ($1, NULL, 0) "
                            "ON CONFLICT (filename) DO NOTHING",
                            mf.name,
                        )
                rows = await conn.fetch("SELECT filename FROM migration_history")
                applied = {row["filename"] for row in rows}

    for migration_file in migration_files:
        fname = migration_file.name
        if fname in applied:
            continue  # already applied — skip

        logger.info(f"Running migration: {fname}")
        sql = await asyncio.to_thread(migration_file.read_text, "utf-8")
        checksum = hashlib.sha256(sql.encode()).hexdigest()[:16]

        lines = [line for line in sql.split("\n") if not line.strip().startswith("--")]
        clean = "\n".join(lines)
        statements = _split_sql(clean)

        t0 = time.monotonic()
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    for stmt in statements:
                        try:
                            # Nested transaction = savepoint. If this
                            # statement raises an idempotent error we
                            # roll back to the savepoint and continue;
                            # the outer transaction stays alive.
                            async with conn.transaction():
                                await conn.execute(stmt)
                        except Exception as stmt_err:
                            msg = str(stmt_err).lower()
                            if "already exists" in msg or "duplicate" in msg:
                                logger.info(
                                    f"  Statement skipped (idempotent): {stmt_err}"
                                )
                                continue
                            # Fatal: re-raise so the outer transaction
                            # rolls back the whole migration. The file
                            # will be retried on the next startup.
                            raise

                    elapsed_ms = int((time.monotonic() - t0) * 1000)
                    await conn.execute(
                        "INSERT INTO migration_history "
                        "(filename, checksum, execution_ms) "
                        "VALUES ($1, $2, $3) "
                        "ON CONFLICT (filename) DO NOTHING",
                        fname, checksum, elapsed_ms,
                    )
        except Exception as e:
            logger.error(
                f"Migration {fname} FAILED — not recorded, will retry on next startup: {e}"
            )
            raise
        logger.info(f"  Applied {fname} ({elapsed_ms}ms)")

    logger.info("Migrations completed")


def _split_sql(sql: str) -> list[str]:
    """Split SQL on semicolons, preserving $$ dollar-quoted blocks."""
    statements = []
    current = []
    in_dollar = False

    i = 0
    while i < len(sql):
        # Detect start/end of $$ dollar-quoted blocks
        if sql[i:i+2] == '$$':
            in_dollar = not in_dollar
            current.append('$$')
            i += 2
            continue

        # Semicolons only split outside dollar quotes
        if sql[i] == ';' and not in_dollar:
            stmt = ''.join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            i += 1
            continue

        current.append(sql[i])
        i += 1

    # Final statement (no trailing semicolon)
    stmt = ''.join(current).strip()
    if stmt:
        statements.append(stmt)

    return statements


def _import_collector(module_name: str):
    """Import a module's collector once and cache it. Called once per poller at startup."""
    mod = __import__(f"modules.{module_name}", fromlist=["collect"])
    if hasattr(mod, "collect"):
        return mod.collect
    return None


async def poller_loop(module_name: str, interval_seconds: int) -> None:
    """Run a module's collector on an interval, logging results."""
    collect_fn = _import_collector(module_name)
    if collect_fn is None:
        logger.warning(f"Poller '{module_name}': no collect() function, skipping")
        return

    consecutive_errors = 0
    while True:
        try:
            result = await collect_fn()
            cache_manager.invalidate(module_name)
            consecutive_errors = 0
            logger.info(f"Poller '{module_name}': {result}")
        except Exception as e:
            consecutive_errors += 1
            backoff = min(interval_seconds, 10 * (2 ** min(consecutive_errors, 5)))
            logger.warning(
                f"Poller '{module_name}' error (#{consecutive_errors}, backoff={backoff}s): {e}"
            )
            await asyncio.sleep(backoff)
            continue
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: connect DB, run migrations, close DB."""
    import os

    logger.info("Starting LamaDB...")

    # Create connection pool
    pool = await create_pool()
    logger.info("Database pool created")

    # Determine if we're in test mode
    is_test = os.environ.get("LAMADB_SKIP_POLLERS", "").lower() in ("1", "true", "yes")

    # Run migrations (skip in test mode — DB is already migrated)
    if not is_test:
        await run_migrations(pool)
        logger.info("Migrations run")

    # Hydrate MCP tool enabled state from `mcp_tool_config` so toggles
    # survive container restarts. Safe in test mode too — the table will
    # simply be empty if the migration hasn't been applied yet.
    from app.mcp_registry import load_persisted_state
    async with pool.acquire() as conn:
        await load_persisted_state(conn)
    logger.info("MCP tool config loaded from DB")

    # Track all background tasks for clean shutdown
    background_tasks: set[asyncio.Task] = set()

    # Start background poller tasks (skip in test mode)
    if not is_test:
        for module_name, interval in [("freshrss", 900), ("ntfy", 300), ("dozzle", 300), ("notflix", 1800), ("hermes", 300), ("homeassistant", 300), ("wiki", 900), ("youtube", 3600)]:
            try:
                mod = __import__(f"modules.{module_name}", fromlist=["ENABLED", "collect"])
                if getattr(mod, "ENABLED", False) and hasattr(mod, "collect"):
                    task = asyncio.create_task(poller_loop(module_name, interval))
                    background_tasks.add(task)
                    task.add_done_callback(background_tasks.discard)
                    logger.info(f"Started poller: {module_name} (every {interval}s)")
            except ImportError:
                pass

        # Start Uptime Kuma registry poller
        if settings.uptime_kuma_url and settings.uptime_kuma_api_key:
            try:
                from modules.uptime.poller import start_poller
                task = start_poller()
                if task:
                    background_tasks.add(task)
                    task.add_done_callback(background_tasks.discard)
                logger.info("Started Uptime Kuma registry poller (every 1 hour)")
            except ImportError:
                logger.warning("Uptime Kuma poller not available (module or dependency missing)")

        # Smart Notification Routing — seed default rules on startup
        try:
            from modules.notifications.engine import seed_default_rules
            await seed_default_rules()
            logger.info("Notification default rules seeded")
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"Notification seed failed (non-fatal): {e}")

        # Daily maintenance — prune old events, dedup dozzle, trim monitor_status
        async def maintenance_loop():
            """Run database maintenance once per day (every 24 hours)."""
            # Wait 60s after startup so the app is fully ready
            await asyncio.sleep(60)
            while True:
                try:
                    pool = get_pool()
                    async with pool.acquire() as conn:
                        await conn.execute("SELECT run_maintenance()")
                    logger.info("Maintenance run completed")
                except Exception as e:
                    logger.warning(f"Maintenance run failed (non-fatal): {e}")
                # Run every 24 hours
                await asyncio.sleep(86400)

        task = asyncio.create_task(maintenance_loop())
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
        logger.info("Started daily maintenance loop (every 24h)")

        # Start SSE pg_listener for real-time dashboard updates
        listener_task = asyncio.create_task(
            pg_listener(
                settings.database_url,
                ["event_created", "task_update", "document_created", "monitor_status", "kanban_task_updated", "secret_updated", "secret_request_updated"],
                _make_notify_callback(),
            )
        )
        background_tasks.add(listener_task)
        listener_task.add_done_callback(background_tasks.discard)
        logger.info("Started SSE pg_listener on channels: event_created, task_update, document_created, monitor_status, kanban_task_updated, secret_updated, secret_request_updated")

        # Wiki LiveSync watcher — continuous CouchDB _changes feed poller
        if (settings.wiki_couchdb_url and settings.wiki_couchdb_db
                and settings.wiki_couchdb_user and settings.wiki_couchdb_password
                and settings.wiki_couchdb_encryption_key):
            try:
                from modules.wiki.collector import watch_wiki_changes
                wiki_task = asyncio.create_task(watch_wiki_changes())
                background_tasks.add(wiki_task)
                wiki_task.add_done_callback(background_tasks.discard)
                logger.info("Started Wiki LiveSync watcher (continuous)")
            except ImportError:
                logger.warning("Wiki LiveSync watcher not available")
    yield
    for task in background_tasks:
        task.cancel()
    if background_tasks:
        await asyncio.gather(*background_tasks, return_exceptions=True)

    # Shutdown
    await close_pool()
    logger.info("Database pool closed")


def make_app() -> FastAPI:
    """Factory to create the FastAPI application."""
    # Parse CORS origins
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]

    app = FastAPI(
        title="LamaDB",
        description="Self-hosted central data layer / Life OS",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health endpoint
    @app.get("/health", tags=["health"])
    async def health_check():
        """Health check endpoint."""
        return {"status": "ok"}

    # Register core routers
    # NOTE: dashboard_router is NOT included here — it lives in modules/dashboard/
    # and is auto-discovered by the module loader below with prefix /api/dashboard.
    # Including it here would create doubled ghost routes at /api/dashboard/api/dashboard/...
    app.include_router(documents_router)
    app.include_router(events_router)
    app.include_router(search_router)

    # User management (kanban)
    from app.core.users import router as users_router
    app.include_router(users_router, prefix="/api")

    # Register WebSocket router
    from app.websocket import router as ws_router
    app.include_router(ws_router)

    # Register MCP server (JSON-RPC 2.0 endpoint)
    from app.mcp_server import router as mcp_router
    app.include_router(mcp_router)

    # Register MCP admin API (stats, tool catalog, enable/disable)
    from app.mcp_admin import router as mcp_admin_router
    app.include_router(mcp_admin_router)

    # Register core MCP tools
    from app.mcp_registry import register_tool
    from app.core.mcp import (
        search_documents, get_document, create_document,
        update_document, create_event, get_events,
        lamadb_docs,
    )

    # Legacy flat tools — kept for backward compatibility with the /mcp
    # endpoint.  Use toolset="legacy" so they do NOT appear on /mcp/admin
    # or /mcp/worker (those expose only the consolidated action-based tools).
    register_tool(
        "search_documents",
        "Full-text + semantic search across documents",
        {"type": "object", "properties": {"q": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["q"]},
        search_documents,
        toolset="legacy",
        module="documents",
    )
    register_tool(
        "get_document",
        "Get a single document by ID with its links",
        {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        get_document,
        toolset="legacy",
        module="documents",
    )
    register_tool(
        "create_document",
        "Create a new document",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "source_type": {"type": "string"},
                "content": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "metadata": {"type": "object"},
            },
            "required": ["title", "source_type"],
        },
        create_document,
        toolset="legacy",
        module="documents",
    )
    register_tool(
        "update_document",
        "Update an existing document (only provided fields change)",
        {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "title": {"type": "string"},
                "content": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "metadata": {"type": "object"},
                "source_type": {"type": "string"},
            },
            "required": ["id"],
        },
        update_document,
        toolset="legacy",
        module="documents",
    )
    register_tool(
        "create_event",
        "Create a new event",
        {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "event_type": {"type": "string"},
                "title": {"type": "string"},
                "severity": {"type": "string", "enum": ["info", "warning", "critical"]},
                "body": {"type": "string"},
                "metadata": {"type": "object"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["source", "event_type", "title"],
        },
        create_event,
        toolset="legacy",
        module="events",
    )
    register_tool(
        "get_events",
        "Get events with optional source/event_type/severity filters",
        {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "event_type": {"type": "string"},
                "severity": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
        get_events,
        toolset="legacy",
        module="events",
    )
    register_tool(
        "lamadb_docs",
        "Read LamaDB documentation. topic='api' for the full agent API reference.",
        {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "default": "api"},
            },
        },
        lamadb_docs,
        toolset="legacy",
        module="",
    )

    # Discover module MCP tools (uptime, agent_board, wiki, kanban, secrets).
    # These are legacy flat tools registered with toolset="legacy" — they only
    # appear on the /mcp endpoint for backward compatibility.
    from app.mcp_registry import discover_module_tools
    discover_module_tools()

    # Register consolidated (action-based) tools — collapses 29 flat tools
    # into 11 dispatchers. These are the primary tools for /mcp/admin and
    # /mcp/worker endpoints.
    from app.mcp_consolidated import register_all as register_consolidated_tools
    register_consolidated_tools()

    logger.info("MCP server ready")

    # Discover and include module routers
    modules_dir = Path(__file__).parent.parent / "modules"
    if modules_dir.exists():
        for item in sorted(modules_dir.iterdir()):
            if not item.is_dir():
                continue
            init_file = item / "__init__.py"
            if not init_file.exists():
                continue

            # Import the module's __init__.py
            module_name = item.name
            try:
                mod = __import__(f"modules.{module_name}", fromlist=["ENABLED", "get_router", "get_public_router"])

                if not getattr(mod, "ENABLED", False):
                    logger.info(f"Module '{module_name}' is disabled, skipping")
                    continue

                router = mod.get_router()
                app.include_router(router, prefix=f"/api/{module_name}")
                logger.info(f"Loaded module: {module_name}")

                # Register public routes if the module exposes them
                if hasattr(mod, "get_public_router"):
                    public_router = mod.get_public_router()
                    # Some modules need public routes at /api/{module}, others at root
                    public_prefix = getattr(mod, "PUBLIC_PREFIX", f"/api/{module_name}")
                    if public_prefix:
                        app.include_router(public_router, prefix=public_prefix)
                    else:
                        app.include_router(public_router)
                    logger.info(f"Loaded public routes for module: {module_name}")

            except Exception as e:
                logger.warning(f"Failed to load module '{module_name}': {e}")

    # Serve dashboard static files (must be LAST — mounts catch all unmatched routes)
    static_dir = Path(__file__).parent.parent / "static"
    if static_dir.exists():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


app = make_app()
