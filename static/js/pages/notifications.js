// Page: Notifications
(function() {
  'use strict';

  window.loadNotificationsPage = async function() {
    try {
      var rules = await window.api('/api/notifications/rules');
      renderNotificationRules(rules);
    } catch (e) {
      var el = document.getElementById('notif-rules-list');
      if (el) el.innerHTML = '<div style="color:var(--danger);padding:10px;">Failed: ' + e.message + '</div>';
    }
    try {
      var log = await window.api('/api/notifications/log?limit=50');
      renderNotificationLog(log);
    } catch (e) {}
  };

  function renderNotificationRules(rules) {
    var list = document.getElementById('notif-rules-list');
    if (!list) return;
    if (!rules || rules.length === 0) {
      list.innerHTML = '<div style="color:var(--muted);padding:20px;text-align:center;">No notification rules configured.</div>'; return;
    }
    list.innerHTML = rules.map(function(r) {
      var enabled = r.enabled ? 'checked' : '';
      return '<div class="module-card" data-rule-id="' + r.id + '">' +
        '<div class="module-card-info">' +
          '<h4>' + window.escHtml(r.name || 'Unnamed Rule') + '</h4>' +
          '<p>' + window.escHtml(r.description || r.condition || '') + '</p>' +
          '<div class="module-card-meta">Channel: ' + window.escHtml(r.channel || 'default') + ' \u00b7 Priority: ' + (r.priority || 'all') + '</div>' +
        '</div>' +
        '<label class="toggle">' +
          '<input type="checkbox" ' + enabled + ' onchange="toggleRule(\'' + r.id + '\', this.checked)" />' +
          '<span class="toggle-slider"></span>' +
        '</label>' +
      '</div>';
    }).join('');
  }

  function renderNotificationLog(log) {
    var el = document.getElementById('notif-log');
    if (!el) return;
    if (!log || log.length === 0) {
      el.innerHTML = '<div style="color:var(--muted);padding:10px;">No recent notification activity.</div>'; return;
    }
    el.innerHTML = log.map(function(entry) {
      var sevClass = entry.status === 'sent' ? 'info' : entry.status === 'failed' ? 'critical' : 'warn';
      var ts = entry.ts || entry.created_at;
      var timeStr = ts ? window.relativeTime(ts) : '';
      return '<div style="display:flex;gap:8px;padding:6px 0;border-bottom:1px solid var(--border-light);align-items:center;">' +
        '<span class="sev-badge ' + sevClass + '" style="font-size:10px;">' + (entry.status || entry.severity || 'info') + '</span>' +
        '<span style="flex:1;font-size:12px;color:var(--fg-2);">' + window.escHtml(entry.message || entry.title || '') + '</span>' +
        '<span style="font-size:11px;color:var(--muted);font-family:var(--font-mono);">' + timeStr + '</span>' +
      '</div>';
    }).join('');
  }

  window.toggleNewRuleForm = function() {
    var form = document.getElementById('notif-new-rule-form');
    if (form) form.style.display = form.style.display === 'none' ? 'block' : 'none';
  };

  window.submitNewRule = async function() {
    var name = document.getElementById('nf-name').value.trim();
    var desc = document.getElementById('nf-desc').value.trim();
    var channel = document.getElementById('nf-channel').value;
    var priority = document.getElementById('nf-priority').value;
    var condition = document.getElementById('nf-condition').value.trim();
    if (!name) { alert('Rule name is required'); return; }
    try {
      await window.api('/api/notifications/rules', {
        method: 'POST',
        body: JSON.stringify({ name: name, description: desc, channel: channel, priority: priority, condition: condition, enabled: true })
      });
      document.getElementById('nf-name').value = '';
      document.getElementById('nf-desc').value = '';
      document.getElementById('nf-condition').value = '';
      document.getElementById('notif-new-rule-form').style.display = 'none';
      window.loadNotificationsPage();
    } catch (e) { alert('Failed to create rule: ' + e.message); }
  };

  window.toggleRule = function(ruleId, enabled) {
    window.api('/api/notifications/rules/' + ruleId, {
      method: 'PATCH', body: JSON.stringify({ enabled: enabled })
    }).catch(function(e) { alert('Failed to toggle rule: ' + e.message); });
  };
})();
