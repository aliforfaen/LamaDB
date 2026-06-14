"""CouchDB HTTP client for Obsidian LiveSync database.

Uses httpx with Basic auth and a 30s connect timeout.
All functions are async.
"""
import logging
from urllib.parse import quote

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT = 30.0


def _base_url() -> str:
    """Build the CouchDB base URL, adding http:// if no scheme present."""
    url = settings.wiki_couchdb_url.strip()
    if not url:
        return ""
    if "://" not in url:
        url = f"http://{url}"
    db = settings.wiki_couchdb_db
    return f"{url.rstrip('/')}/{db}"


def _client() -> httpx.AsyncClient:
    """Create a new httpx client with Basic auth for the wiki CouchDB."""
    auth = httpx.BasicAuth(
        settings.wiki_couchdb_user,
        settings.wiki_couchdb_password,
    )
    return httpx.AsyncClient(
        auth=auth,
        timeout=httpx.Timeout(connect=CONNECT_TIMEOUT, read=120.0, write=30.0, pool=10.0),
    )


async def _couch_request(method: str, path: str, **kwargs) -> httpx.Response:
    """Send a request to the wiki CouchDB and raise on HTTP errors.

    URL-encodes path segments so that special characters in doc IDs
    (e.g. + in chunk IDs like h:+abc123) are preserved.
    """
    base = _base_url()
    encoded = "/".join(quote(seg, safe="") for seg in path.lstrip("/").split("/"))
    url = f"{base}/{encoded}" if encoded else base
    async with _client() as client:
        resp = await client.request(method, url, **kwargs)
        resp.raise_for_status()
        return resp


async def fetch_sync_parameters() -> dict:
    """Fetch the Livesync sync parameters document.

    Returns the JSON body of _local/obsidian_livesync_sync_parameters.
    Contains keys: pbkdf2salt, version, etc.
    """
    resp = await _couch_request("GET", "_local/obsidian_livesync_sync_parameters")
    return resp.json()


async def fetch_doc(doc_id: str) -> dict:
    """Fetch a single document by CouchDB _id."""
    resp = await _couch_request("GET", doc_id)
    return resp.json()


async def fetch_changes(since: str = "0", limit: int = 1000, timeout_ms: int = 60000) -> dict:
    """Fetch CouchDB _changes feed with longpoll.

    Args:
        since: CouchDB sequence token to resume from.
        limit: max changes per batch.
        timeout_ms: longpoll wait time in ms.
    """
    params = {
        "feed": "longpoll",
        "since": since,
        "limit": limit,
        "timeout": timeout_ms,
        "include_docs": "true",
    }
    resp = await _couch_request("GET", "_changes", params=params)
    return resp.json()
