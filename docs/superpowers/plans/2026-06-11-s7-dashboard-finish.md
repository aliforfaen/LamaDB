# S7 Dashboard Finish — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close out the remaining ~24% of S7 Dashboard Admin Expansion — SSE client gaps, document management polish, module health improvements, sidebar alert badges, and per-module force-poll.

**Architecture:** Six independent frontend tasks and one backend migration. Tasks 1, 3, 5, 6, 7 are pure frontend in separate files — they can all dispatch in parallel. Task 2 is a backend SQL migration (also independent). Task 4 mixes backend (one new route) + frontend (force-poll buttons in module cards). Task 4 frontend depends on Task 4 backend.

**Tech Stack:** JavaScript (vanilla), PostgreSQL (NOTIFY triggers), Python/FastAPI (backend route)

---

### Task 1: SSE document_created + monitor_status frontend wiring

**Files:**
- Modify: `static/js/app.js:89-95`

**Context:** Backend NOTIFY triggers exist on `document_created` and `monitor_status` channels at `migrations/011_dashboard_notify_triggers.sql`. The `pg_listener` in `app/main.py:190` already subscribes to both channels. But the frontend SSE client in `app.js:77-95` only handles `event_created`, `task_update`, and `kanban_task_updated` — `document_created` and `monitor_status` events are silently dropped. This task wires them to show toast notifications.

- [ ] **Step 1: Add document_created SSE listener in app.js**

After the existing `task_update` listener block (app.js:79-88), insert:

```javascript
_sseSource.addEventListener('document_created', function(e) {
  try {
    var data = JSON.parse(e.data);
    if (window.showToast) {
      window.showToast('New document: ' + (data.title || 'Untitled'), 'info');
    }
    // Refresh documents page if currently viewing it
    if (typeof window._currentPage !== 'undefined' && window._currentPage === 'documents' && window.loadDocuments) {
      window.loadDocuments();
    }
  } catch(ex) {}
});
```

- [ ] **Step 2: Add monitor_status SSE listener in app.js**

After the document_created block, insert:

```javascript
_sseSource.addEventListener('monitor_status', function(e) {
  try {
    var data = JSON.parse(e.data);
    var statusText = data.status === 1 ? 'UP' : data.status === 0 ? 'DOWN' : 'PENDING';
    if (window.showToast && data.status === 0) {
      window.showToast(data.monitor_name + ' is DOWN', 'error');
    }
    // Refresh uptime page if currently viewing it
    if (typeof window._currentPage !== 'undefined' && window._currentPage === 'uptime' && window.loadUptimePage) {
      window.loadUptimePage();
    }
    // Update monitoring sidebar badge
    if (typeof window.updateSidebarBadges === 'function') {
      window.updateSidebarBadges();
    }
  } catch(ex) {}
});
```

- [ ] **Step 3: Ensure _currentPage is set during page navigation**

Read `static/js/app.js` and find the `navigateTo` function (search for `navigateTo`). After the line that sets the active nav item, add:

```javascript
window._currentPage = page;
```

(If `_currentPage` is already being set, skip this step.)

- [ ] **Step 4: Commit**

```bash
git add static/js/app.js
git commit -m "feat(sse): wire document_created and monitor_status SSE toasts + page refresh"
```

---

### Task 2: Documents UPDATE/DELETE NOTIFY triggers

**Files:**
- Modify: `migrations/011_dashboard_notify_triggers.sql`

**Context:** Current migration only has INSERT triggers on `documents` and `monitor_status`. The S7 spec (line 259) calls for "INSERT, UPDATE, DELETE". This task adds UPDATE and DELETE triggers on `documents` to notify the dashboard of changes.

- [ ] **Step 1: Add document UPDATE trigger**

Append to `migrations/011_dashboard_notify_triggers.sql`:

```sql
-- Trigger: NOTIFY on document UPDATE
CREATE OR REPLACE FUNCTION notify_document_updated()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify('document_created', json_build_object(
        'id', NEW.id,
        'title', NEW.title,
        'source_type', NEW.source_type,
        'action', 'updated'
    )::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_document_updated_notify ON documents;
CREATE TRIGGER trg_document_updated_notify
    AFTER UPDATE ON documents
    FOR EACH ROW
    EXECUTE FUNCTION notify_document_updated();
```

