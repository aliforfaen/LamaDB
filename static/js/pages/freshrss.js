// Page: FreshRSS
(function() {
  'use strict';

  window.loadFreshrssPage = async function() {
    var statusText = document.getElementById('freshrss-status-text');
    var cards = document.getElementById('freshrss-cards');
    var feeds = document.getElementById('freshrss-feeds');
    var articles = document.getElementById('freshrss-articles');
    try {
      var results = await Promise.all([
        window.api('/api/freshrss/status'),
        window.api('/api/freshrss/feeds')
      ]);
      var data = results[0];
      var feedList = results[1];
      if (statusText) statusText.textContent = data.status || 'Unknown';
      if (cards) {
        cards.innerHTML = '<div class="stat-grid" style="grid-template-columns:repeat(3,1fr);">' +
          '<div class="stat-card"><span class="label">Status</span><span class="value" style="font-size:18px;">' + (data.status || '\u2014') + '</span></div>' +
          '<div class="stat-card"><span class="label">Feeds</span><span class="value" style="font-size:18px;">' + (data.feeds || 0) + '</span></div>' +
          '<div class="stat-card"><span class="label">Articles</span><span class="value" style="font-size:18px;">' + (data.articles || 0) + '</span></div>' +
        '</div>';
      }
    } catch (e) {
      if (statusText) statusText.textContent = 'Error';
      if (cards) cards.innerHTML = '<div style="color:var(--danger);padding:10px;">Failed to load FreshRSS status: ' + e.message + '</div>';
    }
    if (feeds) {
      var feedRows = Array.isArray(feedList) ? feedList.map(function(f) {
        return '<tr>' +
          '<td>' + window.escHtml(f.title || f.name || '') + '</td>' +
          '<td>' + window.escHtml(f.category || '') + '</td>' +
          '<td class="mono">' + (f.articles || f.article_count || 0) + '</td>' +
          '<td class="mono" style="font-size:12px;">' + window.relativeTime(f.last_updated || f['last refreshed'] || '') + '</td>' +
        '</tr>';
      }).join('') : '';
      feeds.innerHTML = '<div class="table-wrap"><table><thead><tr><th>Feed</th><th>Category</th><th>Articles</th><th>Last Updated</th></tr></thead><tbody>' +
        feedRows +
      '</tbody></table></div>';
    }
  };

  // ─── Ticker ────────────────────────────────────────────────────────────────
  function renderTicker(items) {
    var track = document.getElementById('ticker-track');
    if (!track || !items || items.length === 0) {
      if (track) track.innerHTML = '<span class="ticker-item"><span class="ti-icon ti-ok">\u2713</span> All systems operational \u2014 no ticker items yet</span>';
      return;
    }
    var html = '';
    items.sort(function(a, b) { return a.break === b.break ? 0 : a.break ? -1 : 1; });
    items.forEach(function(item) {
      if (item.type === 'break' || item.break) {
        html += '<span class="ticker-item"><span class="ti-breaking-badge">BREAKING</span><span class="ti-icon ti-breaking">\u26a1</span> ' + item.text + '</span>';
      } else if (item.type === 'warn' || item.severity === 'warn') {
        html += '<span class="ticker-item"><span class="ti-icon ti-warn">\u26a0</span> ' + item.text + '</span>';
      } else if (item.type === 'err' || item.severity === 'critical' || item.severity === 'error') {
        html += '<span class="ticker-item"><span class="ti-icon ti-err">\u2717</span> ' + item.text + '</span>';
      } else {
        html += '<span class="ticker-item"><span class="ti-icon ti-ok">\u2713</span> ' + item.text + '</span>';
      }
    });
    track.innerHTML = html + html;
    track.style.animation = 'none';
    void track.offsetHeight;
    track.style.animation = '';
  }

  // ─── Header LED update ─────────────────────────────────────────────────────
  function updateHeader() {
    // Fetch overview data + events + monitors for header LEDs
    var upCount = 0, downCount = 0;
    window.api('/api/uptime/status').then(function(status) {
      upCount = (status || []).filter(function(m) { return m.status === 1; }).length;
      downCount = (status || []).filter(function(m) { return m.status === 0; }).length;
      var svcEl = document.getElementById('led-services');
      if (svcEl) {
        svcEl.innerHTML = upCount + '/' + (upCount + downCount);
        var dot = svcEl.closest('.header-led') ? svcEl.closest('.header-led').querySelector('.led-dot') : null;
        if (dot) { dot.className = 'led-dot ' + (downCount > 0 ? 'led-red' : 'led-green'); }
      }
    }).catch(function() {});
    window.api('/api/dashboard/overview').then(function(data) {
      var notifEl = document.getElementById('led-notifications');
      if (notifEl) notifEl.textContent = data.events.today || 0;
      var agentEl = document.getElementById('led-agents');
      if (agentEl) agentEl.textContent = (data.agent_tasks || 0) + ' pending';
    }).catch(function() {});
    window.api('/api/dozzle/stats').then(function(stats) {
      var dozzleEl = document.getElementById('led-dozzle');
      if (dozzleEl) dozzleEl.textContent = (stats.errors || 0) + ' err \u00b7 ' + (stats.warnings || 0) + ' warn';
    }).catch(function() {});
    // Uptime clock
    try {
      var start = document.querySelector('meta[name="app-start"]');
      if (start && start.content) {
        var uptimeMs = Date.now() - new Date(start.content).getTime();
        var days = Math.floor(uptimeMs / 86400000);
        var hours = Math.floor((uptimeMs % 86400000) / 3600000);
        var uptimeEl = document.getElementById('header-uptime');
        if (uptimeEl) uptimeEl.textContent = days + 'd ' + hours + 'h';
      }
    } catch(e) {}
  }

  window.updateFooter = async function() {
    try {
      var status = await window.api('/api/uptime/status');
      var up = (status || []).filter(function(m) { return m.status === 1; }).length;
      var down = (status || []).filter(function(m) { return m.status === 0; }).length;
      var footer = document.querySelector('.sidebar-footer');
      if (!footer) return;
      if (down > 0) {
        footer.innerHTML = '<div><span class="status-dot" style="background:var(--danger);"></span> ' + up + ' up \u00b7 ' + down + ' down</div><span>Self-hosted \u00b7 PostgreSQL \u00b7 FastAPI</span>';
        footer.classList.add('has-issues');
      } else {
        footer.innerHTML = '<div><span class="status-dot"></span>All systems operational</div><span>Self-hosted \u00b7 PostgreSQL \u00b7 FastAPI</span>';
        footer.classList.remove('has-issues');
      }
    } catch (e) {
      var footer = document.querySelector('.sidebar-footer');
      if (footer) {
        footer.innerHTML = '<div><span class="status-dot" style="background:var(--muted);"></span>Status unavailable</div><span>Self-hosted \u00b7 PostgreSQL \u00b7 FastAPI</span>';
        footer.classList.add('has-issues');
      }
    }
  };

  window.syncFreshrss = function() {
    var btn = document.getElementById('btn-sync-freshrss');
    if (btn) { btn.disabled = true; btn.textContent = 'Syncing\u2026'; }
    window.api('/api/freshrss/sync', { method: 'POST' }).then(function() {
      window.loadFreshrssPage();
      if (btn) { btn.disabled = false; btn.textContent = '\u21bb Sync Now'; }
    }).catch(function(e) {
      window.showToast('Sync failed: ' + e.message, null, null, 3000);
      if (btn) { btn.disabled = false; btn.textContent = '\u21bb Sync Now'; }
    });
  };

  // Export ticker and header LED updater so other modules (overview, SSE) can call them
  window.renderTicker = renderTicker;
  window.updateHeader = updateHeader;
})();
