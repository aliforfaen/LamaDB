// Page: Home Assistant
(function() {
  'use strict';

  var _autoRefreshTimer = null;

  window.loadHomeAssistantPage = async function() {
    try {
      var results = await Promise.all([
        window.api('/api/homeassistant/config'),
        window.api('/api/homeassistant/status')
      ]);
      renderHAConfig(results[0]);
      renderHAEntities(results[1]);

      var statusEl = document.getElementById('ha-status');
      if (statusEl) statusEl.textContent = 'Updated ' + new Date().toLocaleTimeString();
    } catch (e) {
      var el = document.getElementById('ha-entities');
      if (el) el.innerHTML = '<div style="color:var(--danger);padding:10px;">Failed: ' + e.message + '</div>';
    }

    // Auto-refresh every 60s
    if (_autoRefreshTimer) clearTimeout(_autoRefreshTimer);
    _autoRefreshTimer = setTimeout(window.loadHomeAssistantPage, 60000);
  };

  // ─── Connection Status ──────────────────────────────────────────────

  function renderHAConfig(config) {
    var el = document.getElementById('ha-config');
    if (!el) return;
    if (!config || !config.connected) {
      el.innerHTML = '<div class="stat-card"><div class="label">Home Assistant</div><div class="value" style="color:var(--danger);">Disconnected</div><div style="font-size:11px;color:var(--muted);">' + (config && config.reason ? window.escHtml(config.reason) : 'Not configured') + '</div></div>';
      return;
    }
    el.innerHTML = '<div class="stat-card"><div class="label">Home Assistant</div><div class="value" style="color:var(--success);">Connected</div><div style="font-size:11px;color:var(--muted);">' + window.escHtml(config.version) + ' \u00b7 ' + window.escHtml(config.location) + '</div></div>';
  }

  // ─── Entity Cards ───────────────────────────────────────────────────

  function renderHAEntities(status) {
    var el = document.getElementById('ha-entities');
    if (!el) return;
    if (!status || status.status === 'no_data' || !status.entities || status.entities.length === 0) {
      el.innerHTML = '<div style="color:var(--muted);padding:10px;">No entity data yet. Configure Home Assistant URL and token.</div>';
      return;
    }

    var entities = status.entities;
    var highlightIds = status.highlight_ids || [];
    var ts = status.ts ? window.relativeTime(status.ts) : '';

    // If highlight IDs configured, filter to those
    if (highlightIds.length > 0) {
      entities = entities.filter(function(e) { return highlightIds.indexOf(e.entity_id) !== -1; });
    } else {
      // Show interesting entity types
      var interestingDomains = ['sensor', 'binary_sensor', 'light', 'switch', 'climate', 'scene', 'lock', 'cover', 'fan', 'media_player'];
      entities = entities.filter(function(e) {
        var domain = e.entity_id.split('.')[0];
        return interestingDomains.indexOf(domain) !== -1;
      });
      // Limit to 100 to avoid overwhelming the page
      entities = entities.slice(0, 100);
    }

    // Group by domain for organized display
    var groups = {};
    entities.forEach(function(e) {
      var domain = e.entity_id.split('.')[0];
      if (!groups[domain]) groups[domain] = [];
      groups[domain].push(e);
    });

    var html = '<div style="font-size:12px;color:var(--muted);margin-bottom:12px;">Last snapshot: ' + ts + ' \u00b7 ' + entities.length + ' entities</div>';

    Object.keys(groups).sort().forEach(function(domain) {
      var groupEntities = groups[domain];
      html += '<div style="margin-bottom:16px;">';
      html += '<div style="font-size:13px;font-weight:600;color:var(--fg-2);margin-bottom:6px;text-transform:uppercase;letter-spacing:0.5px;">' + window.escHtml(domain) + '</div>';
      html += '<div class="stat-grid" style="grid-template-columns:repeat(auto-fill,minmax(180px,1fr));">';

      groupEntities.forEach(function(e) {
        var name = e.attributes.friendly_name || e.entity_id;
        var unit = e.attributes.unit_of_measurement || '';
        var stateDisplay = e.state;
        if (unit) stateDisplay += ' ' + unit;

        // Determine if entity has a toggle action
        var isToggleable = ['light', 'switch', 'fan', 'lock', 'cover', 'media_player'].indexOf(domain) !== -1;
        var isScene = domain === 'scene';
        var isOn = e.state === 'on' || e.state === 'playing' || e.state === 'open' || e.state === 'unlocked';
        var stateClass = isOn ? 'color:var(--success);' : 'color:var(--muted);';

        // Determine entity color based on domain
        var domainColors = {
          sensor: '--accent-cyan', binary_sensor: '--info', light: '--accent-yellow',
          switch: '--accent', climate: '--warn', scene: '--accent-purple',
          lock: '--danger', cover: '--accent-green', fan: '--info', media_player: '--accent'
        };
        var badgeColor = domainColors[domain] || '--muted';

        html += '<div class="stat-card" style="position:relative;">' +
          '<div class="label" style="display:flex;align-items:center;gap:6px;">' +
            '<span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:var(' + badgeColor + ');"></span>' +
            window.escHtml(name) +
          '</div>' +
          '<div class="value" style="font-size:16px;' + stateClass + '">' + window.escHtml(stateDisplay) + '</div>';

        // Action buttons
        if (isToggleable) {
          html += '<div style="margin-top:6px;display:flex;gap:4px;">' +
            '<button class="ha-btn ha-btn-on" onclick="event.stopPropagation();window.haCallService(\'' + domain + '\', \'turn_on\', \'' + e.entity_id + '\')">On</button>' +
            '<button class="ha-btn ha-btn-off" onclick="event.stopPropagation();window.haCallService(\'' + domain + '\', \'turn_off\', \'' + e.entity_id + '\')">Off</button>' +
          '</div>';
        }
        if (isScene) {
          html += '<div style="margin-top:6px;">' +
            '<button class="ha-btn ha-btn-scene" onclick="event.stopPropagation();window.haCallService(\'scene\', \'turn_on\', \'' + e.entity_id + '\')">Activate</button>' +
          '</div>';
        }

        html += '</div>';
      });

      html += '</div></div>';
    });

    el.innerHTML = html;
  }

  // ─── Service Call ────────────────────────────────────────────────────

  window.haCallService = async function(domain, service, entityId, extraData) {
    if (!confirm('Call ' + domain + '/' + service + ' on ' + entityId + '?')) return;
    try {
      var body = { domain: domain, service: service, entity_id: entityId };
      if (extraData) body.data = extraData;
      await window.api('/api/homeassistant/service', { method: 'POST', body: JSON.stringify(body) });
      if (window.showToast) window.showToast('Service called: ' + domain + '/' + service, 'success');
      // Refresh after a short delay
      setTimeout(function() { window.loadHomeAssistantPage(); }, 1000);
    } catch (e) {
      if (window.showToast) window.showToast('Service call failed: ' + e.message, 'error');
    }
  };

})();
