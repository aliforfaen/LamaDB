// Page: Dozzle
(function() {
  'use strict';

  window.loadDozzlePage = async function() {
    try {
      var logs = await window.api('/api/dozzle/logs?lines=100');
      renderDozzleLogs(logs);
      updateDozzleContainerSelect(logs);
    } catch (e) {
      var container = document.getElementById('dozzle-logs');
      if (container) container.innerHTML = '<div style="color:var(--danger);padding:20px;">Failed to load logs: ' + e.message + '</div>';
    }
  };

  function renderDozzleLogs(logs) {
    var container = document.getElementById('dozzle-logs');
    if (!container) return;
    if (!logs || logs.length === 0) {
      container.innerHTML = '<div style="color:var(--muted);text-align:center;padding:30px;">No log entries found.</div>';
      return;
    }
    var level = 'all';
    var levelBtn = document.querySelector('#page-dozzle .filter-bar .sub-tab-btn.active[id^="dozzle-level-"]');
    if (levelBtn) level = levelBtn.id.replace('dozzle-level-', '');
    var containerFilter = document.getElementById('dozzle-container-select');
    var selContainer = containerFilter ? containerFilter.value : 'all';
    var filtered = logs.filter(function(l) {
      if (selContainer !== 'all' && l.container !== selContainer) return false;
      if (level !== 'all') {
        var msg = (l.message || l.msg || '').toLowerCase();
        if (level === 'error' && msg.indexOf('error') === -1 && msg.indexOf('trace') === -1) return false;
        if (level === 'warn' && msg.indexOf('warn') === -1) return false;
        if (level === 'info' && (msg.indexOf('error') !== -1 || msg.indexOf('warn') !== -1)) return false;
      }
      return true;
    });
    container.innerHTML = filtered.map(function(l) {
      var ts = l.ts || l.timestamp || l.time || '';
      var msg = l.message || l.msg || '';
      var levelClass = 'info';
      var ml = msg.toLowerCase();
      if (ml.indexOf('error') !== -1 || ml.indexOf('trace') !== -1) levelClass = 'critical';
      else if (ml.indexOf('warn') !== -1) levelClass = 'warn';
      return '<div style="font-family:var(--font-mono);font-size:12px;padding:3px 8px;border-bottom:1px solid var(--border-light);display:flex;gap:8px;align-items:flex-start;">' +
        '<span class="sev-dot sev-' + levelClass + '" style="margin-top:5px;"></span>' +
        '<span style="color:var(--muted);white-space:nowrap;flex-shrink:0;">' + window.escHtml(typeof ts === 'string' ? ts.substring(11, 23) : ts) + '</span>' +
        '<span style="color:var(--accent-cyan);white-space:nowrap;flex-shrink:0;">' + window.escHtml(l.container || '') + '</span>' +
        '<span style="color:var(--fg-2);word-break:break-word;">' + window.escHtml(msg) + '</span>' +
      '</div>';
    }).join('');
  }

  function updateDozzleContainerSelect(logs) {
    var sel = document.getElementById('dozzle-container-select');
    if (!sel) return;
    var containers = {};
    (logs || []).forEach(function(l) {
      if (l.container) containers[l.container] = true;
    });
    var names = Object.keys(containers).sort();
    sel.innerHTML = '<option value="all">All Containers</option>' +
      names.map(function(n) { return '<option value="' + n + '">' + n + '</option>'; }).join('');
  }

  window.setDozzleLevel = function(level) {
    document.querySelectorAll('#page-dozzle .filter-bar .sub-tab-btn[id^="dozzle-level-"]').forEach(function(b) {
      b.classList.toggle('active', b.id === 'dozzle-level-' + level);
    });
    window.loadDozzlePage();
  };

  window.setDozzleContainer = function() { window.loadDozzlePage(); };
})();
