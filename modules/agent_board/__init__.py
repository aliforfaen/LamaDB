"""Agent Board — coordination layer for AI agents."""
MODULE_NAME = "agent_board"
MODULE_DESCRIPTION = "Agent task queue, messaging, and LISTEN/NOTIFY coordination"
MODULE_VERSION = "0.1.0"
ENABLED = True

def get_router():
    from .routes import router
    return router