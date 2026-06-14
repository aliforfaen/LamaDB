// Page: Settings
(function() {
  'use strict';

  var _apikeyPage = 0;
  var _apikeyPerPage = 25;
  var _apikeyFilter = 'all';
  var _allApiKeys = [];
  var _moduleConfigName = null;

  window.loadSettings = async function() {
    loadModules();
    loadModuleConfigs();
    loadApiKeys();
    loadHealth();
    loadCacheStats();
    loadAppearance();
    loadMaintenance();
  };

  // ─── Module Management ─────────────────────────────────────────────────────
  function loadModules() {
    var list = document.getElementById('modules-list');
    if (!list) return;
    window.api('/api/dashboard/modules').then(function(data) {
      renderModuleCards(data.modules || []);
    }).catch(function(e) {
      list.innerHTML = '<div style="color:var(--danger);padding:10px;">Failed to load modules: ' + e.message + '</div>';
    });
  }

  function getModuleIconColor(name) {
    var colors = ['#6366f1', '#10b981', '#f43f5e', '#f59e0b', '#06b6d4', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#84cc16'];
    var hash = 0;
    for (var i = 0; i < name.length; i++) { hash = ((hash << 5) - hash) + name.charCodeAt(i); hash |= 0; }
    return colors[Math.abs(hash) % colors.length];
  }

  function getModuleInitial(name) {
    return name.charAt(0).toUpperCase();
  }

  function renderModuleCards(modules) {
    var list = document.getElementById('modules-list');
    if (!list) return;
    if (!modules || modules.length === 0) {
      list.innerHTML = '<div style="color:var(--muted);padding:10px;">No modules found</div>'; return;
    }
    list.innerHTML = '<div class="module-grid">' +
      modules.map(function(m) {
        var enabled = m.enabled ? 'checked' : '';
        var iconColor = getModuleIconColor(m.name);
        var initial = getModuleInitial(m.name);
        var iconClass = m.enabled ? 'icon-enabled' : 'icon-disabled';
        return '<div class="module-card" data-module="' + m.name + '">' +
          '<div class="module-card-header">' +
            '<div class="module-card-icon ' + iconClass + '" style="background:' + iconColor + '22;color:' + iconColor + ';">' + initial + '</div>' +
            '<div class="module-card-info">' +
              '<h4>' + window.escHtml(m.name) + '</h4>' +
              '<p>' + window.escHtml(m.description || '') + '</p>' +
              '<div class="module-card-meta">v' + (m.version || '0.0.0') + '</div>' +
            '</div>' +
          '</div>' +
          '<div class="module-card-actions">' +
            '<span class="restart-badge">Restart required</span>' +
            '<label class="toggle" style="margin:0;">' +
              '<input type="checkbox" ' + enabled + ' onchange="toggleModule(\'' + m.name + '\', this.checked)" />' +
              '<span class="toggle-slider"></span>' +
            '</label>' +
          '</div>' +
        '</div>';
      }).join('') +
    '</div>';
  }

  window.toggleModule = function(name, enabled) {
    window.api('/api/dashboard/modules/' + name + '/toggle', {
      method: 'POST', body: JSON.stringify({ enabled: enabled })
    }).then(function() {
      var card = document.querySelector('[data-module="' + name + '"]');
      if (card) {
        var badge = card.querySelector('.restart-badge');
        if (badge) badge.style.display = 'inline';
      }
    }).catch(function(e) { alert('Failed to toggle module: ' + e.message); });
  };

  // ─── API Keys ──────────────────────────────────────────────────────────────
  function loadApiKeys() {
    var tbody = document.getElementById('apikeys-tbody');
    var statsEl = document.getElementById('apikey-stats');
    if (!tbody) return;
    Promise.all([
      window.api('/api/dashboard/api-keys'),
      window.api('/api/dashboard/api-keys/stats')
    ]).then(function(results) {
      _allApiKeys = (results[0] && results[0].keys) || [];
      renderApiKeyStats(results[1]);
      renderApiKeysTable(_allApiKeys);
    }).catch(function(e) {
      tbody.innerHTML = '<tr><td colspan="7" style="color:var(--danger);text-align:center;padding:20px;">Failed to load API keys: ' + e.message + '</td></tr>';
      if (statsEl) statsEl.innerHTML = '<span style="color:var(--danger);">Error</span>';
    });
  }

  function renderApiKeyStats(stats) {
    var statsEl = document.getElementById('apikey-stats');
    if (!statsEl || !stats) return;
    statsEl.innerHTML =
      '<span class="key-stat"><span class="active-dot"></span>' + (stats.active || 0) + ' active</span>' +
      '<span class="key-stat"><span class="inactive-dot"></span>' + (stats.inactive || 0) + ' inactive</span>' +
      '<span class="key-stat"><span class="stale-dot"></span>' + (stats.stale || 0) + ' stale</span>';
  }

  function renderApiKeysTable(keys) {
    var tbody = document.getElementById('apikeys-tbody');
    if (!tbody) return;
    var filter = _apikeyFilter || 'all';
    var filtered = keys.filter(function(k) {
      if (filter === 'active') return k.active;
      if (filter === 'inactive') return !k.active;
      if (filter === 'stale') {
        if (!k.active) return false;
        if (!k.last_used_at) return true;
        var lastUsed = new Date(k.last_used_at);
        var cutoff = new Date(); cutoff.setDate(cutoff.getDate() - 30);
        return lastUsed < cutoff;
      }
      return true;
    });

    // Pagination
    var totalPages = Math.ceil(filtered.length / _apikeyPerPage);
    if (_apikeyPage >= totalPages) _apikeyPage = Math.max(0, totalPages - 1);
    var paged = filtered.slice(_apikeyPage * _apikeyPerPage, (_apikeyPage + 1) * _apikeyPerPage);

    if (filtered.length === 0) {
      var msg = filter === 'all' ? 'No API keys yet.' : filter === 'active' ? 'No active API keys.' : filter === 'inactive' ? 'No inactive API keys.' : 'No stale API keys.';
      tbody.innerHTML = '<tr><td colspan="7" style="color:var(--muted);text-align:center;padding:20px;">' + msg + '</td></tr>';
      renderApiKeyPagination(0, 0); return;
    }
    tbody.innerHTML = paged.map(function(k) {
      var scopes = (k.scopes || []).length > 0 ? (k.scopes || []).map(function(s) {
        return '<span class="scope-pill">' + s + '</span>';
      }).join(' ') : '<span style="color:var(--muted);font-size:12px;">\u2014</span>';
      var roleBadge = 'role-badge ' + k.role;
      var toggleChecked = k.active ? 'checked' : '';
      var lastUsed = window.relativeTime(k.last_used_at);
      var created = window.relativeTime(k.created_at);
      return '<tr data-key-id="' + k.id + '">' +
        '<td><span class="inline-edit" id="key-' + k.id + '-name" onclick="startInlineEdit(\'' + k.id + '\', \'name\', \'' + window.escAttr(k.name) + '\', \'text\')">' + window.escHtml(k.name) + '</span></td>' +
        '<td><span class="inline-edit ' + roleBadge + '" id="key-' + k.id + '-role" onclick="startInlineEdit(\'' + k.id + '\', \'role\', \'' + window.escAttr(k.role) + '\', \'role\')">' + k.role + '</span></td>' +
        '<td><span class="inline-edit" id="key-' + k.id + '-scopes" onclick="startInlineEdit(\'' + k.id + '\', \'scopes\', \'' + window.escAttr((k.scopes || []).join(', ')) + '\', \'scopes\')" style="display:flex;flex-wrap:wrap;gap:3px;">' + scopes + '</span></td>' +
        '<td class="mono" style="font-size:12px;color:var(--fg-2);">' + created + '</td>' +
        '<td class="mono" style="font-size:12px;">' + lastUsed + '</td>' +
        '<td><label class="toggle" style="margin:0;" onclick="event.stopPropagation()">' +
          '<input type="checkbox" ' + toggleChecked + ' onchange="toggleKeyActive(\'' + k.id + '\', ' + k.active + ')" /><span class="toggle-slider"></span></label></td>' +
        '<td class="key-table-actions">' +
          '<button class="btn btn-ghost btn-sm" onclick="rotateApiKey(\'' + k.id + '\', \'' + window.escAttr(k.name) + '\')" title="Rotate key">\ud83d\udd04</button>' +
          '<button class="btn btn-ghost btn-sm" style="color:var(--danger);" onclick="revokeApiKey(\'' + k.id + '\', \'' + window.escAttr(k.name) + '\')" title="Revoke key">\u2717</button></td>' +
      '</tr>';
    }).join('');
    renderApiKeyPagination(filtered.length, totalPages);
  }

  function renderApiKeyPagination(total, totalPages) {
    var el = document.getElementById('apikey-pagination');
    if (!el) return;
    if (total === 0) { el.innerHTML = ''; return; }
    var start = _apikeyPage * _apikeyPerPage + 1;
    var end = Math.min((_apikeyPage + 1) * _apikeyPerPage, total);
    el.innerHTML =
      '<div style="display:flex;align-items:center;gap:10px;font-size:12px;color:var(--fg-2);">' +
        '<select onchange="window.setApiKeyPerPage(this.value)" style="background:var(--surface-2);border:1px solid var(--border);border-radius:var(--radius-sm);padding:3px 6px;color:var(--fg);font-size:12px;">' +
          '<option value="25"' + (_apikeyPerPage === 25 ? ' selected' : '') + '>25/page</option>' +
          '<option value="50"' + (_apikeyPerPage === 50 ? ' selected' : '') + '>50/page</option>' +
          '<option value="100"' + (_apikeyPerPage === 100 ? ' selected' : '') + '>100/page</option>' +
        '</select>' +
        '<span>' + start + '\u2013' + end + ' of ' + total + '</span>' +
        '<button class="btn btn-sm btn-secondary"' + (_apikeyPage === 0 ? ' disabled' : '') + ' onclick="window.prevApiKeyPage()">&laquo; Prev</button>' +
        '<button class="btn btn-sm btn-secondary"' + (_apikeyPage >= totalPages - 1 ? ' disabled' : '') + ' onclick="window.nextApiKeyPage()">Next &raquo;</button>' +
      '</div>';
  }

  window.setApiKeyPerPage = function(n) {
    _apikeyPerPage = parseInt(n, 10);
    _apikeyPage = 0;
    renderApiKeysTable(_allApiKeys);
  };

  window.prevApiKeyPage = function() {
    if (_apikeyPage > 0) { _apikeyPage--; renderApiKeysTable(_allApiKeys); }
  };

  window.nextApiKeyPage = function() {
    var total = Math.ceil(_allApiKeys.length / _apikeyPerPage);
    if (_apikeyPage < total - 1) { _apikeyPage++; renderApiKeysTable(_allApiKeys); }
  };

  window.filterApiKeys = function(filter, btn) {
    document.querySelectorAll('#apikey-filter-tabs .filter-tab').forEach(function(t) { t.classList.remove('active'); });
    if (btn) btn.classList.add('active');
    _apikeyFilter = filter;
    _apikeyPage = 0;
    renderApiKeysTable(_allApiKeys);
  };

  window.populateScopeCheckboxes = function() {
    var container = document.getElementById('apikey-scope-checkboxes');
    if (!container) return;
    window.api('/api/dashboard/modules').then(function(data) {
      var modules = data.modules || [];
      var coreScopes = ['documents', 'events', 'search', 'dashboard'];
      var all = {};
      coreScopes.forEach(function(s) { all[s] = true; });
      modules.forEach(function(m) { all[m.name] = true; });
      var names = Object.keys(all).sort();
      container.innerHTML = names.map(function(s) {
        return '<label class="scope-checkbox" data-scope="' + s + '">' +
          '<input type="checkbox" value="' + s + '" onchange="this.parentElement.classList.toggle(\'checked\', this.checked)" /> ' + s + '</label>';
      }).join('');
    }).catch(function() { container.innerHTML = '<span style="color:var(--danger);font-size:12px;">Failed to load scopes</span>'; });
  };

  window.updateScopeVisibility = function() {
    var role = document.getElementById('apikey-role').value;
    var group = document.getElementById('apikey-scopes-group');
    if (group) group.style.display = role === 'admin' ? 'none' : 'block';
  };

  window.submitCreateApiKey = function() {
    var name = document.getElementById('apikey-name').value.trim();
    if (!name) { alert('Please enter a key name.'); return; }
    var role = document.getElementById('apikey-role').value;
    var scopes = [];
    if (role !== 'admin') {
      scopes = Array.prototype.map.call(
        document.querySelectorAll('#apikey-scope-checkboxes input:checked'),
        function(c) { return c.value; }
      );
    }
    window.api('/api/dashboard/api-keys', {
      method: 'POST', body: JSON.stringify({ name: name, role: role, scopes: scopes })
    }).then(function(data) {
      window.closeModal('modal-apikey');
      window._pendingKey = data.key;
      document.getElementById('new-key-display').textContent = data.key;
      document.getElementById('modal-key-created').classList.add('open');
      loadApiKeys();
    }).catch(function(e) { alert('Failed to create API key: ' + e.message); });
  };

  window.copyNewKey = function() {
    if (window._pendingKey) {
      navigator.clipboard.writeText(window._pendingKey).then(function() {
        var btn = document.querySelector('#modal-key-created .btn-secondary');
        if (btn) { btn.innerHTML = '\u2713 Copied!'; setTimeout(function() { if (btn) btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy to Clipboard'; }, 2000); }
      }).catch(function() {
        var ta = document.createElement('textarea');
        ta.value = window._pendingKey; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta);
      });
    }
  };

  window.revokeApiKey = function(id, name) {
    window.showConfirm('Revoke API Key', 'Revoke "' + name + '"? It will stop working immediately.', '\u2717', function() {
      window.api('/api/dashboard/api-keys/' + id, { method: 'DELETE' }).then(function() {
        loadApiKeys();
        window.showToast('Key "' + name + '" revoked.', 'Undo', function() {
          window.api('/api/dashboard/api-keys/' + id, { method: 'PATCH', body: JSON.stringify({ active: true }) }).then(function() {
            loadApiKeys(); window.showToast('Key "' + name + '" restored.', null, null, 3000);
          }).catch(function(e) { window.showToast('Failed to undo: ' + e.message, null, null, 3000); });
        }, 5000);
      }).catch(function(e) { window.showToast('Failed to revoke key: ' + e.message, null, null, 3000); });
    });
  };

  window.rotateApiKey = function(id, name) {
    window.showConfirm('Rotate API Key', 'Generate a new key for "' + name + '"?', '\ud83d\udd04', function() {
      window.api('/api/dashboard/api-keys/' + id + '/rotate', { method: 'POST' }).then(function(data) {
        window._pendingKey = data.key;
        document.getElementById('new-key-display').textContent = data.key;
        document.getElementById('modal-key-created').classList.add('open');
        loadApiKeys();
        window.showToast('Key "' + name + '" rotated.', null, null, 3000);
      }).catch(function(e) { window.showToast('Failed to rotate key: ' + e.message, null, null, 3000); });
    });
  };

  window.toggleKeyActive = function(id, currentActive) {
    window.api('/api/dashboard/api-keys/' + id, { method: 'PATCH', body: JSON.stringify({ active: !currentActive }) })
      .then(function() { loadApiKeys(); })
      .catch(function(e) { window.showToast('Failed to update key: ' + e.message, null, null, 3000); loadApiKeys(); });
  };

  window.startInlineEdit = function(id, field, currentValue, type) {
    var cell = document.getElementById('key-' + id + '-' + field);
    if (!cell) return;
    if (type === 'role') {
      cell.innerHTML = '<select class="inline-edit-select" id="inline-' + id + '-' + field + '" onblur="saveInlineEdit(\'' + id + '\', \'' + field + '\', this)" onkeydown="if(event.key===\'Enter\')this.blur()">' +
        '<option value="read"' + (currentValue === 'read' ? ' selected' : '') + '>read</option>' +
        '<option value="agent"' + (currentValue === 'agent' ? ' selected' : '') + '>agent</option>' +
        '<option value="admin"' + (currentValue === 'admin' ? ' selected' : '') + '>admin</option></select>';
      document.getElementById('inline-' + id + '-' + field).focus();
    } else {
      cell.innerHTML = '<input class="inline-edit-input" type="text" id="inline-' + id + '-' + field + '" value="' + window.escHtml(String(currentValue)) + '" onblur="saveInlineEdit(\'' + id + '\', \'' + field + '\', this)" onkeydown="if(event.key===\'Enter\')this.blur()" />';
      var input = document.getElementById('inline-' + id + '-' + field);
      input.focus(); input.select();
    }
  };

  window.saveInlineEdit = function(id, field, el) {
    var newValue = el.value.trim();
    if (!newValue) { loadApiKeys(); return; }
    var body = {};
    if (field === 'scopes') { body.scopes = newValue.split(',').map(function(s) { return s.trim(); }).filter(function(s) { return s.length > 0; }); }
    else { body[field] = newValue; }
    window.api('/api/dashboard/api-keys/' + id, { method: 'PATCH', body: JSON.stringify(body) })
      .then(function() { loadApiKeys(); })
      .catch(function(e) { window.showToast('Failed to update: ' + e.message, null, null, 3000); loadApiKeys(); });
  };

  // ─── System Health ─────────────────────────────────────────────────────────
  function loadHealth() {
    var container = document.getElementById('health-cards');
    if (!container) return;
    window.api('/api/dashboard/health').then(function(data) { renderHealthCards(data); })
      .catch(function(e) { container.innerHTML = '<div class="health-card"><h4>System Health</h4><div style="color:var(--danger);padding:10px;">Failed: ' + e.message + '</div></div>'; });
  }

  function renderHealthCards(data) {
    var container = document.getElementById('health-cards');
    if (!container || !data) return;
    var db = data.database || {};
    var pgVersion = db.version ? db.version.split(' ').slice(0, 2).join(' ') : 'Unknown';
    var pool = data.pool || {};
    var extHtml = Object.keys(db.extensions || {}).map(function(k) {
      var ext = db.extensions[k];
      return '<span style="color:var(--accent);margin-right:8px;">\u2713</span> <span style="color:var(--fg-2);">' + k + '</span> <span style="color:var(--muted);font-size:11px;">v' + ext.version + '</span>';
    }).join(' ');
    var tableHtml = Object.keys(db.tables || {}).map(function(t) {
      var tbl = db.tables[t];
      return '<div class="health-item"><span class="label">' + t + '</span><span class="value">' + tbl.rows.toLocaleString() + ' rows \u00b7 ' + tbl.size + '</span></div>';
    }).join('');
    container.innerHTML =
      '<div class="health-card"><h4>Database</h4>' +
        '<div class="health-item"><span class="label">Status</span><span class="value" style="color:var(--accent);">\u2713 Connected</span></div>' +
        '<div class="health-item"><span class="label">Version</span><span class="value">' + pgVersion + '</span></div>' +
        '<div class="health-item"><span class="label">Connection Pool</span><span class="value">' + pool.active + ' active / ' + pool.max + ' max</span></div>' +
        '<div style="margin-top:12px;">' + extHtml + '</div></div>' +
      '<div class="health-card"><h4>Tables</h4>' + tableHtml + '</div>';
  }

  // ─── Maintenance ──────────────────────────────────────────────────────────
  function loadMaintenance() {
    var container = document.getElementById('maintenance-section');
    if (!container) return;

    window.api('/api/dashboard/maintenance/status').then(function(data) {
      var lastRun = data.last_run ? window.relativeTime(data.last_run) : 'Never';
      var stats = data.stats || {};
      container.innerHTML =
        '<h4>Database Maintenance</h4>' +
        '<div class="health-item"><span class="label">Last Run</span><span class="value">' + lastRun + '</span></div>' +
        '<div class="health-item"><span class="label">Events Pruned</span><span class="value">' + (stats.events_deleted || 0) + '</span></div>' +
        '<div class="health-item"><span class="label">Dozzle Dupes Removed</span><span class="value">' + (stats.dozzle_deleted || 0) + '</span></div>' +
        '<div class="health-item"><span class="label">Monitor Rows Pruned</span><span class="value">' + (stats.monitor_deleted || 0) + '</span></div>' +
        '<div style="margin-top:12px;"><button class="btn btn-sm btn-ghost" onclick="triggerMaintenance()">Run Now</button></div>';
    }).catch(function(e) {
      container.innerHTML = '<h4>Database Maintenance</h4><div style="color:var(--danger);padding:10px;">Failed: ' + e.message + '</div>';
    });
  }

  window.triggerMaintenance = function() {
    var btn = document.querySelector('#maintenance-section .btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Running...'; }
    window.api('/api/dashboard/maintenance/run', { method: 'POST' }).then(function() {
      window.showToast('Maintenance run completed', null, null, 3000);
      loadMaintenance();
    }).catch(function(e) {
      window.showToast('Failed: ' + e.message, null, null, 5000);
      if (btn) { btn.disabled = false; btn.textContent = 'Run Now'; }
    });
  };

  window.loadCacheStats = function() {
    try {
      var key = localStorage.getItem('lamadb_api_key');
      if (!key) return;
      fetch('/api/dashboard/cache-stats?key=' + encodeURIComponent(key)).then(function(resp) {
        if (!resp.ok) return;
        resp.json().then(function(data) {
          var hits = document.getElementById('cache-hits');
          var misses = document.getElementById('cache-misses');
          var expired = document.getElementById('cache-expired');
          var entries = document.getElementById('cache-entries');
          if (hits) hits.textContent = data.hits;
          if (misses) misses.textContent = data.misses;
          if (expired) expired.textContent = data.expired;
          if (entries) entries.textContent = data.entries;
        }).catch(function() {});
      }).catch(function() {});
    } catch (e) {}
  };

  // ─── Appearance (Accent Picker) ───────────────────────────────────────────
  function loadAppearance() {
    var container = document.getElementById('appearance-section');
    if (!container) return;

    var accents = [
      { name: 'Indigo', hex: '#6366f1' },
      { name: 'Emerald', hex: '#10b981' },
      { name: 'Rose', hex: '#f43f5e' },
      { name: 'Amber', hex: '#f59e0b' },
      { name: 'Cyan', hex: '#06b6d4' },
      { name: 'Violet', hex: '#8b5cf6' },
    ];

    var currentAccent = localStorage.getItem('lamadb_accent') || '#6366f1';
    var currentScheme = localStorage.getItem('lamadb_theme') || 'dark';

    container.innerHTML =
      '<h4>Appearance</h4>' +
      '<div style="margin-bottom:16px;">' +
        '<label style="display:block;margin-bottom:8px;color:var(--fg-2);font-size:13px;">Color Scheme</label>' +
        '<div style="display:flex;gap:8px;">' +
          '<button class="btn btn-sm ' + (currentScheme === 'dark' ? 'btn-primary' : 'btn-ghost') + '" onclick="window.toggleTheme(); loadAppearance();">Dark</button>' +
          '<button class="btn btn-sm ' + (currentScheme === 'light' ? 'btn-primary' : 'btn-ghost') + '" onclick="window.toggleTheme(); loadAppearance();">Light</button>' +
        '</div>' +
      '</div>' +
      '<div>' +
        '<label style="display:block;margin-bottom:8px;color:var(--fg-2);font-size:13px;">Accent Color</label>' +
        '<div style="display:flex;gap:8px;flex-wrap:wrap;">' +
          accents.map(function(a) {
            var isActive = a.hex === currentAccent;
            return '<button class="accent-swatch' + (isActive ? ' active' : '') + '" ' +
              'onclick="setAccent(\'' + a.hex + '\')" ' +
              'title="' + a.name + '" ' +
              'style="width:32px;height:32px;border-radius:50%;background:' + a.hex + ';border:3px solid ' + (isActive ? 'var(--fg)' : 'transparent') + ';cursor:pointer;transition:border-color 0.2s;">' +
            '</button>';
          }).join('') +
        '</div>' +
      '</div>';
  }

  window.setAccent = function(hex) {
    localStorage.setItem('lamadb_accent', hex);
    if (window.applyAccent) window.applyAccent(hex);
    var scheme = localStorage.getItem('lamadb_theme') || 'dark';
    window.api('/api/users/me/theme', {
      method: 'PUT',
      body: JSON.stringify({ scheme: scheme, accent: hex })
    }).catch(function() {});
    loadAppearance();
  };

  // ─── Module Config ─────────────────────────────────────────────────────────
  function loadModuleConfigs() {
    var grid = document.getElementById('module-config-grid');
    if (!grid) return;
    window.api('/api/dashboard/module-settings').then(function(data) {
      _moduleConfigData = data.modules || {};
      renderModuleConfigGrid(_moduleConfigData);
    }).catch(function(e) { grid.innerHTML = '<div style="grid-column:1/-1;color:var(--danger);padding:10px;">Failed: ' + window.escHtml(e.message) + '</div>'; });
  }

  function renderModuleConfigGrid(modules) {
    var grid = document.getElementById('module-config-grid');
    if (!grid) return;
    var names = Object.keys(modules);
    if (names.length === 0) {
      grid.innerHTML = '<div style="grid-column:1/-1;color:var(--muted);padding:10px;">No configurable modules found.</div>'; return;
    }
    grid.innerHTML = names.map(function(name) {
      var mod = modules[name];
      var schema = mod.schema || {};
      var values = mod.values || {};
      var fieldKeys = Object.keys(schema);
      var fieldCount = fieldKeys.length;
      var sources = fieldKeys.map(function(k) { return values[k] ? values[k].source : 'default'; });
      var hasFile = sources.indexOf('file') !== -1;
      var hasEnv = sources.indexOf('env') !== -1;
      var allDefault = sources.every(function(s) { return s === 'default'; });
      var dotClass, dotTitle;
      if (allDefault) { dotClass = 'grey'; dotTitle = 'Not configured'; }
      else if (hasFile) { dotClass = 'yellow'; dotTitle = 'Configured (restart may be needed)'; }
      else { dotClass = 'green'; dotTitle = 'Configured and active'; }
      return '<div class="module-config-card">' +
        '<div class="module-config-header">' +
          '<span class="name">' + window.escHtml(name) + '</span>' +
          '<div class="module-config-actions">' +
            '<span class="config-status-dot ' + dotClass + '" title="' + dotTitle + '"></span>' +
            '<span class="module-config-field-count">' + fieldCount + ' fields</span>' +
            '<button class="config-gear-btn" onclick="openModuleConfigForm(\'' + window.escAttr(name) + '\')" title="Configure ' + window.escAttr(name) + '">' +
              '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>' +
            '</button>' +
          '</div>' +
        '</div>' +
        (dotTitle ? '<div style="font-size:11px;color:var(--muted);font-family:var(--font-mono);">' + dotTitle + '</div>' : '') +
      '</div>';
    }).join('');
  }

  window.openModuleConfigForm = function(moduleName) {
    if (!_moduleConfigData || !_moduleConfigData[moduleName]) {
      window.showToast('Module data not loaded', null, null, 3000); return;
    }
    _moduleConfigName = moduleName;
    var mod = _moduleConfigData[moduleName];
    var schema = mod.schema || {};
    var values = mod.values || {};
    var titleEl = document.getElementById('module-config-title');
    var bodyEl = document.getElementById('module-config-body');
    if (titleEl) titleEl.textContent = 'Configure: ' + moduleName;
    var fieldHtml = Object.keys(schema).map(function(key) {
      var field = schema[key];
      var val = values[key] || {};
      var ftype = field.type || 'str';
      var label = field.label || key;
      var desc = field.description || '';
      var source = val.source || 'default';
      var currentVal = val.display !== undefined ? val.display : (val.value !== undefined ? val.value : '');
      var actualVal = val.value !== undefined ? val.value : '';
      var sourceClass = source === 'env' ? 'env' : source === 'file' ? 'file' : '';
      var sourceLabel = source === 'env' ? '(env)' : source === 'file' ? '(file)' : '(default)';
      var inputHtml = '';
      if (ftype === 'bool') {
        inputHtml = '<div class="input-row"><input type="checkbox" id="cfg-field-' + key + '" ' + (actualVal ? 'checked' : '') + ' /></div>';
      } else if (ftype === 'secret') {
        inputHtml = '<div class="input-row">' +
          '<input type="password" id="cfg-field-' + key + '" value="' + (currentVal === '***' ? '' : window.escAttr(currentVal)) + '" placeholder="Leave blank to keep current" autocomplete="off" />' +
          '<button class="eye-btn" onclick="toggleSecretVisibility(\'cfg-field-' + key + '\', this)" title="Toggle visibility">\ud83d\udc41</button></div>';
      } else if (ftype === 'int') {
        inputHtml = '<div class="input-row"><input type="number" id="cfg-field-' + key + '" value="' + window.escAttr(actualVal) + '" /></div>';
      } else {
        inputHtml = '<div class="input-row"><input type="text" id="cfg-field-' + key + '" value="' + window.escAttr(currentVal) + '" /></div>';
      }
      return '<div class="config-field">' +
        '<div class="config-label-row"><label for="cfg-field-' + key + '">' + window.escHtml(label) + '</label>' +
        '<span class="source-badge' + (sourceClass ? ' ' + sourceClass : '') + '">' + sourceLabel + '</span></div>' +
        (desc ? '<div class="description">' + window.escHtml(desc) + '</div>' : '') + inputHtml + '</div>';
    }).join('');
    if (bodyEl) bodyEl.innerHTML = fieldHtml || '<div style="color:var(--muted);padding:10px;">No configurable fields.</div>';
    document.getElementById('modal-module-config').classList.add('open');
  };

  window.toggleSecretVisibility = function(inputId, btn) {
    var input = document.getElementById(inputId);
    if (!input) return;
    if (input.type === 'password') { input.type = 'text'; btn.textContent = '\ud83d\ude48'; }
    else { input.type = 'password'; btn.textContent = '\ud83d\udc41'; }
  };

  // ─── Settings sub-tab switching ──────────────────────────────────────────
  window.switchSettingsTab = function(tab) {
    // Hide all settings tab-panels
    document.querySelectorAll('#page-settings .tab-panel').forEach(function(el) {
      el.style.display = 'none';
    });
    // Deactivate all tab buttons
    document.querySelectorAll('#page-settings .tab-bar .tab-btn').forEach(function(el) {
      el.classList.remove('active');
    });
    // Show selected panel
    var panel = document.getElementById('tab-settings-' + tab);
    if (panel) panel.style.display = '';
    // Activate selected button
    var btn = document.querySelector('#page-settings .tab-bar .tab-btn[data-tab="settings-' + tab + '"]');
    if (btn) btn.classList.add('active');
    // Load tab-specific content
    if (tab === 'users') {
      window.loadUsersPage && window.loadUsersPage();
    }
  };

  window.saveModuleConfig = function() {
    var moduleName = _moduleConfigName;
    if (!moduleName || !_moduleConfigData || !_moduleConfigData[moduleName]) {
      window.showToast('No module selected', null, null, 3000); return;
    }
    var mod = _moduleConfigData[moduleName];
    var schema = mod.schema || {};
    var values = mod.values || {};
    var payload = {};
    Object.keys(schema).forEach(function(key) {
      var field = schema[key];
      var ftype = field.type || 'str';
      var input = document.getElementById('cfg-field-' + key);
      if (!input) return;
      var newVal;
      if (ftype === 'bool') { newVal = input.checked; }
      else if (ftype === 'int') {
        newVal = input.value.trim();
        if (newVal === '') return;
      } else {
        newVal = input.value.trim();
        if (ftype === 'secret' && newVal === '' && values[key] && values[key].display === '***') { return; }
        if (newVal === '') return;
      }
      var currentVal = values[key] ? values[key].value : '';
      if (String(newVal) === String(currentVal)) return;
      payload[key] = newVal;
    });
    if (Object.keys(payload).length === 0) { window.showToast('No changes to save', null, null, 3000); return; }
    var saveBtn = document.getElementById('btn-save-module-config');
    if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Saving\u2026'; }
    window.api('/api/dashboard/module-settings/' + encodeURIComponent(moduleName), {
      method: 'PUT', body: JSON.stringify({ settings: payload })
    }).then(function() {
      window.showToast('Settings saved for ' + moduleName, 'Reload', function() { window.location.reload(); }, 6000);
      window.closeModal('modal-module-config');
      if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Save Settings'; }
      loadModuleConfigs();
    }).catch(function(e) {
      window.showToast('Failed: ' + e.message, null, null, 5000);
      if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Save Settings'; }
    });
  };
})();
