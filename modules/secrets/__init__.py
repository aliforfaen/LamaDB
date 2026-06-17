"""Secrets module — encrypted credential storage with access control."""
MODULE_NAME = "secrets"
MODULE_DESCRIPTION = "Encrypted secret, API key, and credential storage for agents"
MODULE_VERSION = "1.0.0"
ENABLED = True

MODULE_MCP_TOOLS = [
    {"name": "list_secrets", "description": "List all secrets visible to you (metadata only — no values). Filter by service, type, tags, accessibility.", "handler": "modules.secrets.mcp:list_secrets", "toolset": "legacy", "module": "secrets"},
    {"name": "get_secret_metadata", "description": "Get full metadata for a specific secret by ID.", "handler": "modules.secrets.mcp:get_secret_metadata", "toolset": "legacy", "module": "secrets"},
    {"name": "reveal_secret", "description": "Decrypt and return a secret value. Requires access grant or ownership. Audit logged.", "handler": "modules.secrets.mcp:reveal_secret", "toolset": "legacy", "module": "secrets"},
    {"name": "request_secret_access", "description": "Request access to a secret you can see but cannot reveal. Provide a reason for the request.", "handler": "modules.secrets.mcp:request_secret_access", "toolset": "legacy", "module": "secrets"},
]

def get_router():
    from .routes import router
    return router
