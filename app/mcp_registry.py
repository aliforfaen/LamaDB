"""MCP tool registry — auto-discovers tools from module declarations."""
import logging
from typing import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

_tools: dict[str, dict] = {}


def register_tool(name: str, description: str, inputSchema: dict, handler: Callable):
    """Register a single tool in the MCP registry."""
    _tools[name] = {
        "name": name,
        "description": description,
        "inputSchema": inputSchema,
        "handler": handler,
    }
    logger.info(f"MCP tool registered: {name}")


def discover_module_tools():
    """Scan all modules for MODULE_MCP_TOOLS declarations."""
    modules_dir = Path(__file__).parent.parent / "modules"
    if not modules_dir.exists():
        return
    for item in sorted(modules_dir.iterdir()):
        if not item.is_dir() or not (item / "__init__.py").exists():
            continue
        try:
            mod = __import__(f"modules.{item.name}", fromlist=["MODULE_MCP_TOOLS", "ENABLED"])
            if not getattr(mod, "ENABLED", False):
                continue
            tools = getattr(mod, "MODULE_MCP_TOOLS", [])
            for tool_def in tools:
                handler_path = tool_def["handler"]
                handler = _import_handler(handler_path)
                register_tool(
                    name=tool_def["name"],
                    description=tool_def["description"],
                    inputSchema=tool_def.get("inputSchema", {"type": "object", "properties": {}}),
                    handler=handler,
                )
        except Exception as e:
            logger.warning(f"Failed to load MCP tools from module '{item.name}': {e}")


def _import_handler(path: str) -> Callable:
    """Import a handler function from a dotted path like 'module.submodule:function_name'."""
    module_path, func_name = path.rsplit(":", 1)
    mod = __import__(module_path, fromlist=[func_name])
    return getattr(mod, func_name)


def list_tools() -> list[dict]:
    """Return all registered tools as MCP-compatible dicts (without handler)."""
    return [
        {"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"]}
        for t in _tools.values()
    ]


def get_tool(name: str) -> dict | None:
    """Get a registered tool by name (includes handler)."""
    return _tools.get(name)
