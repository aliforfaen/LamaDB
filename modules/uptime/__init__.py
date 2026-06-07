# Module metadata for Uptime Kuma webhook integration
MODULE_NAME = "uptime"
MODULE_DESCRIPTION = "Uptime Kuma webhook receiver and monitor status tracking"
MODULE_VERSION = "0.1.0"
ENABLED = True


def get_router():
    from .routes import router
    return router