- [ ] **Step 2: Add document DELETE trigger**

Append:

```sql
-- Trigger: NOTIFY on document DELETE
CREATE OR REPLACE FUNCTION notify_document_deleted()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify('document_created', json_build_object(
        'id', OLD.id,
        'title', OLD.title,
        'source_type', OLD.source_type,
        'action', 'deleted'
    )::text);
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_document_deleted_notify ON documents;
CREATE TRIGGER trg_document_deleted_notify
    AFTER DELETE ON documents
    FOR EACH ROW
    EXECUTE FUNCTION notify_document_deleted();
```

- [ ] **Step 3: Update the frontend SSE handler in app.js to show 'deleted' as warning toast**

In the `document_created` SSE handler added in Task 1, update the toast logic:

```javascript
_sseSource.addEventListener('document_created', function(e) {
  try {
    var data = JSON.parse(e.data);
    if (window.showToast) {
      if (data.action === 'deleted') {
        window.showToast('Document deleted: ' + (data.title || 'Untitled'), 'warning');
      } else if (data.action === 'updated') {
        window.showToast('Document updated: ' + (data.title || 'Untitled'), 'info');
      } else {
        window.showToast('New document: ' + (data.title || 'Untitled'), 'info');
      }
    }
    if (typeof window._currentPage !== 'undefined' && window._currentPage === 'documents' && window.loadDocuments) {
      window.loadDocuments();
    }
  } catch(ex) {}
});
```

- [ ] **Step 4: Commit**

```bash
git add migrations/011_dashboard_notify_triggers.sql static/js/app.js
git commit -m "feat(triggers): add UPDATE/DELETE NOTIFY triggers on documents; wire action-aware SSE toasts"
```

---

### Task 3: Module health cards — document count + error list

**Files:**
- Modify: `static/js/pages/overview.js:158-167`

**Context:** The `module-health` API at `app/core/dashboard.py:360-463` returns `documents` count and `recent_errors` array per module. The frontend `loadModuleCards()` at `overview.js:135-169` only renders events count and an error badge — not documents count or the error list. This task adds both.

- [ ] **Step 1: Update the module card innerHTML to show document count**

In `overview.js:158-167`, replace the `card.innerHTML` assignment with:

```javascript
var errorListHtml = '';
if (errorCount > 0) {
  var errors = m.recent_errors || [];
  var errorItems = errors.slice(0, 3).map(function(err) {
    return '<div class="module-error-item" title="' + window.escHtml(err.title || '') + '">' +
      window.escHtml(err.title || '').substring(0, 60) +
    '</div>';
  }).join('');
  errorListHtml = '<div class="module-error-list">' + errorItems +
    (errors.length > 3 ? '<div class="module-error-more">+' + (errors.length - 3) + ' more</div>' : '') +
    '</div>';
}

card.innerHTML =
  '<span class="status-dot-lg ' + statusClass + '"></span>' +
  '<div class="module-card-body">' +
    '<span class="module-card-name">' + (m.label || m.name) + '</span>' +
    '<span class="module-card-stats">' +
      (m.documents !== undefined ? m.documents.toLocaleString() + ' docs &middot; ' : '') +
      (m.events ? m.events.toLocaleString() + ' events &middot; ' : '') +
      freshness +
    '</span>' +
  '</div>' +
  (errorCount > 0 ? '<span class="module-card-errors">' + errorCount + '</span>' : '') +
  errorListHtml;
```

- [ ] **Step 2: Add CSS for error list items**

Append to `static/css/dashboard.css`:

```css
.module-error-list {
  width: 100%;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--border);
}
.module-error-item {
  font-size: 0.75rem;
  color: var(--danger);
  padding: 2px 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.module-error-more {
  font-size: 0.7rem;
  color: var(--muted);
  padding-top: 2px;
}
```

- [ ] **Step 3: Add escHtml if not already available**

Search for `window.escHtml` in `static/js/app.js`. If it doesn't exist, add it:

```javascript
window.escHtml = function(text) {
  var div = document.createElement('div');
  div.appendChild(document.createTextNode(text || ''));
  return div.innerHTML;
};
```

- [ ] **Step 4: Commit**

