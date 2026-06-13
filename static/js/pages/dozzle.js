// Page: Dozzle — container log viewer
(function() {
  'use strict';

  var _containers = [];
  var _selectedContainerId = null;

  // ─── Helpers ──────────────────────────────────────────────────────────

  function getActiveLevel() {
    var btn = document.querySelector('#page-dozzle .filter-bar .active[id^="dozzle-level-"]');
    if (!btn) return 'error';
    return btn.id.replace('dozzle-level-', '');
  }

  function getActiveSince() {
    var btn = document.querySelector('#page-dozzle .filter-bar .active[id^="dozzle-since-"]');
    if (!btn) return '30m';
    return btn.id.replace('dozzle-since-', '');
  }

  function getLogLevelClass(level) {
    var l = (level || '').toLowerCase();
    if (l === 'error' || l === 'critical') return 'critical';
    if (l === 'warn' || l === 'warning') return 'warn';
    return 'info';
  }

  function getStatusClass(state) {
    var s = (state || '').toLowerCase();
    if (s === 'running') return 'up';
    if (s === 'exited' || s === 'dead') return 'down';
    if (s === 'paused') return 'warn';
    return 'unknown';
  }

  function getStatusBadgeClass(state) {
    var s = (state || '').toLowerCase();
    if (s === 'running') return 'sev-info';
    if (s === 'exited' || s === 'dead') return 'sev-critical';
    if (s === 'paused') return 'sev-warn';
    return '';
  }

  // ─── Main page loader — show container grid ───────────────────────────

  window.loadDozzlePage = async function() {
    try {
      // Ensure we start in grid view
      document.getElementById('dozzle-container-grid').style.display = 'block';
      document.getElementById('dozzle-filter-bar').style.display = 'none';
      document.getElementById('dozzle-content').style.display = 'none';

      _containers = await window.api('/api/dozzle/containers');
      renderContainerGrid(_containers);
    } catch (e) {
      console.error('[LamaDB] Dozzle error:', e);
      var grid = document.getElementById('dozzle-container-grid');
      if (grid) grid.innerHTML = '<div style="color:var(--danger);padding:20px;">Failed to load containers: ' + window.escHtml(e.message) + '</div>';
    }
  };

  // ─── Container grid rendering ────────────────────────────────────────

  function renderContainerGrid(containers) {
    var grid = document.getElementById('dozzle-container-grid');
    if (!grid) return;
    if (!Array.isArray(containers) || containers.length === 0) {
      grid.innerHTML = '<div class="dc-empty">No containers found. Check Dozzle connection.</div>';
      return;
    }
    grid.innerHTML = containers.map(function(c) {
      var id = c.id || '';
      var name = c.name || id.slice(0, 12) || 'unknown';
      var image = c.image || '—';
      var state = c.state || 'unknown';
      var statusText = c.status || state;
      var statusClass = getStatusClass(state);
      var badgeClass = getStatusBadgeClass(state);
      return '<div class="dozzle-container-card dc-' + statusClass + '">' +
        '<div class="dc-name" title="' + window.escAttr(id) + '">' + window.escHtml(name) + '</div>' +
        '<div class="dc-image">' + window.escHtml(image) + '</div>' +
        '<div class="dc-meta">' +
          '<span class="sev-badge ' + badgeClass + '">' + window.escHtml(state) + '</span>' +
          '<span class="dc-status-text">' + window.escHtml(statusText) + '</span>' +
        '</div>' +
        '<div class="dc-actions">' +
          '<button class="btn btn-sm btn-primary" data-container-id="' + window.escAttr(id) + '">View Logs</button>' +
        '</div>' +
      '</div>';
    }).join('');

    // Attach click handlers for View Logs buttons
    grid.querySelectorAll('.dc-actions .btn-primary').forEach(function(btn) {
      btn.addEventListener('click', function() {
        var cid = btn.getAttribute('data-container-id');
        if (cid) window.showDozzleLogs(cid);
      });
    });
  }

  // ─── Show logs for a specific container ───────────────────────────────

  window.showDozzleLogs = async function(containerId) {
    _selectedContainerId = containerId;

    // Hide grid, show log view
    document.getElementById('dozzle-container-grid').style.display = 'none';
    document.getElementById('dozzle-filter-bar').style.display = '';
    var contentEl = document.getElementById('dozzle-content');
    contentEl.style.display = 'block';
    contentEl.innerHTML = '<p class="loading">Loading logs…</p>';

    populateContainerSelect(_containers, containerId);

    // Update container count label
    var countEl = document.getElementById('dozzle-container-count');
    if (countEl) countEl.textContent = '';

    await _loadDozzleLogs();
  };

  // ─── Internal: re-fetch logs for selected container ──────────────────

  async function _loadDozzleLogs() {
    if (!_selectedContainerId) return;

    var level = getActiveLevel();
    var since = getActiveSince();
    // Pass empty level string when 'all' so backend skips level filtering
    var levelParam = level === 'all' ? '' : level;
    var url = '/api/dozzle/logs?container_id=' + encodeURIComponent(_selectedContainerId)
            + '&level=' + encodeURIComponent(levelParam)
            + '&since=' + encodeURIComponent(since)
            + '&limit=50';

    try {
      var result = await window.api(url);
      renderDozzleLogs(result.logs || []);
      updateContainerCount(result.count || 0);
    } catch (e) {
      console.error('[LamaDB] Dozzle log error:', e);
      var container = document.getElementById('dozzle-content');
      if (container) container.innerHTML = '<div style="color:var(--danger);padding:20px;">Failed to load logs: ' + window.escHtml(e.message) + '</div>';
    }
  }

  // ─── Back to container grid ───────────────────────────────────────────

  window.showDozzleContainers = function() {
    document.getElementById('dozzle-container-grid').style.display = 'block';
    document.getElementById('dozzle-filter-bar').style.display = 'none';
    document.getElementById('dozzle-content').style.display = 'none';
    _selectedContainerId = null;
  };

  // ─── Container selector ───────────────────────────────────────────────

  function populateContainerSelect(containers, selectedId) {
    var sel = document.getElementById('dozzle-container-select');
    if (!sel) return;
    if (!Array.isArray(containers) || containers.length === 0) {
      sel.innerHTML = '<option value="">No containers</option>';
      return;
    }
    sel.innerHTML = containers.map(function(c) {
      var id = c.id || '';
      var name = c.name || c.id || 'unknown';
      var selected = id === selectedId ? ' selected' : '';
      return '<option value="' + window.escAttr(id) + '"' + selected + '>' + window.escHtml(name) + '</option>';
    }).join('');
  }

  window.setDozzleContainer = function(containerId) {
    if (containerId && containerId !== 'all' && containerId !== '') {
      _selectedContainerId = containerId;
      _loadDozzleLogs();
    }
  };

  // ─── Log rendering ────────────────────────────────────────────────────

  function renderDozzleLogs(logs) {
    var container = document.getElementById('dozzle-content');
    if (!container) return;
    if (!logs || logs.length === 0) {
      container.innerHTML = '<div style="color:var(--muted);text-align:center;padding:30px;">No log entries found for the selected filter.</div>';
      return;
    }
    container.innerHTML = logs.map(function(l) {
      var ts = l.timestamp || l.time || '';
      var msg = l.message || '';
      var cname = l.container_name || _selectedContainerId || '';
      var levelClass = getLogLevelClass(l.level);
      // Format timestamp to show time portion only
      var timeStr = '';
      if (ts) {
        // If ISO string, take HH:MM:SS
        if (ts.indexOf('T') > 0) {
          timeStr = ts.substring(11, 19);
        } else if (ts.length >= 8) {
          timeStr = ts;
        } else {
          timeStr = ts;
        }
      }
      return '<div style="font-family:var(--font-mono);font-size:12px;padding:3px 8px;border-bottom:1px solid var(--border-light);display:flex;gap:8px;align-items:flex-start;">' +
        '<span class="sev-dot sev-' + levelClass + '" style="margin-top:5px;"></span>' +
        '<span style="color:var(--muted);white-space:nowrap;flex-shrink:0;">' + window.escHtml(timeStr) + '</span>' +
        '<span style="color:var(--accent-cyan);white-space:nowrap;flex-shrink:0;">' + window.escHtml(cname) + '</span>' +
        '<span style="color:var(--fg-2);word-break:break-word;">' + window.escHtml(msg) + '</span>' +
      '</div>';
    }).join('');
  }

  // ─── Status helpers ───────────────────────────────────────────────────

  function updateContainerCount(count) {
    var el = document.getElementById('dozzle-container-count');
    if (el) el.textContent = count + ' entries';
  }

  // ─── Filter handlers (reuse existing HTML buttons) ────────────────────

  window.setDozzleLevel = function(level) {
    document.querySelectorAll('#page-dozzle .filter-bar [id^="dozzle-level-"]').forEach(function(b) {
      b.classList.toggle('active', b.id === 'dozzle-level-' + level);
    });
    _loadDozzleLogs();
  };

  window.setDozzleSince = function(since) {
    document.querySelectorAll('#page-dozzle .filter-bar [id^="dozzle-since-"]').forEach(function(b) {
      b.classList.toggle('active', b.id === 'dozzle-since-' + since);
    });
    _loadDozzleLogs();
  };

  window.syncDozzle = function() {
    // Force re-fetch of containers and go back to grid
    _containers = [];
    _selectedContainerId = null;
    window.loadDozzlePage();
  };
})();
