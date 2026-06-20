// ─── LamaDB Dashboard Core App ───────────────────────────────────────
// Core infrastructure: auth, API, SSE, navigation, theme, palette, sidebar, bootstrap
(function() {
  'use strict';

  // ─── Auth helpers ───────────────────────────────────────────────────────────
  var API_KEY_STORAGE = 'lamadb_api_key';

  function getApiKey() {
    return localStorage.getItem(API_KEY_STORAGE);
  }
  function setApiKey(key) {
    localStorage.setItem(API_KEY_STORAGE, key);
  }
  function clearApiKey() {
    localStorage.removeItem(API_KEY_STORAGE);
  }

  // Global key holder for key-created modal
  window._pendingKey = null;

  async function api(path, options) {
    options = options || {};
    var key = getApiKey();
    if (!key) {
      var err = new Error('Unauthorized');
      err.noAuth = true;
      throw err;
    }
    var headers = { 'Content-Type': 'application/json' };
    headers['Authorization'] = 'Bearer ' + key;
    Object.assign(headers, options.headers || {});

    var resp = await fetch(path, Object.assign({ headers: headers }, options));
    if (resp.status === 401) {
      clearApiKey();
      document.body.classList.remove('authenticated');
      showAuthModal();
      throw new Error('Unauthorized');
    }
    if (!resp.ok) {
      var err = new Error('API error: ' + resp.status);
      err.status = resp.status;
      throw err;
    }
    return resp.json();
  }
  window.api = api;

  // ─── Error banner ───────────────────────────────────────────────────────────
  function showError(message) {
    console.error('[LamaDB]', message);
    if (!document.body.classList.contains('authenticated')) return;
    var existing = document.querySelector('.error-banner');
    if (existing) existing.remove();
    var banner = document.createElement('div');
    banner.className = 'error-banner';
    var span = document.createElement('span');
    span.textContent = '⚠ ' + message;
    banner.appendChild(span);
    var closeBtn = document.createElement('button');
    closeBtn.textContent = '✕';
    closeBtn.onclick = function() { banner.remove(); };
    banner.appendChild(closeBtn);
    var mainContent = document.querySelector('.main-body');
    if (mainContent) mainContent.prepend(banner);
  }
  window.showError = showError;

  function clearErrorBanners() {
    document.querySelectorAll('.error-banner').forEach(function(el) { el.remove(); });
  }
  window.clearErrorBanners = clearErrorBanners;

  window.LlamaApp = {
    getApiKey: getApiKey,
    setApiKey: setApiKey,
    clearApiKey: clearApiKey,
    showAuthModal: showAuthModal,
    hideAuthModal: hideAuthModal,
    connectSSE: connectSSE,
    applyTheme: applyTheme,
    applyAccent: applyAccent,
    fetchAndApplyTheme: fetchAndApplyTheme,
    showError: showError
  };

  function showAuthModal() {
    document.body.classList.remove('authenticated');
    document.getElementById('auth-modal').style.display = 'flex';
    document.getElementById('api-key-input').value = '';
    document.getElementById('api-key-error').style.display = 'none';
    document.getElementById('api-key-input').focus();
  }
  function hideAuthModal() {
    document.getElementById('auth-modal').style.display = 'none';
  }

  async function submitApiKey() {
    var key = document.getElementById('api-key-input').value.trim();
    if (!key) return;
    setApiKey(key);
    try {
      await api('/api/dashboard/header');
      document.body.classList.add('authenticated');
      clearErrorBanners();
      hideAuthModal();
      connectSSE();
      fetchAndApplyTheme();
      window.dispatchEvent(new CustomEvent('lamadb:authenticated'));
      navigateTo(currentPage || 'home', true);
    } catch (e) {
      document.getElementById('api-key-error').textContent = 'Invalid API key — access denied.';
      document.getElementById('api-key-error').style.display = 'block';
      clearApiKey();
    }
  }

  // ─── SSE real-time event stream ──────────────────────────────────────────────
  var _sseSource = null;
  function connectSSE() {
    if (_sseSource) { _sseSource.close(); _sseSource = null; }
    var key = getApiKey();
    if (!key) return;
    _sseSource = new EventSource('/api/dashboard/stream?key=' + encodeURIComponent(key));
    _sseSource.addEventListener('event_created', function(e) {
      try { if (window.updateHeader) window.updateHeader(); } catch(ex) {}
    });
    _sseSource.addEventListener('task_update', function(e) {
      try {
        var data = JSON.parse(e.data);
        var pendingEl = document.getElementById('led-agents');
        if (pendingEl && data.status === 'completed') {
          if (window.updateHeader) window.updateHeader();
        }
      } catch(ex) {}
    });
    _sseSource.addEventListener('document_created', function(e) {
      try {
        var data = JSON.parse(e.data);
        if (window.showToast) {
          if (data.action === 'deleted') {
            window.showToast('Document deleted: ' + (data.title || 'Untitled'), 'warning');
          } else if (data.action === 'updated') {
            window.showToast('Document updated: ' + (data.title || 'Untitled'), 'info');
          } else {
            window.showToast('New document: ' + (data.title || 'Untitled'), 'info');
          }
        }
        if (typeof window._currentPage !== 'undefined' && window._currentPage === 'documents' && window.loadDocuments) {
          window.loadDocuments();
        }
      } catch(ex) {}
    });
    _sseSource.addEventListener('monitor_status', function(e) {
      try {
        var data = JSON.parse(e.data);
        if (window.showToast && data.status === 0) {
          window.showToast(data.monitor_name + ' is DOWN', 'error');
        }
        if (typeof window._currentPage !== 'undefined' && window._currentPage === 'uptime' && window.loadUptime) {
          window.loadUptime();
        }
        if (typeof window.updateSidebarBadges === 'function') {
          window.updateSidebarBadges();
        }
        if (window.updateHeader) window.updateHeader();
      } catch(ex) {}
    });
    _sseSource.addEventListener('message', function(e) {
      try {
        var data = JSON.parse(e.data);
        if (data.channel === 'kanban_task_updated' && window._sseCallbacks && window._sseCallbacks['kanban_task_updated']) {
          window._sseCallbacks['kanban_task_updated'](data);
        }
      } catch(ex) {}
    });
    _sseSource.addEventListener('secret_updated', function(e) {
      try {
        if (window._currentPage === 'secrets' && window.loadSecrets) window.loadSecrets();
      } catch(ex) {}
    });
    _sseSource.addEventListener('secret_request_updated', function(e) {
      try {
        if (window._currentPage === 'access-requests' && window.loadAccessRequests) window.loadAccessRequests();
      } catch(ex) {}
    });
    _sseSource.onerror = function() {
      if (_sseSource && _sseSource.readyState === EventSource.CLOSED) {
        _sseSource = null;
      }
    };
  }

  // ─── Theme system ──────────────────────────────────────────────────────────
  var _currentTheme = null;

  function getPreferredTheme() {
    var stored = localStorage.getItem('lamadb_theme');
    if (stored === 'light' || stored === 'dark') return stored;
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
      return 'light';
    }
    return 'dark';
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    _currentTheme = theme;
    var sunIcon = document.getElementById('theme-icon-sun');
    var moonIcon = document.getElementById('theme-icon-moon');
    if (sunIcon && moonIcon) {
      sunIcon.style.display = theme === 'dark' ? 'block' : 'none';
      moonIcon.style.display = theme === 'light' ? 'block' : 'none';
    }
  }

  function initTheme() {
    var theme = getPreferredTheme();
    applyTheme(theme);
    // Apply stored accent on init
    var storedAccent = localStorage.getItem('lamadb_accent');
    if (storedAccent) applyAccent(storedAccent);
    if (window.matchMedia) {
      window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', function(e) {
        var stored = localStorage.getItem('lamadb_theme');
        if (!stored) {
          applyTheme(e.matches ? 'light' : 'dark');
        }
      });
    }
  }

  function applyAccent(accent) {
    document.documentElement.style.setProperty('--accent', accent);
    document.documentElement.style.setProperty('--accent-dim', accent + '20');
    document.documentElement.style.setProperty('--accent-glow', accent + '40');
  }
  window.applyAccent = applyAccent;

  async function fetchAndApplyTheme() {
    try {
      var theme = await api('/api/users/me/theme');
      if (theme && theme.scheme) {
        applyTheme(theme.scheme);
        localStorage.setItem('lamadb_theme', theme.scheme);
      }
      if (theme && theme.accent) {
        applyAccent(theme.accent);
        localStorage.setItem('lamadb_accent', theme.accent);
      }
    } catch (e) {
      var storedAccent = localStorage.getItem('lamadb_accent');
      if (storedAccent) applyAccent(storedAccent);
    }
  }

  window.toggleTheme = function() {
    var newTheme = _currentTheme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('lamadb_theme', newTheme);
    applyTheme(newTheme);
    var accent = localStorage.getItem('lamadb_accent') || '#6366f1';
    api('/api/users/me/theme', {
      method: 'PUT',
      body: JSON.stringify({ scheme: newTheme, accent: accent })
    }).catch(function() {});
  };

  // ─── Command Palette ────────────────────────────────────────────────────────
  var _paletteItems = [];
  var _paletteHighlightIdx = -1;
  var _paletteOpen = false;

  function buildPaletteItems() {
    var items = [];
    var pageList = [
      { id: 'overview', label: 'Overview', icon: 'home' },
      { id: 'documents', label: 'Documents', icon: 'file' },
      { id: 'events', label: 'Events', icon: 'activity' },
      { id: 'feeds', label: 'Feeds', icon: 'rss' },
      { id: 'uptime', label: 'Uptime', icon: 'monitor' },
      { id: 'dozzle', label: 'Dozzle Logs', icon: 'terminal' },
      { id: 'hermes', label: 'Hermes AI', icon: 'cpu' },
      { id: 'agentboard', label: 'Agent Board', icon: 'grid' },
      { id: 'kanban', label: 'Kanban', icon: 'grid' },
      { id: 'freshrss', label: 'FreshRSS', icon: 'rss' },
      { id: 'ntfy', label: 'Ntfy', icon: 'bell' },
      { id: 'notflix', label: 'Notflix', icon: 'film' },
      { id: 'homeassistant', label: 'Home Assistant', icon: 'home' },
      { id: 'wiki', label: 'Wiki', icon: 'book' },
      { id: 'notifications', label: 'Notifications', icon: 'bell' },
      { id: 'settings', label: 'Settings', icon: 'settings' }
    ];
    pageList.forEach(function(p) {
      items.push({ type: 'page', id: p.id, label: p.label, icon: p.icon });
    });
    items.push({ type: 'separator', label: 'Actions' });
    items.push({ type: 'action', id: 'sync', label: 'Sync / Refresh current page', icon: 'refresh' });
    items.push({ type: 'action', id: 'theme', label: 'Toggle theme (dark/light)', icon: 'sun' });
    items.push({ type: 'action', id: 'shortcuts', label: 'Show keyboard shortcuts', icon: 'help' });
    return items;
  }

  function openPalette() {
    if (!getApiKey()) return;
    _paletteItems = buildPaletteItems();
    _paletteHighlightIdx = -1;
    var input = document.getElementById('palette-input');
    if (input) {
      input.value = '';
      input.focus();
    }
    renderPaletteResults(_paletteItems);
    document.getElementById('modal-palette').classList.add('open');
    _paletteOpen = true;
  }

  function closePalette() {
    document.getElementById('modal-palette').classList.remove('open');
    _paletteOpen = false;
  }
  window.openPalette = openPalette;
  window.closePalette = closePalette;

  function renderPaletteResults(items) {
    var el = document.getElementById('palette-results');
    if (!el) return;
    if (items.length === 0) {
      el.innerHTML = '<div class="palette-no-results">No matching pages or commands</div>';
      return;
    }
    el.innerHTML = items.map(function(item, idx) {
      var hl = idx === _paletteHighlightIdx ? ' highlighted' : '';
      if (item.type === 'separator') {
        return '<div class="palette-result-item pri-section">' + item.label + '</div>';
      }
      var iconSvg = '';
      if (item.type === 'page') {
        iconSvg = '<svg class="pri-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>';
      } else {
        iconSvg = '<svg class="pri-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>';
      }
      var hint = item.type === 'page' ? 'Go to page' : '';
      return '<div class="palette-result-item' + hl + '" data-idx="' + idx + '" onclick="window._paletteSelect(' + idx + ')">' +
        iconSvg +
        '<span class="pri-label">' + item.label + '</span>' +
        (hint ? '<span class="pri-hint">' + hint + '</span>' : '') +
        '</div>';
    }).join('');
  }

  function filterPaletteItems(query) {
    var all = buildPaletteItems();
    if (!query) {
      _paletteHighlightIdx = -1;
      return all;
    }
    var q = query.toLowerCase();
    var results = [];
    all.forEach(function(item) {
      if (item.type === 'separator') return;
      if (item.label.toLowerCase().indexOf(q) !== -1) {
        results.push(item);
      }
    });
    if (q.length > 0) {
      results.push({ type: 'action', id: 'search-docs', label: 'Search documents: "' + query + '"', icon: 'search', query: query });
    }
    _paletteHighlightIdx = -1;
    return results.length > 0 ? results : [];
  }

  function navigatePalette(dir) {
    var items = document.querySelectorAll('.palette-result-item:not(.pri-section)');
    if (items.length === 0) return;
    var currentIdx = -1;
    items.forEach(function(el, i) {
      if (el.classList.contains('highlighted')) currentIdx = i;
    });
    var newIdx = currentIdx + dir;
    if (newIdx < 0) newIdx = items.length - 1;
    if (newIdx >= items.length) newIdx = 0;
    items.forEach(function(el) { el.classList.remove('highlighted'); });
    items[newIdx].classList.add('highlighted');
    items[newIdx].scrollIntoView({ block: 'nearest' });
    _paletteHighlightIdx = parseInt(items[newIdx].dataset.idx, 10);
  }

  window._paletteSelect = function(idx) {
    var items = _paletteItems;
    if (idx < 0 || idx >= items.length) return;
    var item = items[idx];
    closePalette();
    if (item.type === 'page') {
      navigateTo(item.id);
    } else if (item.type === 'action') {
      if (item.id === 'sync') {
        navigateTo(currentPage || 'overview');
      } else if (item.id === 'theme') {
        window.toggleTheme();
      } else if (item.id === 'shortcuts') {
        document.getElementById('shortcut-overlay').classList.add('open');
      } else if (item.id === 'search-docs') {
        navigateTo('documents');
        setTimeout(function() {
          var filterInput = document.getElementById('doc-filter-input');
          if (filterInput) {
            filterInput.value = item.query || '';
            window.docFilterInput();
          }
        }, 100);
      }
    }
  };

  // ─── Navigation ─────────────────────────────────────────────────────────────
  var newPages = Array.from(document.querySelectorAll('.app-page')).reduce(function(acc, el) {
    acc[el.dataset.page] = el;
    return acc;
  }, {});

  var titles = {
    'home': 'Home',
    'overview': 'Overview',
    'feeds': 'Feeds',
    'uptime': 'Uptime',
    'events': 'Events',
    'wiki': 'Wiki',
    'documents': 'Documents',
    'ntfy': 'Ntfy',
    'dozzle': 'Dozzle',
    'freshrss': 'FreshRSS',
    'agentboard': 'Agent Board',
    'kanban': 'Kanban',
    'notflix': 'Notflix',
    'homeassistant': 'Home Assistant',
    'hermes': 'Hermes',
    'settings': 'Settings',
    'notifications': 'Notifications',
    'search': 'Search',
    'secrets': 'Secrets',
    'access-requests': 'Access Requests',
    'groups': 'Groups'
  };
  var currentPage = 'home';

  window.navigateTo = function(pageId, force) {
    if (!pageId) return;
    if (pageId === currentPage && !force) return;
    if (!getApiKey()) {
      showAuthModal();
      return;
    }
    clearErrorBanners();
    document.querySelectorAll('.app-sidebar .nav-item, .mobile-nav .nav-item').forEach(function(el) {
      el.classList.toggle('active', el.dataset.page === pageId);
    });

    // New pages
    var isNewPage = pageId === 'home' || pageId === 'notifications';
    Object.keys(newPages).forEach(function(key) {
      newPages[key].classList.toggle('active', key === pageId);
    });

    // Legacy pages
    var legacyWrapper = document.querySelector('.legacy-page');
    if (legacyWrapper) {
      legacyWrapper.classList.toggle('active', !isNewPage);
      legacyWrapper.querySelectorAll('.page').forEach(function(el) {
        el.classList.remove('page-active');
      });
      if (!isNewPage) {
        var target = document.getElementById('page-' + pageId);
        if (target) target.classList.add('page-active');
      }
    }

    var titleEl = document.getElementById('page-title');
    if (titleEl) titleEl.textContent = titles[pageId] || pageId;
    currentPage = pageId;
    window._currentPage = pageId;

    if (pageId === 'home') window.loadHome && window.loadHome();
    else if (pageId === 'overview') window.loadOverview && window.loadOverview();
    else if (pageId === 'notifications') window.loadNotificationsPage && window.loadNotificationsPage();
    else if (pageId === 'feeds') window.loadFeeds && window.loadFeeds();
    else if (pageId === 'uptime') window.loadUptime && window.loadUptime();
    else if (pageId === 'events') window.loadEvents && window.loadEvents();
    else if (pageId === 'hermes') window.loadHermesPage && window.loadHermesPage();
    else if (pageId === 'wiki') window.loadWiki && window.loadWiki();
    else if (pageId === 'documents') window.loadDocuments && window.loadDocuments();
    else if (pageId === 'ntfy') window.loadNtfyPage && window.loadNtfyPage();
    else if (pageId === 'dozzle') window.loadDozzlePage && window.loadDozzlePage();
    else if (pageId === 'freshrss') window.loadFreshrssPage && window.loadFreshrssPage();
    else if (pageId === 'agentboard') window.loadAgentBoardPage && window.loadAgentBoardPage();
    else if (pageId === 'kanban') window.loadKanbanPage && window.loadKanbanPage();
    else if (pageId === 'notflix') window.loadNotflixPage && window.loadNotflixPage();
    else if (pageId === 'homeassistant') window.loadHomeAssistantPage && window.loadHomeAssistantPage();
    else if (pageId === 'settings') window.loadSettings && window.loadSettings();
    else if (pageId === 'search') window.loadSearch && window.loadSearch();
    else if (pageId === 'secrets') window.loadSecrets && window.loadSecrets();
    else if (pageId === 'access-requests') window.loadAccessRequestsPage && window.loadAccessRequestsPage();
    else if (pageId === 'groups') window.loadGroups && window.loadGroups();

    window.updateSidebarBadges && window.updateSidebarBadges();
  };

  // ─── Modals ─────────────────────────────────────────────────────────────────
  window.closeModal = function(id) {
    var el = document.getElementById(id);
    if (el) el.classList.remove('open');
  };

  window.closeModuleConfigForm = function() {
    window.closeModal('modal-module-config');
  };

  // ─── Mobile bottom nav ──────────────────────────────────────────────────────
  function initMobileNav() {
    document.querySelectorAll('.mobile-nav .nav-item').forEach(function(el) {
      el.addEventListener('click', function() {
        var pageId = this.dataset.page;
        window.navigateTo(pageId);
        document.querySelectorAll('.mobile-nav .nav-item').forEach(function(n) {
          n.classList.toggle('active', n.dataset.page === pageId);
        });
      });
    });
  }

  // ─── Sidebar quick search ───────────────────────────────────────────────────
  window.handleSidebarSearch = function(e) {
    if (e.key === 'Enter') {
      var q = e.target.value.trim();
      if (!q) return;
      window.navigateTo('documents');
      var searchInput = document.getElementById('doc-filter-input');
      if (searchInput) {
        searchInput.value = q;
        if (window._docFilter !== undefined) {
          window._docFilter = q;
          window.loadDocuments && window.loadDocuments();
        }
      }
      e.target.value = '';
      e.target.blur();
    }
    if (e.key === 'Escape') {
      e.target.value = '';
      e.target.blur();
    }
  };

  // ─── Sidebar categories ────────────────────────────────────────────────────
  function initSidebarCategories() {
    var cats = ['core', 'monitoring', 'datasources', 'admin', 'security'];
    cats.forEach(function(cat) {
      var stored = localStorage.getItem('sidebar_cat_' + cat);
      var items = document.getElementById('items-' + cat);
      var chevron = document.getElementById('chevron-' + cat);
      if (!items || !chevron) return;
      var isCollapsed = stored === 'collapsed';
      if (isCollapsed) {
        items.classList.add('collapsed');
      } else {
        chevron.classList.add('open');
      }
    });
  }

  window.toggleSidebarCategory = function(cat) {
    var items = document.getElementById('items-' + cat);
    var chevron = document.getElementById('chevron-' + cat);
    if (!items || !chevron) return;
    var isNowCollapsed = !items.classList.contains('collapsed');
    items.classList.toggle('collapsed', isNowCollapsed);
    chevron.classList.toggle('open', !isNowCollapsed);
    localStorage.setItem('sidebar_cat_' + cat, isNowCollapsed ? 'collapsed' : 'open');
  };

  function setBadge(id, text, cssClass) {
    var badge = document.getElementById(id);
    if (!badge) return;
    badge.textContent = text;
    if (cssClass) {
      badge.className = 'cat-badge has-items ' + cssClass;
    } else {
      badge.className = 'cat-badge';
    }
  }

  function updateSidebarBadges() {
    // Monitoring: count of DOWN services
    api('/api/uptime/status').then(function(status) {
      var down = (status || []).filter(function(m) { return m.status === 0; }).length;
      setBadge('badge-monitoring', down > 0 ? down + ' down' : '', down > 0 ? 'alert' : '');
    }).catch(function() {});

    // Core: count of error events in the last hour
    api('/api/events?severity=error&limit=50').then(function(events) {
      var errors = (events || []).filter(function(e) {
        var ts = new Date(e.ts);
        var hourAgo = new Date(Date.now() - 3600000);
        return ts > hourAgo;
      }).length;
      setBadge('badge-core', errors > 0 ? errors + ' err' : '', errors > 0 ? 'alert' : '');
    }).catch(function() {});

    // Data Sources: aggregated warnings from collector modules
    api('/api/dashboard/module-health').then(function(health) {
      var modules = health.modules || [];
      var warnCount = modules.filter(function(m) {
        return m.status === 'red' || m.status === 'yellow';
      }).length;
      setBadge('badge-datasources', warnCount > 0 ? warnCount + ' issue' + (warnCount > 1 ? 's' : '') : '', warnCount > 0 ? 'alert' : '');
    }).catch(function() {});

    // Admin: count of stale API keys (no usage in 30 days)
    api('/api/dashboard/api-keys/stats').then(function(stats) {
      var stale = stats.stale || 0;
      setBadge('badge-admin', stale > 0 ? stale + ' stale' : '', stale > 0 ? 'alert' : '');
    }).catch(function() {});
  }

  // ─── Shortcut help ──────────────────────────────────────────────────────────
  window.showShortcutHelp = function() {
    var overlay = document.getElementById('shortcut-overlay');
    if (overlay) overlay.classList.add('open');
  };

  window.closeShortcutHelp = function() {
    var overlay = document.getElementById('shortcut-overlay');
    if (overlay) overlay.classList.remove('open');
  };

  // ─── Keyboard shortcut handler (Cmd+K, g+d, ?, /) ──────────────────────────
  var _keyBuffer = '';
  var _keyBufferTimer = null;

  document.addEventListener('keydown', function(e) {
    // Ignore when typing in inputs
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;

    // ? → show shortcut help
    if (e.key === '?' && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      window.showShortcutHelp();
      return;
    }

    // / → focus sidebar search
    if (e.key === '/' && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      var searchInput = document.getElementById('sidebar-quick-search');
      if (searchInput) { searchInput.focus(); searchInput.select(); }
      return;
    }

    // Sequence shortcuts: g <key>
    if (e.key === 'g' && !e.ctrlKey && !e.metaKey) {
      _keyBuffer = 'g';
      if (_keyBufferTimer) clearTimeout(_keyBufferTimer);
      _keyBufferTimer = setTimeout(function() { _keyBuffer = ''; }, 1000);
      return;
    }

    if (_keyBuffer === 'g') {
      if (_keyBufferTimer) clearTimeout(_keyBufferTimer);
      _keyBuffer = '';
      var pageMap = {
        'd': 'documents',
        'e': 'events',
        's': 'settings',
        'u': 'uptime',
        'f': 'feeds',
        'o': 'overview',
        'w': 'wiki',
        'n': 'notifications',
        'h': 'hermes',
        'm': 'homeassistant',
        'a': 'agentboard',
        'k': 'kanban',
        'q': 'search'
      };
      var target = pageMap[e.key];
      if (target) {
        e.preventDefault();
        window.navigateTo(target);
      }
    }
  });

  // ─── Bootstrap ──────────────────────────────────────────────────────────────
  function bootstrap() {
    // Theme init
    initTheme();

    // Mobile nav
    initMobileNav();

    // Nav items
    document.querySelectorAll('.nav-item').forEach(function(item) {
      item.addEventListener('click', function() {
        window.navigateTo(this.dataset.page);
      });
    });

    // Sync button
    var syncBtn = document.getElementById('btn-sync');
    if (syncBtn) {
      syncBtn.addEventListener('click', function() {
        window.navigateTo(currentPage || 'overview');
      });
    }

    // Modal overlay click to close
    document.querySelectorAll('.modal-overlay').forEach(function(el) {
      el.addEventListener('click', function(e) {
        if (e.target === this) {
          this.classList.remove('open');
          if (this.id === 'modal-palette') _paletteOpen = false;
        }
      });
    });

    // Auth modal submit
    var apiKeySubmit = document.getElementById('api-key-submit');
    if (apiKeySubmit) {
      apiKeySubmit.addEventListener('click', submitApiKey);
    }
    var apiKeyInput = document.getElementById('api-key-input');
    if (apiKeyInput) {
      apiKeyInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') submitApiKey();
      });
    }

    // Palette keyboard events
    var paletteInput = document.getElementById('palette-input');
    if (paletteInput) {
      paletteInput.addEventListener('input', function() {
        var q = this.value.trim();
        _paletteItems = filterPaletteItems(q);
        renderPaletteResults(_paletteItems);
      });
    }

    // Keyboard shortcut handler for Cmd+K, palette navigation
    document.addEventListener('keydown', function(e) {
      // Cmd+K or Ctrl+K
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        if (_paletteOpen) {
          closePalette();
        } else {
          openPalette();
        }
        return;
      }
      // Escape closes palette
      if (e.key === 'Escape' && _paletteOpen) {
        closePalette();
        return;
      }
      // Arrow keys in palette
      if (_paletteOpen && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
        e.preventDefault();
        navigatePalette(e.key === 'ArrowDown' ? 1 : -1);
        return;
      }
      // Enter in palette
      if (_paletteOpen && e.key === 'Enter') {
        e.preventDefault();
        var highlighted = document.querySelector('.palette-result-item.highlighted:not(.pri-section)');
        if (highlighted && highlighted.dataset.idx !== undefined) {
          window._paletteSelect(parseInt(highlighted.dataset.idx, 10));
        } else {
          var first = document.querySelector('.palette-result-item:not(.pri-section)');
          if (first && first.dataset.idx !== undefined) {
            window._paletteSelect(parseInt(first.dataset.idx, 10));
          }
        }
        return;
      }
      // / to focus sidebar search (or open palette if mobile)
      if (e.key === '/' && !_paletteOpen && !e.ctrlKey && !e.metaKey) {
        var tag = e.target && e.target.tagName;
        if (tag !== 'INPUT' && tag !== 'TEXTAREA') {
          if (window.innerWidth < 768) {
            e.preventDefault();
            openPalette();
          } else {
            var searchInput = document.getElementById('sidebar-quick-search');
            if (searchInput) {
              e.preventDefault();
              searchInput.focus();
            }
          }
        }
      }
    });

    // If no API key stored, show auth modal immediately
    if (!getApiKey()) {
      showAuthModal();
    } else {
      api('/api/dashboard/header').then(function() {
        document.body.classList.add('authenticated');
        clearErrorBanners();
        window.navigateTo('home', true);
        connectSSE();
        fetchAndApplyTheme();
        window.dispatchEvent(new CustomEvent('lamadb:authenticated'));
      }).catch(function() {
        showAuthModal();
      });
    }

    // Sidebar init
    initSidebarCategories();
    setTimeout(updateSidebarBadges, 2000);

    // Close shortcut overlay on background click
    document.addEventListener('click', function(e) {
      var overlay = document.getElementById('shortcut-overlay');
      if (overlay && overlay.classList.contains('open') && e.target === overlay) {
        overlay.classList.remove('open');
      }
    });
  }

  // Run bootstrap now or on DOMContentLoaded
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootstrap);
  } else {
    bootstrap();
  }

})();
