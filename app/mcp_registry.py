"""MCP tool registry — auto-discovers tools from module declarations."""
import inspect
import logging
from typing import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

_tools: dict[str, dict] = {}


def register_tool(
    name: str,
    description: str,
    inputSchema: dict,
    handler: Callable,
    toolset: str = "both",
    module: str = "",
    enabled: bool = True,
):
    """Register a single tool in the MCP registry.

    Args:
        name: Tool name (must be unique).
        description: Human-readable description.
        inputSchema: JSON Schema for the tool's arguments.
        handler: Async function called to invoke the tool.
        toolset: "admin" | "worker" | "both" — controls which /mcp/* endpoint
                 exposes the tool.
        module: Module scope (used for permission checking against user scopes).
        enabled: Whether the tool is currently enabled. Can be toggled at
                 runtime via toggle_tool().
    """
    _tools[name] = {
        "name": name,
        "description": description,
        "inputSchema": inputSchema,
        "handler": handler,
        "toolset": toolset,
        "module": module,
        "enabled": enabled,
    }
    logger.info(
        f"MCP tool registered: {name} (toolset={toolset}, module={module or '-'})"
    )


def _make_dispatcher(
    actions: dict[str, Callable],
    renames: dict[str, dict[str, str]] | None = None,
) -> Callable:
    """Build an async dispatcher that routes action-based calls to handlers.

    Args:
        actions: Map of action name → handler function.
        renames: Map of action name → {caller_param: handler_param} rename map.
                 Used when the consolidated tool's param name differs from the
                 handler's (e.g. the public API uses `secret_id` but the
                 handler takes `id`).

    The dispatcher:
    1. Reads `action` from kwargs.
    2. Looks up the handler for that action.
    3. Applies renames (caller name → handler name).
    4. Filters kwargs to only the params the handler accepts (by signature).
    5. Calls the handler.
    """
    renames = renames or {}
    # Pre-compute handler signatures so we can filter kwargs at call time.
    sig_cache: dict[str, inspect.Signature] = {}

    def _get_handler_params(action: str) -> inspect.Signature:
        if action not in sig_cache:
            handler = actions[action]
            try:
                sig_cache[action] = inspect.signature(handler)
            except (TypeError, ValueError):
                # Some builtins / wrapped callables don't expose signatures.
                # Fall back to accepting any kwargs.
                sig_cache[action] = inspect.Signature()
        return sig_cache[action]

    async def dispatch(**kwargs):
        action = kwargs.get("action")
        if not action:
            raise ValueError("Missing 'action' parameter")
        if action not in actions:
            raise ValueError(
                f"Unknown action '{action}'. Valid actions: {sorted(actions.keys())}"
            )

        handler = actions[action]
        action_renames = renames.get(action, {})

        # Build the call kwargs: rename, then filter by signature.
        call_kwargs: dict = {}
        for k, v in kwargs.items():
            if k == "action":
                continue
            mapped = action_renames.get(k, k)
            call_kwargs[mapped] = v

        sig = _get_handler_params(action)
        # Always filter — sig.parameters is {} (falsy) for zero-param
        # handlers, so the `if sig.parameters:` guard would skip filtering
        # and let extra kwargs like user_id through.
        valid_params = set(sig.parameters.keys())
        if valid_params:
            call_kwargs = {k: v for k, v in call_kwargs.items() if k in valid_params}
        else:
            call_kwargs = {}

        return await handler(**call_kwargs)

    return dispatch


def register_consolidated_tool(
    name: str,
    description: str,
    inputSchema: dict,
    actions: dict[str, Callable],
    renames: dict[str, dict[str, str]] | None = None,
    toolset: str = "both",
    module: str = "",
    enabled: bool = True,
):
    """Register a consolidated tool that dispatches to one of many handlers.

    The consolidated tool exposes an `action` enum parameter in its
    inputSchema. At call time, the dispatcher routes to the handler that
    matches the action value.

    Args:
        name: Consolidated tool name (e.g. "agent_documents").
        description: Tool description (should mention the available actions).
        inputSchema: JSON Schema; should include an `action` enum property.
        actions: Map of action value → handler function.
        renames: Optional per-action rename map.
        toolset, module, enabled: Same as register_tool().
    """
    dispatcher = _make_dispatcher(actions, renames)
    register_tool(
        name=name,
        description=description,
        inputSchema=inputSchema,
        handler=dispatcher,
        toolset=toolset,
        module=module,
        enabled=enabled,
    )


def discover_module_tools():
    """Scan all modules for MODULE_MCP_TOOLS declarations."""
    modules_dir = Path(__file__).parent.parent / "modules"
    if not modules_dir.exists():
        return
    for item in sorted(modules_dir.iterdir()):
        if not item.is_dir() or not (item / "__init__.py").exists():
            continue
        try:
            mod = __import__(
                f"modules.{item.name}",
                fromlist=["MODULE_MCP_TOOLS", "ENABLED"],
            )
            if not getattr(mod, "ENABLED", False):
                continue
            tools = getattr(mod, "MODULE_MCP_TOOLS", [])
            for tool_def in tools:
                handler_path = tool_def["handler"]
                handler = _import_handler(handler_path)
                register_tool(
                    name=tool_def["name"],
                    description=tool_def["description"],
                    inputSchema=tool_def.get(
                        "inputSchema", {"type": "object", "properties": {}}
                    ),
                    handler=handler,
                    toolset=tool_def.get("toolset", "legacy"),
                    module=tool_def.get("module", item.name),
                    enabled=tool_def.get("enabled", True),
                )
        except Exception as e:
            logger.warning(
                f"Failed to load MCP tools from module '{item.name}': {e}"
            )


