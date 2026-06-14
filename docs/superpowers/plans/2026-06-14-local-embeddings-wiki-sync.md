# Phase 14: Local Embeddings + CouchDB Wiki Sync (2026-06-14)

**Goal:** Replace OpenAI embeddings with local sentence-transformers, sync Obsidian wiki from CouchDB LiveSync, and make wiki pages searchable.

## What Changed

### Local Embeddings
- `app/embeddings.py`: Replaced `AsyncOpenAI` with `sentence-transformers/all-MiniLM-L6-v2` (384-dim, CPU)
- `app/core/search.py`: Updated default dims 1536→384, added `source_type` query param to semantic search
- `app/config.py`: Removed `openai_api_key`, added `WIKI_*` settings
- `migrations/020_local_embeddings_384.sql`: Drop HNSW, clear embeddings, alter vector(1536)→vector(384), recreate HNSW
- `requirements.txt`: Removed `openai`, added `sentence-transformers`, `cryptography`

### CouchDB Wiki Collector
- **`modules/wiki/couchdb_crypto.py`** — LiveSync V2 HKDF+AES-GCM decryption
  - `decrypt_hkdf()` / `decrypt_hkdf_ephemeral()` for `%=`/`%$` prefixes
  - `decrypt_meta()` for path fields (`/\\:` prefix)
  - `decrypt_chunk()` for data chunks
- **`modules/wiki/couchdb_client.py`** — CouchDB HTTP client with URL encoding (`+`→`%2B`)
  - `fetch_sync_parameters()`, `fetch_doc()`, `fetch_changes()`
- **`modules/wiki/collector.py`** — Background watcher + poller
  - Only syncs `wiki/` folder pages
  - Tracks CouchDB `last_seq` in `wiki_sync_state` table (migration 021)
  - Fire-and-forget embeddings via `embed_document_async()`
- Wiring in `app/main.py` — poller list + continuous watcher task

### Search Integration
- `source_type` query param on `/api/search/semantic`
- Cache invalidation (`wiki`, `documents` tags) after each sync cycle

## Key Files
- `app/embeddings.py` — sentence-transformers, 384-dim
- `modules/wiki/couchdb_crypto.py` — HKDF AES-GCM decryption
- `modules/wiki/couchdb_client.py` — CouchDB HTTP
- `modules/wiki/collector.py` — changes feed watcher
- `migrations/020_local_embeddings_384.sql` — vector dim change
- `migrations/021_wiki_sync_state.sql` — sync state table

## Pitfalls
| Issue | Fix |
|-------|------|
| LiveSync `deleted` field inside doc (not CouchDB-level) | Check `change.get("deleted")`, not `doc.get("deleted")` |
| `+` in chunk IDs decoded as space by httpx | URL-encode path segments |
| Gapped SQL placeholders (UPDATE used $2..$6 skipping $1) | Use sequential `$1, $2, $3...` placeholders |
| `meta.get("path")` returns `None` for `"path": null` in JSON | `if not page_path` early return catches None |
| Individual doc failure killed batch | Wrap each doc in try/except |

## Verified
- ✅ Embeddings: 384-dim, local CPU, first call ~5-10s load time
- ✅ Migration: HNSW index recreated, vector(384) column
- ✅ Wiki sync: **107/108** pages from `wiki/` folder with content + embeddings
- ✅ Semantic search: `/api/search/semantic?source_type=wiki` returns results
- ✅ No non-wiki/ paths in synced docs
- ✅ **Zero unhandled errors** in last 30s of monitoring
- ✅ Stability: collector handles LiveSync deletions, duplicates, special chars
