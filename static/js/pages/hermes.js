// Page: Hermes AI
(function() {
  'use strict';

  window.loadHermesPage = async function() {
    loadHermesHealth();
    try {
      var sysData = await window.api('/api/hermes/system');
      renderHermesSystem(sysData);
    } catch (e) { document.getElementById('hermes-sys-cards') && (document.getElementById('hermes-sys-cards').innerHTML = '<div style="color:var(--danger);padding:10px;">Failed: ' + e.message + '</div>'); }
    try {
      var stats = await window.api('/api/hermes/sessions/stats');
      renderHermesStats(stats);
    } catch (e) {}
    try {
      var sessions = await window.api('/api/hermes/sessions');
      renderHermesSessions(sessions);
    } catch (e) {}
  };

  function renderHermesSystem(data) {
    var cards = document.getElementById('hermes-sys-cards');
    if (!cards) return;
    cards.innerHTML = '<div class="two-col">' +
      '<div class="stat-card"><span class="label">Version</span><span class="value" style="font-size:18px;">' + (data.version || '\u2014') + '</span></div>' +
      '<div class="stat-card"><span class="label">Uptime</span><span class="value" style="font-size:18px;">' + (data.uptime || '\u2014') + '</span></div>' +
      '<div class="stat-card"><span class="label">Host</span><span class="value" style="font-size:18px;">' + (data.hostname || '\u2014') + '</span></div>' +
      '<div class="stat-card"><span class="label">Platform</span><span class="value" style="font-size:18px;">' + (data.platform || '\u2014') + '</span></div>' +
    '</div>';
  }

  function renderHermesStats(stats) {
    var el = document.getElementById('hermes-stats');
    if (!el) return;
    el.innerHTML = '<div class="two-col">' +
      '<div class="stat-card"><span class="label">Total Sessions</span><span class="value">' + (stats.total || 0) + '</span></div>' +
      '<div class="stat-card"><span class="label">Active Today</span><span class="value">' + (stats.today || 0) + '</span></div>' +
      '<div class="stat-card"><span class="label">Total Tokens</span><span class="value">' + (stats.total_tokens || 0).toLocaleString() + '</span></div>' +
      '<div class="stat-card"><span class="label">Avg Cost/Session</span><span class="value" style="font-size:20px;">$' + (stats.avg_cost || '0.0000') + '</span></div>' +
    '</div>';
  }

  function renderHermesSessions(sessions) {
    var tbody = document.getElementById('hermes-sessions-tbody');
    if (!tbody) return;
    if (!sessions || sessions.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" style="color:var(--muted);text-align:center;padding:20px;">No sessions found</td></tr>';
      return;
    }
    tbody.innerHTML = sessions.map(function(s) {
      var ts = s.created_at ? window.relativeTime(s.created_at) : '';
      var cost = s.total_cost ? '$' + parseFloat(s.total_cost).toFixed(4) : '\u2014';
      var tokens = s.total_tokens ? s.total_tokens.toLocaleString() : '\u2014';
      return '<tr>' +
        '<td class="mono" style="font-size:12px;">' + (s.id ? s.id.substring(0, 8) : '') + '</td>' +
        '<td>' + (s.model || '\u2014') + '</td>' +
        '<td class="mono">' + tokens + '</td>' +
        '<td class="mono">' + cost + '</td>' +
        '<td class="mono" style="font-size:12px;">' + ts + '</td>' +
      '</tr>';
    }).join('');
  }

  async function loadHermesHealth() {
    var badge = document.getElementById('hermes-health-badge');
    if (!badge) return;
    try {
      var health = await window.api('/api/hermes/health');
      var status = health.status || 'unknown';
      badge.innerHTML = '<span class="sev-badge ' + (status === 'healthy' ? 'info' : 'critical') + '">' + status + '</span>';
    } catch (e) {
      badge.innerHTML = '<span class="sev-badge critical">unreachable</span>';
    }
  }
})();
