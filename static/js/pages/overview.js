// Page: Overview — Life Console
(function() {
  'use strict';

  var POLL_INTERVALS = { health: 30000, modules: 60000, rss: 120000, agents: 60000 };

  // Tracked timers for cleanup on navigation
  var _timers = [];

  function _setPoll(fn, ms) {
    var id = setTimeout(fn, ms);
    _timers.push(id);
    return id;
  }

  window.stopOverviewPolling = function() {
    _timers.forEach(function(id) { clearTimeout(id); });
    _timers = [];
  };

  window.loadOverview = async function() {
    loadHealthBar();
    loadModuleCards();
    loadActivityFeed();
    loadRSSHeadlines();
    loadAgentStatus();

    if (window.updateFooter) window.updateFooter();

    // Initialize header LEDs with real data on page load
    if (window.updateHeader) window.updateHeader();

    // Fetch recent important events for the scrolling ticker
    loadTicker();
  };

  // ─── Ticker ────────────────────────────────────────────

  async function loadTicker() {
    try {
      // Fetch recent events — the ticker displays with severity-appropriate icons
      var events = await window.api('/api/events?limit=10');
      if (window.renderTicker && events && events.length > 0) {
        var items = events.map(function(e) {
          return {
            text: (e.source ? e.source + ': ' : '') + (e.title || e.body || ''),
            severity: e.severity,
            type: e.severity === 'critical' ? 'break' : e.severity
          };
        });
        window.renderTicker(items);
      }
    } catch (e) {
      // Ticker not essential — silently ignore failures
    }
  }

  // ─── Health Bar ───────────────────────────────────────────

  async function loadHealthBar() {
    try {
      var [overview, uptime] = await Promise.all([
        window.api('/api/dashboard/overview'),
        window.api('/api/uptime/status')
      ]);

      // Services
      if (uptime && uptime.length > 0) {
        var up = uptime.filter(function(m) { return m.status === 1; }).length;
        var down = uptime.length - up;
        var el = document.getElementById('hb-services');
        var dot = document.getElementById('hb-services-dot');
        if (el) el.textContent = up + '/' + uptime.length + ' up';
        if (dot) {
          dot.className = 'health-dot ' + (down > 0 ? 'health-dot-down' : 'health-dot-up');
        }
      }

      // Cache (graceful fallback — cache-stats uses query-param auth not available here)
      var el2 = document.getElementById('hb-cache');
      if (el2) el2.textContent = '--';

      // Documents
      var el3 = document.getElementById('hb-documents');
      if (el3 && overview.documents) {
        el3.textContent = (overview.documents.total || 0).toLocaleString();
      }

      // Events
      var el4 = document.getElementById('hb-events');
      if (el4 && overview.events) {
        el4.textContent = (overview.events.today || 0);
      }

      // Database
      var el5 = document.getElementById('hb-db');
      var dot5 = document.getElementById('hb-db-dot');
      if (el5) el5.textContent = 'connected';
      if (dot5) dot5.className = 'health-dot health-dot-up';
    } catch (e) {
      var bar = document.getElementById('health-bar');
      if (bar) bar.classList.add('health-bar-error');
    }

    _setPoll(loadHealthBar, POLL_INTERVALS.health);
  }

  // ─── Module Cards ─────────────────────────────────────────

  async function loadModuleCards() {
    var grid = document.getElementById('modules-grid');
    if (!grid) return;
    grid.innerHTML = '<div class="module-card skeleton">Loading modules...</div>';

    try {
      var health = await window.api('/api/dashboard/module-health');
      var modules = health.modules || [];
      var moduleOrder = await window.loadLayout();

      grid.innerHTML = '';

      // Sort modules to match saved layout order
      var orderedModules = [];
      moduleOrder.forEach(function(moduleName) {
        var m = modules.find(function(mod) { return mod.name === moduleName; });
        if (m) orderedModules.push(m);
      });
      // Add any modules not in the saved order
      modules.forEach(function(m) {
        if (!orderedModules.find(function(om) { return om.name === m.name; })) {
          orderedModules.push(m);
        }
      });

      orderedModules.forEach(function(m) {
        var statusClass = m.status === 'green' ? 'dot-up' :
          m.status === 'yellow' ? 'dot-warn' :
          m.status === 'red' ? 'dot-down' : 'dot-off';

        var freshness = m.last_event ? window.relativeTime(m.last_event) : 'never';
        var errorCount = (m.recent_errors || []).length;

        var card = document.createElement('div');
        card.className = 'module-card';
        card.setAttribute('data-widget-id', m.name);
        (function(moduleName) {
          var pageMap = {
            uptime: 'uptime', hermes: 'hermes', freshrss: 'freshrss',
            ntfy: 'ntfy', dozzle: 'dozzle', notflix: 'notflix',
            wiki: 'wiki', feeds: 'feeds', notifications: 'notifications',
            agent_board: 'agent_board'
          };
          var page = pageMap[moduleName];
          card.onclick = function() {
            if (page && window.navigateTo) window.navigateTo(page);
          };
        })(m.name);
        card.innerHTML =
          '<span class="status-dot-lg ' + statusClass + '"></span>' +
          '<div class="module-card-body">' +
            '<span class="module-card-name">' + (m.label || m.name) + '</span>' +
            '<span class="module-card-stats">' +
              (m.events ? m.events.toLocaleString() + ' events &middot; ' : '') +
              freshness +
            '</span>' +
          '</div>' +
          (errorCount > 0 ? '<span class="module-card-errors">' + errorCount + '</span>' : '');
        grid.appendChild(card);
      });

      var countEl = document.getElementById('modules-count');
      if (countEl) countEl.textContent = orderedModules.length + ' modules';

      // Initialize drag-and-drop
      if (window.initDragDrop) {
        window.initDragDrop(grid.querySelectorAll('.module-card'));
      }
    } catch (e) {
      console.error('Module cards load error:', e);
      grid.innerHTML = '<div class="module-card error">Unable to load module status</div>';
    }

    _setPoll(loadModuleCards, POLL_INTERVALS.modules);
  }

  // ─── Activity Feed ────────────────────────────────────────

  async function loadActivityFeed() {
    var feed = document.getElementById('activity-feed');
    if (!feed) return;

    try {
      var events = await window.api('/api/events?limit=20');
      if (!events || events.length === 0) {
        feed.innerHTML = '<div class="activity-line empty">No recent activity</div>';
        return;
      }

      feed.innerHTML = events.map(function(ev) {
        var sevClass = ev.severity === 'critical' ? 'critical' :
          ev.severity === 'warn' ? 'warn' : 'info';
        var time = ev.ts ? new Date(ev.ts).toLocaleTimeString('en-US', {
          hour: '2-digit', minute: '2-digit', hour12: false
        }) : '';
        var icon = ev.severity === 'critical' ? '\u2717' :
          ev.severity === 'warn' ? '\u26A0' : '\u2713';
        return '<div class="activity-line activity-' + sevClass + '">' +
          '<code>' + time + '</code> ' +
          '<span class="activity-icon">' + icon + '</span> ' +
          '<span class="activity-source">' + (ev.source || '') + '</span>: ' +
          '<span class="activity-title">' + (ev.title || '') + '</span>' +
        '</div>';
      }).join('');
    } catch (e) {
      feed.innerHTML = '<div class="activity-line error">Activity feed unavailable</div>';
    }

    // Refresh every 60s (SSE covers real-time, polling covers initial + missed)
    _setPoll(loadActivityFeed, 60000);
  }

  // ─── RSS Headlines ────────────────────────────────────────

  async function loadRSSHeadlines() {
    var list = document.getElementById('rss-list');
    if (!list) return;

    try {
      var data = await window.api('/api/freshrss/articles?limit=5');
      var articles = data.articles || data || [];
      if (!Array.isArray(articles) || articles.length === 0) {
        list.innerHTML = '<div class="rss-item empty">No unread articles</div>';
        return;
      }

      list.innerHTML = articles.slice(0, 5).map(function(a) {
        return '<div class="rss-item">' +
          '<span class="rss-source">' + (a.feed_title || a.source || 'RSS') + '</span>' +
          '<span class="rss-title">' + (a.title || 'Untitled') + '</span>' +
        '</div>';
      }).join('');
    } catch (e) {
      list.innerHTML = '<div class="rss-item error">RSS unavailable</div>';
    }

    _setPoll(loadRSSHeadlines, POLL_INTERVALS.rss);
  }

  // ─── Agent Status ─────────────────────────────────────────

  async function loadAgentStatus() {
    var list = document.getElementById('agent-list');
    if (!list) return;

    try {
      var [stats, inboxCount] = await Promise.all([
        window.api('/api/hermes/sessions/stats').catch(function() { return null; }),
        window.api('/api/agent_board/inbox/count?agent=all').catch(function() { return { count: 0 }; })
      ]);

      list.innerHTML = '';

      // Hermes
      var hermesItem = document.createElement('div');
      hermesItem.className = 'agent-item';
      var isOnline = stats && stats.total > 0;
      hermesItem.innerHTML =
        '<span class="status-dot-sm ' + (isOnline ? 'dot-up' : 'dot-off') + '"></span>' +
        '<span class="agent-name">Hermes</span>' +
        '<span class="agent-info">' + (isOnline ? (stats.total || 0) + ' sessions' : 'offline') + '</span>';
      list.appendChild(hermesItem);

      // Agent Board
      var boardItem = document.createElement('div');
      boardItem.className = 'agent-item';
      boardItem.innerHTML =
        '<span class="status-dot-sm dot-up"></span>' +
        '<span class="agent-name">Agent Board</span>' +
        '<span class="agent-info">' + (inboxCount.count || 0) + ' unread</span>';
      list.appendChild(boardItem);
    } catch (e) {
      list.innerHTML = '<div class="agent-item error">Agent API unreachable</div>';
    }

    _setPoll(loadAgentStatus, POLL_INTERVALS.agents);
  }

  // ─── Quick Capture ────────────────────────────────────────

  window.submitScratchpad = async function() {
    var input = document.getElementById('scratchpad-input');
    var btn = document.getElementById('scratchpad-save');
    if (!input || !input.value.trim()) return;

    btn.disabled = true;
    btn.textContent = 'Saving...';
    try {
      await window.api('/api/documents', {
        method: 'POST',
        body: JSON.stringify({
          title: input.value.trim().substring(0, 80),
          content: input.value.trim(),
          source_type: 'scratchpad',
          tags: ['scratchpad']
        })
      });
      input.value = '';
      if (window.showToast) window.showToast('Saved to scratchpad', 'success');
    } catch (e) {
      if (window.showToast) window.showToast('Failed to save', 'error');
    }
    btn.disabled = false;
    btn.textContent = 'Save';
  };
})();
