"""MCP (Model Context Protocol) server — JSON-RPC 2.0 handler."""
import json
import logging
from fastapi import APIRouter, Request, HTTPException, status
from app.auth import verify_api_key
from app.mcp_registry import list_tools, get_tool

logger = logging.getLogger(__name__)
router = APIRouter(tags=["mcp"])

JSONRPC_VERSION = "2.0"
ERROR_PARSE = -32700
ERROR_METHOD_NOT_FOUND = -32601
ERROR_INVALID_PARAMS = -32602
ERROR_INTERNAL = -32603

# Tools that require agent or admin role
WRITE_TOOLS = {"create_document", "update_document", "create_event", "send_agent_message"}


@router.post("/mcp")
async def mcp_handler(request: Request):
    """Handle MCP JSON-RPC 2.0 requests.

    Supports:
      - tools/list: return all registered tools
      - tools/call: invoke a tool by name with arguments
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")
    token = auth_header[7:]
    user = await verify_api_key(token)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    try:
        body = await request.json()
    except Exception:
        return _jsonrpc_error(None, ERROR_PARSE, "Parse error")

    rpc_id = body.get("id")
    method = body.get("method", "")
    params = body.get("params", {})

    if method == "tools/list":
        return _jsonrpc_response(rpc_id, {"tools": list_tools()})

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool = get_tool(tool_name)
        if tool is None:
            return _jsonrpc_error(rpc_id, ERROR_METHOD_NOT_FOUND, f"Tool not found: {tool_name}")
        arguments = params.get("arguments", {})
        try:
            # Permission check: admin has full access
            if user.role != "admin":
                module_for_tool = _tool_to_module(tool_name)
                if tool_name in WRITE_TOOLS and user.role not in ("admin", "agent"):
                    return _jsonrpc_error(rpc_id, ERROR_INTERNAL, "Insufficient permissions")
                if module_for_tool and module_for_tool not in user.scopes and user.role != "admin":
                    return _jsonrpc_error(rpc_id, ERROR_INTERNAL, f"Scope '{module_for_tool}' required")
            result = await tool["handler"](**arguments)
            return _jsonrpc_response(rpc_id, {"content": [{"type": "text", "text": json.dumps(result)}]})
        except TypeError as e:
            return _jsonrpc_error(rpc_id, ERROR_INVALID_PARAMS, str(e))
        except Exception as e:
            logger.exception(f"MCP tool '{tool_name}' error")
            return _jsonrpc_error(rpc_id, ERROR_INTERNAL, str(e))

    return _jsonrpc_error(rpc_id, ERROR_METHOD_NOT_FOUND, f"Method not found: {method}")


def _jsonrpc_response(rpc_id, result):
    return {"jsonrpc": JSONRPC_VERSION, "id": rpc_id, "result": result}


def _jsonrpc_error(rpc_id, code, message):
    return {"jsonrpc": JSONRPC_VERSION, "id": rpc_id, "error": {"code": code, "message": message}}


def _tool_to_module(tool_name: str) -> str:
    """Map a tool name to its module name for scope checking."""
    mapping = {
        "search_documents": "documents",
        "get_document": "documents",
        "create_document": "documents",
        "update_document": "documents",
        "create_event": "events",
        "get_events": "events",
        "get_uptime_status": "uptime",
        "get_uptime_history": "uptime",
        "get_agent_tasks": "agent_board",
        "send_agent_message": "agent_board",
        "wiki_search": "wiki",
        "scratchpad_capture": "wiki",
        "lamadb_docs": "",  # Universal — no scope required
    }
    return mapping.get(tool_name, "")
