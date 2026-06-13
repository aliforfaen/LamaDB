// Page: Home Assistant — Smart Home Control Panel
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
      if (el) el.innerHTML = '<div class="ha-error">Failed: ' + window.escHtml(e.message) + '</div>';
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
      el.innerHTML =
        '<div class="ha-config-card disconnected">' +
          '<div class="ha-config-status-row">' +
            '<span class="ha-config-dot"></span>' +
            '<span class="ha-config-label">Home&nbsp;Assistant</span>' +
            '<span class="ha-config-status">Disconnected</span>' +
          '</div>' +
          (config && config.reason ? '<div class="ha-config-reason">' + window.escHtml(config.reason) + '</div>' : '') +
        '</div>';
      return;
    }
    el.innerHTML =
      '<div class="ha-config-card connected">' +
        '<div class="ha-config-status-row">' +
          '<span class="ha-config-dot"></span>' +
          '<span class="ha-config-label">Home&nbsp;Assistant</span>' +
          '<span class="ha-config-status">v' + window.escHtml(config.version) + '</span>' +
        '</div>' +
        '<div class="ha-config-reason">' + window.escHtml(config.location) + '</div>' +
      '</div>';
  }

  // ─── Domain icons (inline SVG — clean, scalable) ────────────────────

  var DOMAIN_ICONS = {
    light:           '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18h6"/><path d="M10 22h4"/><path d="M15.09 14c.18-.98.65-1.74 1.41-2.5A4.65 4.65 0 0018 8 6 6 0 006 8c0 1 .23 2.23 1.5 3.5A4.61 4.61 0 008.91 14"/></svg>',
    switch:          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="6" width="20" height="12" rx="6"/><circle cx="8" cy="12" r="2.5"/></svg>',
    scene:           '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>',
    sensor:          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="7"/><path d="M12 8v4l2 2"/><line x1="12" y1="3" x2="12" y2="5"/><line x1="3" y1="12" x2="5" y2="12"/><line x1="12" y1="19" x2="12" y2="21"/><line x1="19" y1="12" x2="21" y2="12"/></svg>',
    binary_sensor:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>',
    climate:         '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v18"/><path d="M8 7l4-4 4 4"/><path d="M8 17l4 4 4-4"/></svg>',
    lock:            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 018 0v4"/><circle cx="12" cy="16" r="1"/></svg>',
    cover:           '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="18" rx="2"/><line x1="2" y1="9" x2="22" y2="9"/><line x1="12" y1="9" x2="12" y2="21"/></svg>',
    fan:             '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="2.5"/><path d="M12 6a6 6 0 016 6"/><path d="M12 18a6 6 0 01-6-6" opacity=".4"/></svg>',
    media_player:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polygon points="10 8 16 12 10 16 10 8"/></svg>',
    default:         '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/></svg>'
  };

  var DOMAIN_COLORS = {
    light:           '--warn',
    switch:          '--accent',
    scene:           '--accent-cyan',
    sensor:          '--info',
    binary_sensor:   '--accent-cyan',
    climate:         '--warn',
    lock:            '--danger',
    cover:           '--accent',
    fan:             '--info',
    media_player:    '--accent'
  };

  // ─── Entity Cards ───────────────────────────────────────────────────

  function renderHAEntities(status) {
    var el = document.getElementById('ha-entities');
    if (!el) return;
    if (!status || status.status === 'no_data' || !status.entities || status.entities.length === 0) {
      el.innerHTML = '<div class="ha-empty">No entity data yet. Configure Home&nbsp;Assistant URL and token in Settings.</div>';
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

    // Snapshot bar
    var html = '<div class="ha-snapshot-bar">' +
      '<span class="ha-snapshot-dot"></span>' +
      'Snapshot ' + ts + ' &middot; ' + entities.length + ' entities' +
      '</div>';

    // Preferred display order for domains
    var domainOrder = ['light', 'switch', 'scene', 'sensor', 'binary_sensor', 'climate', 'lock', 'cover', 'fan', 'media_player'];
    var sortedDomains = Object.keys(groups).sort(function(a, b) {
      var ia = domainOrder.indexOf(a);
      var ib = domainOrder.indexOf(b);
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
    });

    sortedDomains.forEach(function(domain) {
      var groupEntities = groups[domain];
      var colorVar = DOMAIN_COLORS[domain] || '--muted';
      var iconSvg = DOMAIN_ICONS[domain] || DOMAIN_ICONS.default;

      html += '<div class="ha-domain-group">';
      html += '<div class="ha-domain-header" style="--ha-domain-color:var(' + colorVar + ');">' +
        '<span class="ha-domain-icon">' + iconSvg + '</span>' +
        '<span class="ha-domain-name">' + window.escHtml(domain.replace('_', ' ')) + '</span>' +
        '<span class="ha-domain-count">' + groupEntities.length + '</span>' +
        '</div>';
      html += '<div class="ha-grid">';

      groupEntities.forEach(function(e) {
        var name = e.attributes.friendly_name || e.entity_id;
        var unit = e.attributes.unit_of_measurement || '';
        var d = e.entity_id.split('.')[0];

        // Determine entity capabilities and state (hoisted before use)
        var isToggleable = ['light', 'switch', 'fan', 'lock', 'cover', 'media_player'].indexOf(d) !== -1;
        var isScene = d === 'scene';
        var isOn = e.state === 'on' || e.state === 'playing' || e.state === 'open' || e.state === 'unlocked';
        var isUnavailable = e.state === 'unavailable' || e.state === 'unknown';

        // Format state display
        var stateDisplay;
        if (isScene) {
          stateDisplay = window.relativeTime(e.state);
        } else {
          stateDisplay = window.escHtml(e.state);
          if (unit) stateDisplay += ' <span class="ha-unit">' + window.escHtml(unit) + '</span>';
        }

        var stateClass = isUnavailable ? 'unavailable' : (isOn ? 'on' : 'off');
        var lastChanged = e.last_changed ? window.relativeTime(e.last_changed) : '';

        html += '<div class="ha-card ' + stateClass + '" style="--ha-domain-color:var(' + (DOMAIN_COLORS[d] || '--muted') + ');">';

        // Top row: icon + name
        html += '<div class="ha-card-top">' +
          '<span class="ha-icon">' + iconSvg + '</span>' +
          '<span class="ha-name">' + window.escHtml(name) + '</span>' +
          '</div>';

        // State value
        html += '<div class="ha-state">' + stateDisplay + '</div>';

        // Last changed relative time
        if (lastChanged) {
          html += '<div class="ha-last-change" title="' + window.escAttr(e.last_changed) + '">' + lastChanged + '</div>';
        }

        // Action buttons
        if (isToggleable) {
          html += '<div class="ha-actions">' +
            '<button class="ha-btn ha-btn-on" onclick="event.stopPropagation();window.haCallService(\'' + d + '\', \'turn_on\', \'' + e.entity_id + '\')">On</button>' +
            '<button class="ha-btn ha-btn-off" onclick="event.stopPropagation();window.haCallService(\'' + d + '\', \'turn_off\', \'' + e.entity_id + '\')">Off</button>' +
            '</div>';
        }
        if (isScene) {
          html += '<div class="ha-actions">' +
            '<button class="ha-btn ha-btn-scene" onclick="event.stopPropagation();window.haCallService(\'scene\', \'turn_on\', \'' + e.entity_id + '\')">Activate</button>' +
            '</div>';
        }

        html += '</div>';  // .ha-card
      });

      html += '</div></div>';  // .ha-grid, .ha-domain-group
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
