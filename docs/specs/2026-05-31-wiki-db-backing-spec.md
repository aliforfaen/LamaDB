# LamaDB — Wiki DB-Backing Spec

> **For MiMo v2.5 / DeepSeek v4 Flash via OpenCode Go:** Self-contained implementation spec. Read AGENTS.md for module patterns and Docker workflow. All paths relative to `/home/messhias/LamaFiles/projects/lamadb/`.

**Goal:** Migrate the LamaDB wiki from filesystem-reader to DB-backed storage using the existing `documents` table, with CRUD API, wikilink resolution, semantic search, and a dashboard editor.

**Repo:** `/home/messhias/LamaFiles/projects/lamadb/`
**Tech:** Python 3.12, FastAPI, asyncpg, pgvector, Docker Compose

---

## Architecture

The `documents` table already has everything needed:
```sql
documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_type TEXT,      -- 'wiki_page' for wiki pages, 'scratchpad' for notes
  title TEXT,            -- page title (filename without .md)
  content TEXT,          -- markdown body
  metadata JSONB,        -- {path, source_url, frontmatter, ...}
  tags TEXT[],           -- ambient categorization
  embedding vector(1536), -- pgvector for semantic search
  created_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ
)
```

**source_type convention:** All wiki pages use `source_type='wiki_page'`. Filesystem path stored in `metadata.path` (e.g., `"entities/uptime-kuma-topology.md"`).

**Files to modify:**
- `modules/wiki/routes.py` — add DB-backed CRUD endpoints
- `modules/wiki/models.py` — add page models
- `modules/wiki/wiki_reader.py` — add DB read functions (alongside filesystem fallback)
- `scripts/migrate_wiki.py` — new migration script
- `static/index.html` — dashboard wiki editor UI
- `modules/wiki/__init__.py` — no changes needed (ENABLED already True)

**New files:**
- `modules/wiki/wiki_db.py` — DB-backed wiki page CRUD
- `scripts/migrate_wiki.py` — filesystem → DB import

---

## Phase 1: DB-Backed Wiki CRUD (wiki_db.py)

### 1a. Create `modules/wiki/wiki_db.py`

Core functions to read/write wiki pages from the documents table:

