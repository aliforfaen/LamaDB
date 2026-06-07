"""
Tests for the Feeds RSS generator module.

Uses httpx ASGITransport to test the FastAPI app directly.
Tests use the real database (migrations already run on startup via docker compose).
"""
import pytest
import pytest_asyncio
import xml.etree.ElementTree as ET
from uuid import uuid4

from httpx import ASGITransport, AsyncClient


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def client():
    """
    Create an async test client for the FastAPI app.
    """
    from app.main import make_app

    app = make_app()

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(scope="function")
async def db_pool():
    """Get the database pool for direct DB queries in tests."""
    from app.db import get_pool
    return get_pool()


@pytest_asyncio.fixture(scope="function")
async def sample_documents(db_pool):
    """
    Create sample documents for feed testing.
    Returns list of doc ids.
    """
    doc_ids = []
    async with db_pool.acquire() as conn:
        # Summary doc with tags
        row = await conn.fetchrow(
            """
            INSERT INTO documents (source_type, title, content, tags)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            "summary",
            "Test Summary Document",
            "This is a test summary with important content about things.",
            ["tech", "news"]
        )
        doc_ids.append(row["id"])

        # Another summary doc
        row = await conn.fetchrow(
            """
            INSERT INTO documents (source_type, title, content, tags)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            "summary",
            "Another Summary",
            "More content for the second document.",
            ["tech", "opinion"]
        )
        doc_ids.append(row["id"])

        # Agent output doc (should be filtered out by default)
        row = await conn.fetchrow(
            """
            INSERT INTO documents (source_type, title, content, tags)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            "agent_output",
            "Raw Agent Output",
            "This is raw log output that should not appear in RSS by default.",
            ["logs"]
        )
        doc_ids.append(row["id"])

    yield doc_ids

    # Cleanup
    async with db_pool.acquire() as conn:
        for doc_id in doc_ids:
            await conn.execute("DELETE FROM documents WHERE id = $1", doc_id)


@pytest_asyncio.fixture(scope="function")
async def sample_feed(client, db_pool):
    """Create a sample feed for testing and return the slug."""
    slug = f"test-feed-{uuid4().hex[:8]}"

    # Create API key for auth
    import bcrypt
    from app.config import settings
    key_plain = "test-feeds-key"
    key_hash = bcrypt.hashpw(f"{settings.api_key_salt}{key_plain}".encode(), bcrypt.gensalt()).decode()

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO api_keys (name, key_hash, role, scopes)
            VALUES ($1, $2, $3, $4)
            """,
            "test-feeds-user",
            key_hash,
            "admin",
            ["feeds"]
        )

    response = await client.post(
        "/api/feeds",
        json={
            "name": "Test Feed",
            "slug": slug,
            "description": "A test feed",
            "filter_tags": ["tech"],
            "filter_source_types": [],
            "max_items": 50,
        },
        headers={"Authorization": f"Bearer {key_plain}"}
    )
    assert response.status_code == 201

    yield slug

    # Cleanup
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM feeds WHERE slug = $1", slug)
        await conn.execute("DELETE FROM api_keys WHERE name = $1", "test-feeds-user")


# --------------------------------------------------------------------------
# Test 1: create_feed_via_post
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_feed_via_post(client, db_pool):
    """POST /api/feeds creates a new feed in the database."""
    slug = f"create-test-{uuid4().hex[:8]}"

    # Create API key for auth
    import bcrypt
    from app.config import settings
    key_plain = "create-test-key"
    key_hash = bcrypt.hashpw(f"{settings.api_key_salt}{key_plain}".encode(), bcrypt.gensalt()).decode()

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO api_keys (name, key_hash, role, scopes)
            VALUES ($1, $2, $3, $4)
            """,
            "create-test-user",
            key_hash,
            "admin",
            ["feeds"]
        )

    response = await client.post(
        "/api/feeds",
        json={
            "name": "Create Test Feed",
            "slug": slug,
            "description": "Testing feed creation",
            "filter_tags": ["python", "news"],
            "filter_source_types": ["summary"],
            "max_items": 25,
        },
        headers={"Authorization": f"Bearer {key_plain}"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Create Test Feed"
    assert data["slug"] == slug
    assert data["description"] == "Testing feed creation"
    assert data["filter_tags"] == ["python", "news"]
    assert data["filter_source_types"] == ["summary"]
    assert data["max_items"] == 25
    assert "id" in data
    assert "created_at" in data

    # Cleanup
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM feeds WHERE slug = $1", slug)
        await conn.execute("DELETE FROM api_keys WHERE name = $1", "create-test-user")


# --------------------------------------------------------------------------
# Test 2: create_feed_requires_admin_or_agent_role
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_feed_requires_admin_or_agent_role(client, db_pool):
    """POST /api/feeds with read-only key returns 403."""
    slug = f"auth-test-{uuid4().hex[:8]}"

    # Create read-only API key
    import bcrypt
    from app.config import settings
    key_plain = "read-only-key"
    key_hash = bcrypt.hashpw(f"{settings.api_key_salt}{key_plain}".encode(), bcrypt.gensalt()).decode()

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO api_keys (name, key_hash, role, scopes)
            VALUES ($1, $2, $3, $4)
            """,
            "read-only-user",
            key_hash,
            "read",
            []
        )

    response = await client.post(
        "/api/feeds",
        json={
            "name": "Should Fail",
            "slug": slug,
        },
        headers={"Authorization": f"Bearer {key_plain}"}
    )
    assert response.status_code == 403

    # Cleanup
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM api_keys WHERE name = $1", "read-only-user")


