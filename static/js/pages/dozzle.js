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

  // ─── Main page loader ─────────────────────────────────────────────────

  window.loadDozzlePage = async function() {
    try {
      // Step 1: Fetch containers (once)
      if (_containers.length === 0) {
        _containers = await window.api('/api/dozzle/containers');
        populateContainerSelect(_containers);
        // Auto-select the first container
        if (_containers.length > 0 && !_selectedContainerId) {
          _selectedContainerId = _containers[0].id;
          var sel = document.getElementById('dozzle-container-select');
          if (sel) sel.value = _selectedContainerId;
        }
      }

      // Step 2: Show prompt if no container selected
      var contentEl = document.getElementById('dozzle-content');
      if (!_selectedContainerId || _containers.length === 0) {
        if (contentEl) {
          contentEl.innerHTML = _containers.length === 0
            ? '<div style="color:var(--muted);text-align:center;padding:30px;">No containers found. Check Dozzle connection.</div>'
            : '<div style="color:var(--muted);text-align:center;padding:30px;">Select a container to view logs.</div>';
        }
        updateContainerCount(0);
        return;
      }

      // Defensive guard: do not fetch logs without a selected container_id
      if (!_selectedContainerId) {
        var contentElGuard = document.getElementById('dozzle-content');
        if (contentElGuard) {
          contentElGuard.innerHTML = '<div style="color:var(--muted);text-align:center;padding:30px;">Select a container to view logs.</div>';
        }
        return;
      }

      // Step 3: Fetch logs for the selected container with current filters
      var level = getActiveLevel();
      var since = getActiveSince();
      // Pass empty level string when 'all' so backend skips level filtering
      var levelParam = level === 'all' ? '' : level;
      var url = '/api/dozzle/logs?container_id=' + encodeURIComponent(_selectedContainerId)
              + '&level=' + encodeURIComponent(levelParam)
              + '&since=' + encodeURIComponent(since)
              + '&limit=50';

      var result = await window.api(url);
      renderDozzleLogs(result.logs || []);
      updateContainerCount(result.count || 0);

    } catch (e) {
      var container = document.getElementById('dozzle-content');
      if (container) container.innerHTML = '<div style="color:var(--danger);padding:20px;">Failed to load logs: ' + window.escHtml(e.message) + '</div>';
    }
  };

  // ─── Container selector ───────────────────────────────────────────────

  function populateContainerSelect(containers) {
    var sel = document.getElementById('dozzle-container-select');
    if (!sel) return;
    if (!Array.isArray(containers) || containers.length === 0) {
      sel.innerHTML = '<option value="">No containers</option>';
      return;
    }
    sel.innerHTML = containers.map(function(c) {
      var id = c.id || '';
      var name = c.name || c.id || 'unknown';
      return '<option value="' + window.escAttr(id) + '">' + window.escHtml(name) + '</option>';
    }).join('');
  }

  window.setDozzleContainer = function(containerId) {
    _selectedContainerId = containerId || null;
    window.loadDozzlePage();
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
    window.loadDozzlePage();
  };

  window.setDozzleSince = function(since) {
    document.querySelectorAll('#page-dozzle .filter-bar [id^="dozzle-since-"]').forEach(function(b) {
      b.classList.toggle('active', b.id === 'dozzle-since-' + since);
    });
    window.loadDozzlePage();
  };

  window.syncDozzle = function() {
    // Force re-fetch of containers
    _containers = [];
    _selectedContainerId = null;
    window.loadDozzlePage();
  };
})();
