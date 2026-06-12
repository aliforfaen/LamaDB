"""Groups module — user group management for LamaDB."""
MODULE_NAME = "groups"
MODULE_DESCRIPTION = "User group management — first-class LamaDB access primitive"
MODULE_VERSION = "0.1.0"
ENABLED = True

def get_router():
    from .routes import router
    return router
