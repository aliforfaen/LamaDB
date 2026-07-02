-- Migration 030: MCP tool config — persist enable/disable state per tool
-- Replaces the in-memory `_tools[name]["enabled"]` flag in mcp_registry with a
-- database row so the state survives container restarts. The in-memory dict
-- stays as the read cache; startup calls `load_persisted_state()` once to
-- hydrate it from this table.
CREATE TABLE IF NOT EXISTS mcp_tool_config (
    name TEXT PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT true,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);