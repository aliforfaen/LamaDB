// Page: Audiobookshelf
(function() {
  'use strict';

  window.loadAudiobookshelfPage = async function() {
    try {
      var results = await Promise.all([
        window.api('/api/audiobookshelf/health'),
        window.api('/api/audiobookshelf/status'),
        window.api('/api/audiobookshelf/libraries'),
        window.api('/api/audiobookshelf/books?limit=50'),
      ]);
      renderAudiobookshelfHealth(results[0]);
      renderAudiobookshelfSnapshot(results[1], results[2]);
      renderAudiobookshelfLibraries(results[2]);
      renderAudiobookshelfBooks(results[3]);

      var statusEl = document.getElementById('audiobookshelf-status');
      if (statusEl) statusEl.textContent = 'Updated ' + new Date().toLocaleTimeString();
    } catch (e) {
      console.error('[LamaDB] Audiobookshelf error:', e);
      var statsEl = document.getElementById('audiobookshelf-stats');
      if (statsEl) statsEl.innerHTML = '<div style="color:var(--danger);padding:10px;">Failed: ' + e.message + '</div>';
    }
  };

  // ─── Health Card ─────────────────────────────────────────────
  function renderAudiobookshelfHealth(health) {
    var el = document.getElementById('audiobookshelf-stats');
    if (!el) return;

    var reachable = health && health.reachable === true;
    var reason = health && health.reason ? health.reason : '';
    var dotClass = reachable ? 'sev-info' : 'sev-critical';
    var statusText = reachable ? 'Reachable' : 'Unreachable';

    var html = '<div class="stat-card">' +
      '<div class="label" style="display:flex;align-items:center;gap:6px;">' +
        '<span class="sev-dot ' + dotClass + '" style="margin:0;"></span>' +
        'Audiobookshelf Server' +
      '</div>' +
      '<div class="value" style="font-size:18px;font-weight:500;">' + window.escHtml(statusText) + '</div>' +
      (reason ? '<span style="font-size:11px;color:var(--muted);display:block;margin-top:2px;">' + window.escHtml(reason) + '</span>' : '') +
    '</div>';
    el.innerHTML = html;
  }

  // ─── Snapshot Summary ────────────────────────────────────────
  function renderAudiobookshelfSnapshot(status, librariesResp) {
    var el = document.getElementById('audiobookshelf-stats');
    if (!el) return;

    var snapshot = (status && status.data) ? status.data : null;
    if (!snapshot) {
      // Append a "no data" placeholder after the health card
      el.innerHTML += '<div class="stat-card">' +
        '<div class="label">Books Synced</div>' +
        '<div class="value" style="color:var(--muted);">No data</div>' +
      '</div>';
      return;
    }

    var html = el.innerHTML; // keep the health card
    html += '<div class="stat-card">' +
      '<div class="label">Libraries</div>' +
      '<div class="value">' + (snapshot.libraries ? snapshot.libraries.length : 0) + '</div>' +
    '</div>';
    html += '<div class="stat-card">' +
      '<div class="label">Books Synced</div>' +
      '<div class="value">' + (snapshot.book_count || 0) + '</div>' +
    '</div>';
    html += '<div class="stat-card">' +
      '<div class="label">In Progress</div>' +
      '<div class="value">' + (snapshot.in_progress_count || 0) + '</div>' +
    '</div>';
    html += '<div class="stat-card">' +
      '<div class="label">Finished</div>' +
      '<div class="value">' + (snapshot.finished_count || 0) + '</div>' +
    '</div>';

    var ts = status.ts ? window.relativeTime(status.ts) : '';
    if (ts) {
      html += '<div class="stat-card" style="grid-column:1/-1;">' +
        '<div class="label">Last Snapshot</div>' +
        '<div class="value" style="font-size:13px;color:var(--muted);">' + window.escHtml(ts) + '</div>' +
      '</div>';
    }

    el.innerHTML = html;
  }

  // ─── Libraries Grid ──────────────────────────────────────────
  function renderAudiobookshelfLibraries(librariesResp) {
    var el = document.getElementById('audiobookshelf-libraries');
    if (!el) return;
    var libraries = (librariesResp && Array.isArray(librariesResp.libraries)) ? librariesResp.libraries : [];
    if (libraries.length === 0) {
      el.innerHTML = '<div style="color:var(--muted);padding:10px;">No libraries synced yet — check Audiobookshelf configuration.</div>';
      return;
    }

    el.innerHTML = libraries.map(function(lib) {
      var icon = lib.media_type === 'podcast' ? '&#x1F399;' : '&#x1F4D6;';
      var mediaLabel = lib.media_type === 'podcast' ? 'podcasts' : 'books';
      return '<div class="stat-card">' +
        '<div class="label" style="display:flex;align-items:center;gap:6px;">' +
          '<span style="font-size:14px;">' + icon + '</span>' +
          window.escHtml(lib.name || 'Untitled') +
        '</div>' +
        '<div class="value" style="font-size:18px;">' + (lib.item_count || 0) + ' <span style="font-size:12px;color:var(--muted);font-weight:400;">' + mediaLabel + '</span></div>' +
      '</div>';
    }).join('');
  }

  // ─── Recent Books Table ──────────────────────────────────────
  function renderAudiobookshelfBooks(booksResp) {
    var tbody = document.getElementById('audiobookshelf-tbody');
    if (!tbody) return;
    var books = (booksResp && Array.isArray(booksResp.books)) ? booksResp.books : [];
    if (books.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" style="color:var(--muted);text-align:center;padding:20px;">No books synced yet.</td></tr>';
      return;
    }

    tbody.innerHTML = books.map(function(book) {
      var meta = book.metadata || {};
      var progress = meta.progress_percent;
      var isFinished = meta.is_finished === true;
      var progressCell;
      if (isFinished) {
        progressCell = '<span class="source-badge" style="background:var(--success,#22c55e);color:#000;">Finished</span>';
      } else if (progress && progress > 0) {
        var pct = Math.round(progress * 100);
        progressCell = '<div style="display:flex;flex-direction:column;gap:2px;min-width:80px;">' +
          '<div style="font-size:11px;color:var(--muted);">' + pct + '%</div>' +
          '<div style="background:var(--surface-2,#1f2937);height:4px;border-radius:2px;overflow:hidden;">' +
            '<div style="background:var(--accent);height:100%;width:' + pct + '%;"></div>' +
          '</div>' +
        '</div>';
      } else {
        progressCell = '<span style="color:var(--muted);font-size:11px;">Unstarted</span>';
      }

      var updated = book.updated_at ? window.relativeTime(book.updated_at) : '';
      var libraryName = meta.library_name || '';
      var author = meta.author || '—';

      return '<tr>' +
        '<td style="font-weight:500;color:var(--fg);">' + window.escHtml(book.title || 'Untitled') + '</td>' +
        '<td style="color:var(--fg-2);">' + window.escHtml(author) + '</td>' +
        '<td><span class="source-badge" style="background:var(--info);color:#000;">' + window.escHtml(libraryName || '—') + '</span></td>' +
        '<td>' + progressCell + '</td>' +
        '<td class="mono" style="font-size:12px;">' + window.escHtml(updated) + '</td>' +
      '</tr>';
    }).join('');
  }
})();