```bash
git add static/js/pages/overview.js static/css/dashboard.css static/js/app.js
git commit -m "feat(overview): show document count and error list in module health cards"
```

---

### Task 4: Per-module force-poll endpoints + UI buttons

**Files:**
- Modify: `app/core/dashboard.py` (new route)
- Modify: `static/js/pages/overview.js` (add force-poll buttons)
- Modify: `static/css/dashboard.css` (button styling)

**Context:** Each poller module has an `async def collect()` function in its `collector.py` (freshrss, hermes, ntfy, dozzle, notflix) and uptime has `poll_kuma_registry()` in `poller.py`. This task adds a single generic `POST /api/dashboard/poll/{module_name}` endpoint that dispatches to the right collector, then adds "Force Poll" buttons to module health cards.

- [ ] **Step 1: Add generic force-poll endpoint**

In `app/core/dashboard.py`, after the existing `POST /poll-uptime` route (line ~744), add:

```python
# POST /api/dashboard/poll/{module_name} — trigger per-module collector
FORCE_POLL_REGISTRY: dict[str, tuple[str, str]] = {
    "freshrss": ("modules.freshrss.collector", "collect"),
    "hermes":   ("modules.hermes.collector",   "collect"),
    "ntfy":     ("modules.ntfy.collector",     "collect"),
    "dozzle":   ("modules.dozzle.collector",   "collect"),
    "notflix":  ("modules.notflix.collector",  "collect"),
    "uptime":   ("modules.uptime.poller",      "poll_kuma_registry"),
}


@router.post("/poll/{module_name}")
async def force_poll_module(
    module_name: str,
    user: AuthUser = Depends(require_admin),
):
    """Manually trigger a module's data collector immediately.

    Supports: freshrss, hermes, ntfy, dozzle, notflix, uptime.
    Returns collector stats or error if the module has no poller.
    """
    import importlib

    entry = FORCE_POLL_REGISTRY.get(module_name)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No force-poll available for module '{module_name}'. Supported: {', '.join(sorted(FORCE_POLL_REGISTRY.keys()))}",
        )

    mod_path, fn_name = entry
    try:
        mod = importlib.import_module(mod_path)
        fn = getattr(mod, fn_name)
        stats = await fn()
        # Collectors may return dicts with non-serializable values (datetimes, etc.)
        # Wrap in str() for the message, pass raw dict for the stats field
        return {
            "success": True,
            "module": module_name,
            "stats": stats if isinstance(stats, dict) else {"raw": str(stats)},
            "message": f"Polled {module_name} successfully",
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Poll failed for {module_name}: {str(e)}",
        )
```

- [ ] **Step 2: Check that modules with `collect()` return a dict**

Quickly read `collect()` in each collector to verify it returns a dict (not None and not raises). Most return `{"inserted": N, "skipped": N, ...}`. If any return `None`, wrap the call to return `{"note": "collector did not return stats"}`.

- [ ] **Step 3: Add force-poll button to module health cards**

In `overview.js:141`, after the `freshness` variable, add:

```javascript
var isPollable = ['uptime', 'freshrss', 'hermes', 'ntfy', 'dozzle', 'notflix'].indexOf(m.name) !== -1;
```

In `overview.js:158-167`, inside the `card.innerHTML`, after the `errorListHtml`, append:

```javascript
card.innerHTML += isPollable
  ? '<button class="module-poll-btn" onclick="event.stopPropagation(); window.forcePollModule(\'' + m.name + '\', this)" title="Force poll ' + m.name + '">&#8635; Poll</button>'
  : '';
```

- [ ] **Step 4: Add forcePollModule function**

At the top of `static/js/pages/overview.js`, before or after the `loadModuleCards` function, add:

```javascript
window.forcePollModule = async function(moduleName, btn) {
  var origText = btn.textContent;
  btn.textContent = '...';
  btn.disabled = true;
  try {
    var result = await window.api('/api/dashboard/poll/' + moduleName, { method: 'POST' });
    if (window.showToast) window.showToast('Polled ' + moduleName + ': OK', 'success');
  } catch (e) {
    if (window.showToast) window.showToast('Poll failed: ' + e.message, 'error');
  }
  btn.textContent = origText;
  btn.disabled = false;
  // Refresh module cards after a short delay for the collector to finish
  setTimeout(function() { loadModuleCards(); }, 2000);
};
```

