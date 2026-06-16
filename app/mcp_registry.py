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
        if sig.parameters:
            valid_params = set(sig.parameters.keys())
            call_kwargs = {k: v for k, v in call_kwargs.items() if k in valid_params}

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
                    toolset=tool_def.get("toolset", "both"),
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
    """
    out = []
    for t in _tools.values():
        if not t.get("enabled", True):
            continue
        if toolset is not None and toolset != "both":
            if t.get("toolset", "both") not in (toolset, "both"):
                continue
        out.append(
            {
                "name": t["name"],
                "description": t["description"],
                "inputSchema": t["inputSchema"],
            }
        )
    return out


def get_tool(name: str) -> dict | None:
    """Get a registered tool by name (includes handler)."""
    return _tools.get(name)


def toggle_tool(name: str, enabled: bool) -> bool:
    """Enable or disable a tool. Returns True if the tool was found."""
    tool = _tools.get(name)
    if tool is None:
        return False
    tool["enabled"] = enabled
    logger.info(f"MCP tool {'enabled' if enabled else 'disabled'}: {name}")
    return True


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
