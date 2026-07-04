function safeShowError(msg) {
  if (window.LlamaApp && window.LlamaApp.showError) {
    window.LlamaApp.showError(msg);
  } else {
    console.error('[LamaDB]', msg);
  }
}

function bucketNotifications(groups) {
  var now = Date.now();
  var buckets = { today: [], yesterday: [], week: [], older: [] };
  (groups || []).forEach(function(g) {
    var t = new Date(g.last_seen || g.first_seen).getTime();
    var d = now - t;
    if (d < 86400000) buckets.today.push(g);
    else if (d < 172800000) buckets.yesterday.push(g);
    else if (d < 604800000) buckets.week.push(g);
    else buckets.older.push(g);
  });
  return buckets;
}
window.bucketNotifications = bucketNotifications;

var _selectedNotificationIds = [];

window.openNotificationDetail = function(group) {
  _selectedNotificationIds = group.event_ids || [];
  var titleEl = document.getElementById('notification-detail-title');
  var metaEl = document.getElementById('notification-detail-meta');
  var bodyEl = document.getElementById('notification-detail-body');
  var idsEl = document.getElementById('notification-detail-ids');
  if (!titleEl) return;
  titleEl.textContent = group.title || 'Alert';
  if (metaEl) metaEl.textContent = (group.source || '') + ' \u00b7 ' + (group.type || '') + ' \u00b7 ' + (group.severity || 'info');
  if (bodyEl) bodyEl.textContent = group.body || '';
  if (idsEl) idsEl.textContent = _selectedNotificationIds.join(', ');
  document.getElementById('notification-detail-modal').style.display = 'flex';
};

window.closeNotificationDetail = function() {
  document.getElementById('notification-detail-modal').style.display = 'none';
  _selectedNotificationIds = [];
};

window.dismissSelectedNotifications = async function() {
  if (!_selectedNotificationIds.length) return;
  try {
    await window.api('/api/events/bulk-dismiss', {
      method: 'POST',
      body: JSON.stringify({ event_ids: _selectedNotificationIds })
    });
    window.closeNotificationDetail();
    if (window.loadNotifications) window.loadNotifications();
  } catch (e) {
    safeShowError('Failed to dismiss alerts');
  }
};

document.addEventListener('alpine:init', function() {
  Alpine.data('notificationsPage', function() {
    return {
      loading: true,
      groups: [],
      filterSeverity: '',
      filterSource: '',
      showProcessed: false,
      sources: [],

      async init() {
        if (window.LlamaApp && window.LlamaApp.getApiKey && window.LlamaApp.getApiKey()) {
          await this.load();
        }
        var self = this;
        window.addEventListener('lamadb:authenticated', function() {
          self.load();
        }, { once: true });
      },

      async load() {
        this.loading = true;
        try {
          if (this.showProcessed) {
            var events = await window.api('/api/events?limit=100');
            this.groups = (events || []).map(function(e) {
              return {
                key: e.id,
                title: e.title,
                source: e.source,
                severity: e.severity,
                count: 1,
                first_seen: e.ts,
                last_seen: e.ts,
                event_ids: [e.id]
              };
            });
          } else {
            var resp = await window.api('/api/notifications/unread?aggregate=true');
            this.groups = resp.items || resp || [];
          }

          var sourceSet = {};
          this.groups.forEach(function(g) { sourceSet[g.source] = true; });
          this.sources = Object.keys(sourceSet).sort();
        } catch (e) {
          safeShowError('Failed to load notifications');
        } finally {
          this.loading = false;
        }
      },

      filteredGroups() {
        var self = this;
        return this.groups.filter(function(g) {
          if (self.filterSeverity && g.severity !== self.filterSeverity) return false;
          if (self.filterSource && g.source !== self.filterSource) return false;
          return true;
        }).sort(function(a, b) {
          var sevOrder = { critical: 0, error: 1, warning: 2, warn: 2, info: 3 };
          var sa = sevOrder[a.severity] || 99;
          var sb = sevOrder[b.severity] || 99;
          if (sa !== sb) return sa - sb;
          return new Date(b.last_seen) - new Date(a.last_seen);
        });
      },

      sections() {
        var buckets = bucketNotifications(this.filteredGroups());
        var labels = { today: 'Today', yesterday: 'Yesterday', week: 'This week', older: 'Older' };
        var result = [];
        ['today', 'yesterday', 'week', 'older'].forEach(function(key) {
          if (buckets[key].length) {
            result.push({ label: labels[key], items: buckets[key] });
          }
        });
        return result;
      },

      severityLedClass(sev) {
        if (sev === 'critical' || sev === 'error') return 'error';
        if (sev === 'warning' || sev === 'warn') return 'warn';
        return 'on';
      },

      openDetail(group) {
        window.openNotificationDetail(group);
      },

      async dismissGroup(group, event) {
        if (event) event.stopPropagation();
        try {
          await window.api('/api/events/bulk-dismiss', {
            method: 'POST',
            body: JSON.stringify({ event_ids: group.event_ids })
          });
          this.groups = this.groups.filter(function(g) { return g !== group; });
        } catch (e) {
          safeShowError('Failed to dismiss notification group');
        }
      },

      groupIcon(source) {
        var map = {
          'uptime_kuma': '📡',
          'dozzle': '🐳',
          'hermes': '🧠',
          'ntfy': '🔔',
          'freshrss': '📰'
        };
        return map[source] || '📎';
      },

      formatTime(ts) {
        var d = new Date(ts);
        return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
      }
    };
  });
});

// Legacy notification rules management (preserved during redesign)
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
