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

  /**
   * Group similar events by source + title within 1-hour windows.
   * Events sorted newest-first; only the latest per group is shown.
   * Repeated events get a count badge in the title, e.g. "Severance added (×3)".
   */
  function consolidateActivity(events) {
    if (!events || events.length === 0) return [];

    var groups = [];
    var currentGroup = null;

    events.forEach(function(ev) {
      var key = ev.source + '::' + (ev.title || ev.type || '');

      if (currentGroup && currentGroup.key === key) {
        var anchorTs = new Date(currentGroup.events[0].ts).getTime();
        var evTs = new Date(ev.ts).getTime();
        var hourMs = 3600000;

        if (Math.abs(anchorTs - evTs) <= hourMs) {
          currentGroup.events.push(ev);
          currentGroup.count++;
          return;
        }
      }

      var newGroup = { key: key, events: [ev], count: 1 };
      groups.push(newGroup);
      currentGroup = newGroup;
    });

    // Return latest event per group with count appended to title
    return groups.map(function(g) {
      var latest = g.events[0];
      var titleDisplay = latest.title || latest.type || '';
      if (g.count > 1) {
        titleDisplay += ' (\u00d7' + g.count + ')';
      }
      return {
        source: latest.source,
        title: titleDisplay,
        type: latest.type,
        body: latest.body,
        metadata: latest.metadata,
        ts: latest.ts,
      };
    });
  }

  /**
   * Format the detail column as readable key:value pairs.
   * Tries JSON.parse on string body, then renders as rows.
   */
  function formatDetail(ev) {
    // Special-formatted snapshot summary
    if (ev.type === 'media_snapshot' && ev.metadata && typeof ev.metadata === 'object') {
      var parts = [];
      if (ev.metadata.sonarr) parts.push('Sonarr: ' + (ev.metadata.sonarr.series_count || 0) + ' series');
      if (ev.metadata.radarr) parts.push('Radarr: ' + (ev.metadata.radarr.movie_count || 0) + ' movies');
      if (ev.metadata.tautulli) parts.push('Tautulli: ' + (ev.metadata.tautulli.active_streams || 0) + ' streams');
      return parts.join(' \u00b7 ') || '\u2014';
    }

    // Try to parse body as JSON and render key:value rows
    var detail = ev.body;
    if (typeof detail === 'string') {
      try { detail = JSON.parse(detail); } catch (e) { /* not JSON, use raw */ }
    }
    if (typeof detail === 'object' && detail !== null) {
      return Object.keys(detail).map(function(k) {
        var v = detail[k];
        var val = (typeof v === 'object' && v !== null) ? JSON.stringify(v) : String(v);
        return window.escHtml(k) + ': ' + window.escHtml(val);
      }).join('<br>');
    }
    return detail ? window.escHtml(detail) : '\u2014';
  }

  function renderNotflixActivity(response) {
    var tbody = document.getElementById('notflix-tbody');
    if (!tbody) return;

    var events = response && Array.isArray(response.events) ? response.events : [];
    if (events.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" style="color:var(--muted);text-align:center;padding:20px;">No recent activity</td></tr>';
      return;
    }

    // Consolidate repeated events
    events = consolidateActivity(events);

    tbody.innerHTML = events.map(function(ev) {
      var ts = ev.ts || '';
      var timeStr = ts ? window.relativeTime(ts) : '';
      var source = ev.source || '';

      // Pick a badge color per source
      var sourceColors = {sonarr: '--accent-cyan', radarr: '--accent', tautulli: '--info', notflix: '--warn'};
      var colorVar = sourceColors[source] || '--muted';

      var detailHtml = formatDetail(ev);

      return '<tr>' +
        '<td class="mono" style="font-size:12px;">' + timeStr + '</td>' +
        '<td><span class="source-badge" style="background:var(' + colorVar + ');color:#000;">' + window.escHtml(source) + '</span></td>' +
        '<td style="font-weight:500;color:var(--fg);">' + window.escHtml(ev.title) + '</td>' +
        '<td style="font-size:12px;color:var(--fg-2);max-width:300px;word-break:break-word;">' + detailHtml + '</td>' +
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
