"""Tests for the Audiobookshelf module."""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

_LOCAL_REPO = str(Path(__file__).resolve().parent.parent)
_STALE_PATHS = (
    "/home/messhias/LamaFiles/projects/lamadb",
    "/home/messhiah/LamaFiles/projects/lamadb",
)


@pytest.fixture(autouse=True)
def _prefer_local_checkout():
    """Make sure `modules` resolves to *this* checkout.

    Other tests in this folder `sys.path.insert(0, "/home/messhias/LamaFiles/...")`
    which is a stale checkout missing newer modules. Without this fixture the
    `modules` package gets cached from that stale path during test collection
    and audiobookshelf (which only lives here) is unreachable.
    """
    for _p in _STALE_PATHS:
        while _p in sys.path:
            sys.path.remove(_p)
    if _LOCAL_REPO in sys.path:
        sys.path.remove(_LOCAL_REPO)
    sys.path.insert(0, _LOCAL_REPO)

    for _key in [k for k in sys.modules if k == "modules" or k.startswith("modules.")]:
        del sys.modules[_key]
    yield


# ---------------------------------------------------------------------------
# Module structure tests
# ---------------------------------------------------------------------------

def test_module_exists():
    """Verify the audiobookshelf module is importable."""
    from modules.audiobookshelf import (
        MODULE_NAME, MODULE_DESCRIPTION, MODULE_VERSION, ENABLED,
    )
    assert MODULE_NAME == "audiobookshelf"
    assert MODULE_VERSION == "0.1.0"
    assert ENABLED is True


def test_module_has_get_router():
    """Verify the module exposes get_router."""
    from modules.audiobookshelf import get_router
    assert callable(get_router)


def test_module_has_collect():
    """Verify the module exposes collect."""
    from modules.audiobookshelf import collect
    assert callable(collect)


def test_module_config_schema_keys():
    """The MODULE_CONFIG_SCHEMA exposes the expected settings keys."""
    from modules.audiobookshelf import MODULE_CONFIG_SCHEMA

    expected_keys = {
        "audiobookshelf_url",
        "audiobookshelf_token",
        "audiobookshelf_poll_interval",
        "audiobookshelf_max_books_per_library",
    }
    assert expected_keys.issubset(MODULE_CONFIG_SCHEMA.keys())
    # token must be marked secret so it doesn't leak in module-settings UI
    assert MODULE_CONFIG_SCHEMA["audiobookshelf_token"]["type"] == "secret"


def test_routes_module_has_expected_endpoints():
    """Verify routes.py defines the expected endpoints."""
    from modules.audiobookshelf.routes import router

    route_paths = []
    for route in router.routes:
        if hasattr(route, "path"):
            route_paths.append(route.path)
    assert "/status" in route_paths
    assert "/libraries" in route_paths
    assert "/books" in route_paths
    assert "/health" in route_paths
    assert "/poll" in route_paths


# ---------------------------------------------------------------------------
# Collector tests — not configured
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_collect_not_configured_returns_error():
    """collect() returns an error dict when settings are missing."""
    with patch("modules.audiobookshelf.collector.settings") as mock_settings:
        mock_settings.audiobookshelf_url = ""
        mock_settings.audiobookshelf_token = ""

        from modules.audiobookshelf.collector import collect
        result = await collect()

    assert "error" in result
    assert "URL or token" in result["error"]


