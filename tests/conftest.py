"""Shared test fixtures for LamaDB tests.

Sets LAMADB_SKIP_POLLERS=1 so the lifespan skips background
poller tasks during test runs. Provides a container_required
marker that skips tests when the Docker container isn't running.
"""
import os
import socket
import pytest

os.environ["LAMADB_SKIP_POLLERS"] = "1"


def _container_reachable() -> bool:
    """Check if the LamaDB container is running on localhost:8000."""
    try:
        s = socket.create_connection(("localhost", 8000), timeout=1)
        s.close()
        return True
    except Exception:
        return False


container_required = pytest.mark.skipif(
    not _container_reachable(),
    reason="Docker container not running — run: docker compose up -d"
)
