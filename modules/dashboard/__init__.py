"""Module metadata for management dashboard."""
MODULE_NAME = "dashboard"
MODULE_DESCRIPTION = "Management dashboard for LamaDB"
MODULE_VERSION = "0.1.0"
ENABLED = True


def get_router():
    from app.core.dashboard import router
    return router