@pytest.mark.asyncio
async def test_collect_handles_libraries_fetch_error():
    """collect() returns an error if /api/libraries fails."""
    with patch("modules.audiobookshelf.collector.settings") as mock_settings:
        mock_settings.audiobookshelf_url = "http://localhost:13378"
        mock_settings.audiobookshelf_token = "fake-token"

        with patch("modules.audiobookshelf.collector.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.side_effect = Exception("Connection refused")

            from modules.audiobookshelf.collector import collect
            result = await collect()

    assert "error" in result
    assert "libraries fetch failed" in result["error"]


@pytest.mark.asyncio
async def test_collect_inserts_snapshot_event():
    """collect() inserts an abs_snapshot event when libraries + items are returned."""
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_acquire_cm = AsyncMock()
    mock_acquire_cm.__aenter__.return_value = mock_conn
    mock_acquire_cm.__aexit__.return_value = None
    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_acquire_cm

    with patch("modules.audiobookshelf.collector.settings") as mock_settings:
        mock_settings.audiobookshelf_url = "http://localhost:13378"
        mock_settings.audiobookshelf_token = "fake-token"
        mock_settings.audiobookshelf_max_books_per_library = 10

        with patch("modules.audiobookshelf.collector.httpx.AsyncClient") as mock_client_class, \
             patch("modules.audiobookshelf.collector.get_pool", return_value=mock_pool):

            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            def make_response(data, status=200):
                m = MagicMock()
                m.status_code = status
                m.raise_for_status = MagicMock()
                m.json = MagicMock(return_value=data)
                return m

            mock_client.get.side_effect = [
                make_response({  # /api/libraries
                    "libraries": [
                        {"id": "lib_books", "name": "Audiobooks",
                         "mediaType": "book", "bookCount": 1}
                    ]
                }),
                make_response({  # /api/libraries/lib_books/items
                    "results": [
                        {
                            "id": "item_1",
                            "addedAt": 1700000000000,
                            "updatedAt": 1700000000000,
                            "media": {
                                "id": "med_1",
                                "duration": 19800.0,
                                "tracks": [{"index": 1}],
                                "chapters": [],
                                "metadata": {
                                    "title": "Project Hail Mary",
                                    "authorName": "Andy Weir",
                                    "narratorName": "Ray Porter",
                                    "publishedYear": 2021,
                                    "genres": ["Science Fiction"],
                                    "series": [{"name": "Standalone"}],
                                },
                            },
                            "progress": {"isFinished": False, "progress": 0.5},
                        }
                    ]
                }),
            ]

            from modules.audiobookshelf.collector import collect
            result = await collect()

    # abs_snapshot event row was inserted
    assert mock_conn.execute.called
    insert_calls = [
        c for c in mock_conn.execute.call_args_list
        if len(c[0]) >= 2 and c[0][1] == "audiobookshelf" and c[0][2] == "abs_snapshot"
    ]
    assert len(insert_calls) == 1
    # one document upsert happened (inserted column)
    insert_args = insert_calls[0][0]
    metadata = json.loads(insert_args[6])  # metadata positional arg
    assert metadata["book_count"] == 1
    assert metadata["in_progress_count"] == 1
    assert metadata["finished_count"] == 0
    assert len(metadata["libraries"]) == 1
    assert metadata["libraries"][0]["name"] == "Audiobooks"
    assert result["book_count"] == 1


@pytest.mark.asyncio
async def test_book_from_item_normalizes_metadata():
    """_book_from_item flattens ABS payload into the document shape."""
    with patch("modules.audiobookshelf.collector.settings") as mock_settings:
        mock_settings.audiobookshelf_url = "http://localhost:13378"
        mock_settings.audiobookshelf_token = "x"

        from modules.audiobookshelf.collector import _book_from_item

        book = _book_from_item(
            {
                "id": "item_x",
                "addedAt": 1700000000000,
                "updatedAt": 1700000000000,
                "media": {
                    "id": "med_x",
                    "duration": 3600.5,
                    "tracks": [{"index": 1}, {"index": 2}],
                    "chapters": [],
                    "metadata": {
                        "title": "Dune",
                        "authorName": "Frank Herbert",
                        "narratorName": "Scott Brick",
                        "publishedYear": 1965,
                        "genres": ["Sci-Fi", "Classic"],
                        "series": [{"name": "Dune Saga"}],
                    },
                },
                "progress": {"isFinished": True, "progress": 1.0},
            },
            {"id": "lib_books", "name": "Audiobooks"},
        )

    assert book is not None
    assert book["item_id"] == "item_x"
    assert book["library_id"] == "lib_books"
    assert book["library_name"] == "Audiobooks"
    assert book["title"] == "Dune"
    assert book["author"] == "Frank Herbert"
    assert book["narrator"] == "Scott Brick"
    assert book["published_year"] == 1965
    assert book["genres"] == ["Sci-Fi", "Classic"]
    assert book["series"] == ["Dune Saga"]
    assert book["duration"] == 3600.5
    assert book["track_count"] == 2
    assert book["progress_percent"] == 1.0
    assert book["is_finished"] is True
    assert book["added_at"] is not None and "T" in book["added_at"]


@pytest.mark.asyncio
async def test_book_from_item_returns_none_when_media_missing():
    """Items without a media payload are skipped."""
    with patch("modules.audiobookshelf.collector.settings") as mock_settings:
        mock_settings.audiobookshelf_url = "http://localhost:13378"
        mock_settings.audiobookshelf_token = "x"

        from modules.audiobookshelf.collector import _book_from_item

        # No media at all -> skipped
        assert _book_from_item({"id": "item_x"}, {}) is None
        # No usable id (item and media both blank) -> skipped
        assert _book_from_item({"id": "", "media": {"id": ""}}, {}) is None


# ---------------------------------------------------------------------------
# Health endpoint tests
# ---------------------------------------------------------------------------

def test_health_endpoint_exists():
    """Health endpoint is defined on the module router."""
    from modules.audiobookshelf.routes import router

    for route in router.routes:
        if hasattr(route, "path") and route.path == "/health":
            return
    raise AssertionError("health endpoint not registered")


def test_status_endpoint_exists():
    """Status endpoint is defined on the module router."""
    from modules.audiobookshelf.routes import router

    for route in router.routes:
        if hasattr(route, "path") and route.path == "/status":
            return
    raise AssertionError("status endpoint not registered")


def test_libraries_endpoint_exists():
    """Libraries endpoint is defined on the module router."""
    from modules.audiobookshelf.routes import router

    for route in router.routes:
        if hasattr(route, "path") and route.path == "/libraries":
            return
    raise AssertionError("libraries endpoint not registered")


def test_books_endpoint_exists():
    """Books endpoint is defined on the module router."""
    from modules.audiobookshelf.routes import router

    for route in router.routes:
        if hasattr(route, "path") and route.path == "/books":
            return
    raise AssertionError("books endpoint not registered")


# ---------------------------------------------------------------------------
# Migration test
# ---------------------------------------------------------------------------

def test_migration_file_present():
    """Migration 033 exists and declares the partial unique index."""
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    migration = repo_root / "migrations" / "033_audiobookshelf_module.sql"
    assert migration.exists(), f"Missing migration: {migration}"

    text = migration.read_text()
    assert "audiobookshelf" in text
    assert "idx_documents_audiobookshelf_item_id" in text
    assert "source_type = 'audiobookshelf'" in text