- [ ] **Step 5: Add CSS for poll button**

Append to `static/css/dashboard.css`:

```css
.module-poll-btn {
  margin-top: 8px;
  padding: 4px 10px;
  font-size: 0.75rem;
  background: var(--surface);
  color: var(--accent);
  border: 1px solid var(--border);
  border-radius: 4px;
  cursor: pointer;
  width: 100%;
}
.module-poll-btn:hover {
  background: var(--accent);
  color: #fff;
}
.module-poll-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
```

- [ ] **Step 6: Commit**

```bash
git add app/core/dashboard.py static/js/pages/overview.js static/css/dashboard.css
git commit -m "feat(poll): add generic force-poll endpoint per module + UI buttons on health cards"
```

---

### Task 5: Document detail modal — Edit button + content inline edit

**Files:**
- Modify: `static/js/pages/documents.js` (add `docEditContent` function)
- Modify: `static/index.html` (add Edit button to detail modal)

**Context:** Documents page has inline editing for title (`docEditTitle`, line 207) and tags (`docEditTags`, line 248). Content inline editing was spec'd but never built (S7b spec line 241). The detail modal (`#doc-detail-content`, index.html:1424-1449) is read-only. This task adds content editing via the modal, and an Edit button.

- [ ] **Step 1: Add docEditContent function to documents.js**

After `docEditTags` (around line 300), add:

```javascript
window.docEditContent = function(docId) {
  var contentEl = document.getElementById('doc-detail-content');
  if (!contentEl) return;
  var current = contentEl.textContent;
  var textarea = document.createElement('textarea');
  textarea.value = current || '';
  textarea.className = 'doc-content-editor';
  textarea.style.width = '100%';
  textarea.style.minHeight = '150px';
  textarea.style.padding = '8px';
  textarea.style.fontSize = '0.85rem';
  textarea.style.background = 'var(--surface)';
  textarea.style.color = 'var(--fg)';
  textarea.style.border = '1px solid var(--border)';
  textarea.style.borderRadius = '4px';
  textarea.style.resize = 'vertical';
  contentEl.parentElement.replaceChild(textarea, contentEl);
  textarea.focus();

  var editBtn = document.getElementById('doc-detail-edit-btn');
  if (editBtn) editBtn.style.display = 'none';
  var saveBtn = document.createElement('button');
  saveBtn.textContent = 'Save';
  saveBtn.className = 'btn btn-primary btn-sm';
  saveBtn.style.marginLeft = '8px';
  saveBtn.onclick = function() {
    var val = textarea.value;
    var indicator = document.createElement('span');
    indicator.textContent = 'saving\u2026';
    indicator.style.marginLeft = '8px';
    textarea.parentElement.appendChild(indicator);
    window.api('/api/documents/' + docId, { method: 'PUT', body: JSON.stringify({ content: val }) }).then(function() {
      indicator.textContent = '\u2713';
      // replace textarea back with content element
      var newContent = document.createElement('div');
      newContent.id = 'doc-detail-content';
      newContent.textContent = val;
      textarea.parentElement.replaceChild(newContent, textarea);
      if (editBtn) editBtn.style.display = '';
      indicator.remove();
      saveBtn.remove();
    }).catch(function(e) {
      indicator.textContent = '\u2717 ' + e.message;
    });
  };
  var cancelBtn = document.createElement('button');
  cancelBtn.textContent = 'Cancel';
  cancelBtn.className = 'btn btn-sm';
  cancelBtn.style.marginLeft = '4px';
  cancelBtn.onclick = function() {
    var newContent = document.createElement('div');
    newContent.id = 'doc-detail-content';
    newContent.textContent = current;
    textarea.parentElement.replaceChild(newContent, textarea);
    if (editBtn) editBtn.style.display = '';
    saveBtn.remove();
    cancelBtn.remove();
  };
  textarea.parentElement.appendChild(saveBtn);
  textarea.parentElement.appendChild(cancelBtn);
};
```

- [ ] **Step 2: Update openDocDetail to store current docId and add Edit button**

