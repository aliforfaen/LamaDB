// Page: Wiki
(function() {
  'use strict';

  var _wikiCurrentPageId = null;
  var _wikiTab = 'browse';

  window.loadWiki = async function() {
    loadScratchpadEntries();
    document.querySelectorAll('.tab-btn[data-tab]').forEach(function(btn) {
      btn.addEventListener('click', function() {
        var tab = this.dataset.tab;
        document.querySelectorAll('#page-wiki .tab-btn').forEach(function(b) { b.classList.toggle('active', b.dataset.tab === tab); });
        document.querySelectorAll('#page-wiki .tab-panel').forEach(function(p) {
          p.style.display = (p.id === 'tab-' + tab) ? '' : 'none';
        });
        if (tab === 'wiki-browser') window.loadWikiPages();
        else if (tab === 'wiki-activity') loadWikiActivity();
        else if (tab === 'wiki-editor') {
          var content = document.getElementById('wiki-edit-content');
          if (content) {
            var preview = document.getElementById('wiki-edit-preview');
            if (preview && content.value) { preview.innerHTML = simpleMarkdown(content.value); }
          }
        }
      });
    });
  };

  window.switchWikiTab = function(tab) {
    _wikiTab = tab;
    var tabs = ['browser', 'editor', 'scratchpad', 'activity'];
    tabs.forEach(function(t) {
      var btn = document.querySelector('.tab-btn[data-tab="wiki-' + t + '"]');
      var panel = document.getElementById('tab-wiki-' + t);
      if (btn) btn.classList.toggle('active', t === tab);
      if (panel) panel.style.display = t === tab ? '' : 'none';
    });
    if (tab === 'browse') window.loadWikiPages();
  };

  window.loadWikiPages = async function() {
    var el = document.getElementById('wiki-page-list');
    if (!el) return;
    el.innerHTML = '<p class="loading">Loading\u2026</p>';
    try {
      var pages = await window.api('/api/wiki/pages?limit=100');
      renderWikiPageList(pages);
    } catch(e) { el.innerHTML = '<p class="error">Failed to load pages</p>'; }
  };

  function renderWikiPageList(pages) {
    var el = document.getElementById('wiki-page-list');
    if (!el) return;
    if (!pages || pages.length === 0) {
      el.innerHTML = '<p class="empty">No pages yet. <a href="#" onclick="switchWikiTab(\'editor\');window.newWikiPage();return false;">Create one!</a></p>';
      return;
    }
    var html = '<div class="table-wrap"><table><thead><tr><th>Title</th><th>Path</th><th>Updated</th><th></th></tr></thead><tbody>';
    pages.forEach(function(p) {
      var updated = p.updated_at ? new Date(p.updated_at).toLocaleDateString() : '';
      var pathEsc = window.escAttr(p.path || '');
      html += '<tr class="wiki-row" style="cursor:pointer;" onclick="window.openWikiPage(\'' + pathEsc + '\')">' +
        '<td style="font-weight:500;">' + window.escHtml(p.title || '') + '</td>' +
        '<td style="font-size:12px;color:var(--fg-2);">' + window.escHtml(p.path || '') + '</td>' +
        '<td class="mono" style="font-size:11px;">' + window.escHtml(updated) + '</td>' +
        '<td>' +
          '<button class="btn btn-sm btn-secondary" onclick="event.stopPropagation();window.editWikiPage(\'' + window.escAttr(p.id || '') + '\')">Edit</button> ' +
          '<button class="btn btn-sm btn-danger" onclick="event.stopPropagation();window.deleteWikiPage(\'' + window.escAttr(p.id || '') + '\')">\u00d7</button>' +
        '</td>' +
        '</tr>';
    });
    html += '</tbody></table></div>';
    el.innerHTML = html;
  }

  window.openWikiPage = async function(pageId) {
    try {
      var page;
      if (pageId && pageId.includes('-') && pageId.length > 20) {
        page = await window.api('/api/wiki/pages/' + pageId);
      } else {
        page = await window.api('/api/wiki/pages/by-path?path=' + encodeURIComponent(pageId));
      }
      var el = document.getElementById('wiki-page-list');
      if (!el) return;
      var ts = page.updated_at ? new Date(page.updated_at).toLocaleString('en-US', { month: 'short', day: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }) : '';
      el.innerHTML = '<div class="col-card">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">' +
        '<h3 style="margin:0;">' + window.escHtml(page.title || page.path || '') + '</h3>' +
        '<div><button class="btn btn-sm btn-secondary" onclick="window.editWikiPage(\'' + window.escAttr(page.id || '') + '\')">Edit</button> ' +
        '<button class="btn btn-sm btn-secondary" onclick="window.loadWikiPages()">\u2190 Back</button></div>' +
        '</div>' +
        '<div style="color:var(--muted);font-size:11px;margin-bottom:12px;">' + ts + ' \u00b7 ' + window.escHtml(page.path || '') + '</div>' +
        '<div style="line-height:1.7;font-size:13px;">' + simpleMarkdown(page.content || '') + '</div>' +
        '</div>';
    } catch(e) {
      var el2 = document.getElementById('wiki-page-list');
      if (el2) el2.innerHTML = '<div class="col-card"><div style="color:var(--danger);padding:20px;">Page not found</div></div>';
    }
  };

  window.editWikiPage = async function(pageId) {
    _wikiCurrentPageId = pageId;
    window.switchWikiTab('editor');
    try {
      var page = await window.api('/api/wiki/pages/' + pageId);
      document.getElementById('wiki-edit-title').value = page.title || '';
      document.getElementById('wiki-edit-path').value = page.path || '';
      document.getElementById('wiki-edit-content').value = page.content || '';
      updateWikiPreview();
    } catch(e) {}
  };

  window.newWikiPage = function() {
    _wikiCurrentPageId = null;
    document.getElementById('wiki-edit-title').value = '';
    document.getElementById('wiki-edit-path').value = '';
    document.getElementById('wiki-edit-content').value = '';
    document.getElementById('wiki-edit-preview').innerHTML = '<p class="empty" style="color:var(--muted);">Preview will appear here\u2026</p>';
  };

  window.saveWikiPage = async function() {
    var title = document.getElementById('wiki-edit-title').value.trim();
    var path = document.getElementById('wiki-edit-path').value.trim();
    var content = document.getElementById('wiki-edit-content').value;
    if (!title) { alert('Title is required'); return; }
    if (!path) { alert('Path is required'); return; }
    try {
      if (_wikiCurrentPageId) {
        await window.api('/api/wiki/pages/' + _wikiCurrentPageId, {
          method: 'PATCH', body: JSON.stringify({ title: title, content: content })
        });
      } else {
        await window.api('/api/wiki/pages', {
          method: 'POST', body: JSON.stringify({ title: title, content: content, path: path, tags: [] })
        });
      }
      window.switchWikiTab('browser');
      window.loadWikiPages();
    } catch(e) { alert('Failed to save: ' + (e.message || 'Unknown error')); }
  };

  window.deleteWikiPage = async function(pageId) {
    if (!confirm('Delete this page?')) return;
    try {
      await window.api('/api/wiki/pages/' + pageId, { method: 'DELETE' });
      window.loadWikiPages();
    } catch(e) { alert('Failed to delete: ' + (e.message || 'Unknown error')); }
  };

  window.searchWikiPages = async function() {
    var q = document.getElementById('wiki-search-input').value.trim();
    var el = document.getElementById('wiki-page-list');
    if (!q) { window.loadWikiPages(); return; }
    if (!el) return;
    el.innerHTML = '<p class="loading">Searching\u2026</p>';
    try {
      var results = await window.api('/api/wiki/pages/search?q=' + encodeURIComponent(q));
      renderWikiPageList(results);
    } catch(e) { if (el) el.innerHTML = '<p class="error">Search failed</p>'; }
  };

  function simpleMarkdown(md) {
    if (!md) return '';
    var html = md
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/^### (.+)$/gm, '<h3>$1</h3>')
      .replace(/^## (.+)$/gm, '<h2>$1</h2>')
      .replace(/^# (.+)$/gm, '<h1>$1</h1>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g, '<em>$1</em>')
      .replace(/`(.+?)`/g, '<code>$1</code>')
      .replace(/^- (.+)$/gm, '<li>$1</li>')
      .replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>')
      .replace(/\n/g, '<br />');
    return html;
  }

  document.addEventListener('DOMContentLoaded', function() {
    var contentEl = document.getElementById('wiki-edit-content');
    if (contentEl) { contentEl.addEventListener('input', updateWikiPreview); }
  });

  function updateWikiPreview() {
    var contentEl = document.getElementById('wiki-edit-content');
    var previewEl = document.getElementById('wiki-edit-preview');
    if (!contentEl || !previewEl) return;
    var md = contentEl.value;
    if (!md) { previewEl.innerHTML = '<p class="empty" style="color:var(--muted);">Preview will appear here\u2026</p>'; return; }
    previewEl.innerHTML = simpleMarkdown(md);
  }

  function loadScratchpadEntries() {
    var container = document.getElementById('scratchpad-entries');
    if (!container) return;
    window.api('/api/wiki/scratchpad?limit=20').then(function(entries) {
      if (!entries || entries.length === 0) {
        container.innerHTML = '<div style="color:var(--muted);font-size:12px;padding:10px 0;">No entries yet. Write something above!</div>'; return;
      }
      container.innerHTML = entries.map(function(e) {
        var ts = e.created_at ? new Date(e.created_at).toLocaleString('en-US', { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) : '';
        var preview = (e.content || '').substring(0, 120);
        if (preview.length === 120) preview += '...';
        return '<div style="padding:8px 0;border-bottom:1px solid var(--border-light);">' +
          '<div style="color:var(--muted);font-size:11px;margin-bottom:3px;">' + ts + '</div>' +
          '<div style="color:var(--fg-2);font-size:12px;line-height:1.4;">' + window.escHtml(preview) + '</div></div>';
      }).join('');
    }).catch(function() {
      container.innerHTML = '<div style="color:var(--danger);font-size:12px;padding:10px 0;">Failed to load entries.</div>';
    });
  }

  function loadWikiActivity() {
    var list = document.getElementById('wiki-activity-list');
    if (!list) return;
    window.api('/api/wiki/log?limit=50').then(function(entries) {
      if (!entries || entries.length === 0) {
        list.innerHTML = '<div style="color:var(--muted);font-size:13px;padding:10px 0;">No activity yet.</div>'; return;
      }
      list.innerHTML = entries.map(function(ev) {
        var sev = ev.severity || 'info';
        var sevClass = sev === 'critical' || sev === 'error' ? 'critical' : sev === 'warn' ? 'warn' : 'info';
        var ts = ev.ts ? new Date(ev.ts).toLocaleString('en-US', { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) : '';
        return '<div style="display:flex;gap:12px;padding:8px 0;border-bottom:1px solid var(--border-light);align-items:flex-start;">' +
          '<span class="sev-badge ' + sevClass + '" style="flex-shrink:0;">' + sev + '</span>' +
          '<div style="flex:1;min-width:0;">' +
          '<div style="color:var(--fg);font-size:13px;font-weight:500;">' + window.escHtml(ev.title || '') + '</div>' +
          '<div style="color:var(--muted);font-size:11px;margin-top:2px;">' + window.escHtml(ev.source || '') + ' \u00b7 ' + ts + '</div>' +
          (ev.body ? '<div style="color:var(--fg-2);font-size:12px;margin-top:4px;">' + window.escHtml(ev.body.substring(0, 150)) + '</div>' : '') +
          '</div></div>';
      }).join('');
    }).catch(function() {
      list.innerHTML = '<div style="color:var(--danger);font-size:13px;padding:10px 0;">Failed to load activity.</div>';
    });
  }
})();
