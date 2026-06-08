"""LamaDB FastAPI application with module auto-discovery."""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import create_pool, close_pool, get_pool
from app.sse import pg_listener, _make_notify_callback, sse_manager

# Import core routers
from app.core.documents import router as documents_router
from app.core.events import router as events_router
from app.core.search import router as search_router
from app.core.dashboard import router as dashboard_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


async def run_migrations(pool) -> None:
    """Read and execute all SQL migration files in order."""
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    for migration_file in migration_files:
        logger.info(f"Running migration: {migration_file.name}")
        sql = migration_file.read_text(encoding="utf-8")

        # Remove comment lines
        lines = [line for line in sql.split("\n") if not line.strip().startswith("--")]
        clean = "\n".join(lines)

        # Split on semicolons but preserve $$ dollar-quoted blocks
        statements = _split_sql(clean)

        async with pool.acquire() as conn:
            for stmt in statements:
                try:
                    await conn.execute(stmt)
                except Exception as e:
                    msg = str(e).lower()
                    if "already exists" in msg or "duplicate" in msg:
                        logger.info(f"Migration skipped (already applied): {e}")
                    else:
                        logger.warning(f"Migration statement error (may be non-fatal): {e}")

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


async def poller_loop(module_name: str, interval_seconds: int) -> None:
    """Run a module's collector on an interval, logging results."""
    while True:
        try:
            mod = __import__(f"modules.{module_name}", fromlist=["collect"])
            if hasattr(mod, "collect"):
                result = await mod.collect()
                logger.info(f"Poller '{module_name}': {result}")
        except Exception as e:
            logger.warning(f"Poller '{module_name}' error: {e}")
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

    # Track all background tasks for clean shutdown
    background_tasks: set[asyncio.Task] = set()

    # Start background poller tasks (skip in test mode)
    if not is_test:
        for module_name, interval in [("freshrss", 900), ("ntfy", 300), ("dozzle", 300), ("notflix", 1800), ("hermes", 300)]:
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

        # Start SSE pg_listener for real-time dashboard updates
        listener_task = asyncio.create_task(
            pg_listener(
                settings.database_url,
                ["event_created", "task_update"],
                _make_notify_callback(),
            )
        )
        background_tasks.add(listener_task)
        listener_task.add_done_callback(background_tasks.discard)
        logger.info("Started SSE pg_listener on channels: event_created, task_update")

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
    app.include_router(documents_router)
    app.include_router(events_router)
    app.include_router(search_router)
    app.include_router(dashboard_router)

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
