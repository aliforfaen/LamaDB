// Page: Overview
(function() {
  'use strict';

  window.loadOverview = async function() {
    try {
      var data = await window.api('/api/dashboard/overview');
      var docCard = document.querySelector('[data-stat="documents"]');
      if (docCard) {
        docCard.querySelector('.value').textContent = (data.documents.total || 0).toLocaleString();
        docCard.querySelector('.change').textContent = '+' + (data.documents.today || 0) + ' today';
      }
      var feedCard = document.querySelector('[data-stat="feeds"]');
      if (feedCard) {
        feedCard.querySelector('.value').textContent = data.feeds.total || 0;
        feedCard.querySelector('.change').textContent = data.feeds.total > 0 ? 'All healthy' : 'No feeds';
      }
      var monCard = document.querySelector('[data-stat="monitors"]');
      if (monCard) {
        var up = data.monitors.up || 0;
        var down = data.monitors.down || 0;
        monCard.querySelector('.value').innerHTML = up + ' <span class="stat-divider">/</span> ' + (up + down);
        var change = monCard.querySelector('.change');
        change.textContent = down > 0 ? down + ' down' : 'All up';
        change.className = 'change ' + (down > 0 ? 'down' : 'up');
      }
      var evtCard = document.querySelector('[data-stat="events"]');
      if (evtCard) {
        evtCard.querySelector('.value').textContent = data.events.today || 0;
        var delta = data.events.delta_yesterday || 0;
        evtCard.querySelector('.change').textContent = (delta >= 0 ? '+' : '') + delta + ' from yesterday';
      }
    } catch (e) {}

    try {
      var events = await window.api('/api/events?limit=5');
      renderRecentEvents(events);
    } catch (e) {}

    try {
      var status = await window.api('/api/uptime/status');
      renderUptimeStatus(status);
    } catch (e) {}

    try {
      var feeds = await window.api('/api/feeds');
      renderActiveFeeds(feeds);
    } catch (e) {}

    if (window.updateFooter) window.updateFooter();
  };

  function renderRecentEvents(events) {
    var tbody = document.querySelector('#page-overview .col-card table tbody');
    if (!tbody || !events) return;
    if (events.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" style="color:var(--muted);text-align:center;padding:20px;">No recent events</td></tr>';
      return;
    }
    tbody.innerHTML = events.map(function(ev) {
      var sev = ev.severity || 'info';
      var sevClass = sev === 'critical' ? 'critical' : sev === 'warn' ? 'warn' : 'info';
      var ts = ev.ts ? new Date(ev.ts).toLocaleString('en-US', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).replace(',', '') : '';
      return '<tr>' +
        '<td class="mono nowrap">' + ts + '</td>' +
        '<td class="nowrap">' + (ev.source || '') + '</td>' +
        '<td><span class="sev-dot sev-' + sevClass + '"></span></td>' +
        '<td>' + (ev.title || '') + '</td>' +
      '</tr>';
    }).join('');
  }

  function renderUptimeStatus(status) {
    var container = document.querySelector('#page-overview .uptime-list');
    if (!container || !status) return;
    if (status.length === 0) {
      container.innerHTML = '<div style="color:var(--muted);padding:10px 0;">No monitors configured</div>';
      return;
    }
    container.innerHTML = status.slice(0, 8).map(function(m) {
      var cls = m.status === 1 ? 'status-up' : m.status === 0 ? 'status-down' : 'status-unknown';
      var ts = m.received_at ? new Date(m.received_at).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) : '';
      return '<div class="uptime-item">' +
        '<span class="status-dot-lg ' + cls + '"></span>' +
        '<span class="u-name">' + (m.monitor_name || m.monitor_id || '?') + '</span>' +
        '<span class="u-time">' + ts + '</span>' +
      '</div>';
    }).join('');
  }

  function renderActiveFeeds(feeds) {
    var strip = document.querySelector('#page-overview .feed-strip');
    if (!strip || !feeds) return;
    if (feeds.length === 0) {
      strip.innerHTML = '<div style="color:var(--muted);padding:10px;">No feeds configured</div>';
      return;
    }
    strip.innerHTML = feeds.slice(0, 6).map(function(f) {
      return '<div class="feed-card">' +
        '<span class="name">' + f.name + '</span>' +
        '<span class="slug">/feeds/' + f.slug + '</span>' +
        '<div class="meta">' +
          '<span class="num">' + (f.max_items || 0) + ' items</span>' +
        '</div>' +
      '</div>';
    }).join('');
  }
})();
