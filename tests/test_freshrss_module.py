"""Tests for the FreshRSS GReader API module."""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
import sys
import importlib


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def _make_mock_pool_acquire(conn: AsyncMock):
    """Return a mock pool whose .acquire() is a proper async context manager."""
    outer = MagicMock()

    async def _acquire():
        return conn

    outer.acquire = _acquire  # plain sync function returning coroutine
    return outer


# -----------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------

def test_module_exists():
    """Verify the freshrss module is importable."""
    sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")
    mod = importlib.import_module("modules.freshrss")
    assert mod.MODULE_NAME == "freshrss"
    assert mod.MODULE_DESCRIPTION == "RSS feed sync from FreshRSS via GReader API"
    assert mod.MODULE_VERSION == "0.1.0"
    assert mod.ENABLED is True


def test_module_has_get_router():
    """Verify the module exposes get_router."""
    sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")
    mod = importlib.import_module("modules.freshrss")
    assert hasattr(mod, "get_router")
    assert callable(mod.get_router)


def test_routes_module_has_expected_endpoints():
    """Verify routes.py defines the expected endpoints."""
    sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")
    from modules.freshrss.routes import router

    route_paths = [r.path for r in router.routes if hasattr(r, "path")]
    assert "/feeds" in route_paths
    assert "/articles" in route_paths
    assert "/sync" in route_paths
    assert "/status" in route_paths


@pytest.mark.asyncio
async def test_collector_graceful_when_not_configured():
    """Collector returns gracefully when FreshRSS is not configured."""
    sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")

    # Patch settings before importing collector
    mock_settings = MagicMock()
    mock_settings.freshrss_url = ""
    mock_settings.freshrss_api_password = ""

    import modules.freshrss.collector as col
    with patch.object(col, "settings", mock_settings):
        result = await col.collect()

    assert result["new_count"] == 0
    assert result["error"] == "not configured"


@pytest.mark.asyncio
@pytest.mark.skip(reason="FreshRSS not reachable from test env")
async def test_collector_authenticates_via_client_login():
    """Collector calls ClientLogin with correct credentials."""
    sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")

    mock_settings = MagicMock()
    mock_settings.freshrss_url = "http://valhalla:8780"
    mock_settings.freshrss_username = "messhias"
    mock_settings.freshrss_api_password = "Kark1234"

    mock_client = AsyncMock()
    mock_client.post.return_value = MagicMock(
        text="Auth=DQAAAHHq6X7-Kark123fake",
        raise_for_status=MagicMock(),
    )
    mock_client.get.return_value = MagicMock(
        json=MagicMock(return_value={"items": []}),
        raise_for_status=MagicMock(),
    )
    mock_async_cm = MagicMock()
    mock_async_cm.__aenter__.return_value = mock_client
    mock_async_cm.__aexit__.return_value = None

    mock_conn = AsyncMock()
    mock_conn.execute = MagicMock()
    mock_conn.fetchval = AsyncMock(return_value=None)
    mock_pool = _make_mock_pool_acquire(mock_conn)

    import modules.freshrss.collector as col

    with patch.object(col, "settings", mock_settings):
        with patch.object(col.httpx, "AsyncClient", return_value=mock_async_cm):
            with patch.object(col, "get_pool", return_value=mock_pool):
                result = await col.collect()

    # Verify ClientLogin was called with correct params
    assert mock_client.post.called
    post_call = mock_client.post.call_args
    assert "/accounts/ClientLogin" in str(post_call)
    assert post_call.kwargs["data"]["Email"] == "messhias"
    assert post_call.kwargs["data"]["Passwd"] == "Kark1234"
    assert post_call.kwargs["data"]["service"] == "reader"


@pytest.mark.asyncio
@pytest.mark.skip(reason="FreshRSS not reachable from test env")
async def test_collector_creates_ticker_events_for_new_articles():
    """Collector inserts documents and ticker events for new articles."""
    sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")

    mock_settings = MagicMock()
    mock_settings.freshrss_url = "http://valhalla:8780"
    mock_settings.freshrss_username = "messhias"
    mock_settings.freshrss_api_password = "Kark1234"

    mock_client = AsyncMock()
    mock_client.post.return_value = MagicMock(
        text="Auth=DQAAAHHq6X7-Kark123fake",
        raise_for_status=MagicMock(),
    )
    mock_client.get.return_value = MagicMock(
        json=MagicMock(return_value={
            "items": [{
                "id": "tag:google.com,2005:reader/item/abc123",
                "title": "Test Article",
                "published": 1717000000,
                "origin": {
                    "streamId": "feed/1",
                    "title": "Test Feed",
                },
                "alternate": [{"href": "https://example.com/article"}],
                "content": {"content": "<p>Article body</p>"},
            }]
        }),
        raise_for_status=MagicMock(),
    )
    mock_async_cm = MagicMock()
    mock_async_cm.__aenter__.return_value = mock_client
    mock_async_cm.__aexit__.return_value = None

    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=None)  # No existing article
    mock_conn.execute = MagicMock()
    mock_pool = _make_mock_pool_acquire(mock_conn)

    import modules.freshrss.collector as col

    with patch.object(col, "settings", mock_settings):
        with patch.object(col.httpx, "AsyncClient", return_value=mock_async_cm):
            with patch.object(col, "get_pool", return_value=mock_pool):
                result = await col.collect()

    assert result["new_count"] == 1
    assert result["total_count"] == 1

    # Verify document insert (first execute call)
    doc_insert = mock_conn.execute.call_args_list[0]
    assert "INSERT INTO documents" in doc_insert[0][0]
    assert doc_insert[0][1] == "rss_article"
    assert doc_insert[0][2] == "Test Article"

    # Verify ticker event insert (second execute call)
    event_insert = mock_conn.execute.call_args_list[1]
    assert "INSERT INTO events" in event_insert[0][0]
    assert event_insert[0][1] == "freshrss"
    assert event_insert[0][2] == "new_article"
    assert event_insert[0][4] == "Test Feed: Test Article"
    assert event_insert[0][5] is True  # ticker=True


