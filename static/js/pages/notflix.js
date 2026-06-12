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
      console.error('[LamaDB] Notflix error:', e);
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

    // Handle both {data: {sonarr: ...}} and {sonarr: ...} shapes
    var data = status.data || status;
    var ts = status.ts ? window.relativeTime(status.ts) : '';
    var html = '';

    // Timestamp header
    html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;">' +
      '<span style="font-size:12px;color:var(--muted);">Last snapshot: ' + ts + '</span>' +
    '</div>';

    // ── Sonarr ──
    if (data.sonarr) {
      var s = data.sonarr;
      html += '<h4 style="margin:0 0 8px;font-size:14px;color:var(--accent-cyan);">Sonarr</h4>' +
        '<div class="stat-grid" style="grid-template-columns:repeat(auto-fit,minmax(140px,1fr));margin-bottom:16px;">' +
          _statCard('Series', s.series_count) +
          _statCard('Episodes Available', s.episodes_available) +
          _statCard('Missing', s.missing_count, true) +
          _statCard('Queue', s.queue_count) +
          _statCard('Recent Grabs', s.recent_grabs) +
          _statCard('Total Episodes', s.total_episodes) +
        '</div>';
    }

    // ── Radarr ──
    if (data.radarr) {
      var r = data.radarr;
      html += '<h4 style="margin:0 0 8px;font-size:14px;color:var(--accent);">Radarr</h4>' +
        '<div class="stat-grid" style="grid-template-columns:repeat(auto-fit,minmax(140px,1fr));margin-bottom:16px;">' +
          _statCard('Movies', r.movie_count) +
          _statCard('Available', r.movies_available) +
          _statCard('Missing', r.missing_count, true) +
          _statCard('Queue', r.queue_count) +
          _statCard('Recent Grabs', r.recent_grabs) +
        '</div>';
    }

    // ── Tautulli ──
    if (data.tautulli) {
      var t = data.tautulli;
      var watchesHtml = '';
      if (t.recent_watches && t.recent_watches.length > 0) {
        var watches = t.recent_watches.slice(0, 5);
        watchesHtml = watches.map(function(w) {
          var watchTime = w.date ? window.relativeTime(new Date(w.date * 1000).toISOString()) : '';
          return '<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--border);font-size:12px;">' +
            '<span style="color:var(--fg);">' + window.escHtml(w.title || '?') + '</span>' +
            '<span style="color:var(--muted);white-space:nowrap;margin-left:8px;">' +
              window.escHtml(w.user || '') +
              (watchTime ? ' \u00b7 ' + watchTime : '') +
            '</span>' +
          '</div>';
        }).join('');
      } else {
        watchesHtml = '<div style="color:var(--muted);font-size:12px;padding:6px 0;">No recent watches</div>';
      }

      html += '<h4 style="margin:0 0 8px;font-size:14px;color:var(--info);">Tautulli</h4>' +
        '<div style="display:flex;gap:16px;margin-bottom:16px;flex-wrap:wrap;">' +
          '<div class="stat-card" style="min-width:120px;flex:0 0 auto;">' +
            '<div class="label">Active Streams</div>' +
            '<div class="value" style="font-size:24px;">' + _fmtNum(t.active_streams) + '</div>' +
          '</div>' +
          '<div style="flex:1;min-width:200px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:12px 14px;">' +
            '<div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:0.04em;font-weight:500;margin-bottom:4px;">Recent Watches</div>' +
            watchesHtml +
          '</div>' +
        '</div>';
    }

    if (!html) {
      el.innerHTML = '<div style="color:var(--muted);padding:10px;">Snapshot has no data.</div>';
      return;
    }

    el.innerHTML = html;
  }

  // ── Internal helper: stat card ──
  function _statCard(label, value, isWarning) {
    if (value === null || value === undefined) return '';
    var valClass = isWarning && value > 0 ? ' style="font-size:20px;color:var(--danger);"' : '';
    return '<div class="stat-card">' +
      '<div class="label">' + window.escHtml(label) + '</div>' +
      '<div class="value"' + valClass + '>' + _fmtNum(value) + '</div>' +
    '</div>';
  }

  function _fmtNum(n) {
    if (n === null || n === undefined) return '\u2014';
    return Number(n).toLocaleString();
  }
})();
