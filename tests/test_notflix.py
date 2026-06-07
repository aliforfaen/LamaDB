"""Tests for the Notflix media poller module."""
import json
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

import sys
sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")


# ---------------------------------------------------------------------------
# Module structure tests
# ---------------------------------------------------------------------------

def test_module_exists():
    """Verify the notflix module is importable."""
    from modules.notflix import MODULE_NAME, MODULE_DESCRIPTION, MODULE_VERSION, ENABLED
    assert MODULE_NAME == "notflix"
    assert MODULE_VERSION == "0.1.0"
    assert ENABLED is True


def test_module_has_get_router():
    """Verify the module exposes get_router."""
    from modules.notflix import get_router
    assert callable(get_router)


def test_module_has_collect():
    """Verify the module exposes collect."""
    from modules.notflix import collect
    assert callable(collect)


def test_routes_module_has_expected_endpoints():
    """Verify routes.py defines the expected endpoints."""
    from modules.notflix.routes import router

    route_paths = []
    for route in router.routes:
        if hasattr(route, "path"):
            route_paths.append(route.path)
    assert "/status" in route_paths
    assert "/activity" in route_paths
    assert "/health" in route_paths


# ---------------------------------------------------------------------------
# Collector tests — not configured
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_collect_not_configured_returns_errors():
    """collect() returns error dicts when services are not configured."""
    mock_conn = AsyncMock()
    mock_acquire_cm = AsyncMock()
    mock_acquire_cm.__aenter__.return_value = mock_conn
    mock_acquire_cm.__aexit__.return_value = None
    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_acquire_cm

    with patch("modules.notflix.collector.settings") as mock_settings:
        mock_settings.sonarr_url = ""
        mock_settings.sonarr_api_key = ""
        mock_settings.radarr_url = ""
        mock_settings.radarr_api_key = ""
        mock_settings.tautulli_url = ""
        mock_settings.tautulli_api_key = ""

        with patch("modules.notflix.collector.get_pool", return_value=mock_pool):
            from modules.notflix.collector import collect
            result = await collect()

    assert "sonarr" in result
    assert "radarr" in result
    assert "tautulli" in result
    assert result["sonarr"]["error"] == "Sonarr not configured"
    assert result["radarr"]["error"] == "Radarr not configured"
    assert result["tautulli"]["error"] == "Tautulli not configured"


@pytest.mark.asyncio
async def test_collect_handles_http_errors():
    """collect() handles HTTP errors gracefully for each service."""
    mock_conn = AsyncMock()
    mock_acquire_cm = AsyncMock()
    mock_acquire_cm.__aenter__.return_value = mock_conn
    mock_acquire_cm.__aexit__.return_value = None
    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_acquire_cm

    with patch("modules.notflix.collector.settings") as mock_settings:
        mock_settings.sonarr_url = "http://localhost:8989"
        mock_settings.sonarr_api_key = "fake-key"
        mock_settings.radarr_url = ""
        mock_settings.radarr_api_key = ""
        mock_settings.tautulli_url = ""
        mock_settings.tautulli_api_key = ""

        with patch("modules.notflix.collector.httpx.AsyncClient") as mock_client_class, \
             patch("modules.notflix.collector.get_pool", return_value=mock_pool):

            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            # Simulate connection error for Sonarr
            mock_client.get.side_effect = Exception("Connection refused")

            from modules.notflix.collector import collect
            result = await collect()

    assert "sonarr" in result
    assert "error" in result["sonarr"]
    assert "radarr" in result
    assert result["radarr"]["error"] == "Radarr not configured"
    assert "tautulli" in result
    assert result["tautulli"]["error"] == "Tautulli not configured"


# ---------------------------------------------------------------------------
# Collector tests — ticker events
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_collect_creates_media_snapshot_event():
    """collect() inserts a media_snapshot event into the events table."""
    with patch("modules.notflix.collector.settings") as mock_settings:
        mock_settings.sonarr_url = "http://localhost:8989"
        mock_settings.sonarr_api_key = "fake-key"
        mock_settings.radarr_url = "http://localhost:7878"
        mock_settings.radarr_api_key = "fake-key"
        mock_settings.tautulli_url = ""
        mock_settings.tautulli_api_key = ""

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_acquire_cm = AsyncMock()
        mock_acquire_cm.__aenter__.return_value = mock_conn
        mock_acquire_cm.__aexit__.return_value = None
        mock_pool = MagicMock()
        mock_pool.acquire.return_value = mock_acquire_cm

        with patch("modules.notflix.collector.httpx.AsyncClient") as mock_client_class, \
             patch("modules.notflix.collector.get_pool", return_value=mock_pool):

            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            def make_response(data, status=200):
                m = MagicMock()
                m.status_code = status
                m.raise_for_status = MagicMock()
                m.json = MagicMock(return_value=data)
                return m

            # Sonarr returns data
            mock_client.get.side_effect = [
                make_response([{"id": 1, "title": "TV Show"}]),  # series list
                make_response([{"id": 1, "hasFile": True}]),    # episodes
                make_response({"totalRecords": 0}),              # missing
                make_response({"totalRecords": 0}),              # queue
                make_response({"records": []}),                  # history
            ]

            from modules.notflix.collector import collect
            result = await collect()

    # Should have called execute at least once (for the snapshot event)
    assert mock_conn.execute.called
    # First call should insert notflix media_snapshot
    first_call_args = mock_conn.execute.call_args_list[0][0]
    assert first_call_args[1] == "notflix"
    assert first_call_args[2] == "media_snapshot"