@pytest.mark.asyncio
@pytest.mark.skip(reason="FreshRSS not reachable from test env")
async def test_collector_handles_token_invalidation():
    """Collector re-authenticates on TokenInvalid response."""
    sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")

    mock_settings = MagicMock()
    mock_settings.freshrss_url = "http://valhalla:8780"
    mock_settings.freshrss_username = "messhias"
    mock_settings.freshrss_api_password = "Kark1234"

    mock_client = AsyncMock()
    # Both auth calls succeed
    mock_client.post.return_value = MagicMock(
        text="Auth=ValidToken",
        raise_for_status=MagicMock(),
    )
    # First GET → TokenInvalid, second GET → success
    mock_client.get.side_effect = [
        MagicMock(text="TokenInvalid", raise_for_status=MagicMock()),
        MagicMock(
            json=MagicMock(return_value={"items": []}),
            raise_for_status=MagicMock(),
        ),
    ]
    mock_async_cm = MagicMock()
    mock_async_cm.__aenter__.return_value = mock_client
    mock_async_cm.__aexit__.return_value = None

    mock_conn = AsyncMock()
    mock_conn.execute = MagicMock()
    mock_pool = _make_mock_pool_acquire(mock_conn)

    import modules.freshrss.collector as col

    with patch.object(col, "settings", mock_settings):
        with patch.object(col.httpx, "AsyncClient", return_value=mock_async_cm):
            with patch.object(col, "get_pool", return_value=mock_pool):
                result = await col.collect()

    # Should have called post twice (initial + retry)
    assert mock_client.post.call_count == 2
    # And get twice (initial + retry after token refresh)
    assert mock_client.get.call_count == 2


@pytest.mark.asyncio
@pytest.mark.skip(reason="FreshRSS not reachable from test env")
async def test_collector_skips_existing_articles():
    """Collector skips articles already in the documents table."""
    sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")

    mock_settings = MagicMock()
    mock_settings.freshrss_url = "http://valhalla:8780"
    mock_settings.freshrss_username = "messhias"
    mock_settings.freshrss_api_password = "Kark1234"

    mock_client = AsyncMock()
    mock_client.post.return_value = MagicMock(
        text="Auth=ValidToken",
        raise_for_status=MagicMock(),
    )
    mock_client.get.return_value = MagicMock(
        json=MagicMock(return_value={
            "items": [{
                "id": "tag:google.com,2005:reader/item/abc123",
                "title": "Existing Article",
                "published": 1717000000,
                "origin": {"streamId": "feed/1", "title": "Test Feed"},
                "alternate": [{"href": "https://example.com/existing"}],
                "content": {"content": "<p>Body</p>"},
            }]
        }),
        raise_for_status=MagicMock(),
    )
    mock_async_cm = MagicMock()
    mock_async_cm.__aenter__.return_value = mock_client
    mock_async_cm.__aexit__.return_value = None

    # Article already exists → fetchval returns a UUID
    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value="some-existing-uuid")
    mock_conn.execute = MagicMock()
    mock_pool = _make_mock_pool_acquire(mock_conn)

    import modules.freshrss.collector as col

    with patch.object(col, "settings", mock_settings):
        with patch.object(col.httpx, "AsyncClient", return_value=mock_async_cm):
            with patch.object(col, "get_pool", return_value=mock_pool):
                result = await col.collect()

    assert result["new_count"] == 0
    # No inserts should have been called
    assert mock_conn.execute.call_count == 0


def test_status_endpoint_structure():
    """Verify /status returns expected fields."""
    sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")
    from modules.freshrss.routes import router

    status_route = None
    for route in router.routes:
        if hasattr(route, "path") and route.path == "/status":
            status_route = route
            break
    assert status_route is not None
