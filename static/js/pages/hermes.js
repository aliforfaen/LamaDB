// Page: Hermes AI
(function() {
  'use strict';

  window.loadHermesPage = async function() {
    loadHermesHealth();
    try {
      var results = await Promise.all([
        window.api('/api/hermes/system'),
        window.api('/api/hermes/sessions/stats'),
        window.api('/api/hermes/sessions')
      ]);
      renderHermesSystem(results[0]);
      renderHermesStats(results[1]);
      renderHermesSessions(results[2]);
    } catch (e) {
      console.error('[LamaDB] Hermes error:', e);
      var cards = document.getElementById('hermes-sys-cards');
      if (cards) cards.innerHTML = '<div style="color:var(--danger);padding:10px;">Failed: ' + e.message + '</div>';
    }
  };

  function formatUptime(seconds) {
    if (seconds == null) return '\u2014';
    var d = Math.floor(seconds / 86400);
    var h = Math.floor((seconds % 86400) / 3600);
    var m = Math.floor((seconds % 3600) / 60);
    if (d > 0) return d + 'd ' + h + 'h';
    if (h > 0) return h + 'h ' + m + 'm';
    return m + 'm';
  }

  // Detect the graceful-error response from routes.py ({"error": "Hermes unreachable"}).
  // Returns the error string when data is the error envelope, or null when data is real.
  function _extractError(data) {
    if (data && typeof data === 'object' && data.error && Object.keys(data).length <= 2) {
      return data.error;
    }
    return null;
  }

  function _unreachableHtml(message) {
    return '<div style="color:var(--muted);padding:14px;text-align:center;">' +
      '<div style="font-size:24px;margin-bottom:6px;">\u26a0</div>' +
      '<div>Hermes unreachable</div>' +
      '<div style="font-size:12px;margin-top:4px;">' + window.escHtml(message || '') + '</div>' +
      '</div>';
  }

  function renderHermesSystem(data) {
    var cards = document.getElementById('hermes-sys-cards');
    if (!cards) return;
    var err = _extractError(data);
    if (err) {
      cards.innerHTML = _unreachableHtml(err);
      return;
    }
    if (!data || typeof data !== 'object') {
      cards.innerHTML = _unreachableHtml('No data');
      return;
    }
    var memPct = data.memory ? data.memory.percent : data.memory_percent;
    var diskPct = data.disk ? data.disk.percent : data.disk_percent;
    cards.innerHTML = '<div class="two-col">' +
      '<div class="stat-card"><span class="label">Version</span><span class="value" style="font-size:18px;">' + (data.hermes_version || '\u2014') + '</span></div>' +
      '<div class="stat-card"><span class="label">Uptime</span><span class="value" style="font-size:18px;">' + formatUptime(data.uptime_seconds) + '</span></div>' +
      '<div class="stat-card"><span class="label">Host</span><span class="value" style="font-size:18px;">' + (data.hostname || '\u2014') + '</span></div>' +
      '<div class="stat-card"><span class="label">Platform</span><span class="value" style="font-size:18px;">' + (data.os || data.platform || '\u2014') + '</span></div>' +
      '<div class="stat-card"><span class="label">CPU</span><span class="value" style="font-size:18px;">' + (data.cpu_percent != null ? data.cpu_percent + '%' : '\u2014') + '</span></div>' +
      '<div class="stat-card"><span class="label">Memory</span><span class="value" style="font-size:18px;">' + (memPct != null ? memPct + '%' : '\u2014') + '</span></div>' +
      '<div class="stat-card"><span class="label">Disk</span><span class="value" style="font-size:18px;">' + (diskPct != null ? diskPct + '%' : '\u2014') + '</span></div>' +
    '</div>';
  }

  function renderHermesStats(stats) {
    var el = document.getElementById('hermes-stats');
    if (!el) return;
    if (!stats || typeof stats !== 'object' || _extractError(stats)) {
      el.innerHTML = '';
      return;
    }
    var html = '<div class="two-col">' +
      '<div class="stat-card"><span class="label">Total Sessions</span><span class="value">' + (stats.total || 0) + '</span></div>' +
      '<div class="stat-card"><span class="label">Messages</span><span class="value">' + ((stats.messages || 0).toLocaleString()) + '</span></div>';
    if (stats.by_source) {
      var sourceParts = Object.keys(stats.by_source).map(function(k) {
        return k + ': ' + stats.by_source[k];
      });
      html += '<div class="stat-card" style="grid-column:1/-1;"><span class="label">By Source</span><span class="value" style="font-size:14px;">' + sourceParts.join(' &middot; ') + '</span></div>';
    }
    html += '</div>';
    el.innerHTML = html;
  }

  function renderHermesSessions(raw) {
    var tbody = document.getElementById('hermes-sessions-tbody');
    if (!tbody) return;
    if (!raw || _extractError(raw)) {
      tbody.innerHTML = '<tr><td colspan="5" style="color:var(--muted);text-align:center;padding:20px;">Sessions unavailable \u2014 Hermes unreachable</td></tr>';
      return;
    }
    // sessions endpoint returns {sessions: [...], total, limit, offset} or a bare array
    var list = Array.isArray(raw) ? raw : (raw && raw.sessions) || [];
    if (list.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" style="color:var(--muted);text-align:center;padding:20px;">No sessions found</td></tr>';
      return;
    }
    tbody.innerHTML = list.map(function(s) {
      var ts = s.started_at ? window.relativeTime(new Date(s.started_at * 1000).toISOString()) : '';
      var cost = s.estimated_cost_usd != null ? '$' + parseFloat(s.estimated_cost_usd).toFixed(4) : '\u2014';
      var tokens = (s.input_tokens || 0) + (s.output_tokens || 0);
      var tokensStr = tokens ? tokens.toLocaleString() : '\u2014';
      return '<tr>' +
        '<td class="mono" style="font-size:12px;">' + (s.id ? s.id.substring(0, 8) : '') + '</td>' +
        '<td>' + (s.model || '\u2014') + '</td>' +
        '<td class="mono">' + tokensStr + '</td>' +
        '<td class="mono">' + cost + '</td>' +
        '<td class="mono" style="font-size:12px;">' + ts + '</td>' +
      '</tr>';
    }).join('');
  }

  // Tab switcher exported to window for onclick handlers
  window.switchHermesTab = function(tab) {
    var panels = ['overview', 'costs', 'health'];
    panels.forEach(function(p) {
      var el = document.getElementById('hermes-panel-' + p);
      if (el) el.style.display = p === tab ? '' : 'none';
      var btn = document.getElementById('hermes-tab-' + p);
      if (btn) btn.className = 'btn btn-sm' + (p === tab ? '' : ' btn-secondary');
    });
  };

  async function loadHermesHealth() {
    var badge = document.getElementById('hermes-health-badge');
    if (!badge) return;
    try {
      var health = await window.api('/api/hermes/health');
      if (health && health.reachable) {
        var versionTag = health.version ? ' <span style="color:var(--muted);font-size:11px;">v' + health.version + '</span>' : '';
        badge.innerHTML = '<span class="sev-badge info">healthy</span>' + versionTag;
      } else {
        badge.innerHTML = '<span class="sev-badge critical">unreachable</span>';
      }
    } catch (e) {
      console.error('[LamaDB] Hermes health error:', e);
      badge.innerHTML = '<span class="sev-badge critical">unreachable</span>';
    }
  }
})();