def _import_handler(path: str) -> Callable:
    """Import a handler function from a dotted path like 'module.submodule:function_name'."""
    module_path, func_name = path.rsplit(":", 1)
    mod = __import__(module_path, fromlist=[func_name])
    return getattr(mod, func_name)


def list_tools(toolset: str | None = None) -> list[dict]:
    """Return registered tools as MCP-compatible dicts (without handler).

    Args:
        toolset: If provided, filter to tools whose `toolset` is this value
                 OR "both". If None, return all tools.

    Tool descriptions are augmented with health warnings from the stats
    tracker when error rates are elevated (≥3 calls, >50% error rate).
    """
    from app.mcp_tracker import get_stats
    import time

    stats = get_stats()
    now = time.time()

    out = []
    for t in _tools.values():
        if not t.get("enabled", True):
            continue
        if toolset is not None and toolset != "both":
            if t.get("toolset", "both") not in (toolset, "both"):
                continue

        desc = t["description"]

        # Augment description with health warning if error rate is high.
        name = t["name"]
        s = stats.get(name)
        if s and s["calls"] >= 3:
            error_rate = s["errors"] / s["calls"]
            if error_rate > 0.5:
                # Only show if the last error was recent (within 1 hour)
                if s["last_error_ts"] and (now - s["last_error_ts"]) < 3600:
                    pct = int(error_rate * 100)
                    desc = f"{desc} ⚠️ {pct}% error rate ({s['errors']}/{s['calls']} calls) — may be broken."

        out.append(
            {
                "name": name,
                "description": desc,
                "inputSchema": t["inputSchema"],
            }
        )
    return out


def get_tool(name: str) -> dict | None:
    """Get a registered tool by name (includes handler)."""
    return _tools.get(name)


def toggle_tool(name: str, enabled: bool) -> bool:
    """Enable or disable a tool (in-memory only).

    Returns True if the tool was found. For DB persistence, use
    `set_tool_enabled(conn, name, enabled)` instead — it both updates
    this in-memory cache and writes the row to `mcp_tool_config`.
    """
    tool = _tools.get(name)
    if tool is None:
        return False
    tool["enabled"] = enabled
    logger.info(f"MCP tool {'enabled' if enabled else 'disabled'}: {name}")
    return True


async def set_tool_enabled(conn, name: str, enabled: bool) -> bool:
    """Persist a tool's enabled flag to `mcp_tool_config` and update cache.

    Upserts the row (so the first toggle for a tool creates it) and updates
    the in-memory `_tools[name]["enabled"]` so subsequent calls in the same
    process see the change without re-reading from DB.

    Args:
        conn: An asyncpg connection (transactional with the caller).
        name: Tool name. Must match a registered tool — we return False
              if the tool isn't known to avoid persisting garbage rows.
        enabled: New enabled state.

    Returns:
        True if the tool was found (and the row was upserted). False if no
        tool with that name is registered, in which case the row is NOT
        written.
    """
    if name not in _tools:
        return False

    await conn.execute(
        """
        INSERT INTO mcp_tool_config (name, enabled, updated_at)
        VALUES ($1, $2, now())
        ON CONFLICT (name) DO UPDATE
            SET enabled = EXCLUDED.enabled,
                updated_at = now()
        """,
        name, enabled,
    )
    _tools[name]["enabled"] = enabled
    logger.info(f"MCP tool {'enabled' if enabled else 'disabled'} (persisted): {name}")
    return True


async def load_persisted_state(conn) -> int:
    """Hydrate `_tools[name]["enabled"]` from `mcp_tool_config`.

    Called once during application startup, after migrations have run.
    Tools registered after this call that have no row in the table default
    to `enabled=True` (which is what `register_tool()` already sets).

    Args:
        conn: An asyncpg connection (read-only is fine).

    Returns:
        Number of tools whose enabled state was restored from the DB.
    """
    rows = await conn.fetch("SELECT name, enabled FROM mcp_tool_config")
    restored = 0
    for row in rows:
        tool = _tools.get(row["name"])
        if tool is None:
            # Stale row for a tool that no longer exists. Leave it alone —
            # admins may re-register the tool later and we'd want to keep
            # their preference. Skip silently rather than warn loudly.
            continue
        tool["enabled"] = row["enabled"]
        restored += 1
    if restored:
        logger.info(f"Restored MCP tool enabled state for {restored} tool(s) from DB")
    return restored


def get_all_tools_with_metadata() -> list[dict]:
    """Return all registered tools with their metadata (for admin views)."""
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "inputSchema": t["inputSchema"],
            "toolset": t.get("toolset", "both"),
            "module": t.get("module", ""),
            "enabled": t.get("enabled", True),
        }
        for t in _tools.values()
    ]
