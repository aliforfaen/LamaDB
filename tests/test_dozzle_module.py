"""Tests for the Dozzle log viewer module."""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

import sys
import importlib


def test_module_exists():
    """Verify the dozzle module is importable."""
    sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")
    mod = importlib.import_module("modules.dozzle")
    assert mod.MODULE_NAME == "dozzle"
    assert mod.MODULE_DESCRIPTION == "Dozzle container log viewer and error aggregation"
    assert mod.MODULE_VERSION == "0.1.0"
    assert mod.ENABLED is True


def test_module_has_get_router():
    """Verify the module exposes get_router."""
    sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")
    mod = importlib.import_module("modules.dozzle")
    assert hasattr(mod, "get_router")
    assert callable(mod.get_router)


def test_module_has_get_public_router():
    """Verify the module exposes get_public_router."""
    sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")
    mod = importlib.import_module("modules.dozzle")
    assert hasattr(mod, "get_public_router")
    assert callable(mod.get_public_router)


def test_routes_module_has_expected_endpoints():
    """Verify routes.py defines the expected endpoints."""
    sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")
    from modules.dozzle.routes import router

    route_paths = []
    for route in router.routes:
        if hasattr(route, "path"):
            route_paths.append(route.path)
    assert "/containers" in route_paths
    assert "/logs" in route_paths
    assert "/errors" in route_paths
    assert "/sync" in route_paths


def test_public_webhook_endpoint_exists():
    """Verify public_router has /webhook endpoint (no auth)."""
    sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")
    from modules.dozzle.routes import public_router

    webhook_route = None
    for route in public_router.routes:
        if hasattr(route, "path") and route.path == "/webhook":
            webhook_route = route
            break
    assert webhook_route is not None, "public_router should have /webhook endpoint"


@pytest.mark.asyncio
async def test_collector_graceful_when_not_configured():
    """Collector returns gracefully when DOZZLE_URL is empty."""
    sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")

    with patch("modules.dozzle.collector.settings") as mock_settings:
        mock_settings.dozzle_url = ""

        from modules.dozzle.collector import collect
        result = await collect()

        assert result["errors"] == 0
        assert result["error"] == "not configured"


@pytest.mark.asyncio
async def test_collector_graceful_on_http_error():
    """Collector handles HTTP errors gracefully."""
    sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")

    with patch("modules.dozzle.collector.settings") as mock_settings:
        mock_settings.dozzle_url = "http://localhost:8080"

        with patch("modules.dozzle.collector.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.side_effect = Exception("Connection refused")

            from modules.dozzle.collector import collect
            result = await collect()

            assert result["errors"] == 0
            assert "error" in result


def test_errors_endpoint_exists():
    """Verify /errors endpoint is defined."""
    sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")
    from modules.dozzle.routes import router

    errors_route = None
    for route in router.routes:
        if hasattr(route, "path") and route.path == "/errors":
            errors_route = route
            break
    assert errors_route is not None


def test_logs_endpoint_with_level_param():
    """Verify /logs endpoint accepts level query parameter."""
    sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")
    from modules.dozzle.routes import router

    logs_route = None
    for route in router.routes:
        if hasattr(route, "path") and route.path == "/logs":
            logs_route = route
            break
    assert logs_route is not None

    # Verify the route has query parameters
    sig_params = set()
    if hasattr(logs_route, "dependant"):
        sig_params = {p.name for p in logs_route.dependant.query_params}
    assert "level" in sig_params
    assert "limit" in sig_params


@pytest.mark.asyncio
async def test_webhook_processes_error_payload():
    """Webhook handler creates an event with ticker=true for error severity."""
    sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")

    from modules.dozzle.webhook import process_webhook_payload

    payload = {
        "type": "notification",
        "title": "nginx error: connection refused",
        "body": "2026-05-30 12:00:00 [ERROR] upstream timed out",
        "tags": ["error", "nginx"],
        "priority": 5,
        "timestamp": "2026-05-30T12:00:00Z",
        "containerName": "web-nginx",
        "containerId": "abc123",
    }

    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {"id": 42}

    # pool.acquire() is an async method; the code does:
    #   async with pool.acquire() as conn:
    # So acquire() is awaited, returning an async context manager.
    # We need to set up acquire() to return a context manager for mock_conn.
    mock_acquire_cm = AsyncMock()
    mock_acquire_cm.__aenter__.return_value = mock_conn
    mock_acquire_cm.__aexit__.return_value = None

    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_acquire_cm

    with patch("modules.dozzle.webhook.get_pool", return_value=mock_pool):
        result = await process_webhook_payload(payload)

    assert result["event_id"] == 42
    assert result["ticker_created"] is True


@pytest.mark.asyncio
async def test_webhook_processes_info_payload_no_ticker():
    """Webhook handler creates an event without ticker for low priority."""
    sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")

    from modules.dozzle.webhook import process_webhook_payload

    payload = {
        "type": "notification",
        "title": "info log",
        "body": "Everything is fine",
        "tags": ["info"],
        "priority": 1,
        "timestamp": "2026-05-30T12:00:00Z",
        "containerName": "web-nginx",
        "containerId": "abc123",
    }

    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {"id": 99}

    mock_acquire_cm = AsyncMock()
    mock_acquire_cm.__aenter__.return_value = mock_conn
    mock_acquire_cm.__aexit__.return_value = None

    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_acquire_cm

    with patch("modules.dozzle.webhook.get_pool", return_value=mock_pool):
        result = await process_webhook_payload(payload)

    assert result["event_id"] == 99
    assert result["ticker_created"] is False


@pytest.mark.asyncio
async def test_webhook_test_type_returns_without_event():
    """Webhook handler returns early for type=test without creating an event."""
    sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")

    from modules.dozzle.webhook import process_webhook_payload

    payload = {"type": "test", "title": "Test notification"}

    with patch("modules.dozzle.webhook.get_pool") as mock_get_pool:
        result = await process_webhook_payload(payload)

    assert result["test"] is True
    assert result["event_id"] is None
    mock_get_pool.assert_not_called()