# --------------------------------------------------------------------------
# Test 3: list_feeds
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_feeds(client, sample_feed):
    """GET /api/feeds returns a list of feeds."""
    response = await client.get(
        "/api/feeds",
        headers={"Authorization": "Bearer test-feeds-key"}
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert any(f["slug"] == sample_feed for f in data)


# --------------------------------------------------------------------------
# Test 4: get_feed_by_slug
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_feed_by_slug(client, sample_feed):
    """GET /api/feeds/{slug} returns the feed details."""
    response = await client.get(
        f"/api/feeds/{sample_feed}",
        headers={"Authorization": "Bearer test-feeds-key"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["slug"] == sample_feed
    assert data["name"] == "Test Feed"


# --------------------------------------------------------------------------
# Test 5: get_feed_by_slug_not_found
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_feed_by_slug_not_found(client, db_pool):
    """GET /api/feeds/{nonexistent} returns 404."""
    # Create a temporary key for this test (doesn't use sample_feed fixture)
    import bcrypt
    from app.config import settings

    key_plain = "notfound-test-key"
    key_hash = bcrypt.hashpw(f"{settings.api_key_salt}{key_plain}".encode(), bcrypt.gensalt()).decode()

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO api_keys (name, key_hash, role, scopes)
            VALUES ($1, $2, $3, $4)
            """,
            "notfound-test-user",
            key_hash,
            "admin",
            ["feeds"]
        )

    response = await client.get(
        "/api/feeds/nonexistent-feed-slug-xyz",
        headers={"Authorization": f"Bearer {key_plain}"}
    )
    assert response.status_code == 404

    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM api_keys WHERE name = $1", "notfound-test-user")


# --------------------------------------------------------------------------
# Test 6: update_feed
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_feed(client, sample_feed):
    """PUT /api/feeds/{slug} updates the feed."""
    response = await client.put(
        f"/api/feeds/{sample_feed}",
        json={
            "name": "Updated Feed Name",
            "max_items": 100,
        },
        headers={"Authorization": "Bearer test-feeds-key"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Feed Name"
    assert data["max_items"] == 100
    assert data["description"] == "A test feed"  # Unchanged


# --------------------------------------------------------------------------
# Test 7: delete_feed
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_feed(client, db_pool):
    """DELETE /api/feeds/{slug} removes the feed."""
    slug = f"delete-test-{uuid4().hex[:8]}"

    # Create API key
    import bcrypt
    from app.config import settings
    key_plain = "delete-test-key"
    key_hash = bcrypt.hashpw(f"{settings.api_key_salt}{key_plain}".encode(), bcrypt.gensalt()).decode()

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO api_keys (name, key_hash, role, scopes)
            VALUES ($1, $2, $3, $4)
            """,
            "delete-test-user",
            key_hash,
            "admin",
            ["feeds"]
        )
        # Create the feed directly
        await conn.execute(
            """
            INSERT INTO feeds (name, slug, description, filter_tags, filter_source_types, max_items)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            "To Be Deleted",
            slug,
            "Will be deleted",
            ["temp"],
            [],
            50
        )

    response = await client.delete(
        f"/api/feeds/{slug}",
        headers={"Authorization": f"Bearer {key_plain}"}
    )
    assert response.status_code == 204

    # Verify it's gone
    response2 = await client.get(
        f"/api/feeds/{slug}",
        headers={"Authorization": f"Bearer {key_plain}"}
    )
    assert response2.status_code == 404

    # Cleanup
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM api_keys WHERE name = $1", "delete-test-user")


# --------------------------------------------------------------------------
# Test 8: rss_xml_output_valid_xml
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rss_xml_output_valid_xml(client, sample_feed, sample_documents):
    """GET /feeds/{slug}.xml returns valid RSS XML with correct content-type."""
    response = await client.get(f"/feeds/{sample_feed}.xml")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/xml"

    # Parse as XML
    content = response.text
    assert content.startswith("<?xml")
    root = ET.fromstring(content)

    # Check RSS structure
    assert root.tag == "rss"
    channel = root.find("channel")
    assert channel is not None
    assert channel.find("title").text == "Test Feed"
    assert channel.find("description").text == "A test feed"


# --------------------------------------------------------------------------
# Test 9: rss_filtering_by_tags
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rss_filtering_by_tags(client, sample_documents, db_pool):
    """
    Create a feed that filters by tag 'opinion' and verify only matching
    documents appear in the RSS.
    """
    slug = f"tag-filter-{uuid4().hex[:8]}"

    # Create API key
    import bcrypt
    from app.config import settings
    key_plain = "tag-filter-key"
    key_hash = bcrypt.hashpw(f"{settings.api_key_salt}{key_plain}".encode(), bcrypt.gensalt()).decode()

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO api_keys (name, key_hash, role, scopes)
            VALUES ($1, $2, $3, $4)
            """,
            "tag-filter-user",
            key_hash,
            "admin",
            ["feeds"]
        )
        await conn.execute(
            """
            INSERT INTO feeds (name, slug, description, filter_tags, filter_source_types, max_items)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            "Opinion Feed",
            slug,
            "Only opinion articles",
            ["opinion"],
            ["summary"],
            50
        )

    response = await client.get(f"/feeds/{slug}.xml")
    assert response.status_code == 200

    root = ET.fromstring(response.text)
    channel = root.find("channel")
    items = channel.findall("item")

    # Should have at least one item (the doc with 'opinion' tag)
    titles = [item.find("title").text for item in items]
    assert "Another Summary" in titles
    assert "Test Summary Document" not in titles  # Has 'tech', not 'opinion'

    # Cleanup
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM feeds WHERE slug = $1", slug)
        await conn.execute("DELETE FROM api_keys WHERE name = $1", "tag-filter-user")


# --------------------------------------------------------------------------
# Test 10: rss_filtering_by_source_type
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rss_filtering_by_source_type(client, sample_documents, db_pool):
    """
    Create a feed that filters by source_type='agent_output' and verify
    raw agent output docs appear but summaries don't.
    """
    slug = f"source-filter-{uuid4().hex[:8]}"

    # Create API key
    import bcrypt
    from app.config import settings
    key_plain = "source-filter-key"
    key_hash = bcrypt.hashpw(f"{settings.api_key_salt}{key_plain}".encode(), bcrypt.gensalt()).decode()

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO api_keys (name, key_hash, role, scopes)
            VALUES ($1, $2, $3, $4)
            """,
            "source-filter-user",
            key_hash,
            "admin",
            ["feeds"]
        )
        await conn.execute(
            """
            INSERT INTO feeds (name, slug, description, filter_tags, filter_source_types, max_items)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            "Agent Output Feed",
            slug,
            "Only agent output",
            [],
            ["agent_output"],
            50
        )

    response = await client.get(f"/feeds/{slug}.xml")
    assert response.status_code == 200

    root = ET.fromstring(response.text)
    channel = root.find("channel")
    items = channel.findall("item")

    titles = [item.find("title").text for item in items]
    assert "Raw Agent Output" in titles
    assert "Test Summary Document" not in titles  # source_type='summary', not 'agent_output'

    # Cleanup
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM feeds WHERE slug = $1", slug)
        await conn.execute("DELETE FROM api_keys WHERE name = $1", "source-filter-user")


# --------------------------------------------------------------------------
# Test 11: rss_public_endpoint_no_auth
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rss_public_endpoint_no_auth(client, sample_feed):
    """GET /feeds/{slug}.xml works without any Authorization header."""
    response = await client.get(f"/feeds/{sample_feed}.xml")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/xml"


# --------------------------------------------------------------------------
# Test 12: rss_feed_with_no_matching_documents
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rss_feed_with_no_matching_documents(client, db_pool):
    """
    Create a feed with filters that match nothing. RSS should be valid
    but have zero items.
    """
    slug = f"empty-feed-{uuid4().hex[:8]}"

    # Create API key
    import bcrypt
    from app.config import settings
    key_plain = "empty-feed-key"
    key_hash = bcrypt.hashpw(f"{settings.api_key_salt}{key_plain}".encode(), bcrypt.gensalt()).decode()

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO api_keys (name, key_hash, role, scopes)
            VALUES ($1, $2, $3, $4)
            """,
            "empty-feed-user",
            key_hash,
            "admin",
            ["feeds"]
        )
        await conn.execute(
            """
            INSERT INTO feeds (name, slug, description, filter_tags, filter_source_types, max_items)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            "Empty Feed",
            slug,
            "No matching documents",
            ["nonexistent-tag-xyz"],
            [],
            50
        )

    response = await client.get(f"/feeds/{slug}.xml")
    assert response.status_code == 200

    root = ET.fromstring(response.text)
    channel = root.find("channel")
    items = channel.findall("item")
    assert len(items) == 0  # Empty but valid RSS

    # Cleanup
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM feeds WHERE slug = $1", slug)
        await conn.execute("DELETE FROM api_keys WHERE name = $1", "empty-feed-user")


# --------------------------------------------------------------------------
# Test 13: rss_item_content_truncated
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rss_item_content_truncated(client, db_pool):
    """RSS description is truncated to ~500 chars for long content."""
    slug = f"long-content-{uuid4().hex[:8]}"

    # Create a doc with very long content
    long_content = "A" * 1000  # 1000 chars

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO documents (source_type, title, content, tags)
            VALUES ($1, $2, $3, $4)
            """,
            "summary",
            "Long Content Doc",
            long_content,
            ["truncation-test"]
        )

        # Create API key
        import bcrypt
        from app.config import settings
        key_plain = "long-content-key"
        key_hash = bcrypt.hashpw(f"{settings.api_key_salt}{key_plain}".encode(), bcrypt.gensalt()).decode()

        await conn.execute(
            """
            INSERT INTO api_keys (name, key_hash, role, scopes)
            VALUES ($1, $2, $3, $4)
            """,
            "long-content-user",
            key_hash,
            "admin",
            ["feeds"]
        )
        await conn.execute(
            """
            INSERT INTO feeds (name, slug, description, filter_tags, filter_source_types, max_items)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            "Long Content Feed",
            slug,
            "Tests truncation",
            ["truncation-test"],
            [],
            50
        )

    response = await client.get(f"/feeds/{slug}.xml")
    assert response.status_code == 200

    root = ET.fromstring(response.text)
    channel = root.find("channel")
    item = channel.find("item")
    description = item.find("description").text

    # Should be truncated to ~500 chars (with ellipsis)
    assert len(description) <= 510

    # Cleanup
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM feeds WHERE slug = $1", slug)
        await conn.execute("DELETE FROM documents WHERE title = $1", "Long Content Doc")
        await conn.execute("DELETE FROM api_keys WHERE name = $1", "long-content-user")


# --------------------------------------------------------------------------
# Test 14: create_feed_invalid_slug_format
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_feed_invalid_slug_format(client, db_pool):
    """POST with invalid slug format (uppercase, spaces) returns 422."""
    import bcrypt
    from app.config import settings

    key_plain = "slug-test-key"
    key_hash = bcrypt.hashpw(f"{settings.api_key_salt}{key_plain}".encode(), bcrypt.gensalt()).decode()
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO api_keys (name, key_hash, role, scopes)
            VALUES ($1, $2, $3, $4)
            """,
            "slug-test-user",
            key_hash,
            "admin",
            ["feeds"]
        )

    response = await client.post(
        "/api/feeds",
        json={
            "name": "Bad Slug",
            "slug": "Invalid Slug With Spaces",
        },
        headers={"Authorization": f"Bearer {key_plain}"}
    )
    assert response.status_code == 422

    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM api_keys WHERE name = $1", "slug-test-user")


# --------------------------------------------------------------------------
# Test 15: rss_item_has_pubdate_and_link
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rss_item_has_pubdate_and_link(client, db_pool):
    """RSS items include pubDate and link elements."""
    slug = f"pubdate-test-{uuid4().hex[:8]}"

    doc_id = None
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO documents (source_type, title, content, tags)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            "summary",
            "PubDate Test Doc",
            "Content for pubDate test.",
            ["pubdate-test"]
        )
        doc_id = row["id"]

        import bcrypt
        from app.config import settings
        key_plain = "pubdate-key"
        key_hash = bcrypt.hashpw(f"{settings.api_key_salt}{key_plain}".encode(), bcrypt.gensalt()).decode()

        await conn.execute(
            """
            INSERT INTO api_keys (name, key_hash, role, scopes)
            VALUES ($1, $2, $3, $4)
            """,
            "pubdate-user",
            key_hash,
            "admin",
            ["feeds"]
        )
        await conn.execute(
            """
            INSERT INTO feeds (name, slug, description, filter_tags, filter_source_types, max_items)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            "PubDate Feed",
            slug,
            "Tests pubDate",
            ["pubdate-test"],
            [],
            50
        )

    response = await client.get(f"/feeds/{slug}.xml")
    assert response.status_code == 200

    root = ET.fromstring(response.text)
    channel = root.find("channel")
    item = channel.find("item")

    pub_date = item.find("pubDate")
    assert pub_date is not None
    assert len(pub_date.text) > 0

    link = item.find("link")
    assert link is not None
    assert len(link.text) > 0

    # Cleanup
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM feeds WHERE slug = $1", slug)
        await conn.execute("DELETE FROM documents WHERE id = $1", doc_id)
        await conn.execute("DELETE FROM api_keys WHERE name = $1", "pubdate-user")