Find `window.openDocDetail` or the function that populates the `#doc-detail-content` modal. After setting the content, store the doc ID. In the modal footer (or next to the content), add:

In `static/index.html`, find the doc detail modal (search for `doc-detail-content`). After the content div, add:

```html
<button id="doc-detail-edit-btn" class="btn btn-sm" style="margin-top:8px;" onclick="window.docEditContent(window._openDocId)">Edit Content</button>
```

Then find `window.openDocDetail` in `documents.js` and ensure it sets:

```javascript
window._openDocId = doc.id;
```

- [ ] **Step 3: Verify the doc detail modal structure**

Read the doc detail modal in `static/index.html` (search for `#doc-detail-modal`). Ensure the modal has a proper header with title, and a content section where the Edit button fits naturally.

- [ ] **Step 4: Commit**

```bash
git add static/js/pages/documents.js static/index.html
git commit -m "feat(documents): add content inline editing via detail modal with Edit button"
```

---

### Task 6: Document bulk "Change source_type" action

**Files:**
- Modify: `static/js/pages/documents.js` (add bulk source_type function)
- Modify: `static/index.html` (add button to bulk toolbar if not present)

**Context:** The bulk toolbar at `index.html:705-711` has Tag and Delete buttons. The S7b spec calls for a "Change source_type" toolbar action. This task adds it.

- [ ] **Step 1: Add docBulkSourceType function to documents.js**

After `docBulkDelete` (around line 205), add:

```javascript
window.docBulkChangeSourceType = function() {
  var ids = Object.keys(_docSelected).filter(function(id) { return _docSelected[id]; });
  if (ids.length === 0) return alert('No documents selected.');
  if (!confirm('Change source_type for ' + ids.length + ' document(s)?\nThis will update the source_type field for all selected documents.')) return;

  var newType = prompt('Enter new source_type:');
  if (!newType || !newType.trim()) return;
  newType = newType.trim();

  var promises = ids.map(function(id) {
    return window.api('/api/documents/' + id, {
      method: 'PUT',
      body: JSON.stringify({ source_type: newType })
    });
  });

  Promise.all(promises).then(function() {
    window.loadDocuments();
    window.showToast('Source type changed for ' + ids.length + ' document(s)', 'success');
  }).catch(function(e) {
    window.showError('Bulk source_type update failed: ' + e.message);
  });
};
```

- [ ] **Step 2: Add button to bulk toolbar in index.html**

In `static/index.html`, find the bulk toolbar (search for `doc-bulk-toolbar`). After the Delete button, add:

```html
<button class="btn btn-sm btn-outline" onclick="window.docBulkChangeSourceType()">Change Source</button>
```

- [ ] **Step 3: Commit**

```bash
git add static/js/pages/documents.js static/index.html
git commit -m "feat(documents): add bulk 'Change source_type' action to document toolbar"
```

---

### Task 7: Alert badges on all sidebar categories

**Files:**
- Modify: `static/js/app.js:452-467` (extend `updateSidebarBadges`)

**Context:** Currently `updateSidebarBadges()` only populates the Monitoring category badge with down-count from uptime/status. The Core, Data Sources, and Admin category badges exist as empty `<span class="cat-badge">` placeholders in `index.html`. This task wires them all.

- [ ] **Step 1: Rewrite updateSidebarBadges in app.js**

Replace the current `updateSidebarBadges` function (app.js:452-467) with:

