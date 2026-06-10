// Page: Notflix
(function() {
  'use strict';

  window.loadNotflixPage = async function() {
    try {
      var results = await Promise.all([
        window.api('/api/notflix/health'),
        window.api('/api/notflix/activity?limit=20'),
        window.api('/api/notflix/status')
      ]);
      renderNotflixHealth(results[0]);
      renderNotflixActivity(results[1]);
      renderNotflixSnapshot(results[2]);

      var statusEl = document.getElementById('notflix-status');
      if (statusEl) statusEl.textContent = 'Updated ' + new Date().toLocaleTimeString();
    } catch (e) {
      var statsEl = document.getElementById('notflix-stats');
      if (statsEl) statsEl.innerHTML = '<div style="color:var(--danger);padding:10px;">Failed: ' + e.message + '</div>';
    }
  };

  // ─── Service Health Cards ─────────────────────────────────────────────

  function renderNotflixHealth(health) {
    var el = document.getElementById('notflix-stats');
    if (!el) return;
    if (!health || typeof health !== 'object') {
      el.innerHTML = '<div style="color:var(--muted);padding:10px;">No health data</div>';
      return;
    }

    el.innerHTML = Object.keys(health).map(function(service) {
      var info = health[service] || {};
      var reachable = info.reachable === true;
      var dotClass = reachable ? 'sev-info' : 'sev-critical';
      var statusText = reachable ? 'Reachable' : 'Unreachable';
      var reason = info.reason ? '<span style="font-size:11px;color:var(--muted);display:block;margin-top:2px;">' + window.escHtml(info.reason) + '</span>' : '';
      return '<div class="stat-card">' +
        '<div class="label" style="display:flex;align-items:center;gap:6px;">' +
          '<span class="sev-dot ' + dotClass + '" style="margin:0;"></span>' +
          window.escHtml(service.charAt(0).toUpperCase() + service.slice(1)) +
        '</div>' +
        '<div class="value" style="font-size:14px;font-weight:500;">' + window.escHtml(statusText) + '</div>' +
        reason +
      '</div>';
    }).join('');
  }

  // ─── Recent Activity Table ────────────────────────────────────────────

  function renderNotflixActivity(response) {
    var tbody = document.getElementById('notflix-tbody');
    if (!tbody) return;

    var events = response && Array.isArray(response.events) ? response.events : [];
    if (events.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" style="color:var(--muted);text-align:center;padding:20px;">No recent activity</td></tr>';
      return;
    }

    tbody.innerHTML = events.map(function(ev) {
      var ts = ev.ts || '';
      var timeStr = ts ? window.relativeTime(ts) : '';
      var source = ev.source || '';
      var title = ev.title || ev.type || '';
      var body = ev.body || '';

      // Pick a badge color per source
      var sourceColors = {sonarr: '--accent-cyan', radarr: '--accent', tautulli: '--info', notflix: '--warn'};
      var colorVar = sourceColors[source] || '--muted';

      return '<tr>' +
        '<td class="mono" style="font-size:12px;">' + timeStr + '</td>' +
        '<td><span class="source-badge" style="background:var(' + colorVar + ');color:#000;">' + window.escHtml(source) + '</span></td>' +
        '<td style="font-weight:500;color:var(--fg);">' + window.escHtml(title) + '</td>' +
        '<td style="font-size:12px;color:var(--fg-2);">' + window.escHtml(body) + '</td>' +
      '</tr>';
    }).join('');
  }

  // ─── Library Snapshot ─────────────────────────────────────────────────

  function renderNotflixSnapshot(status) {
    var el = document.getElementById('notflix-snapshot');
    if (!el) return;
    if (!status || status.status === 'no_data' || !status.data) {
      el.innerHTML = '<div style="color:var(--muted);padding:10px;">No library snapshot available yet.</div>';
      return;
    }

    var data = status.data;
    var ts = status.ts ? window.relativeTime(status.ts) : '';
    var items = '';

    // Render each key-value from the snapshot as stat cards
    Object.keys(data).forEach(function(key) {
      var val = data[key];
      if (val === null || val === undefined) return;
      items += '<div class="stat-card">' +
        '<div class="label">' + window.escHtml(key.replace(/_/g, ' ')) + '</div>' +
        '<div class="value" style="font-size:18px;">' + window.escHtml(String(val)) + '</div>' +
      '</div>';
    });

    if (!items) {
      el.innerHTML = '<div style="color:var(--muted);padding:10px;">Snapshot has no data.</div>';
      return;
    }

    el.innerHTML = '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">' +
      '<span style="font-size:12px;color:var(--muted);">Last snapshot: ' + ts + '</span>' +
    '</div>' +
    '<div class="stat-grid" style="grid-template-columns:repeat(auto-fit,minmax(160px,1fr));">' +
      items +
    '</div>';
  }
})();
