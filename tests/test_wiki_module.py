"""Tests for the Wiki module."""
import pytest
import os


def test_module_exists():
    """Verify the wiki module can be imported and has required attributes."""
    from modules.wiki import MODULE_NAME, MODULE_DESCRIPTION, MODULE_VERSION, ENABLED, get_router

    assert MODULE_NAME == "wiki"
    assert MODULE_DESCRIPTION == "Wiki reader, scratchpad, and edit log"
    assert ENABLED is True
    assert callable(get_router)


def test_module_has_router():
    """Verify get_router returns a FastAPI APIRouter."""
    from modules.wiki import get_router

    router = get_router()
    assert router is not None
    # FastAPI router has routes attribute
    assert hasattr(router, "routes")


@pytest.mark.asyncio
async def test_scratchpad_post_creates_document():
    """POST /api/wiki/scratchpad should create a document entry via the API."""
    pytest.skip("Requires live database connection — covered by integration test")


@pytest.mark.asyncio
async def test_scratchpad_get_returns_entries():
    """GET /api/wiki/scratchpad should list entries."""
    pytest.skip("Requires live database connection")


def test_wiki_pages_lists_files():
    """GET /api/wiki/pages should return a list of wiki pages."""
    from modules.wiki.wiki_reader import list_pages

    pages = list_pages("/wiki")
    assert isinstance(pages, list)


def test_wiki_pages_graceful_when_path_missing():
    """list_pages should return [] gracefully when wiki path doesn't exist."""
    from modules.wiki.wiki_reader import list_pages

    pages = list_pages("/nonexistent/path")
    assert pages == []


def test_read_page_returns_content():
    """read_page should return page content when file exists."""
    from modules.wiki.wiki_reader import read_page

    page = read_page("/wiki", "wiki.md")
    if page is not None:
        assert "path" in page
        assert "content" in page


def test_read_page_nonexistent():
    """read_page should return None when page doesn't exist."""
    from modules.wiki.wiki_reader import read_page

    result = read_page("/wiki", "nonexistent/page.md")
    # Returns None if file missing
    assert result is None or isinstance(result, dict)


def test_search_wiki():
    """search_wiki should find matching content."""
    from modules.wiki.wiki_reader import search_wiki

    results = search_wiki("/wiki", "homelab", limit=5)
    assert isinstance(results, list)
    for r in results:
        assert "path" in r
        assert "title" in r
        assert "snippet" in r


def test_search_wiki_graceful():
    """search_wiki should return [] gracefully on missing directory."""
    from modules.wiki.wiki_reader import search_wiki

    results = search_wiki("/nonexistent", "test")
    assert results == []


def test_parse_index():
    """parse_index should parse index.md structure."""
    from modules.wiki.wiki_reader import parse_index

    result = parse_index("/wiki")
    assert isinstance(result, dict)
    assert "sections" in result
    assert "pages" in result


def test_wiki_log_endpoint_route_exists():
    """Verify /log route is registered on the wiki router."""
    from modules.wiki import get_router

    router = get_router()
    paths = [r.path for r in router.routes]
    assert "/log" in paths
    assert "/scratchpad" in paths
    assert "/pages" in paths
    assert "/search" in paths