```python
"""DB-backed wiki page storage — uses the documents table."""
import json
from typing import Optional
from uuid import uuid4

from app.db import get_pool


async def create_page(title: str, content: str, path: str, tags: list[str] = None) -> dict:
    """Create a wiki page in the documents table."""
    pool = get_pool()
    page_id = str(uuid4())
    metadata = {"path": path, "type": "wiki_page"}
    
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO documents (id, source_type, title, content, metadata, tags)
               VALUES ($1, 'wiki_page', $2, $3, $4, $5)
               RETURNING id, title, content, metadata, tags, created_at, updated_at""",
            page_id, title, content, json.dumps(metadata), tags or [],
        )
    return _doc_to_page(dict(row))


async def get_page(page_id: str) -> Optional[dict]:
    """Get a wiki page by ID."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM documents WHERE id = $1 AND source_type = 'wiki_page'",
            page_id,
        )
    if not row:
        return None
    return _doc_to_page(dict(row))


async def get_page_by_path(path: str) -> Optional[dict]:
    """Get a wiki page by filesystem path (stored in metadata)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT * FROM documents
               WHERE source_type = 'wiki_page'
                 AND metadata->>'path' = $1
               LIMIT 1""",
            path,
        )
    if not row:
        return None
    return _doc_to_page(dict(row))


async def update_page(page_id: str, title: str = None, content: str = None, tags: list[str] = None) -> Optional[dict]:
    """Update a wiki page. Only provided fields are changed."""
    pool = get_pool()
    updates = []
    params = []
    idx = 1
    
    if title is not None:
        updates.append(f"title = ${idx}")
        params.append(title)
        idx += 1
    if content is not None:
        updates.append(f"content = ${idx}")
        params.append(content)
        idx += 1
    if tags is not None:
        updates.append(f"tags = ${idx}")
        params.append(tags)
        idx += 1
    
    if not updates:
        return await get_page(page_id)
    
    updates.append("updated_at = now()")
    params.append(page_id)
    
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""UPDATE documents
                SET {', '.join(updates)}
                WHERE id = ${idx} AND source_type = 'wiki_page'
                RETURNING *""",
            *params,
        )
    if not row:
        return None
    return _doc_to_page(dict(row))


async def delete_page(page_id: str) -> bool:
    """Delete a wiki page and its document links."""
    pool = get_pool()
    async with pool.acquire() as conn:
        # Delete outgoing links
        await conn.execute(
            "DELETE FROM document_links WHERE source_id = $1", page_id
        )
        # Delete the page
        result = await conn.execute(
            "DELETE FROM documents WHERE id = $1 AND source_type = 'wiki_page'",
            page_id,
        )
    return result != "DELETE 0"


async def list_pages(sort: str = "updated_at", limit: int = 100, offset: int = 0) -> list[dict]:
    """List wiki pages with pagination."""
    valid_sort = {"updated_at", "created_at", "title"}
    if sort not in valid_sort:
        sort = "updated_at"
    
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT id, title, metadata, tags, created_at, updated_at
               FROM documents
               WHERE source_type = 'wiki_page'
               ORDER BY {sort} DESC
               LIMIT $1 OFFSET $2""",
            limit, offset,
        )
    return [_doc_to_page(dict(r)) for r in rows]


async def search_pages(query: str, limit: int = 20) -> list[dict]:
    """Full-text search across wiki page titles and content using pg_trgm."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, title, content, metadata, tags, created_at, updated_at,
                      similarity(title, $1) AS sim
               FROM documents
               WHERE source_type = 'wiki_page'
                 AND (title % $1 OR content % $1)
               ORDER BY sim DESC
               LIMIT $2""",
            query, limit,
        )
    return [_doc_to_page(dict(r)) for r in rows]


async def resolve_wikilink(title: str) -> Optional[str]:
    """Resolve a [[page-title]] wikilink to a document ID. Case-insensitive."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id FROM documents
               WHERE source_type = 'wiki_page'
                 AND LOWER(title) = LOWER($1)
               LIMIT 1""",
            title,
        )
    return str(row["id"]) if row else None


async def sync_wikilinks(page_id: str, content: str):
    """Parse [[wikilinks]] from markdown content and create document_links."""
    import re
    pool = get_pool()
    
    # Find all [[page-name]] patterns
    wikilinks = re.findall(r'\[\[([^\]]+)\]\]', content)
    
    async with pool.acquire() as conn:
        # Remove old wikilinks for this page
        await conn.execute(
            "DELETE FROM document_links WHERE source_id = $1 AND link_type = 'wiki_link'",
            page_id,
        )
        
        # Resolve and create new links
        for link_title in wikilinks:
            target_id = await resolve_wikilink(link_title)
            if target_id and target_id != page_id:
                await conn.execute(
                    """INSERT INTO document_links (source_id, target_id, link_type, context)
                       VALUES ($1, $2, 'wiki_link', $3)
                       ON CONFLICT DO NOTHING""",
                    page_id, target_id, link_title,
                )


def _doc_to_page(d: dict) -> dict:
    """Convert a documents row dict to a wiki page dict."""
    meta = d.get("metadata")
    if isinstance(meta, str):
        meta = json.loads(meta)
    
    return {
        "id": str(d["id"]) if d.get("id") else None,
        "title": d.get("title", ""),
        "content": d.get("content", ""),
        "path": meta.get("path", "") if meta else "",
        "tags": d.get("tags", []),
        "created_at": d.get("created_at").isoformat() if d.get("created_at") else None,
        "updated_at": d.get("updated_at").isoformat() if d.get("updated_at") else None,
    }
```

---

## Phase 2: API Routes (routes.py additions)

Add these endpoints to `modules/wiki/routes.py` (alongside existing scratchpad routes):

### Page CRUD

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/wiki/pages` | admin/agent | Create a wiki page |
| GET | `/api/wiki/pages` | any | List wiki pages (?sort=updated_at&limit=50) |
| GET | `/api/wiki/pages/{page_id}` | any | Get page by ID |
| GET | `/api/wiki/pages/by-path` | any | Get page by path (?path=entities/foo.md) |
| PATCH | `/api/wiki/pages/{page_id}` | admin/agent | Update page (title, content, tags) |
| DELETE | `/api/wiki/pages/{page_id}` | admin | Delete page |
| GET | `/api/wiki/pages/search` | any | Search pages (?q=query) |

### Route implementation pattern (for POST /pages):

```python
from .wiki_db import create_page, get_page, update_page, delete_page, list_pages, search_pages, sync_wikilinks

