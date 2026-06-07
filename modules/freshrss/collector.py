"""Collector for polling FreshRSS via GReader API for unread entries."""
import json
import logging
import re
from datetime import datetime

import httpx

from app.db import get_pool
from app.config import settings

logger = logging.getLogger(__name__)

# GReader API base URL (e.g. http://valhalla:8780/api/greader.php)
_API_PATH = "/greader.php"


class AuthToken:
    """Holds the GReader auth token with lazy refresh on 401."""

    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self._token: str | None = None

    async def get(self, client: httpx.AsyncClient) -> str:
        """Return a valid auth token, re-authenticating if expired."""
        if self._token is not None:
            return self._token
        return await self._authenticate(client)

    async def _authenticate(self, client: httpx.AsyncClient) -> str:
        """Authenticate via ClientLogin and return the Auth token."""
        resp = await client.post(
            f"{self.base_url}{_API_PATH}/accounts/ClientLogin",
            data={
                "Email": self.username,
                "Passwd": self.password,
                "source": "lamadb-freshrss",
                "service": "reader",
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        body = resp.text
        # Response is plain text: Auth=tokenvalue
        match = re.search(r"Auth=(\S+)", body)
        if not match:
            raise ValueError(f"No Auth token in ClientLogin response: {body[:200]}")
        self._token = match.group(1)
        logger.info("FreshRSS: authenticated successfully")
        return self._token

    def invalidate(self):
        """Mark the token as expired so the next get() re-authenticates."""
        self._token = None


def _is_token_invalid(resp_text: str) -> bool:
    return "TokenInvalid" in resp_text or "AuthenticationInvalid" in resp_text


async def _greader_get(
    client: httpx.AsyncClient,
    auth: AuthToken,
    path: str,
    params: dict | None = None,
) -> httpx.Response:
    """
    Perform an authenticated GReader API GET, retrying once on TokenInvalid.
    """
    token = await auth.get(client)
    headers = {"Authorization": f"GoogleLogin auth={token}"}
    url = f"{auth.base_url}{_API_PATH}{path}"

    resp = await client.get(url, params=params, headers=headers, timeout=15.0)

    # Retry once on token expiry
    if _is_token_invalid(resp.text):
        logger.info("FreshRSS: token expired, re-authenticating")
        auth.invalidate()
        token = await auth.get(client)
        headers = {"Authorization": f"GoogleLogin auth={token}"}
        resp = await client.get(url, params=params, headers=headers, timeout=15.0)

    return resp


async def collect() -> dict:
    """
    Poll FreshRSS for unread entries via GReader API, store as documents,
    create ticker events.

    Returns:
        dict with new_count, total_count, feeds_synced, last_sync.
    """
    if not settings.freshrss_url or not settings.freshrss_api_password:
        logger.info("FreshRSS collector: not configured, skipping")
        return {
            "new_count": 0,
            "total_count": 0,
            "feeds_synced": 0,
            "last_sync": "",
            "error": "not configured",
        }

    auth = AuthToken(
        settings.freshrss_url,
        settings.freshrss_username,
        settings.freshrss_api_password,
    )

    try:
        async with httpx.AsyncClient() as client:
            # 1. Fetch the reading list stream
            resp = await _greader_get(
                client,
                auth,
                "/reader/api/0/stream/contents/reading-list",
                params={"n": 50, "output": "json"},
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", [])
    except Exception as e:
        logger.warning(f"FreshRSS collector: error fetching stream: {e}")
        return {
            "new_count": 0,
            "total_count": 0,
            "feeds_synced": 0,
            "last_sync": "",
            "error": str(e),
        }

    pool = get_pool()
    new_count = 0
    total_feeds: set[str] = set()

    async with pool.acquire() as conn:
        for item in items:
            # Extract article URL from alternate links
            article_url = ""
            if item.get("alternate"):
                article_url = item["alternate"][0].get("href", "")

            # Feed info lives in 'origin'
            origin = item.get("origin", {})
            feed_id = origin.get("streamId", "")
            feed_title = origin.get("title", "Unknown")

            if feed_id:
                total_feeds.add(feed_id)

            if not article_url:
                continue

            # Deduplicate by URL
            existing = await conn.fetchval(
                "SELECT id FROM documents WHERE source_type = 'rss_article' AND metadata->>'url' = $1",
                article_url,
            )
            if existing:
                continue

            # Content: GReader API puts content in item['content']['content']
            content_html = ""
            if item.get("content"):
                content_html = item["content"].get("content", "")
            elif item.get("summary"):
                content_html = item["summary"].get("content", "")

            # Title
            title = item.get("title", "Untitled")

            # Published timestamp (unix epoch)
            published_ts = item.get("published", 0)

            # Tags / categories
            categories = item.get("categories", [])
            feed_tag = feed_title.lower().replace(" ", "-")
            tags = ["rss", feed_tag]

            # Insert document
            await conn.execute(
                """
                INSERT INTO documents (source_type, title, content, metadata, tags)
                VALUES ($1, $2, $3, $4, $5)
                """,
                "rss_article",
                title,
                content_html,
                json.dumps({
                    "url": article_url,
                    "feed_name": feed_title,
                    "feed_id": feed_id,
                    "published_ts": published_ts,
                    "item_id": item.get("id", ""),
                }),
                tags,
            )

            # Create ticker event
            await conn.execute(
                """
                INSERT INTO events (source, type, severity, title, ticker, tags)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                "freshrss",
                "new_article",
                "info",
                f"{feed_title}: {title}",
                True,
                ["rss", "feed"],
            )
            new_count += 1

    return {
        "new_count": new_count,
        "total_count": len(items),
        "feeds_synced": len(total_feeds),
        "last_sync": datetime.utcnow().isoformat(),
    }
