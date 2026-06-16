"""MCP (Model Context Protocol) server — JSON-RPC 2.0 handler.

Exposes three endpoints:
  POST /mcp         — legacy, returns all tools (toolset=None), deprecation warning
  POST /mcp/admin   — admin tools only (toolset="admin" or "both")
  POST /mcp/worker  — worker tools only (toolset="worker" or "both")

All endpoints share the same auth + JSON-RPC plumbing via _handle().
Permission checks now use tool['module'] metadata + user.scopes instead
of a hard-coded map.
"""
import json
import logging
import time

from fastapi import APIRouter, Request, HTTPException, status

from app.auth import verify_api_key
from app.mcp_registry import list_tools, get_tool
from app.mcp_tracker import track_call, track_error

logger = logging.getLogger(__name__)
router = APIRouter(tags=["mcp"])

JSONRPC_VERSION = "2.0"
ERROR_PARSE = -32700
ERROR_METHOD_NOT_FOUND = -32601
ERROR_INVALID_PARAMS = -32602
ERROR_INTERNAL = -32603

# Tools considered "write" for permission elevation. Conservative set — any
# tool that mutates persistent state. Used to require agent-or-admin role.
_WRITE_TOOLS = {
    "create_document",
    "update_document",
    "create_event",
    "send_agent_message",
}


# ---------------------------------------------------------------------------
# JSON-RPC envelope helpers
# ---------------------------------------------------------------------------
def _jsonrpc_response(rpc_id, result):
    return {"jsonrpc": JSONRPC_VERSION, "id": rpc_id, "result": result}


def _jsonrpc_error(rpc_id, code, message):
    return {"jsonrpc": JSONRPC_VERSION, "id": rpc_id, "error": {"code": code, "message": message}}


# ---------------------------------------------------------------------------
# Permission check
# ---------------------------------------------------------------------------
def _check_permission(user, tool: dict) -> str | None:
    """Return an error message if the user can't invoke the tool, else None."""
    # Admin role bypasses everything.
    if user.role == "admin":
        return None

    # Write tools require agent or admin.
    tool_name = tool.get("name", "")
    if tool_name in _WRITE_TOOLS and user.role not in ("admin", "agent"):
        return "Insufficient permissions"

    # Module scope check.
    module_for_tool = tool.get("module", "")
    if module_for_tool and module_for_tool not in (user.scopes or []):
        return f"Scope '{module_for_tool}' required"

    return None


# ---------------------------------------------------------------------------
# Toolset endpoint gating
# ---------------------------------------------------------------------------
def _tool_visible_to_endpoint(tool: dict, endpoint_toolset: str | None) -> bool:
    """Return True if the tool should be exposed by the given endpoint.

    - endpoint_toolset=None: legacy /mcp — all enabled tools.
    - endpoint_toolset="admin": tools with toolset in {"admin", "both"}.
    - endpoint_toolset="worker": tools with toolset in {"worker", "both"}.
    """
    if not tool.get("enabled", True):
        return False
    if endpoint_toolset is None:
        return True
    return tool.get("toolset", "both") in (endpoint_toolset, "both")


# ---------------------------------------------------------------------------
# Shared handler
# ---------------------------------------------------------------------------
async def _handle(request: Request, toolset: str | None) -> dict:
    """Shared JSON-RPC dispatcher for /mcp, /mcp/admin, /mcp/worker."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
        )
    token = auth_header[7:]
    user = await verify_api_key(token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    try:
        body = await request.json()
    except Exception:
        return _jsonrpc_error(None, ERROR_PARSE, "Parse error")

    rpc_id = body.get("id")
    method = body.get("method", "")
    params = body.get("params", {})

    if method == "tools/list":
        # list_tools() already applies the toolset filter; for the legacy
        # endpoint (toolset=None) it returns all enabled tools.
        return _jsonrpc_response(rpc_id, {"tools": list_tools(toolset=toolset)})

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool = get_tool(tool_name)
        if tool is None:
            return _jsonrpc_error(
                rpc_id, ERROR_METHOD_NOT_FOUND, f"Tool not found: {tool_name}"
            )

        # Endpoint visibility — is this tool offered on this endpoint?
        if not _tool_visible_to_endpoint(tool, toolset):
            return _jsonrpc_error(
                rpc_id,
                ERROR_METHOD_NOT_FOUND,
                f"Tool '{tool_name}' is not available on this endpoint",
            )

        # Disabled tools are rejected.
        if not tool.get("enabled", True):
            return _jsonrpc_error(
                rpc_id,
                ERROR_INTERNAL,
                f"Tool '{tool_name}' is disabled",
            )

        # Permission check.
        perm_err = _check_permission(user, tool)
        if perm_err is not None:
            return _jsonrpc_error(rpc_id, ERROR_INTERNAL, perm_err)

        arguments = params.get("arguments", {}) or {}
        start = time.monotonic()
        try:
            result = await tool["handler"](**arguments)
            elapsed_ms = (time.monotonic() - start) * 1000
            track_call(tool_name, elapsed_ms)
            return _jsonrpc_response(
                rpc_id,
                {"content": [{"type": "text", "text": json.dumps(result)}]},
            )
        except TypeError as e:
            elapsed_ms = (time.monotonic() - start) * 1000
            track_error(tool_name, str(e), elapsed_ms)
            return _jsonrpc_error(rpc_id, ERROR_INVALID_PARAMS, str(e))
        except Exception as e:
            elapsed_ms = (time.monotonic() - start) * 1000
            track_error(tool_name, str(e), elapsed_ms)
            logger.exception(f"MCP tool '{tool_name}' error")
            return _jsonrpc_error(rpc_id, ERROR_INTERNAL, str(e))

    return _jsonrpc_error(rpc_id, ERROR_METHOD_NOT_FOUND, f"Method not found: {method}")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/mcp")
async def mcp_handler_legacy(request: Request):
    """Legacy MCP endpoint — returns all tools regardless of toolset.

    Emits a deprecation warning log; clients should migrate to
    /mcp/admin or /mcp/worker.
    """
    logger.warning(
        "DEPRECATION: /mcp endpoint called — migrate to /mcp/admin or /mcp/worker"
    )
    return await _handle(request, toolset=None)


@router.post("/mcp/admin")
async def mcp_handler_admin(request: Request):
    """Admin endpoint — exposes all admin+both tools."""
    return await _handle(request, toolset="admin")


@router.post("/mcp/worker")
async def mcp_handler_worker(request: Request):
    """Worker endpoint — exposes worker+both tools only.

    Tools with toolset='admin' are NOT visible here.
    """
    return await _handle(request, toolset="worker")
