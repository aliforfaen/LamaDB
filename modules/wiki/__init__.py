# Module metadata for Wiki reader, scratchpad, and edit log
MODULE_NAME = "wiki"
MODULE_DESCRIPTION = "Wiki reader, scratchpad, and edit log"
MODULE_VERSION = "0.1.0"
ENABLED = True


def get_router():
    from .routes import router

    return router
