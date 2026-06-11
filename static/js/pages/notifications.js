// Page: Notifications
(function() {
  'use strict';

  window.loadNotificationsPage = async function() {
    try {
      var results = await Promise.all([
        window.api('/api/notifications/rules'),
        window.api('/api/notifications/log?limit=50')
      ]);
      renderNotificationRules(results[0]);
      renderNotificationLog(results[1]);
    } catch (e) {
      var rulesEl = document.getElementById('notif-rules-list');
      if (rulesEl) rulesEl.innerHTML = '<div style="color:var(--danger);padding:10px;">Failed: ' + window.escHtml(e.message) + '</div>';
      var logEl = document.getElementById('notif-log');
      if (logEl) logEl.innerHTML = '<div style="color:var(--muted);padding:10px;">Error loading log: ' + window.escHtml(e.message) + '</div>';
    }
  };

  function renderNotificationRules(rules) {
    var list = document.getElementById('notif-rules-list');
    if (!list) return;
    if (!Array.isArray(rules) || rules.length === 0) {
      list.innerHTML = '<div style="color:var(--muted);padding:20px;text-align:center;">No notification rules configured.</div>'; return;
    }
    list.innerHTML = rules.map(function(r) {
      var enabled = r.enabled ? 'checked' : '';
      return '<div class="module-card" data-rule-id="' + r.id + '">' +
        '<div class="module-card-info">' +
          '<h4>' + window.escHtml(r.name || 'Unnamed Rule') + '</h4>' +
          '<p>' + window.escHtml(r.description || r.match_source || '') + '</p>' +
          '<div class="module-card-meta">Channel: ' + window.escHtml(r.channel || 'default') + ' \u00b7 Priority: ' + (r.priority || 'all') + '</div>' +
        '</div>' +
        '<label class="toggle">' +
          '<input type="checkbox" ' + enabled + ' onchange="toggleRule(\'' + r.id + '\', this.checked)" />' +
          '<span class="toggle-slider"></span>' +
        '</label>' +
      '</div>';
    }).join('');
  }

  function renderNotificationLog(data) {
    var el = document.getElementById('notif-log');
    if (!el) return;
    // API returns {log: [...], count: N} — extract the inner array
    var log = Array.isArray(data) ? data : (data && data.log);
    if (!Array.isArray(log) || log.length === 0) {
      el.innerHTML = '<div style="color:var(--muted);padding:10px;">No recent notification activity.</div>'; return;
    }
    el.innerHTML = log.map(function(entry) {
      var sevClass = entry.status === 'sent' ? 'info' : entry.status === 'failed' ? 'critical' : 'warn';
      var ts = entry.fired_at || entry.ts || entry.created_at;
      var timeStr = ts ? window.relativeTime(ts) : '';
      return '<div style="display:flex;gap:8px;padding:6px 0;border-bottom:1px solid var(--border-light);align-items:center;">' +
        '<span class="sev-badge ' + sevClass + '" style="font-size:10px;">' + (entry.status || entry.severity || 'info') + '</span>' +
        '<span style="flex:1;font-size:12px;color:var(--fg-2);">' + window.escHtml(entry.message || entry.title || entry.rule_name || '') + '</span>' +
        '<span style="font-size:11px;color:var(--muted);font-family:var(--font-mono);">' + timeStr + '</span>' +
      '</div>';
    }).join('');
  }

  window.toggleNewRuleForm = function() {
    var form = document.getElementById('notif-rule-form');
    if (form) form.style.display = form.style.display === 'none' ? 'block' : 'none';
  };

  window.submitNewRule = async function() {
    var name = document.getElementById('nf-name').value.trim();
    var channel = document.getElementById('nf-channel').value;
    var priority = document.getElementById('nf-priority').value;
    var matchSource = document.getElementById('nf-match-source').value.trim() || null;
    var matchSeverity = document.getElementById('nf-match-severity').value || null;
    var matchTagsStr = document.getElementById('nf-match-tags').value.trim();
    var matchTags = matchTagsStr ? matchTagsStr.split(',').map(function(s) { return s.trim(); }).filter(Boolean) : [];
    var cooldown = parseInt(document.getElementById('nf-cooldown').value) || 0;
    var chatId = document.getElementById('nf-chat-id') ? document.getElementById('nf-chat-id').value.trim() : '';
    var webhookUrl = document.getElementById('nf-webhook-url') ? document.getElementById('nf-webhook-url').value.trim() : '';

    if (!name) { alert('Rule name is required'); return; }

    var channelConfig = {};
    if (channel === 'telegram' || channel === 'ntfy') {
      channelConfig.chat_id = chatId;
    } else if (channel === 'webhook') {
      channelConfig.url = webhookUrl;
    }

    try {
      await window.api('/api/notifications/rules', {
        method: 'POST',
        body: JSON.stringify({
          name: name,
          channel: channel,
          priority: priority,
          match_source: matchSource,
          match_severity: matchSeverity,
          match_tags: matchTags,
          cooldown_seconds: cooldown,
          channel_config: channelConfig,
          enabled: true
        })
      });
      document.getElementById('nf-name').value = '';
      document.getElementById('nf-match-source').value = '';
      document.getElementById('nf-match-tags').value = '';
      document.getElementById('nf-cooldown').value = '0';
      document.getElementById('notif-rule-form').style.display = 'none';
      window.loadNotificationsPage();
    } catch (e) { alert('Failed to create rule: ' + e.message); }
  };

  window.toggleRule = function(ruleId, enabled) {
    window.api('/api/notifications/rules/' + ruleId, {
      method: 'PATCH', body: JSON.stringify({ enabled: enabled })
    }).catch(function(e) { alert('Failed to toggle rule: ' + e.message); });
  };
})();
