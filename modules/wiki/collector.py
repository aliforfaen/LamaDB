"""Wiki collector: syncs Obsidian LiveSync CouchDB into LamaDB documents table.

Only syncs pages under the wiki/ folder in the Obsidian vault.
Incremental sync via CouchDB _changes feed (longpoll).
"""
import asyncio
import base64
import json
import logging
from pathlib import Path as _Path

from app.cache import cache_manager
from app.config import settings
from app.db import get_pool

from .couchdb_client import fetch_changes, fetch_doc, fetch_sync_parameters
from .couchdb_crypto import decrypt_chunk, decrypt_meta

logger = logging.getLogger(__name__)


def _is_configured() -> bool:
    return bool(
        settings.wiki_couchdb_url
        and settings.wiki_couchdb_db
        and settings.wiki_couchdb_user
        and settings.wiki_couchdb_password
        and settings.wiki_couchdb_encryption_key
    )


async def _get_pbkdf2_salt() -> bytes:
    sync = await fetch_sync_parameters()
    return base64.b64decode(sync["pbkdf2salt"])


async def _reconstruct_content(children, passphrase, pbkdf2_salt):
    chunks = []
    for child_id in children:
        try:
            doc = await fetch_doc(child_id)
        except Exception:
            logger.warning("Failed to fetch chunk %s", child_id, exc_info=True)
            continue
        data_field = doc.get("data", "")
        try:
            raw = decrypt_chunk(data_field, passphrase, pbkdf2_salt)
            chunks.append(raw.decode("utf-8", errors="replace"))
        except Exception:
            logger.warning("Failed to decrypt chunk %s", child_id, exc_info=True)
            continue
    return "".join(chunks)


def _extract_title(path, content):
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            return stripped[2:].strip()
    return _Path(path).stem


async def _upsert_wiki_page(doc, passphrase, pbkdf2_salt):
    # CouchDB-level deletions are handled by collect().
    # LiveSync marks vault-file deletions with deleted:true inside doc content.
    if doc.get("deleted"):
        await _delete_by_couchdb_id(doc.get("_id", ""))
        return False

    doc_type = doc.get("type", "plain")
    if doc_type not in ("plain", "newnote"):
        return False

    path_field = doc.get("path", "")
    if not path_field:
        return False

    try:
        meta = decrypt_meta(path_field, passphrase, pbkdf2_salt)
    except Exception:
        logger.warning("Failed to decrypt path for doc %s", doc.get("_id"), exc_info=True)
        return False

    page_path = meta.get("path", "")
    if not page_path or not page_path.lower().endswith(".md"):
        return False

    stem = _Path(page_path).name
    if stem.startswith(".") and stem != ".md":
        return False

    # Only sync pages under wiki/ folder
    if not page_path.startswith("wiki/") and page_path != "wiki":
        return False

    children = meta.get("children", [])
    if children:
        try:
            content = await _reconstruct_content(children, passphrase, pbkdf2_salt)
        except Exception:
            logger.warning("Failed to reconstruct content for %s", page_path, exc_info=True)
            content = ""
    else:
        content = ""

    title = _extract_title(page_path, content) or page_path
    title = str(title or page_path)
    content = str(content or "")
    page_path = str(page_path or "")

    meta["_id"] = doc["_id"]
    meta_json = json.dumps(meta)

    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM documents WHERE source_type = 'wiki' AND metadata->>'path' = $1",
            page_path,
        )
        if existing:
            doc_id = existing["id"]
            await conn.execute(
                """UPDATE documents
                   SET title = $1, content = $2, metadata = $3,
                       tags = $4, updated_at = now()
                   WHERE id = $5""",
                title, content, meta_json, ["wiki"], doc_id,
            )
        else:
            row = await conn.fetchrow(
                """INSERT INTO documents (source_type, title, content, metadata, tags)
                   VALUES ('wiki', $1, $2, $3, $4)
                   RETURNING id""",
                title, content, meta_json, ["wiki"],
            )
            doc_id = row["id"]

    from app.embeddings import embed_document_async
    try:
        asyncio.create_task(embed_document_async(str(doc_id), title, content))
    except Exception:
        pass

    return True


async def _delete_wiki_page(path):
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM documents WHERE source_type = 'wiki' AND metadata->>'path' = $1",
            path,
        )


async def _delete_by_couchdb_id(couchdb_id):
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM documents WHERE source_type = 'wiki' AND metadata->>'_id' = $1",
            couchdb_id,
        )


async def _get_last_seq(pool):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT last_seq FROM wiki_sync_state WHERE id = 1")
        return row["last_seq"] if row else "0"


async def _set_last_seq(pool, seq):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE wiki_sync_state SET last_seq = $1, updated_at = now() WHERE id = 1",
            seq,
        )


async def collect():
    if not _is_configured():
        return {"status": "not_configured"}

    try:
        pbkdf2_salt = await _get_pbkdf2_salt()
    except Exception as e:
        logger.warning("Wiki collector: failed to fetch pbkdf2 salt: %s", e)
        return {"status": "error", "error": f"pbkdf2_salt: {e}"}

    pool = get_pool()
    last_seq = await _get_last_seq(pool)

    processed = 0
    deleted = 0
    current_seq = last_seq

    try:
        while True:
            changes = await fetch_changes(since=current_seq, limit=1000)
            results = changes.get("results", [])
            if not results:
                break

            for change in results:
                doc = change.get("doc", {})
                doc_id = doc.get("_id", "")
                doc_seq = change.get("seq", current_seq)

                if not doc_id.startswith("f:"):
                    if doc_seq:
                        current_seq = doc_seq
                    continue

                try:
                    if change.get("deleted"):
                        await _delete_by_couchdb_id(doc_id)
                        deleted += 1
                    else:
                        changed = await _upsert_wiki_page(
                            doc, settings.wiki_couchdb_encryption_key, pbkdf2_salt
                        )
                        if changed:
                            processed += 1
                except Exception:
                    logger.warning("Wiki collector: failed to process doc %s", doc_id, exc_info=True)

                if doc_seq:
                    current_seq = doc_seq

            await _set_last_seq(pool, current_seq)
            logger.info("Wiki collector: processed=%d deleted=%d", processed, deleted)

            if len(results) < 1000:
                break
    except Exception as e:
        logger.warning("Wiki collector: changes feed error: %s", e, exc_info=True)
        return {"status": "error", "error": str(e), "processed": processed, "deleted": deleted, "last_seq": current_seq}

    cache_manager.invalidate("wiki")
    cache_manager.invalidate("documents")

    return {"status": "ok", "processed": processed, "deleted": deleted, "last_seq": current_seq}


async def watch_wiki_changes():
    errors = 0
    while True:
        try:
            result = await collect()
            errors = 0
            logger.info("Wiki watcher: %s (processed=%d deleted=%d)",
                        result.get("status", "unknown"),
                        result.get("processed", 0),
                        result.get("deleted", 0))
        except Exception as e:
            errors += 1
            backoff = min(300, 10 * (2 ** min(errors, 5)))
            logger.warning("Wiki watcher error (#%d, backoff=%ds): %s", errors, backoff, e)
            await asyncio.sleep(backoff)
            continue
        await asyncio.sleep(5)
