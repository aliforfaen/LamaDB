// Page: Search — full-text and semantic document search
(function() {
  'use strict';

  window._searchMode = 'fulltext';

  window.loadSearch = function() {
    var input = document.getElementById('search-input');
    if (input) {
      input.value = '';
      input.focus();
    }
    var results = document.getElementById('search-results');
    if (results) {
      results.innerHTML = '<div style="color:var(--muted);padding:20px;text-align:center;">Enter a query to search documents.</div>';
    }
    document.getElementById('search-result-count').textContent = '';
  };

  window.runSearch = async function() {
    var q = document.getElementById('search-input').value.trim();
    if (!q) return;

    var resultsEl = document.getElementById('search-results');
    if (!resultsEl) return;
    resultsEl.innerHTML = '<div style="color:var(--muted);padding:20px;text-align:center;">Searching…</div>';

    try {
      var endpoint = window._searchMode === 'semantic' ? '/api/search/semantic' : '/api/search';
      var data = await window.api(endpoint + '?q=' + encodeURIComponent(q) + '&limit=30');

      if (!Array.isArray(data) || data.length === 0) {
        resultsEl.innerHTML = '<div style="color:var(--muted);padding:20px;text-align:center;">No results found for "' + window.escHtml(q) + '".</div>';
        document.getElementById('search-result-count').textContent = '0 results';
        return;
      }

      document.getElementById('search-result-count').textContent = data.length + ' result' + (data.length !== 1 ? 's' : '');

      resultsEl.innerHTML = data.map(function(doc) {
        var excerpt = doc.content ? doc.content.substring(0, 200) : '';
        if (excerpt.length >= 200) excerpt += '…';
        var tags = Array.isArray(doc.tags) && doc.tags.length > 0
          ? doc.tags.map(function(t) { return '<span style="background:var(--surface-2);padding:1px 6px;border-radius:3px;font-size:10px;color:var(--muted);">' + window.escHtml(t) + '</span>'; }).join(' ')
          : '';
        var dateStr = doc.created_at ? window.relativeTime(doc.created_at) : '';
        return '<div class="module-card" style="cursor:pointer;" onclick="window.navigateTo(\'documents\')">' +
          '<div class="module-card-info">' +
            '<h4>' + window.escHtml(doc.title || 'Untitled') + '</h4>' +
            '<p style="font-size:12px;line-height:1.4;">' + window.escHtml(excerpt) + '</p>' +
            '<div class="module-card-meta">' +
              '<span>' + window.escHtml(doc.source_type || '') + '</span>' +
              (tags ? '<span>\u00b7 ' + tags + '</span>' : '') +
              '<span style="font-family:var(--font-mono);">' + dateStr + '</span>' +
            '</div>' +
          '</div>' +
        '</div>';
      }).join('');
    } catch (e) {
      resultsEl.innerHTML = '<div style="color:var(--danger);padding:20px;">Error: ' + window.escHtml(e.message) + '</div>';
    }
  };
})();
