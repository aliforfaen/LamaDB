"""Tests for the ntfy notifications module."""
import pytest
from unittest.mock import patch, AsyncMock

import sys
import importlib


def test_module_exists():
    """Verify the ntfy module is importable."""
    sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")
    mod = importlib.import_module("modules.ntfy")
    assert mod.MODULE_NAME == "ntfy"
    assert mod.MODULE_DESCRIPTION == "ntfy notification receiver and poller"
    assert mod.MODULE_VERSION == "0.1.0"
    assert mod.ENABLED is True


def test_module_has_get_router():
    """Verify the module exposes get_router."""
    sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")
    mod = importlib.import_module("modules.ntfy")
    assert hasattr(mod, "get_router")
    assert callable(mod.get_router)


def test_routes_module_has_expected_endpoints():
    """Verify routes.py defines the expected endpoints."""
    sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")
    from modules.ntfy.routes import router

    route_paths = []
    for route in router.routes:
        if hasattr(route, "path"):
            route_paths.append(route.path)
    assert "/health" in route_paths
    assert "/messages" in route_paths
    assert "/sync" in route_paths


def test_priority_mapping():
    """Verify priority to severity mapping."""
    sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")
    from modules.ntfy.routes import _priority_to_severity

    assert _priority_to_severity(5) == "critical"
    assert _priority_to_severity(4) == "warn"
    assert _priority_to_severity(3) == "info"
    assert _priority_to_severity(2) == "info"
    assert _priority_to_severity(1) == "info"


def test_collector_priority_mapping():
    """Verify collector has same priority mapping."""
    sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")
    from modules.ntfy.collector import _priority_to_severity

    assert _priority_to_severity(5) == "critical"
    assert _priority_to_severity(4) == "warn"
    assert _priority_to_severity(3) == "info"


@pytest.mark.asyncio
async def test_collector_graceful_when_not_configured():
    """Collector returns gracefully when NTFY_URL is empty."""
    sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")

    with patch("modules.ntfy.collector.settings") as mock_settings:
        mock_settings.ntfy_url = ""

        from modules.ntfy.collector import collect
        result = await collect()

        assert result["message_count"] == 0
        assert result["error"] == "not configured"


@pytest.mark.asyncio
async def test_collector_graceful_on_http_error():
    """Collector handles HTTP errors gracefully."""
    sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")

    with patch("modules.ntfy.collector.settings") as mock_settings:
        mock_settings.ntfy_url = "http://localhost:8080"
        mock_settings.ntfy_topic = "test-topic"

        with patch("modules.ntfy.collector.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.side_effect = Exception("Connection refused")

            from modules.ntfy.collector import collect
            result = await collect()

            assert result["message_count"] == 0
            assert "error" in result


def test_health_endpoint_exists():
    """Health endpoint is defined."""
    sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")
    from modules.ntfy.routes import router

    health_route = None
    for route in router.routes:
        if hasattr(route, "path") and route.path == "/health":
            health_route = route
            break
    assert health_route is not None
