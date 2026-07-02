// Page: Things / Home Assistant — mobile-first Life-OS control panel
(function() {
  'use strict';

  var _refreshTimer = null;
  var _lastSnapshotTs = null;

  // ─── Domain icons (inline SVG) ────────────────────────────────────
  var DOMAIN_ICONS = {
    light:         '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18h6"/><path d="M10 22h4"/><path d="M15.09 14c.18-.98.65-1.74 1.41-2.5A4.65 4.65 0 0018 8 6 6 0 006 8c0 1 .23 2.23 1.5 3.5A4.61 4.61 0 008.91 14"/></svg>',
    switch:        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="6" width="20" height="12" rx="6"/><circle cx="8" cy="12" r="2.5"/></svg>',
    scene:         '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>',
    sensor:        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="7"/><path d="M12 8v4l2 2"/><line x1="12" y1="3" x2="12" y2="5"/><line x1="3" y1="12" x2="5" y2="12"/><line x1="12" y1="19" x2="12" y2="21"/><line x1="19" y1="12" x2="21" y2="12"/></svg>',
    binary_sensor: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>',
    climate:       '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v18"/><path d="M8 7l4-4 4 4"/><path d="M8 17l4 4 4-4"/></svg>',
    lock:          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 018 0v4"/><circle cx="12" cy="16" r="1"/></svg>',
    cover:         '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="18" rx="2"/><line x1="2" y1="9" x2="22" y2="9"/><line x1="12" y1="9" x2="12" y2="21"/></svg>',
    fan:           '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="2.5"/><path d="M12 6a6 6 0 016 6"/><path d="M12 18a6 6 0 01-6-6"/></svg>',
    media_player:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polygon points="10 8 16 12 10 16 10 8"/></svg>',
    vacuum:        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="2"/><path d="M12 2a10 10 0 0110 10"/><path d="M12 22a10 10 0 01-10-10"/><path d="M8 12h8"/></svg>',
    person:        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
    default:       '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/></svg>'
  };

  var DOMAIN_LABELS = {
    light: 'Light', switch: 'Switch', scene: 'Scene', sensor: 'Sensor',
    binary_sensor: 'Binary', climate: 'Climate', lock: 'Lock',
    cover: 'Cover', fan: 'Fan', media_player: 'Media', vacuum: 'Vacuum'
  };

  // ─── Room inference ────────────────────────────────────────────────
  var KNOWN_ROOMS = [
    'kitchen', 'living.?room', 'bedroom', 'bathroom', 'office', 'garage',
    'hallway', 'entry', 'dining', 'laundry', 'basement', 'attic',
    'guest', 'nursery', 'study', 'library', 'patio', 'deck', 'balcony',
    'closet', 'pantry', 'mudroom', 'sunroom', 'gym', 'theater',
    'game.?room', 'storage', 'utility', 'workshop', 'conservatory'
  ];

  var ROOM_RE = new RegExp('^(' + KNOWN_ROOMS.join('|') + ')', 'i');

  function inferRoom(entity) {
    var name = (entity.attributes.friendly_name || entity.entity_id).toLowerCase();
    var eid = entity.entity_id.toLowerCase();
    var domain = eid.split('.')[0];
    var afterDot = eid.split('.').slice(1).join('.') || '';

    var match = name.match(ROOM_RE);
    if (match) return capitalize(match[1].replace(/_/g, ' '));
    match = afterDot.match(ROOM_RE);
    if (match) return capitalize(match[1].replace(/_/g, ' '));

    var parts = afterDot.split('_');
    if (parts.length >= 2) {
      var candidate = parts[0];
      if (candidate.length > 2 && /^[a-z]+$/.test(candidate)) {
        return capitalize(candidate);
      }
    }

    return domain === 'person' ? 'People' : 'Other';
  }

  function capitalize(s) {
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  function getDomainColor(domain) {
    var map = {
      light: '--warn', switch: '--accent', scene: '--accent-cyan',
      sensor: '--info', binary_sensor: '--accent-cyan', climate: '--warn',
      lock: '--danger', cover: '--accent', fan: '--info',
      media_player: '--accent', vacuum: '--info'
    };
    return map[domain] || '--muted';
  }

  function getDomainIcon(domain) {
    return DOMAIN_ICONS[domain] || DOMAIN_ICONS.default;
  }

  // ─── Main load function ────────────────────────────────────────────
  window.loadHomeAssistantPage = async function() {
    try {
      var results = await Promise.all([
        window.api('/api/homeassistant/config'),
        window.api('/api/homeassistant/status')
      ]);
      renderConnection(results[0]);
      renderThings(results[1]);
      var tsEl = document.getElementById('ha-status');
      if (tsEl) tsEl.textContent = '\u25cf ' + new Date().toLocaleTimeString();
    } catch (e) {
      var roomsEl = document.getElementById('ha-rooms');
      if (roomsEl) roomsEl.innerHTML = '<div class="things-error">Failed: ' + window.escHtml(e.message) + '</div>';
    }
    scheduleRefresh();
  };

  function scheduleRefresh() {
    if (_refreshTimer) clearTimeout(_refreshTimer);
    _refreshTimer = setTimeout(window.loadHomeAssistantPage, 30000);
  }

  // ─── Connection bar ────────────────────────────────────────────────
  function renderConnection(config) {
    var el = document.getElementById('ha-config');
    if (!el) return;
    if (!config || !config.connected) {
      el.innerHTML =
        '<div class="things-conn things-conn-off">' +
          '<span class="things-conn-dot"></span>' +
          '<span class="things-conn-label">Home Assistant</span>' +
          '<span class="things-conn-status">Disconnected</span>' +
          (config && config.reason ? '<span class="things-conn-reason">' + window.escHtml(config.reason) + '</span>' : '') +
        '</div>';
      return;
    }
    el.innerHTML =
      '<div class="things-conn things-conn-on">' +
        '<span class="things-conn-dot"></span>' +
        '<span class="things-conn-label">Home Assistant</span>' +
        '<span class="things-conn-status">v' + window.escHtml(config.version) + '</span>' +
        '<span class="things-conn-location">' + window.escHtml(config.location) + '</span>' +
      '</div>';
  }

  // ─── Core render: rooms + scenes ──────────────────────────────────
  function renderThings(status) {
    var entitiesEl = document.getElementById('ha-rooms');
    var scenesEl = document.getElementById('ha-scenes');
    var otherEl = document.getElementById('ha-other');
    if (!entitiesEl) return;

    if (!status || status.status === 'no_data' || !status.entities || status.entities.length === 0) {
      entitiesEl.innerHTML = '<div class="things-empty">No entities yet. Configure Home Assistant in Settings.</div>';
      return;
    }

    var entities = status.entities;
    var highlightIds = status.highlight_ids || [];

    if (highlightIds.length > 0) {
      var highlightSet = {};
      highlightIds.forEach(function(id) { highlightSet[id] = true; });
      entities = entities.filter(function(e) { return highlightSet[e.entity_id]; });
    }

    // Separate scenes from rest
    var scenes = [];
    var grouped = {};
    var roomOrder = [];

    entities.forEach(function(e) {
      var domain = e.entity_id.split('.')[0];
      if (domain === 'scene') {
        scenes.push(e);
        return;
      }
      var room = inferRoom(e);
      if (!grouped[room]) {
        grouped[room] = [];
        roomOrder.push(room);
      }
      grouped[room].push(e);
    });

    // Sort scenes by name
    scenes.sort(function(a, b) {
      var an = (a.attributes.friendly_name || a.entity_id).toLowerCase();
      var bn = (b.attributes.friendly_name || b.entity_id).toLowerCase();
      return an < bn ? -1 : an > bn ? 1 : 0;
    });

    // Render scenes section
    if (scenes.length > 0) {
      scenesEl.innerHTML =
        '<div class="things-section">' +
          '<div class="things-section-header">' +
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>' +
            '<span>Scenes</span>' +
            '<span class="things-section-count">' + scenes.length + '</span>' +
          '</div>' +
          '<div class="things-scene-grid">' +
            scenes.map(function(s) {
              var name = s.attributes.friendly_name || s.entity_id;
              var domain = 'scene';
              return '<button class="things-scene-btn" onclick="window.haCallService(\'scene\', \'turn_on\', \'' + s.entity_id + '\')">' +
                '<span class="things-scene-icon">' + getDomainIcon(domain) + '</span>' +
                '<span class="things-scene-name">' + window.escHtml(name) + '</span>' +
              '</button>';
            }).join('') +
          '</div>' +
        '</div>';
      scenesEl.style.display = '';
    } else {
      scenesEl.style.display = 'none';
    }

    // Sort room order: known rooms first, then alphabetically, "Other" last
    var ROOM_PRIORITY = ['Living Room', 'Kitchen', 'Bedroom', 'Bathroom', 'Office', 'Garage', 'Hallway', 'Entry'];
    roomOrder.sort(function(a, b) {
      var ia = ROOM_PRIORITY.indexOf(a);
      var ib = ROOM_PRIORITY.indexOf(b);
      if (ia !== -1 && ib !== -1) return ia - ib;
      if (ia !== -1) return -1;
      if (ib !== -1) return 1;
      if (a === 'Other') return 1;
      if (b === 'Other') return -1;
      return a < b ? -1 : a > b ? 1 : 0;
    });

    var html = '';
    roomOrder.forEach(function(room) {
      if (room === 'Other') return;
      var roomEntities = grouped[room];
      html += renderRoom(room, roomEntities);
    });
    entitiesEl.innerHTML = html;

    // Render "Other" group separately at the bottom
    var otherEntities = grouped['Other'] || [];
    var otherRoomKeys = roomOrder.filter(function(r) { return r !== 'Other'; });
    var remaining = [];
    Object.keys(grouped).forEach(function(r) {
      if (roomOrder.indexOf(r) === -1 || r === 'Other') return;
      if (otherRoomKeys.indexOf(r) === -1) {
        remaining = remaining.concat(grouped[r]);
      }
    });
    var allOther = otherEntities.concat(remaining);
    if (allOther.length > 0) {
      otherEl.innerHTML = renderRoom('Other', allOther);
      otherEl.style.display = '';
    } else {
      otherEl.style.display = 'none';
    }

    _lastSnapshotTs = status.ts;
  }

  // ─── Render a single room ─────────────────────────────────────────
  function renderRoom(roomName, entities) {
    var toggleableDomains = ['light', 'switch', 'fan', 'lock', 'cover', 'media_player', 'vacuum'];

    var entityCards = entities.map(function(e) {
      var domain = e.entity_id.split('.')[0];
      var name = e.attributes.friendly_name || e.entity_id;
      var unit = e.attributes.unit_of_measurement || '';
      var isToggleable = toggleableDomains.indexOf(domain) !== -1;
      var isOn = e.state === 'on' || e.state === 'playing' || e.state === 'open' || e.state === 'unlocked' || e.state === 'home';
      var isUnavailable = e.state === 'unavailable' || e.state === 'unknown';
      var stateClass = isUnavailable ? 'unavailable' : (isOn ? 'on' : 'off');
      var colorVar = getDomainColor(domain);
      var iconSvg = getDomainIcon(domain);

      var stateDisplay;
      if (isToggleable) {
        stateDisplay = isOn ? 'On' : 'Off';
      } else {
        stateDisplay = window.escHtml(e.state);
        if (unit) stateDisplay += ' <span class="things-unit">' + window.escHtml(unit) + '</span>';
      }

      var lastChanged = e.last_changed ? window.relativeTime(e.last_changed) : '';
      var domainLabel = DOMAIN_LABELS[domain] || domain;

      return '<div class="things-card things-card-' + stateClass + '" style="--things-accent:var(' + colorVar + ');" onclick="' +
        (isToggleable ? 'window.haToggle(\'' + e.entity_id + '\',\'' + domain + '\',' + isOn + ')' : '') + '">' +
        '<div class="things-card-icon">' + iconSvg + '</div>' +
        '<div class="things-card-body">' +
          '<div class="things-card-name">' + window.escHtml(name) + '</div>' +
          '<div class="things-card-state">' + stateDisplay + '</div>' +
        '</div>' +
        (lastChanged ? '<div class="things-card-meta">' + lastChanged + '</div>' : '') +
        '<span class="things-card-domain">' + domainLabel + '</span>' +
      '</div>';
    }).join('');

    return '<div class="things-section">' +
      '<div class="things-section-header">' +
        '<span class="things-section-dot"></span>' +
        '<span class="things-section-name">' + window.escHtml(roomName) + '</span>' +
        '<span class="things-section-count">' + entities.length + '</span>' +
      '</div>' +
      '<div class="things-card-grid">' + entityCards + '</div>' +
    '</div>';
  }

  // ─── Toggle helper ────────────────────────────────────────────────
  window.haToggle = async function(entityId, domain, isCurrentlyOn) {
    var service = isCurrentlyOn ? 'turn_off' : 'turn_on';
    try {
      await window.haCallService(domain, service, entityId);
      // Optimistic toggle: flip the card class immediately
      var cards = document.querySelectorAll('.things-card');
      cards.forEach(function(card) {
        if (card.getAttribute('onclick') && card.getAttribute('onclick').indexOf(entityId) !== -1) {
          card.classList.remove('things-card-on', 'things-card-off');
          card.classList.add(isCurrentlyOn ? 'things-card-off' : 'things-card-on');
          var stateEl = card.querySelector('.things-card-state');
          if (stateEl) stateEl.textContent = isCurrentlyOn ? 'Off' : 'On';
          card.setAttribute('onclick', 'window.haToggle(\'' + entityId + '\',\'' + domain + '\',' + (!isCurrentlyOn) + ')');
        }
      });
    } catch (e) {
      if (window.showToast) window.showToast('Failed: ' + e.message, 'error');
    }
  };

  window.haCallService = async function(domain, service, entityId, extraData) {
    try {
      var body = { domain: domain, service: service, entity_id: entityId };
      if (extraData) body.data = extraData;
      await window.api('/api/homeassistant/service', { method: 'POST', body: JSON.stringify(body) });
      if (window.showToast) window.showToast(domain + ' ' + service, 'success');
      setTimeout(function() { window.loadHomeAssistantPage(); }, 500);
    } catch (e) {
      if (window.showToast) window.showToast('Service call failed: ' + e.message, 'error');
    }
  };

  // ─── SSE live update hook ───────────────────────────────────────
  // Registers a callback on the shared SSE message channel so future
  // backend HA events (e.g. channel: 'things_update') trigger refresh.
  if (!window._sseCallbacks) window._sseCallbacks = {};
  window._sseCallbacks['things_update'] = function() {
    if (window._currentPage === 'homeassistant') {
      if (_refreshTimer) clearTimeout(_refreshTimer);
      window.loadHomeAssistantPage();
    }
  };

  // ─── Cleanup on unload ────────────────────────────────────────────
  window.addEventListener('beforeunload', function() {
    if (_refreshTimer) clearTimeout(_refreshTimer);
  });

})();
