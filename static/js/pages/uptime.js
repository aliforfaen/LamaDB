// Page: Uptime
(function() {
  'use strict';

  var _topologyLoaded = false;

  window.loadUptime = async function() {
    try {
      var status = await window.api('/api/uptime/status');
      renderMonitorGrid(status);
      updateSummaryBar(status);
    } catch (e) { window.showError('Failed to load uptime status: ' + e.message); }
    try {
      var history = await window.api('/api/uptime/history?limit=50');
      renderStatusHistory(history);
    } catch (e) {}
    try {
      var recentData = await window.api('/api/uptime/history/recent?limit=30');
      renderSparklines(recentData.monitors);
    } catch (e) {}
  };

  function updateSummaryBar(status) {
    var bar = document.querySelector('.summary-bar');
    if (!bar) return;
    var up = 0, down = 0, unknown = 0;
    (status || []).forEach(function(m) {
      if (m.status === 1) up++;
      else if (m.status === 0) down++;
      else unknown++;
    });
    bar.innerHTML =
      '<span class="stat"><span class="status-dot-lg status-up"></span><span class="num green">' + up + '</span> Up</span>' +
      '<span class="sep">\u00b7</span>' +
      '<span class="stat"><span class="status-dot-lg status-down"></span><span class="num red">' + down + '</span> Down</span>' +
      '<span class="sep">\u00b7</span>' +
      '<span class="stat"><span class="status-dot-lg status-unknown"></span><span class="num muted">' + unknown + '</span> Unknown</span>';
  }

  function renderMonitorGrid(status) {
    var grid = document.querySelector('#page-uptime .monitor-grid');
    if (!grid) return;
    if (!status || status.length === 0) {
      grid.innerHTML = '<div style="color:var(--muted);padding:20px;">No monitors configured. Send webhooks to /api/uptime/webhook</div>';
      return;
    }
    grid.innerHTML = status.map(function(m) {
      var cls = m.status === 1 ? 'up' : m.status === 0 ? 'down' : 'unknown';
      var statusLabel = m.status === 1 ? 'Operational' : m.status === 0 ? 'Unreachable' : 'Unknown';
      var statusCls = m.status === 1 ? 'up' : m.status === 0 ? 'down' : '';
      var ts = m.received_at ? new Date(m.received_at).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) : '\u2014';
      var dur = m.duration_ms !== null ? m.duration_ms + 'ms' : '\u2014';
      return '<div class="monitor-card ' + cls + '" data-monitor-id="' + m.monitor_id + '">' +
        '<div class="mon-name">' + (m.monitor_name || m.monitor_id || '?') + '</div>' +
        '<div class="mon-url monitor-url">' + (m.monitor_url || '\u2014') + '</div>' +
        '<div class="mon-status ' + statusCls + '">' + statusLabel + '</div>' +
        '<div class="mon-meta"><span>\u2665 ' + ts + '</span><span>\u21bb ' + dur + '</span></div>' +
        '<div class="sparkline-container" data-monitor-id="' + m.monitor_id + '"></div>' +
      '</div>';
    }).join('');
  }

  function renderStatusHistory(history) {
    var tbody = document.querySelector('#page-uptime tbody');
    if (!tbody || !history) return;
    if (history.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" style="color:var(--muted);text-align:center;padding:20px;">No history yet</td></tr>';
      return;
    }
    tbody.innerHTML = history.map(function(h) {
      var sevCls = h.status === 0 ? 'critical' : 'info';
      var sevLabel = h.status === 0 ? 'down' : 'up';
      var ts = h.received_at ? new Date(h.received_at).toLocaleString('en-US', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) : '';
      var dur = h.duration_ms !== null ? h.duration_ms + 'ms' : '\u2014';
      return '<tr>' +
        '<td class="mono nowrap">' + ts + '</td>' +
        '<td class="nowrap">' + (h.monitor_name || h.monitor_id || '?') + '</td>' +
        '<td><span class="sev-badge ' + sevCls + '">' + sevLabel + '</span></td>' +
        '<td>' + (h.msg || '\u2014') + '</td>' +
        '<td class="mono">' + dur + '</td>' +
      '</tr>';
    }).join('');
  }

  function renderSparklines(monitors) {
    var containers = document.querySelectorAll('#page-uptime .sparkline-container');
    containers.forEach(function(container) {
      var mid = container.dataset.monitorId;
      if (!mid || !monitors || !monitors[mid]) return;
      var svg = buildSparkline(monitors[mid]);
      container.innerHTML = svg;
    });
  }

  function buildSparkline(points) {
    var w = 120, h = 24, pad = 2;
    var n = points.length;
    if (n < 2) return '<div class="sparkline" style="height:' + h + 'px;display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:10px;">\u2014</div>';
    var stepX = (w - pad * 2) / (n - 1);
    var ptsStr = '';
    for (var i = 0; i < n; i++) {
      var s = points[i].status;
      var y = pad;
      if (s === 0) y = h - pad;
      else if (s === 1) y = pad;
      else y = h / 2;
      var x = pad + i * stepX;
      ptsStr += x.toFixed(1) + ',' + y.toFixed(1) + ' ';
    }
    var latest = points[n - 1].status;
    var color = latest === 1 ? 'var(--status-up, #4ade80)' : latest === 0 ? 'var(--status-down, #f87171)' : 'var(--muted, #94a3b8)';
    return '<svg class="sparkline" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '" style="display:block;margin-top:4px;">' +
      '<polyline points="' + ptsStr.trim() + '" fill="none" stroke="' + color + '" stroke-width="2" stroke-linejoin="round" /></svg>';
  }

  window.switchUptimeTab = function(tab) {
    var tc = document.getElementById('topology-container');
    var mg = document.querySelector('#page-uptime .monitor-grid');
    var hc = document.querySelector('#page-uptime .col-card');
    var tabMon = document.getElementById('tab-monitors');
    var tabTopo = document.getElementById('tab-topology');
    if (tab === 'topology') {
      if (mg) mg.style.display = 'none';
      if (hc) hc.style.display = 'none';
      if (tc) tc.style.display = 'block';
      if (tabMon) tabMon.classList.remove('active');
      if (tabTopo) tabTopo.classList.add('active');
      if (!_topologyLoaded) { _topologyLoaded = true; loadTopology(); }
    } else {
      if (mg) mg.style.display = '';
      if (hc) hc.style.display = '';
      if (tc) tc.style.display = 'none';
      if (tabMon) tabMon.classList.add('active');
      if (tabTopo) tabTopo.classList.remove('active');
    }
  };

  async function loadTopology() {
    var tc = document.getElementById('topology-container');
    if (!tc) return;
    try {
      var data = await window.api('/api/uptime/topology');
      renderTopology(data);
    } catch (e) {
      tc.innerHTML = '<div style="padding:20px;color:var(--danger);">Failed to load topology: ' + window.escHtml(e.message) + '</div>';
    }
  }

  window.pollUptimeKuma = async function() {
    var btn = document.getElementById('btn-poll-uptime');
    var result = document.getElementById('poll-result');
    if (!btn || !result) return;
    btn.disabled = true;
    btn.textContent = 'Polling\u2026';
    result.style.display = 'none';
    try {
      var data = await window.api('/api/dashboard/poll-uptime', { method: 'POST' });
      result.style.display = 'block';
      result.innerHTML = '<div style="color:var(--accent);padding:8px;background:var(--accent-dim);border-radius:4px;">' +
        '\u2713 ' + data.message + '</div>';
    } catch (e) {
      result.style.display = 'block';
      result.innerHTML = '<div style="color:var(--danger);padding:8px;background:var(--danger-dim);border-radius:4px;">' +
        '\u2717 Poll failed: ' + e.message + '</div>';
    } finally {
      btn.disabled = false;
      btn.textContent = 'Poll Uptime Kuma';
    }
  };

  function renderTopology(data) {
    data = data || {};
    var hosts = data.hosts || [];
    var orphans = data.orphans || [];
    var sum = data.summary || {};
    var container = document.getElementById('topology-container');
    var topoSummary = document.getElementById('topo-summary');
    var topoGrid = document.getElementById('topo-grid');
    var topoOrphans = document.getElementById('topo-orphans');
    topoSummary.innerHTML =
      '<span><span class="num">' + (sum.total_hosts || 0) + '</span> Hosts</span>' +
      '<span class="sep">\u00b7</span>' +
      '<span><span class="num">' + (sum.hosts_up || 0) + '</span> Up</span>' +
      '<span class="sep">\u00b7</span>' +
      '<span><span class="num">' + (sum.total_services || 0) + '</span> Services</span>' +
      '<span class="sep">\u00b7</span>' +
      '<span><span class="num">' + (sum.services_up || 0) + '</span> Up</span>' +
      (sum.orphans ? '<span class="sep">\u00b7</span><span><span class="num">' + sum.orphans + '</span> Orphans</span>' : '');
    if (hosts.length === 0) {
      topoGrid.innerHTML = '<div style="color:var(--muted);padding:20px;">No hosts found. Send uptime webhooks to /api/uptime/webhook</div>';
    } else {
      topoGrid.innerHTML = hosts.map(function(h) {
        var cls = h.status === 0 ? 'topo-down' : (h.up_count > 0 && h.up_count < h.total_services) ? 'topo-partial' : 'topo-up';
        var dotCls = h.status === 0 ? 'topo-down' : (h.up_count > 0 && h.up_count < h.total_services) ? 'topo-partial' : 'topo-up';
        var services = (h.services || []).map(function(s) {
          var scls = s.status === 1 ? 'topo-up' : s.status === 0 ? 'topo-down' : 'topo-pending';
          return '<span class="svc-dot ' + scls + '" title="' + window.escHtml(s.name || '') + ' \u2014 ' + window.escHtml(s.status_label || '') + (s.msg ? ': ' + window.escHtml(s.msg) : '') + '"></span>';
        }).join('');
        return '<div class="host-card ' + cls + '">' +
          '<div class="host-card-header">' +
            '<span class="host-dot ' + dotCls + '"></span>' +
            '<span class="host-name">' + window.escHtml(h.name || '?') + '</span>' +
            '<span class="host-count">' + (h.up_count || 0) + '/' + (h.total_services || 0) + ' UP</span>' +
          '</div>' +
          '<div class="host-services">' + (services || '<span style="color:var(--muted);font-size:12px;">No services</span>') + '</div>' +
        '</div>';
      }).join('');
    }
    if (orphans.length === 0) {
      topoOrphans.innerHTML = '';
    } else {
      var orphanChips = orphans.map(function(o) {
        var tags = (o.tags || []).map(function(t) { return '<span class="orphan-tag-chip">' + window.escHtml(t) + '</span>'; }).join('');
        return '<span class="orphan-chip" title="Add a host-name tag in Uptime Kuma to assign this monitor">' +
            window.escHtml(o.name || o.monitor_id || '?') + (tags ? ' ' + tags : '') + '</span>';
      }).join('');
      topoOrphans.innerHTML = '<h4>Orphan Monitors <span class="orphan-count">' + orphans.length + ' orphan' + (orphans.length !== 1 ? 's' : '') + '</span></h4>' + orphanChips;
    }
  }
})();