@pytest.mark.asyncio
async def test_collect_creates_ticker_for_new_grabs():
    """collect() fires ticker events when recent_grabs > 0."""
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_acquire_cm = AsyncMock()
    mock_acquire_cm.__aenter__.return_value = mock_conn
    mock_acquire_cm.__aexit__.return_value = None
    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_acquire_cm

    with patch("modules.notflix.collector.settings") as mock_settings:
        mock_settings.sonarr_url = "http://localhost:8989"
        mock_settings.sonarr_api_key = "fake-key"
        mock_settings.radarr_url = ""
        mock_settings.radarr_api_key = ""
        mock_settings.tautulli_url = ""
        mock_settings.tautulli_api_key = ""

        with patch("modules.notflix.collector.httpx.AsyncClient") as mock_client_class, \
             patch("modules.notflix.collector.get_pool", return_value=mock_pool):

            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            def make_response(data):
                m = MagicMock()
                m.status_code = 200
                m.raise_for_status = MagicMock()
                m.json = MagicMock(return_value=data)
                return m

            # History returns 3 grabbed episodes — this is what triggers ticker
            mock_client.get.side_effect = [
                make_response([{"id": 1, "title": "TV Show"}]),   # series
                make_response([{"id": 1, "hasFile": True}]),      # episodes
                make_response({"totalRecords": 0}),                # missing
                make_response({"totalRecords": 0}),                # queue
                make_response({"records": [                        # history with 3 grabs
                    {"eventType": "grabbed", "title": "Ep 1"},
                    {"eventType": "grabbed", "title": "Ep 2"},
                    {"eventType": "grabbed", "title": "Ep 3"},
                ]}),
            ]

            from modules.notflix.collector import collect
            result = await collect()

    # collect() calls execute() once for the snapshot + once per ticker
    assert mock_conn.execute.call_count >= 2
    # Find the ticker call — ticker=True is at positional index 5
    calls = mock_conn.execute.call_args_list
    ticker_calls = [c for c in calls if len(c[0]) > 5 and c[0][5] is True]
    assert len(ticker_calls) >= 1
    # The ticker should be from sonarr for new TV content
    assert ticker_calls[0][0][1] == "sonarr"
    assert ticker_calls[0][0][2] == "new_content"
    assert "3 new TV episodes grabbed" in ticker_calls[0][0][4]


# ---------------------------------------------------------------------------
# Health endpoint tests
# ---------------------------------------------------------------------------

def test_health_endpoint_exists():
    """Health endpoint is defined."""
    from modules.notflix.routes import router

    health_route = None
    for route in router.routes:
        if hasattr(route, "path") and route.path == "/health":
            health_route = route
            break
    assert health_route is not None


def test_status_endpoint_exists():
    """Status endpoint is defined."""
    from modules.notflix.routes import router

    status_route = None
    for route in router.routes:
        if hasattr(route, "path") and route.path == "/status":
            status_route = route
            break
    assert status_route is not None


def test_activity_endpoint_exists():
    """Activity endpoint is defined."""
    from modules.notflix.routes import router

    activity_route = None
    for route in router.routes:
        if hasattr(route, "path") and route.path == "/activity":
            activity_route = route
            break
    assert activity_route is not None


# ---------------------------------------------------------------------------
# _poll_sonarr / _poll_radarr / _poll_tautulli — not configured path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_poll_sonarr_not_configured():
    """_poll_sonarr returns error dict when URL is empty."""
    with patch("modules.notflix.collector.settings") as mock_settings:
        mock_settings.sonarr_url = ""
        mock_settings.sonarr_api_key = ""

        from modules.notflix.collector import _poll_sonarr
        result = await _poll_sonarr(AsyncMock())

    assert result == {"error": "Sonarr not configured"}


@pytest.mark.asyncio
async def test_poll_radarr_not_configured():
    """_poll_radarr returns error dict when URL is empty."""
    with patch("modules.notflix.collector.settings") as mock_settings:
        mock_settings.radarr_url = ""
        mock_settings.radarr_api_key = ""

        from modules.notflix.collector import _poll_radarr
        result = await _poll_radarr(AsyncMock())

    assert result == {"error": "Radarr not configured"}


@pytest.mark.asyncio
async def test_poll_tautulli_not_configured():
    """_poll_tautulli returns error dict when URL is empty."""
    with patch("modules.notflix.collector.settings") as mock_settings:
        mock_settings.tautulli_url = ""
        mock_settings.tautulli_api_key = ""

        from modules.notflix.collector import _poll_tautulli
        result = await _poll_tautulli(AsyncMock())

    assert result == {"error": "Tautulli not configured"}