@router.post("/pages", status_code=status.HTTP_201_CREATED)
async def create_wiki_page(
    page: WikiPageCreate,
    user: Annotated[AuthUser, Depends(get_current_user)],
):
    """Create a new wiki page."""
    if user.role not in ("admin", "agent"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    result = await create_page(
        title=page.title,
        content=page.content,
        path=page.path,
        tags=page.tags or [],
    )
    
    # Sync wikilinks
    await sync_wikilinks(result["id"], page.content)
    
    # Log event
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO events (source, type, severity, title, body, ticker, tags)
               VALUES ('wiki', 'page_created', 'info', $1, $2, false, $3)""",
            f"Page created: {page.title}", f"Path: {page.path}", ["wiki"],
        )
    
    return result
```

### Model additions (models.py):

```python
class WikiPageCreate(BaseModel):
    title: str
    content: str = ""
    path: str  # e.g., "entities/my-page.md"
    tags: list[str] = []

class WikiPageUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[list[str]] = None
```

### Filesystem fallback

Keep the existing filesystem reader endpoints (`/pages`, `/page/{path}`, `/search`) but add a `?source=db` parameter. Default to DB, fallback to filesystem if page not found in DB:

```python
@router.get("/page/{path:path}")
async def read_wiki_page(path: str, source: str = "db"):
    """Read a wiki page. source=db (default) or source=fs (filesystem)."""
    if source == "db":
        page = await get_page_by_path(path)
        if page:
            return page
        # Fall through to filesystem if not found
    # Existing filesystem reader...
```

---

## Phase 3: Migration Script (scripts/migrate_wiki.py)

One-time import of `~/Basecamp/wiki/` into the documents table. Runs inside the Docker container.

```python
#!/usr/bin/env python3
"""Migrate filesystem wiki into LamaDB documents table.
Usage: docker exec lamadb_api python3 scripts/migrate_wiki.py
"""

import json
import os
import re
from pathlib import Path

WIKI_ROOT = Path(os.environ.get("WIKI_PATH", "/wiki"))
SKIP_DIRS = {"_archive", "raw", ".git", ".obsidian", "_meta", "assets"}
SKIP_FILES = {"SCHEMA.md", "index.md", "log.md"}  # Meta files, not content pages


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Extract YAML frontmatter from markdown. Returns (frontmatter_dict, body)."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            # Simple key:value parser (no PyYAML dependency)
            fm = {}
            for line in parts[1].strip().split("\n"):
                line = line.strip()
                if ":" in line:
                    key, _, val = line.partition(":")
                    fm[key.strip()] = val.strip().strip('"').strip("'")
            return fm, parts[2].strip()
    return {}, text


def main():
    from app.db import get_pool
    import asyncio
    
    async def migrate():
        pool = get_pool()
        count = 0
        skipped = 0
        
        async with pool.acquire() as conn:
            for md_file in WIKI_ROOT.rglob("*.md"):
                rel_path = str(md_file.relative_to(WIKI_ROOT))
                
                # Skip dirs
                parts = Path(rel_path).parts
                if parts and parts[0] in SKIP_DIRS:
                    continue
                if md_file.name in SKIP_FILES:
                    continue
                
                # Check if already imported
                existing = await conn.fetchval(
                    """SELECT id FROM documents
                       WHERE source_type = 'wiki_page'
                         AND metadata->>'path' = $1""",
                    rel_path,
                )
                if existing:
                    skipped += 1
                    continue
                
                # Read and parse
                text = md_file.read_text(encoding="utf-8")
                fm, body = parse_frontmatter(text)
                
                title = fm.get("title", md_file.stem)
                tags = []
                if "tags" in fm:
                    raw_tags = fm["tags"]
                    if isinstance(raw_tags, str):
                        # YAML list: "[tag1, tag2]" or "tag1, tag2"
                        tags = [t.strip().strip("[]'\"") for t in raw_tags.split(",") if t.strip()]
                
                # Store metadata
                metadata = {
                    "path": rel_path,
                    "type": "wiki_page",
                    "frontmatter": fm,
                    "migrated_from": "filesystem",
                }
                
                # Insert
                import uuid
                await conn.execute(
                    """INSERT INTO documents (id, source_type, title, content, metadata, tags)
                       VALUES ($1, 'wiki_page', $2, $3, $4, $5)""",
                    str(uuid.uuid4()), title, body, json.dumps(metadata), tags,
                )
                count += 1
                
                if count % 20 == 0:
                    print(f"  Migrated {count} pages...")
        
        print(f"\nDone. {count} pages imported, {skipped} already existed.")
        return count
    
    return asyncio.run(migrate())


if __name__ == "__main__":
    main()
```

**Run after deployment:**
```bash
docker exec lamadb_api python3 scripts/migrate_wiki.py
```

---

## Phase 4: Dashboard Wiki Editor UI

### Replace the current filesystem reader with DB-backed editor

The current wiki tab has: file browser, page viewer, scratchpad. Replace the file browser with a DB page list + a page editor.

### HTML structure (static/index.html)

In the `#page-wiki` section, add sub-tabs:

```html
<div class="wiki-tabs">
  <button class="sub-tab-btn active" onclick="switchWikiTab('browse')">Browse</button>
  <button class="sub-tab-btn" onclick="switchWikiTab('edit')">Edit</button>
  <button class="sub-tab-btn" onclick="switchWikiTab('scratchpad')">Scratchpad</button>
</div>

<!-- Browse tab: page list + search -->
<div id="wiki-browse-tab">
  <div class="filter-bar">
    <input type="text" id="wiki-search-input" placeholder="Search pages..." 
           onkeyup="if(event.key==='Enter')window.searchWikiPages()"
           style="width:250px;background:var(--surface-2);color:var(--fg);border:1px solid var(--border);border-radius:var(--radius-sm);padding:4px 10px;font-size:13px;" />
    <button class="btn btn-sm btn-primary" onclick="window.searchWikiPages()">Search</button>
    <span style="flex:1;"></span>
    <button class="btn btn-sm btn-primary" onclick="switchWikiTab('edit');window.newWikiPage()">+ New Page</button>
  </div>
  <div id="wiki-page-list"><p class="loading">Loading…</p></div>
</div>

<!-- Edit tab: markdown editor -->
<div id="wiki-edit-tab" style="display:none;">
  <div class="filter-bar">
    <input type="text" id="wiki-edit-title" placeholder="Page title" style="..." />
    <input type="text" id="wiki-edit-path" placeholder="path/to/page.md" style="..." />
    <span style="flex:1;"></span>
    <button class="btn btn-sm btn-primary" onclick="window.saveWikiPage()">Save</button>
    <button class="btn btn-sm btn-secondary" onclick="switchWikiTab('browse')">Cancel</button>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;height:calc(100vh - 250px);">
    <textarea id="wiki-edit-content" placeholder="Markdown content..." 
              style="width:100%;height:100%;background:var(--surface-2);color:var(--fg);border:1px solid var(--border);border-radius:var(--radius-sm);padding:12px;font-family:var(--font-mono);font-size:13px;resize:none;"></textarea>
    <div id="wiki-edit-preview" style="overflow-y:auto;padding:12px;background:var(--surface-2);border:1px solid var(--border);border-radius:var(--radius-sm);font-size:13px;line-height:1.6;">
      <p class="empty">Preview will appear here…</p>
    </div>
  </div>
</div>
```

### JS functions

```javascript
var _wikiCurrentPageId = null;
var _wikiTab = 'browse';

window.switchWikiTab = function(tab) {
  _wikiTab = tab;
  document.getElementById('wiki-browse-tab').style.display = tab === 'browse' ? '' : 'none';
  document.getElementById('wiki-edit-tab').style.display = tab === 'edit' ? '' : 'none';
  // ... handle scratchpad tab visibility
  
  if (tab === 'browse') loadWikiPages();
};

window.loadWikiPages = async function() {
  var el = document.getElementById('wiki-page-list');
  el.innerHTML = '<p class="loading">Loading…</p>';
  try {
    var pages = await api('/api/wiki/pages?limit=100');
    renderWikiPageList(pages);
  } catch(e) {
    el.innerHTML = '<p class="error">Failed to load pages</p>';
  }
};

function renderWikiPageList(pages) {
  var el = document.getElementById('wiki-page-list');
  if (!pages || pages.length === 0) {
    el.innerHTML = '<p class="empty">No pages yet. Create one!</p>';
    return;
  }
  var html = '<div class="table-wrap"><table><thead><tr><th>Title</th><th>Path</th><th>Updated</th><th></th></tr></thead><tbody>';
  pages.forEach(function(p) {
    var updated = p.updated_at ? new Date(p.updated_at).toLocaleDateString() : '';
    html += '<tr class="wiki-row" style="cursor:pointer;" onclick="window.openWikiPage(\'' + p.id + '\')">' +
      '<td style="font-weight:500;">' + escHtml(p.title) + '</td>' +
      '<td style="font-size:12px;color:var(--fg-2);">' + escHtml(p.path) + '</td>' +
      '<td class="mono" style="font-size:11px;">' + escHtml(updated) + '</td>' +
      '<td>' +
        '<button class="btn btn-sm btn-secondary" onclick="event.stopPropagation();window.editWikiPage(\'' + p.id + '\')">Edit</button>' +
        '<button class="btn btn-sm btn-danger" onclick="event.stopPropagation();window.deleteWikiPage(\'' + p.id + '\')">×</button>' +
      '</td>' +
      '</tr>';
  });
  html += '</tbody></table></div>';
  el.innerHTML = html;
}

window.openWikiPage = async function(pageId) {
  try {
    var page = await api('/api/wiki/pages/' + pageId);
    var el = document.getElementById('wiki-page-list');
    // Render page content with markdown (use simple regex or just show content)
    el.innerHTML = '<div class="col-card">' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">' +
      '<h3 style="margin:0;">' + escHtml(page.title) + '</h3>' +
      '<div><button class="btn btn-sm btn-secondary" onclick="window.editWikiPage(\'' + page.id + '\')">Edit</button>' +
      '<button class="btn btn-sm btn-secondary" onclick="window.loadWikiPages()">← Back</button></div>' +
      '</div>' +
      '<div style="line-height:1.7;font-size:13px;">' + simpleMarkdown(page.content) + '</div>' +
      '</div>';
  } catch(e) {
    alert('Failed to load page');
  }
};

window.editWikiPage = async function(pageId) {
  _wikiCurrentPageId = pageId;
  switchWikiTab('edit');
  try {
    var page = await api('/api/wiki/pages/' + pageId);
    document.getElementById('wiki-edit-title').value = page.title;
    document.getElementById('wiki-edit-path').value = page.path;
    document.getElementById('wiki-edit-content').value = page.content;
  } catch(e) {}
};

window.newWikiPage = function() {
  _wikiCurrentPageId = null;
  document.getElementById('wiki-edit-title').value = '';
  document.getElementById('wiki-edit-path').value = '';
  document.getElementById('wiki-edit-content').value = '';
};

window.saveWikiPage = async function() {
  var title = document.getElementById('wiki-edit-title').value.trim();
  var path = document.getElementById('wiki-edit-path').value.trim();
  var content = document.getElementById('wiki-edit-content').value;
  if (!title || !path) { alert('Title and path are required'); return; }
  
  try {
    if (_wikiCurrentPageId) {
      await api('/api/wiki/pages/' + _wikiCurrentPageId, {
        method: 'PATCH',
        body: JSON.stringify({ title: title, content: content })
      });
    } else {
      await api('/api/wiki/pages', {
        method: 'POST',
        body: JSON.stringify({ title: title, content: content, path: path, tags: [] })
      });
    }
    switchWikiTab('browse');
    loadWikiPages();
  } catch(e) {
    alert('Failed to save: ' + (e.message || 'Unknown error'));
  }
};

window.deleteWikiPage = async function(pageId) {
  if (!confirm('Delete this page?')) return;
  try {
    await api('/api/wiki/pages/' + pageId, { method: 'DELETE' });
    loadWikiPages();
  } catch(e) { alert('Failed to delete'); }
};

window.searchWikiPages = async function() {
  var q = document.getElementById('wiki-search-input').value.trim();
  if (!q) { loadWikiPages(); return; }
  var el = document.getElementById('wiki-page-list');
  el.innerHTML = '<p class="loading">Searching…</p>';
  try {
    var results = await api('/api/wiki/pages/search?q=' + encodeURIComponent(q));
    renderWikiPageList(results);
  } catch(e) {
    el.innerHTML = '<p class="error">Search failed</p>';
  }
};

// Simple markdown→HTML for preview (no heavy library)
function simpleMarkdown(md) {
  if (!md) return '';
  return md
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/^### (.+)$/gm, '<h4>$1</h4>')
    .replace(/^## (.+)$/gm, '<h3>$1</h3>')
    .replace(/^# (.+)$/gm, '<h2>$1</h2>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .replace(/\[\[([^\]]+)\]\]/g, '<a href="#" class="wikilink">$1</a>')
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br>');
}

// Export to window
window.switchWikiTab = switchWikiTab;
window.loadWikiPages = loadWikiPages;
window.openWikiPage = openWikiPage;
window.editWikiPage = editWikiPage;
window.newWikiPage = newWikiPage;
window.saveWikiPage = saveWikiPage;
window.deleteWikiPage = deleteWikiPage;
window.searchWikiPages = searchWikiPages;
```

---

## Phase 5: Semantic Search (pgvector)

Add vector search endpoint. Requires embedding generation — for MVP, use a simple text embedding or skip pgvector and use pg_trgm similarity (already implemented in `search_pages`).

Future: Add `POST /api/wiki/pages/{id}/embed` that generates an embedding for a page. For now, the pg_trgm `similarity()` search in Phase 1 is sufficient.

---

## Tests (tests/test_wiki_db.py)

```python
# Test cases:
# 1. test_create_page — POST /api/wiki/pages → 201
# 2. test_get_page — GET /api/wiki/pages/{id} → 200 with page data
# 3. test_get_page_by_path — GET /api/wiki/pages/by-path?path=X → 200
# 4. test_update_page — PATCH /api/wiki/pages/{id} → updated page
# 5. test_delete_page — DELETE /api/wiki/pages/{id} → 200
# 6. test_list_pages — GET /api/wiki/pages → array
# 7. test_search_pages — GET /api/wiki/pages/search?q=X → results
# 8. test_wikilink_sync — create page with [[links]], verify document_links created
# 9. test_wikilink_resolve — resolve_wikilink finds existing page
# 10. test_create_duplicate_path — conflict on same path
# 11. test_unauthorized_create — read role → 403
# 12. test_migration_script — import .md files into documents table
```

Use the same test fixture pattern as `test_ntfy_events.py` (`make_app()` + lifespan + seeded API key).

---

## Acceptance Criteria

- [ ] DB-backed CRUD: create, read, update, delete wiki pages via documents table
- [ ] Path-based lookup: `/api/wiki/pages/by-path?path=entities/foo.md`
- [ ] Full-text search via pg_trgm similarity
- [ ] Wikilink resolution: `[[page-name]]` → document_links table entries
- [ ] Filesystem fallback: pages not in DB still readable from /wiki mount
- [ ] Migration script idempotent (skip already-imported pages)
- [ ] Dashboard wiki editor: browse list, create/edit/delete pages, markdown preview
- [ ] Scratchpad tab preserved (no changes needed)
- [ ] 12+ tests passing
- [ ] Docker build + force-recreate picks up changes

---

## Known Pitfalls

| # | Pitfall | Prevention |
|---|---------|------------|
| 1 | asyncpg returns JSONB metadata as string | `isinstance(meta, str)` check before `json.loads()` |
| 2 | UUID columns return UUID objects, not strings | `str(d["id"])` in `_doc_to_page()` |
| 3 | Wikilink regex matches inside code blocks | Simple MVP: accept false positives. Fix in v2 with proper markdown parser. |
| 4 | Migration script creates duplicate pages | Check `metadata->>'path'` before insert |
| 5 | Frontmatter parser fails on complex YAML | Simple key:value only. No PyYAML dependency. |
| 6 | Dashboard JS: onclick handlers not on window | Export ALL new functions to window |
| 7 | Static files stale after build | Always `build` + `up -d --force-recreate` |
| 8 | pg_trgm similarity requires extension | Already installed in 001_initial.sql |
| 9 | Delete page doesn't clean up inbound links | MVP: documents with broken wikilinks render as plain text. Fix in v2. |
| 10 | Path uniqueness not enforced at DB level | Check in application code before create |
