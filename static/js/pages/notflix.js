// Page: Notflix
(function() {
  'use strict';

  window.loadNotflixPage = async function() {
    try {
      var results = await Promise.all([
        window.api('/api/notflix/status'),
        window.api('/api/notflix/activity?limit=30')
      ]);
      renderNotflixStats(results[0]);
      renderNotflixActivity(results[1]);
    } catch (e) {
      var statsEl = document.getElementById('notflix-stats');
      if (statsEl) statsEl.innerHTML = '<div style="color:var(--danger);padding:10px;">Failed: ' + e.message + '</div>';
    }
  };

  function renderNotflixStats(data) {
    var el = document.getElementById('notflix-stats');
    if (!el) return;
    el.innerHTML = '<div class="stat-grid" style="grid-template-columns:repeat(4,1fr);">' +
      '<div class="stat-card"><span class="label">Sonarr</span><span class="value" style="font-size:18px;">' + (data.sonarr_status || '\u2014') + '</span></div>' +
      '<div class="stat-card"><span class="label">Radarr</span><span class="value" style="font-size:18px;">' + (data.radarr_status || '\u2014') + '</span></div>' +
      '<div class="stat-card"><span class="label">Tautulli</span><span class="value" style="font-size:18px;">' + (data.tautulli_status || '\u2014') + '</span></div>' +
      '<div class="stat-card"><span class="label">Active Streams</span><span class="value" style="font-size:18px;">' + (data.active_streams || 0) + '</span></div>' +
    '</div>';
  }

  function renderNotflixActivity(events) {
    var tbody = document.getElementById('notflix-tbody');
    if (!tbody) return;
    if (!events || events.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" style="color:var(--muted);text-align:center;padding:20px;">No recent activity</td></tr>';
      return;
    }
    tbody.innerHTML = events.map(function(ev) {
      var ts = ev.ts || ev.timestamp || ev.created_at;
      var timeStr = ts ? window.relativeTime(ts) : '';
      var title = ev.title || ev.event || '';
      var source = ev.source || ev.service || '';
      var detail = ev.body || ev.detail || '';
      return '<tr>' +
        '<td class="mono" style="font-size:12px;">' + timeStr + '</td>' +
        '<td>' + window.escHtml(source) + '</td>' +
        '<td>' + window.escHtml(title) + '</td>' +
        '<td style="font-size:12px;color:var(--fg-2);">' + window.escHtml(detail) + '</td>' +
      '</tr>';
    }).join('');
  }
})();
