// Page: Ntfy
(function() {
  'use strict';

  window.loadNtfyPage = async function() {
    try {
      var src = document.getElementById('ntfy-src-events').classList.contains('active') ? 'events' : 'live';
      var pri = 'all';
      document.querySelectorAll('#page-ntfy .filter-bar .sub-tab-btn[id^="ntfy-pri-"]').forEach(function(b) {
        if (b.classList.contains('active')) pri = b.id.replace('ntfy-pri-', '');
      });
      var since = '24h';
      document.querySelectorAll('#page-ntfy .filter-bar .sub-tab-btn[id^="ntfy-since-"]').forEach(function(b) {
        if (b.classList.contains('active')) since = b.id.replace('ntfy-since-', '');
      });
      var params = '?source=' + src + '&priority=' + pri + '&since=' + since;
      var messages = await window.api('/api/ntfy/messages' + params);
      renderNtfyMessages(messages, src === 'events');
    } catch (e) {
      var container = document.getElementById('ntfy-messages');
      if (container) container.innerHTML = '<div style="color:var(--danger);padding:20px;">Failed to load messages: ' + e.message + '</div>';
    }
  };

  function renderNtfyMessages(messages, showDetail) {
    var container = document.getElementById('ntfy-messages');
    if (!container) return;
    if (!messages || messages.length === 0) {
      container.innerHTML = '<div style="color:var(--muted);text-align:center;padding:30px;">No notifications found matching these filters.</div>';
      return;
    }
    container.innerHTML = messages.map(function(m) {
      var sev = m.severity || m.priority || 'info';
      var sevClass = sev === 'critical' || sev === '5' ? 'critical' : sev === 'warn' || sev === '4' ? 'warn' : 'info';
      var ts = m.ts || m.time || m.created_at;
      var timeStr = ts ? window.relativeTime(ts) : '';
      var body = m.body || m.message || '';
      var title = m.title || '';
      return '<div style="background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:12px 14px;margin-bottom:8px;">' +
        '<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">' +
          '<span class="sev-badge ' + sevClass + '" style="font-size:10px;">' + sev + '</span>' +
          '<span style="font-weight:600;font-size:13px;color:var(--fg);">' + window.escHtml(title) + '</span>' +
          '<span style="margin-left:auto;font-size:11px;color:var(--muted);font-family:var(--font-mono);">' + timeStr + '</span>' +
        '</div>' +
        (body ? '<div style="font-size:12px;color:var(--fg-2);line-height:1.5;">' + window.escHtml(body) + '</div>' : '') +
      '</div>';
    }).join('');
  }
})();