```javascript
function updateSidebarBadges() {
  // Monitoring: count of DOWN services
  api('/api/uptime/status').then(function(status) {
    var down = (status || []).filter(function(m) { return m.status === 0; }).length;
    setBadge('badge-monitoring', down > 0 ? down + ' down' : '', down > 0 ? 'alert' : '');
  }).catch(function() {});

  // Core: count of error events across all modules (signals issues)
  api('/api/events?severity=error&limit=50').then(function(events) {
    var errors = (events || []).filter(function(e) {
      var ts = new Date(e.ts);
      var hourAgo = new Date(Date.now() - 3600000);
      return ts > hourAgo;
    }).length;
    setBadge('badge-core', errors > 0 ? errors + ' err' : '', errors > 0 ? 'alert' : '');
  }).catch(function() {});

  // Data Sources: aggregated warnings from collector modules
  api('/api/dashboard/module-health').then(function(health) {
    var modules = health.modules || [];
    var warnCount = modules.filter(function(m) {
      return m.status === 'red' || m.status === 'yellow';
    }).length;
    setBadge('badge-datasources', warnCount > 0 ? warnCount + ' issue' + (warnCount > 1 ? 's' : '') : '', warnCount > 0 ? 'warn' : '');
  }).catch(function() {});

  // Admin: count of stale API keys (no usage in 30 days)
  api('/api/dashboard/api-keys/stats').then(function(stats) {
    var stale = stats.stale || 0;
    setBadge('badge-admin', stale > 0 ? stale + ' stale' : '', stale > 0 ? 'warn' : '');
  }).catch(function() {});
}

function setBadge(id, text, cssClass) {
  var badge = document.getElementById(id);
  if (!badge) return;
  badge.textContent = text;
  if (cssClass) {
    badge.className = 'cat-badge has-items ' + cssClass;
  } else {
    badge.className = 'cat-badge';
  }
}
```

- [ ] **Step 2: Check that /api/dashboard/api-keys/stats endpoint exists**

Read `app/core/dashboard.py` and search for `api-keys/stats`. If it doesn't exist, add a minimal version:

```python
@router.get("/api-keys/stats")
async def api_key_stats(user: AuthUser = Depends(require_admin)):
    pool = get_pool()
    async with pool.acquire() as conn:
        active = await conn.fetchval("SELECT count(*) FROM api_keys WHERE active = true")
        inactive = await conn.fetchval("SELECT count(*) FROM api_keys WHERE active = false")
        stale = await conn.fetchval(
            "SELECT count(*) FROM api_keys WHERE active = true AND (last_used_at IS NULL OR last_used_at < now() - interval '30 days')"
        )
    return {"active": active, "inactive": inactive, "stale": stale}
```

- [ ] **Step 3: Add CSS for warn badge variant**

In `static/css/dashboard.css`, find the `.cat-badge.alert` style. Add:

```css
.cat-badge.warn {
  background: var(--accent-yellow);
  color: #000;
}
```

- [ ] **Step 4: Ensure updateSidebarBadges is called on page load and SSE events**

In the SSE handler for `monitor_status` (Task 1), `updateSidebarBadges()` is already called. Also ensure it's called in the main bootstrap function in app.js (search for where `updateSidebarBadges` is first called — around line 550-600). If not called at all on load, add `updateSidebarBadges();` to the init/bootstrap function.

- [ ] **Step 5: Commit**

```bash
git add static/js/app.js static/css/dashboard.css app/core/dashboard.py
git commit -m "feat(sidebar): wire alert badges on all four categories (Core, Monitoring, Data Sources, Admin)"
```

---

## Task Dependency Map

```
Task 2 (SQL migration)     ── independent ──┐
Task 3 (module health)     ── independent ──┤
Task 4 (force-poll)        ── independent ──┼ All can run in parallel
                                             │ (different files, or non-overlapping edits)
Task 1 (SSE frontend)      ── touches app.js ──┐
Task 7 (alert badges)      ── touches app.js ──┤ These two both edit app.js
                                               │ but at different line ranges (1: ~89, 7: ~452)
Task 5 (doc edit modal)    ── touches documents.js + index.html ──┐
Task 6 (bulk source_type)  ── touches documents.js + index.html ──┤ Must run sequential
```

**Execution strategy:**
- **Parallel batch 1:** Tasks 2, 3, 4, (1+7 together as one agent since both edit app.js), (5+6 together as one agent since both edit documents.js+index.html)
- After all complete: rebuild Docker, smoke test dashboard pages
- Tasks 1+7 can be one agent (both edits in app.js but non-overlapping lines). Tasks 5+6 can be one agent (both edit documents.js + index.html).

**Total estimated:** 4 parallel agents, ~15-20 min.

**Files touched (by task):**
| Task | Files |
|------|-------|
| 1 | app.js |
| 2 | migration SQL, app.js |
| 3 | overview.js, dashboard.css |
| 4 | dashboard.py, overview.js, dashboard.css |
| 5 | documents.js, index.html |
| 6 | documents.js, index.html |
| 7 | app.js, dashboard.css, dashboard.py |
