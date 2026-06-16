"""MCP admin API — stats, tool catalog, and tool enable/disable.

All routes are mounted at /api/mcp/admin and require admin role.
"""
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import get_current_user, AuthUser
from app.mcp_registry import (
    get_all_tools_with_metadata,
    toggle_tool,
)
from app.mcp_tracker import get_stats, reset_stats

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp/admin", tags=["mcp-admin"])


async def require_admin_user(
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> AuthUser:
    """Dependency: ensure the caller is an admin."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return user


AdminUser = Annotated[AuthUser, Depends(require_admin_user)]


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
@router.get("/stats")
async def get_stats_endpoint(user: AdminUser) -> dict:
    """Return call stats enriched with each tool's metadata.

    Response shape:
      {
        "stats": {
          "<tool_name>": {
            "calls": int, "errors": int, "total_ms": float,
            "avg_duration_ms": float, "last_call_ts": float|None,
            "last_error_ts": float|None, "last_error": str|None,
            "module": str, "toolset": str, "enabled": bool
          }, ...
        },
        "summary": {"total_calls": int, "total_errors": int, "tool_count": int}
      }
    """
    raw = get_stats()

    # Enrich with metadata.
    tools_meta = {t["name"]: t for t in get_all_tools_with_metadata()}
    enriched: dict[str, dict] = {}
    for name, s in raw.items():
        meta = tools_meta.get(name, {})
        s2 = dict(s)
        s2["module"] = meta.get("module", "")
        s2["toolset"] = meta.get("toolset", "both")
        s2["enabled"] = meta.get("enabled", True)
        enriched[name] = s2

    total_calls = sum(s["calls"] for s in raw.values())
    total_errors = sum(s["errors"] for s in raw.values())
    return {
        "stats": enriched,
        "summary": {
            "total_calls": total_calls,
            "total_errors": total_errors,
            "tool_count": len(raw),
        },
    }


@router.post("/stats/reset")
async def reset_stats_endpoint(user: AdminUser) -> dict:
    """Reset all stats. For testing."""
    reset_stats()
    return {"status": "reset"}


# ---------------------------------------------------------------------------
# Tool catalog
# ---------------------------------------------------------------------------
@router.get("/tools")
async def list_tools_endpoint(user: AdminUser) -> dict:
    """Return all registered tools with metadata."""
    return {"tools": get_all_tools_with_metadata()}


# ---------------------------------------------------------------------------
# Toggle
# ---------------------------------------------------------------------------
class ToggleRequest(BaseModel):
    enabled: bool


@router.patch("/tools/{tool_name}")
async def toggle_tool_endpoint(
    tool_name: str, body: ToggleRequest, user: AdminUser,
) -> dict:
    """Enable or disable a tool."""
    ok = toggle_tool(tool_name, body.enabled)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool '{tool_name}' not found",
        )
    return {"tool": tool_name, "enabled": body.enabled}
