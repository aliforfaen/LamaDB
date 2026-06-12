// Page: FreshRSS
(function() {
  'use strict';

  window.loadFreshrssPage = async function() {
    var statusText = document.getElementById('freshrss-status-text');
    var cards = document.getElementById('freshrss-cards');
    var feeds = document.getElementById('freshrss-feeds');
    var articlesEl = document.getElementById('freshrss-articles');
    try {
      var results = await Promise.all([
        window.api('/api/freshrss/status'),
        window.api('/api/freshrss/feeds'),
        window.api('/api/freshrss/articles?limit=5')
      ]);
      var data = results[0];
      var feedList = results[1];
      var articlesData = results[2];
      var statusDisplay = data.configured ? (data.last_sync_title || 'Connected') : 'Disconnected';
      if (statusText) statusText.textContent = statusDisplay;
      if (cards) {
        cards.innerHTML = '<div class="stat-grid" style="grid-template-columns:repeat(3,1fr);">' +
          '<div class="stat-card"><span class="label">Status</span><span class="value" style="font-size:18px;">' + window.escHtml(statusDisplay) + '</span></div>' +
          '<div class="stat-card"><span class="label">Feeds</span><span class="value" style="font-size:18px;">' + (data.feeds_count || 0) + '</span></div>' +
          '<div class="stat-card"><span class="label">Articles</span><span class="value" style="font-size:18px;">' + (data.article_count || 0) + '</span></div>' +
        '</div>';
      }
      if (feeds) {
        var subs = feedList && feedList.subscriptions ? feedList.subscriptions : (Array.isArray(feedList) ? feedList : []);
        var feedRows = subs.map(function(f) {
          var cat = f.categories && f.categories.length ? f.categories[0].label : '';
          return '<tr>' +
            '<td>' + window.escHtml(f.title || '') + '</td>' +
            '<td>' + window.escHtml(cat) + '</td>' +
            '<td class="mono">\u2014</td>' +
            '<td class="mono" style="font-size:12px;">\u2014</td>' +
          '</tr>';
        }).join('');
        feeds.innerHTML = '<div class="table-wrap"><table><thead><tr><th>Feed</th><th>Category</th><th>Articles</th><th>Last Updated</th></tr></thead><tbody>' +
          (feedRows || '<tr><td colspan="4" style="color:var(--muted);text-align:center;padding:20px;">No feeds found</td></tr>') +
        '</tbody></table></div>';
      }
      if (articlesEl) {
        var articleRows = articlesData && articlesData.articles ? articlesData.articles.map(function(a) {
          return '<tr>' +
            '<td>' + window.escHtml(a.title || '') + '</td>' +
            '<td style="font-size:12px;color:var(--muted);">' + window.relativeTime(a.created_at || '') + '</td>' +
          '</tr>';
        }).join('') : '';
        articlesEl.innerHTML = '<div class="table-wrap"><table><thead><tr><th>Title</th><th>Synced</th></tr></thead><tbody>' +
          (articleRows || '<tr><td colspan="2" style="color:var(--muted);text-align:center;padding:20px;">No articles synced yet</td></tr>') +
        '</tbody></table></div>';
      }
    } catch (e) {
      console.error('[LamaDB] FreshRSS error:', e);
      if (statusText) statusText.textContent = 'Error';
      if (cards) cards.innerHTML = '<div style="color:var(--danger);padding:10px;">Failed to load FreshRSS status: ' + e.message + '</div>';
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
      console.error('[LamaDB] Sidebar status error:', e);
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
      console.error('[LamaDB] Freshrss sync error:', e);
      window.showToast('Sync failed: ' + e.message, null, null, 3000);
      if (btn) { btn.disabled = false; btn.textContent = '\u21bb Sync Now'; }
    });
  };

  // Export ticker so other modules (overview, SSE) can call it
  window.renderTicker = renderTicker;
})();
