// Page: Ntfy — Topic Dashboard
(function() {
  'use strict';

  // ─── Severity helpers ──────────────────────────────────────────────────────
  var SEV_MAP = {
    'critical': { label: 'critical', cls: 'critical', order: 0 },
    '5':        { label: 'critical', cls: 'critical', order: 0 },
    'warn':     { label: 'warn',     cls: 'warn',     order: 1 },
    '4':        { label: 'warn',     cls: 'warn',     order: 1 },
    'info':     { label: 'info',     cls: 'info',     order: 2 },
    '3':        { label: 'info',     cls: 'info',     order: 2 },
  };

  function getSeverity(m) {
    var raw = m.severity || m.priority || 'info';
    return SEV_MAP[raw] || SEV_MAP['info'];
  }

  function highestSeverity(messages) {
    var best = SEV_MAP['info'];
    messages.forEach(function(m) {
      var s = getSeverity(m);
      if (s.order < best.order) best = s;
    });
    return best;
  }

  // ─── Timestamp extraction (robust: avoids falsy-0 pitfall) ─────────────────
  function getMessageTs(m) {
    if (m.ts != null) return m.ts;
    if (m.time != null) return m.time;
    if (m.created_at != null) return m.created_at;
    return null;
  }

  function latestTs(messages) {
    var max = 0;
    messages.forEach(function(m) {
      var t = getMessageTs(m);
      if (t && t > max) max = t;
    });
    return max;
  }

  // ─── Topic grouping ────────────────────────────────────────────────────────
  function groupByTopic(messages) {
    var groups = {};
    messages.forEach(function(m) {
      var topic = m.topic || 'notifications';
      if (!groups[topic]) groups[topic] = [];
      groups[topic].push(m);
    });
    // Sort topics by latest message ts (descending)
    var sorted = Object.keys(groups).map(function(topic) {
      return { topic: topic, messages: groups[topic], latestTs: latestTs(groups[topic]) };
    });
    sorted.sort(function(a, b) { return b.latestTs - a.latestTs; });
    return sorted;
  }

  // ─── Render a single message row ───────────────────────────────────────────
  function renderMessageRow(m) {
    var sev = getSeverity(m);
    var ts = getMessageTs(m);
    var timeStr = ts ? window.relativeTime(ts) : '';
    var body = m.body || m.message || '';
    var title = m.title || '(no title)';
    var tags = m.tags || [];
    return '<div class="ntfy-msg-row sev-' + sev.cls + '">' +
      '<span class="sev-badge ' + sev.cls + '">' + sev.label + '</span>' +
      '<span class="ntfy-msg-title">' + window.escHtml(title) + '</span>' +
      '<span class="ntfy-msg-time">' + timeStr + '</span>' +
      (body ? '<span class="ntfy-msg-body">' + window.escHtml(body) + '</span>' : '') +
      (tags.length ? '<span class="ntfy-msg-tags">' + tags.map(function(t) {
        return '<span class="tag-pill">' + window.escHtml(t) + '</span>';
      }).join('') + '</span>' : '') +
    '</div>';
  }

  // ─── Render topic card ─────────────────────────────────────────────────────
  function renderTopicCard(group) {
    var sev = highestSeverity(group.messages);
    var count = group.messages.length;
    var latest = latestTs(group.messages);
    var timeStr = latest ? window.relativeTime(latest) : '';

    // Take the most recent 5 messages for inline list
    var previews = group.messages.slice(0, 5);
    var hasMore = count > 5;

    return '<div class="ntfy-topic-card sev-' + sev.cls + '">' +
      '<div class="ntfy-topic-header">' +
        '<span class="ntfy-topic-name">' + window.escHtml(group.topic) + '</span>' +
        '<span class="ntfy-topic-count">' + count + (count === 1 ? ' notification' : ' notifications') + '</span>' +
        '<span class="ntfy-topic-latest">' + timeStr + '</span>' +
      '</div>' +
      '<div class="ntfy-topic-body">' +
        previews.map(renderMessageRow).join('') +
        (hasMore ? '<div class="ntfy-msg-more">+' + (count - 5) + ' more</div>' : '') +
      '</div>' +
    '</div>';
  }

  // ─── Fetch and render ──────────────────────────────────────────────────────
  window.loadNtfyPage = async function() {
    var container = document.getElementById('ntfy-content');
    if (!container) return;
    container.innerHTML = '<p class="loading">Loading\u2026</p>';

    try {
      var src = document.getElementById('ntfy-src-events').classList.contains('active') ? 'events' : 'live';
      var pri = 'all';
      document.querySelectorAll('#page-ntfy .filter-bar [id^="ntfy-pri-"]').forEach(function(b) {
        if (b.classList.contains('active')) pri = b.id.replace('ntfy-pri-', '');
      });
      var since = '24h';
      document.querySelectorAll('#page-ntfy .filter-bar [id^="ntfy-since-"]').forEach(function(b) {
        if (b.classList.contains('active')) since = b.id.replace('ntfy-since-', '');
      });
      var data;
      if (src === 'events') {
        data = await window.api('/api/ntfy/events?priority=' + pri + '&since=' + since);
      } else {
        data = await window.api('/api/ntfy/messages?since=' + since);
      }
      var messages = data.messages || data;
      renderTopicDashboard(messages, container);
    } catch (e) {
      container.innerHTML = '<div class="error-banner">Failed to load notifications: ' + window.escHtml(e.message) + '</div>';
    }
  };

  function renderTopicDashboard(messages, container) {
    if (!messages || messages.length === 0) {
      container.innerHTML = '<div class="ntfy-empty">No notifications found matching these filters.</div>';
      return;
    }

    var groups = groupByTopic(messages);
    var html = '<div class="ntfy-topic-grid">' +
      groups.map(renderTopicCard).join('') +
    '</div>';
    container.innerHTML = html;
  }

  // ─── Filter helpers ────────────────────────────────────────────────────────
  window.setNtfySource = function(src) {
    document.querySelectorAll('#page-ntfy .filter-bar [id^="ntfy-src-"]').forEach(function(b) {
      b.classList.toggle('active', b.id === 'ntfy-src-' + src);
    });
    window.loadNtfyPage();
  };

  window.setNtfyPriority = function(pri) {
    document.querySelectorAll('#page-ntfy .filter-bar [id^="ntfy-pri-"]').forEach(function(b) {
      b.classList.toggle('active', b.id === 'ntfy-pri-' + pri);
    });
    window.loadNtfyPage();
  };

  window.setNtfySince = function(since) {
    document.querySelectorAll('#page-ntfy .filter-bar [id^="ntfy-since-"]').forEach(function(b) {
      b.classList.toggle('active', b.id === 'ntfy-since-' + since);
    });
    window.loadNtfyPage();
  };

  window.toggleNtfyAutoRefresh = function() {
    // Placeholder — auto-refresh interval logic can be added later
  };

  window.syncNtfy = function() {
    window.loadNtfyPage();
  };
})();
