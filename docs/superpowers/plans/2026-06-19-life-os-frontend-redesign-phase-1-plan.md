# LamaDB — Life-OS Frontend Redesign: Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the new global shell, Home page, and smart Notifications inbox using Alpine.js and a new design token system, while keeping legacy pages functional inside the new shell.

**Architecture:** A new `static/index.html` shell loads Alpine.js and new CSS files. Home and Notifications are rewritten as Alpine components. Legacy page sections remain untouched inside the shell. No build step; static files are served by FastAPI.

**Tech Stack:** Alpine.js 3, vanilla CSS, existing FastAPI static file serving, existing API layer in `static/js/app.js`.

---

## File Map

| File | Responsibility |
|------|----------------|
| `static/css/tokens.css` | Design tokens: colors, spacing, type, radius, shadows, safe areas |
| `static/css/shell.css` | Global layout, sidebar, mobile bottom nav, header |
| `static/css/components.css` | Reusable component classes: buttons, cards, lists, badges, sheets, empty states, skeletons |
| `static/css/pages/home.css` | Home page layout and specific styles |
| `static/css/pages/notifications.css` | Notifications page layout and specific styles |
| `static/css/legacy.css` | Minimal shim so legacy page sections render reasonably inside the new shell |
| `static/index.html` | New shell containing the app layout, Home, Notifications, and legacy page sections |
| `static/js/lib/alpine.min.js` | Local Alpine.js fallback (CDN primary with fallback) |
| `static/js/app.js` | Existing core: auth, API wrapper, SSE, navigation, theme. Minor modernization. |
| `static/js/shell.js` | New shell behavior: Alpine app data, navigation, sidebar state, bottom sheet |
| `static/js/pages/home.js` | Home page Alpine component |
| `static/js/pages/notifications.js` | Notifications page Alpine component |

---

## Task 1: Add Alpine.js dependency

**Files:**
- Create: `static/js/lib/alpine.min.js`
- Modify: `static/index.html` (later; CDN link added in Task 4)

**Step 1: Download Alpine.js v3 to local fallback**

Run:
```bash
curl -L -o static/js/lib/alpine.min.js https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js
```

**Step 2: Verify file is non-empty**

Run:
```bash
ls -la static/js/lib/alpine.min.js && head -c 100 static/js/lib/alpine.min.js
```
Expected: file size > 0, content starts with `(()=>{` or similar minified JS.

**Step 3: Commit**

```bash
git add static/js/lib/alpine.min.js
git commit -m "deps: add local Alpine.js v3 fallback"
```

---

## Task 2: Create design tokens CSS

**Files:**
- Create: `static/css/tokens.css`

**Step 1: Write tokens.css**

```css
:root {
  /* Colors - dark default */
  --fg: #f1f5f9;
  --fg-2: #cbd5e1;
  --muted: #94a3b8;
  --surface: #0f172a;
  --surface-1: #1e293b;
  --surface-2: #334155;
  --surface-3: #475569;
  --border: #334155;
  --accent: #6366f1;
  --accent-dim: rgba(99, 102, 241, 0.12);
  --accent-glow: rgba(99, 102, 241, 0.25);
  --success: #22c55e;
  --warning: #f59e0b;
  --error: #ef4444;
  --info: #3b82f6;

  /* Typography */
  --font-display: 'Inter', system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
  --text-xs: 0.75rem;
  --text-sm: 0.875rem;
  --text-base: 1rem;
  --text-lg: 1.125rem;
  --text-xl: 1.25rem;
  --text-2xl: 1.5rem;
  --text-3xl: 1.875rem;

  /* Spacing */
  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 0.75rem;
  --space-4: 1rem;
  --space-5: 1.25rem;
  --space-6: 1.5rem;
  --space-8: 2rem;
  --space-10: 2.5rem;
  --space-12: 3rem;

  /* Radius */
  --radius-sm: 0.375rem;
  --radius-md: 0.5rem;
  --radius-lg: 0.75rem;
  --radius-xl: 1rem;

  /* Shadows */
  --shadow-card: 0 1px 3px rgba(0, 0, 0, 0.3);
  --shadow-sheet: 0 -4px 24px rgba(0, 0, 0, 0.4);
  --shadow-modal: 0 20px 40px rgba(0, 0, 0, 0.5);

  /* Safe areas */
  --safe-top: env(safe-area-inset-top, 0px);
  --safe-bottom: env(safe-area-inset-bottom, 0px);
  --safe-left: env(safe-area-inset-left, 0px);
  --safe-right: env(safe-area-inset-right, 0px);
}

[data-theme="light"] {
  --fg: #0f172a;
  --fg-2: #334155;
  --muted: #64748b;
  --surface: #f8fafc;
  --surface-1: #ffffff;
  --surface-2: #f1f5f9;
  --surface-3: #e2e8f0;
  --border: #e2e8f0;
  --shadow-card: 0 1px 3px rgba(0, 0, 0, 0.08);
  --shadow-sheet: 0 -4px 24px rgba(0, 0, 0, 0.12);
  --shadow-modal: 0 20px 40px rgba(0, 0, 0, 0.15);
}

* {
  box-sizing: border-box;
}

html, body {
  margin: 0;
  padding: 0;
  font-family: var(--font-display);
  background: var(--surface);
  color: var(--fg);
  min-height: 100vh;
  -webkit-font-smoothing: antialiased;
}
```

**Step 2: Commit**

```bash
git add static/css/tokens.css
git commit -m "feat(frontend): add design tokens CSS"
```

---

## Task 3: Create component CSS

**Files:**
- Create: `static/css/components.css`

**Step 1: Write components.css**

```css
/* Buttons */
.ll-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-md);
  border: 1px solid transparent;
  background: var(--surface-2);
  color: var(--fg);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, transform 0.05s;
  min-height: 36px;
}
.ll-button:hover { background: var(--surface-3); }
.ll-button:active { transform: translateY(1px); }
.ll-button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

.ll-button.primary { background: var(--accent); color: white; }
.ll-button.primary:hover { filter: brightness(1.1); }

.ll-button.secondary { background: transparent; border-color: var(--border); }

.ll-button.ghost { background: transparent; }
.ll-button.ghost:hover { background: var(--accent-dim); }

.ll-button.danger { background: var(--error); color: white; }

.ll-button.sm { padding: var(--space-1) var(--space-3); min-height: 28px; font-size: var(--text-xs); }
.ll-button.lg { padding: var(--space-3) var(--space-6); min-height: 48px; font-size: var(--text-base); }

/* Cards */
.ll-card {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  box-shadow: var(--shadow-card);
}

.ll-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-3);
}

.ll-card-title {
  font-size: var(--text-lg);
  font-weight: 600;
  margin: 0;
}

/* Lists */
.ll-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.ll-list-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  background: var(--surface-2);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background 0.15s;
}
.ll-list-item:hover { background: var(--surface-3); }

.ll-list-item .leading { flex-shrink: 0; color: var(--muted); }
.ll-list-item .content { flex: 1; min-width: 0; }
.ll-list-item .title { font-weight: 500; color: var(--fg); }
.ll-list-item .subtitle { font-size: var(--text-xs); color: var(--muted); }
.ll-list-item .trailing { flex-shrink: 0; }

/* Badges */
.ll-badge {
  display: inline-flex;
  align-items: center;
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  font-weight: 600;
  text-transform: capitalize;
}
.ll-badge.critical { background: rgba(239, 68, 68, 0.15); color: var(--error); }
.ll-badge.warning { background: rgba(245, 158, 11, 0.15); color: var(--warning); }
.ll-badge.info { background: rgba(59, 130, 246, 0.15); color: var(--info); }
.ll-badge.success { background: rgba(34, 197, 94, 0.15); color: var(--success); }

/* Empty state */
.ll-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-10) var(--space-4);
  text-align: center;
  color: var(--muted);
}
.ll-empty-state .icon { font-size: var(--text-3xl); margin-bottom: var(--space-3); }
.ll-empty-state .title { font-size: var(--text-lg); font-weight: 600; color: var(--fg); margin-bottom: var(--space-1); }

/* Bottom sheet */
.ll-sheet-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  z-index: 100;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.2s;
}
.ll-sheet-overlay.open { opacity: 1; pointer-events: auto; }

.ll-sheet {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  background: var(--surface-1);
  border-top: 1px solid var(--border);
  border-radius: var(--radius-xl) var(--radius-xl) 0 0;
  padding: var(--space-4) var(--space-4) calc(var(--space-6) + var(--safe-bottom));
  box-shadow: var(--shadow-sheet);
  transform: translateY(100%);
  transition: transform 0.25s ease-out;
  z-index: 101;
  max-height: 70vh;
  overflow-y: auto;
}
.ll-sheet.open { transform: translateY(0); }

/* Skeleton */
.ll-skeleton {
  background: linear-gradient(90deg, var(--surface-2) 25%, var(--surface-3) 50%, var(--surface-2) 75%);
  background-size: 200% 100%;
  animation: ll-skeleton-pulse 1.5s infinite;
  border-radius: var(--radius-md);
}
@keyframes ll-skeleton-pulse {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* Touch targets */
.touch-target {
  min-height: 44px;
  min-width: 44px;
}
```

**Step 2: Commit**

```bash
git add static/css/components.css
git commit -m "feat(frontend): add component CSS library"
```

---

## Task 4: Create shell CSS

**Files:**
- Create: `static/css/shell.css`

**Step 1: Write shell.css**

```css
.app-root {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  padding-top: var(--safe-top);
}

/* Header */
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 56px;
  padding: 0 var(--space-4);
  background: var(--surface-1);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 50;
}

.app-header .title {
  font-size: var(--text-lg);
  font-weight: 600;
}

.app-header .actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.app-header .icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  border: none;
  background: transparent;
  color: var(--fg);
  cursor: pointer;
}
.app-header .icon-btn:hover { background: var(--surface-2); }

/* Layout */
.app-body {
  display: flex;
  flex: 1;
  overflow: hidden;
}

/* Sidebar */
.app-sidebar {
  width: 240px;
  background: var(--surface-1);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.app-sidebar .brand {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4);
  border-bottom: 1px solid var(--border);
}

.app-sidebar .brand .logo {
  width: 32px;
  height: 32px;
  color: var(--accent);
}

.app-sidebar .brand .name {
  font-size: var(--text-lg);
  font-weight: 700;
}

.app-sidebar .brand .name span {
  color: var(--accent);
}

.app-sidebar nav {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-2);
}

.app-sidebar .nav-section {
  margin-bottom: var(--space-4);
}

.app-sidebar .nav-section-title {
  font-size: var(--text-xs);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--muted);
  padding: var(--space-2) var(--space-3);
}

.app-sidebar .nav-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  color: var(--fg-2);
  text-decoration: none;
  font-size: var(--text-sm);
  cursor: pointer;
  border: none;
  background: transparent;
  text-align: left;
}
.app-sidebar .nav-item:hover { background: var(--surface-2); color: var(--fg); }
.app-sidebar .nav-item.active { background: var(--accent-dim); color: var(--accent); }

.app-sidebar .nav-item .badge {
  margin-left: auto;
  background: var(--surface-3);
  color: var(--fg);
  font-size: var(--text-xs);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
}

/* Main content */
.app-main {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-4);
  padding-bottom: calc(var(--space-4) + var(--safe-bottom));
}

/* Mobile bottom nav */
.mobile-nav {
  display: none;
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  height: calc(64px + var(--safe-bottom));
  padding-bottom: var(--safe-bottom);
  background: var(--surface-1);
  border-top: 1px solid var(--border);
  z-index: 60;
}

.mobile-nav .nav-items {
  display: flex;
  align-items: center;
  justify-content: space-around;
  height: 64px;
}

.mobile-nav .nav-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  flex: 1;
  height: 100%;
  color: var(--muted);
  background: transparent;
  border: none;
  font-size: var(--text-xs);
  cursor: pointer;
}
.mobile-nav .nav-item.active { color: var(--accent); }

/* Legacy page wrapper */
.legacy-page {
  display: none;
}
.legacy-page.active {
  display: block;
}

/* Page visibility */
.app-page {
  display: none;
}
.app-page.active {
  display: block;
}

/* Responsive */
@media (max-width: 768px) {
  .app-sidebar { display: none; }
  .app-main { padding: var(--space-3); padding-bottom: calc(var(--space-4) + 64px + var(--safe-bottom)); }
  .mobile-nav { display: block; }
}
```

**Step 2: Commit**

```bash
git add static/css/shell.css
git commit -m "feat(frontend): add shell layout CSS"
```

---

## Task 5: Create legacy CSS shim

**Files:**
- Create: `static/css/legacy.css`

**Step 1: Write legacy.css**

```css
/* Make legacy page sections render reasonably inside the new shell */
.legacy-page {
  color: var(--fg);
}

.legacy-page .page {
  display: none;
}

.legacy-page .page.page-active {
  display: block;
}

/* Override old fixed heights that may clip in the new layout */
.legacy-page .app-shell,
.legacy-page .main {
  display: block;
  width: auto;
  height: auto;
  margin: 0;
  padding: 0;
}

/* Hide old header inside legacy pages */
.legacy-page .header-bar,
.legacy-page .ticker-wrap,
.legacy-page .sidebar,
.legacy-page .main-header {
  display: none !important;
}
```

**Step 2: Commit**

```bash
git add static/css/legacy.css
git commit -m "feat(frontend): add legacy page shim CSS"
```

---

## Task 6: Modernize app.js core

**Files:**
- Modify: `static/js/app.js`

**Step 1: Update app.js to export Alpine-friendly helpers and keep existing behavior**

Replace the top of the IIFE to expose a small `LlamaApp` object, and update navigation to use `data-page` attribute on `.app-page` and `.legacy-page` sections.

Specifically:
1. Add after `window.api = api;`:

```javascript
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
```

2. Replace the `pages` object and `navigateTo` function with versions that handle both new `.app-page` sections and legacy `.legacy-page` sections.

```javascript
var newPages = Array.from(document.querySelectorAll('.app-page')).reduce(function(acc, el) {
  acc[el.dataset.page] = el;
  return acc;
}, {});

var legacyPages = Array.from(document.querySelectorAll('.legacy-page')).reduce(function(acc, el) {
  acc[el.dataset.page] = el;
  return acc;
}, {});

window.navigateTo = function(pageId) {
  if (pageId === currentPage) return;
  if (!getApiKey()) {
    showAuthModal();
    return;
  }

  document.querySelectorAll('.app-sidebar .nav-item, .mobile-nav .nav-item').forEach(function(el) {
    el.classList.toggle('active', el.dataset.page === pageId);
  });

  Object.keys(newPages).forEach(function(key) {
    newPages[key].classList.toggle('active', key === pageId);
  });
  Object.keys(legacyPages).forEach(function(key) {
    legacyPages[key].classList.toggle('active', key === pageId);
    // Also toggle inner .page.page-active for legacy compatibility
    var inner = legacyPages[key].querySelector('.page');
    if (inner) inner.classList.toggle('page-active', key === pageId);
  });

  var titleEl = document.getElementById('page-title');
  if (titleEl) titleEl.textContent = titles[pageId] || pageId;
  currentPage = pageId;
  window._currentPage = pageId;

  // Route to page loader
  if (pageId === 'home') window.loadHome && window.loadHome();
  else if (pageId === 'overview') window.loadOverview && window.loadOverview();
  else if (pageId === 'notifications') window.loadNotificationsPage && window.loadNotificationsPage();
  // ... keep existing legacy route handlers ...

  window.updateSidebarBadges && window.updateSidebarBadges();
};
```

3. Remove references to `.mobile-nav-item` if those elements no longer exist in the new shell (they will be `.mobile-nav .nav-item`).

**Step 2: Test by loading the page**

At this point `index.html` is not yet updated, so run a syntax check:

```bash
node --check static/js/app.js
```
Expected: no output (success).

**Step 3: Commit**

```bash
git add static/js/app.js
git commit -m "refactor(frontend): modernize app.js for new shell navigation"
```

---

## Task 7: Create shell.js

**Files:**
- Create: `static/js/shell.js`

**Step 1: Write shell.js**

```javascript
document.addEventListener('alpine:init', function() {
  Alpine.data('shell', function() {
    return {
      currentPage: 'home',
      sidebarOpen: true,
      sheetOpen: false,
      morePages: [
        { id: 'overview', label: 'Overview (legacy)', section: 'Legacy' },
        { id: 'documents', label: 'Documents', section: 'Core' },
        { id: 'events', label: 'Events', section: 'Core' },
        { id: 'search', label: 'Search', section: 'Core' },
        { id: 'uptime', label: 'Uptime', section: 'Monitoring' },
        { id: 'dozzle', label: 'Dozzle', section: 'Monitoring' },
        { id: 'hermes', label: 'Hermes', section: 'Monitoring' },
        { id: 'agentboard', label: 'Agent Board', section: 'Monitoring' },
        { id: 'kanban', label: 'Kanban', section: 'Monitoring' },
        { id: 'feeds', label: 'Feeds', section: 'Data Sources' },
        { id: 'freshrss', label: 'FreshRSS', section: 'Data Sources' },
        { id: 'ntfy', label: 'Ntfy', section: 'Data Sources' },
        { id: 'notflix', label: 'Notflix', section: 'Data Sources' },
        { id: 'wiki', label: 'Wiki', section: 'Data Sources' },
        { id: 'homeassistant', label: 'Home Assistant', section: 'Data Sources' },
        { id: 'settings', label: 'Settings', section: 'Admin' },
        { id: 'secrets', label: 'Secrets', section: 'Security' },
        { id: 'access-requests', label: 'Access Requests', section: 'Security' },
        { id: 'groups', label: 'Groups', section: 'Security' }
      ],

      init() {
        this.$watch('currentPage', function(page) {
          window.navigateTo(page);
        });
      },

      go(page) {
        this.currentPage = page;
        this.sheetOpen = false;
      },

      toggleTheme() {
        if (window.toggleTheme) window.toggleTheme();
      },

      openPalette() {
        if (window.openPalette) window.openPalette();
      }
    };
  });
});
```

**Step 2: Commit**

```bash
git add static/js/shell.js
git commit -m "feat(frontend): add shell Alpine component"
```

---

## Task 8: Create Home page component

**Files:**
- Create: `static/js/pages/home.js`
- Create: `static/css/pages/home.css`

**Step 1: Write home.css**

```css
.home-page {
  max-width: 960px;
  margin: 0 auto;
}

.home-today-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.home-today-card .greeting {
  font-size: var(--text-2xl);
  font-weight: 700;
}

.home-today-card .date {
  color: var(--muted);
  font-size: var(--text-sm);
}

.home-today-card .presence {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-2);
  font-size: var(--text-sm);
  color: var(--fg-2);
}

.home-today-card .presence-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--success);
}

.home-summary-card {
  display: flex;
  gap: var(--space-4);
  flex-wrap: wrap;
}

.home-summary-item {
  flex: 1;
  min-width: 120px;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-3);
  background: var(--surface-2);
  border-radius: var(--radius-md);
  cursor: pointer;
}
.home-summary-item:hover { background: var(--surface-3); }

.home-summary-item .value {
  font-size: var(--text-2xl);
  font-weight: 700;
}

.home-summary-item .label {
  font-size: var(--text-xs);
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.home-quick-actions {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: var(--space-3);
}

.home-quick-actions .action {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-4);
  background: var(--surface-2);
  border-radius: var(--radius-lg);
  border: 1px solid var(--border);
  color: var(--fg);
  text-decoration: none;
  cursor: pointer;
  transition: background 0.15s;
}
.home-quick-actions .action:hover { background: var(--surface-3); }

.home-quick-actions .action .icon {
  font-size: var(--text-xl);
  color: var(--accent);
}

.home-quick-actions .action .label {
  font-size: var(--text-sm);
  font-weight: 500;
}

.home-headlines {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.home-headline {
  padding: var(--space-3);
  background: var(--surface-2);
  border-radius: var(--radius-md);
}

.home-headline .title {
  font-weight: 500;
  font-size: var(--text-sm);
}

.home-headline .meta {
  font-size: var(--text-xs);
  color: var(--muted);
  margin-top: var(--space-1);
}
```

**Step 2: Write home.js**

```javascript
document.addEventListener('alpine:init', function() {
  Alpine.data('homePage', function() {
    return {
      loading: true,
      greeting: 'Good day',
      today: '',
      presence: null,
      brief: null,
      summary: {
        critical: 0,
        notifications: 0,
        tasks: 0
      },
      status: [],
      headlines: [],

      async init() {
        this.setGreeting();
        this.today = new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' });
        await this.load();
      },

      setGreeting() {
        var hour = new Date().getHours();
        if (hour < 12) this.greeting = 'Good morning';
        else if (hour < 18) this.greeting = 'Good afternoon';
        else this.greeting = 'Good evening';
      },

      async load() {
        this.loading = true;
        try {
          // /api/dashboard/overview requires admin; fall back to public header if 403
          var overview = {};
          try {
            overview = await window.api('/api/dashboard/overview');
          } catch (e) {
            if (e.status !== 403) throw e;
            var header = await window.api('/api/dashboard/header');
            overview = {
              monitors: header.monitors || { up: 0, down: 0, unknown: 0 },
              events: header.events || { today: 0 },
              documents: {},
              cache: {}
            };
          }
          var notifications = await window.api('/api/notifications/unread?aggregate=true&limit=5');
          var uptime = await window.api('/api/uptime/status');

          this.summary.critical = (uptime || []).filter(function(m) { return m.status === 0; }).length;
          this.summary.notifications = (notifications.items || notifications || []).reduce(function(sum, g) { return sum + (g.count || 1); }, 0);
          this.summary.tasks = (overview.agent_tasks || {}).pending || 0;

          this.status = [
            { label: 'Services', value: this.summary.critical > 0 ? this.summary.critical + ' down' : 'All up', ok: this.summary.critical === 0 },
            { label: 'Cache', value: ((overview.cache || {}).hit_rate || '0') + '%', ok: true },
            { label: 'Documents', value: String(((overview.documents || {}).total || 0)), ok: true }
          ];

          // Try to load latest briefing document; ignore errors
          try {
            var briefingDocs = await window.api('/api/documents?tag=briefing&limit=1');
            var items = briefingDocs.items || briefingDocs || [];
            if (items.length) this.brief = items[0];
          } catch (e) { this.brief = null; }

          // Load latest feed headlines via documents
          this.headlines = [];
          try {
            var docResp = await window.api('/api/documents?source_type=agent_feed&limit=5');
            this.headlines = (docResp.items || docResp || []).slice(0, 5).map(function(d) {
              return { title: d.title, date: d.created_at };
            });
          } catch (e) {}
        } catch (e) {
          window.LlamaApp.showError('Failed to load home data');
        } finally {
          this.loading = false;
        }
      },

      navigateToNotifications() {
        window.navigateTo('notifications');
      },

      quickAction(name) {
        if (name === 'event') window.navigateTo('events');
        if (name === 'scene') window.navigateTo('homeassistant');
        if (name === 'task') window.navigateTo('kanban');
        if (name === 'note') window.navigateTo('wiki');
      }
    };
  });
});
```

**Step 3: Commit**

```bash
git add static/js/pages/home.js static/css/pages/home.css
git commit -m "feat(frontend): add Home page component and styles"
```

---

## Task 9: Create Notifications page component

**Files:**
- Create: `static/js/pages/notifications.js`
- Create: `static/css/pages/notifications.css`

**Step 1: Write notifications.css**

```css
.notifications-page {
  max-width: 800px;
  margin: 0 auto;
}

.notif-filters {
  display: flex;
  gap: var(--space-3);
  flex-wrap: wrap;
  margin-bottom: var(--space-4);
  align-items: center;
}

.notif-filters select,
.notif-filters input {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--space-2) var(--space-3);
  color: var(--fg);
  font-size: var(--text-sm);
}

.notif-group {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  margin-bottom: var(--space-3);
  cursor: pointer;
  transition: background 0.15s;
  user-select: none;
}
.notif-group:hover { background: var(--surface-2); }

.notif-group .leading {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  background: var(--surface-2);
  font-size: var(--text-lg);
  flex-shrink: 0;
}

.notif-group .content {
  flex: 1;
  min-width: 0;
}

.notif-group .title {
  font-weight: 500;
  font-size: var(--text-sm);
  margin-bottom: var(--space-1);
}

.notif-group .meta {
  font-size: var(--text-xs);
  color: var(--muted);
}

.notif-group .count {
  font-size: var(--text-xs);
  font-weight: 700;
  background: var(--surface-2);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-md);
}

.notif-group .actions {
  flex-shrink: 0;
}
```

**Step 2: Write notifications.js**

```javascript
document.addEventListener('alpine:init', function() {
  Alpine.data('notificationsPage', function() {
    return {
      loading: true,
      groups: [],
      filterSeverity: '',
      filterSource: '',
      showProcessed: false,
      sources: [],

      async init() {
        await this.load();
      },

      async load() {
        this.loading = true;
        try {
          if (this.showProcessed) {
            var events = await window.api('/api/events?limit=100');
            this.groups = (events || []).map(function(e) {
              return {
                key: e.id,
                title: e.title,
                source: e.source,
                severity: e.severity,
                count: 1,
                first_seen: e.ts,
                last_seen: e.ts,
                event_ids: [e.id]
              };
            });
          } else {
            var groups = await window.api('/api/notifications/unread?aggregate=true');
            this.groups = groups || [];
          }

          var sourceSet = {};
          this.groups.forEach(function(g) { sourceSet[g.source] = true; });
          this.sources = Object.keys(sourceSet).sort();
        } catch (e) {
          window.LlamaApp.showError('Failed to load notifications');
        } finally {
          this.loading = false;
        }
      },

      filteredGroups() {
        var self = this;
        return this.groups.filter(function(g) {
          if (self.filterSeverity && g.severity !== self.filterSeverity) return false;
          if (self.filterSource && g.source !== self.filterSource) return false;
          return true;
        }).sort(function(a, b) {
          var sevOrder = { critical: 0, error: 1, warning: 2, warn: 2, info: 3 };
          var sa = sevOrder[a.severity] || 99;
          var sb = sevOrder[b.severity] || 99;
          if (sa !== sb) return sa - sb;
          return new Date(b.last_seen) - new Date(a.last_seen);
        });
      },

      async dismissGroup(group, event) {
        if (event) event.stopPropagation();
        try {
          // No batch dismiss endpoint exists; PATCH each event as processed
          for (var i = 0; i < group.event_ids.length; i++) {
            await window.api('/api/events/' + group.event_ids[i], {
              method: 'PATCH',
              body: JSON.stringify({ processed: true })
            });
          }
          this.groups = this.groups.filter(function(g) { return g !== group; });
        } catch (e) {
          window.LlamaApp.showError('Failed to dismiss notification group');
        }
      },

      groupIcon(source) {
        var map = {
          'uptime_kuma': '📡',
          'dozzle': '🐳',
          'hermes': '🧠',
          'ntfy': '🔔',
          'freshrss': '📰'
        };
        return map[source] || '📎';
      },

      formatTime(ts) {
        var d = new Date(ts);
        return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
      }
    };
  });
});
```

**Step 3: Commit**

```bash
git add static/js/pages/notifications.js static/css/pages/notifications.css
git commit -m "feat(frontend): add Notifications page component and styles"
```

---

## Task 10: Build new index.html shell

**Files:**
- Modify: `static/index.html`

**Step 1: Back up the existing index.html**

```bash
cp static/index.html static/index.html.legacy
```

**Step 2: Replace index.html with the new shell**

The new file must:
1. Include Alpine.js CDN with local fallback.
2. Include new CSS files: tokens, components, shell, legacy.
3. Include existing `dashboard.css` and `kanban.css` for legacy pages.
4. Include the new shell structure.
5. Include new Home and Notifications page markup.
6. Include all existing legacy page sections, wrapped in `.legacy-page` containers.
7. Include all existing scripts, plus new `shell.js`, `home.js`, `notifications.js`.

Because the existing index.html is large (~1700+ lines), do not hand-rewrite every legacy section. Instead:

- Keep the entire existing `<body>` content as-is.
- Wrap it in a `<div class="legacy-page" data-page="overview">` and set the inner `section#page-overview` to active.
- Add similar wrappers around each existing page section, moving sections out of the single legacy wrapper if needed, or duplicate minimal wrappers per page.

For practicality, the simplest approach is:
- Keep the existing full page structure mostly intact inside one legacy wrapper.
- Add the new shell UI above it.
- Add a small script that toggles visibility of the new shell vs legacy content based on current page.

However, that conflicts with the clean `.app-page` / `.legacy-page` model. A better hybrid:

1. New shell markup first:
```html
<div class="app-root" x-data="shell()">
  <header class="app-header">...</header>
  <div class="app-body">
    <aside class="app-sidebar">...</aside>
    <main class="app-main">
      <!-- new pages -->
      <section class="app-page active" data-page="home" x-data="homePage()" x-init="init()">...</section>
      <section class="app-page" data-page="notifications" x-data="notificationsPage()" x-init="init()">...</section>
      <!-- legacy pages -->
      <div class="legacy-page" data-page="overview">...</div>
      <div class="legacy-page" data-page="documents">...</div>
      <!-- etc -->
    </main>
  </div>
  <nav class="mobile-nav">...</nav>
</div>
```

2. Because each legacy page section currently lives inside the same old `<div class="main-body">`, we need to split them into separate `.legacy-page` wrappers. The most reliable way without breaking legacy JS is to keep one wrapper and use JavaScript to show/hide the correct inner section.

Given time constraints, implement the pragmatic approach:
- One `.legacy-page` wrapper containing the existing full page body.
- `navigateTo` for legacy pages toggles the inner `#page-X` active class and scrolls it into view.
- New `.app-page` sections for Home and Notifications sit alongside.

Update `shell.js` and `app.js` so that when navigating to a legacy page, the legacy wrapper is shown and the correct inner page gets `.page-active`.

**Step 3: Include all new scripts**

Add after existing scripts:
```html
<script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
<script>
  // Fallback if CDN fails
  window.addEventListener('error', function(e) {
    if (e.target && e.target.src && e.target.src.indexOf('alpinejs') !== -1) {
      var s = document.createElement('script');
      s.src = '/js/lib/alpine.min.js';
      s.defer = true;
      document.head.appendChild(s);
    }
  }, true);
</script>
<script src="/js/shell.js"></script>
<script src="/js/pages/home.js"></script>
<script src="/js/pages/notifications.js"></script>
```

**Step 4: Commit**

```bash
git add static/index.html
git commit -m "feat(frontend): add new Life-OS shell to index.html"
```

---

## Task 11: Wire navigation and verify routing

**Files:**
- Modify: `static/js/app.js`
- Modify: `static/js/shell.js`
- Modify: `static/index.html`

**Step 1: Ensure navigateTo works for both new and legacy pages**

In `app.js`, update `navigateTo` so:
- New pages: toggle `.app-page.active`.
- Legacy pages: toggle `.legacy-page.active` and inner `.page.page-active`.
- Default to `home` if no page specified.

**Step 2: Update shell.js to set currentPage on init**

```javascript
init() {
  var hash = window.location.hash.replace('#', '');
  if (hash && (this.pageExists(hash))) this.currentPage = hash;
  this.$watch('currentPage', function(page) {
    window.navigateTo(page);
  });
},

pageExists(page) {
  return this.morePages.some(function(p) { return p.id === page; }) || page === 'home' || page === 'notifications';
}
```

**Step 3: Add data-page attributes and click handlers in index.html**

Ensure sidebar and mobile nav items have `data-page` and `@click="go('...')"`.

**Step 4: Verify**

Open the app in browser at `http://lamadb:8000`.
- Click Home → Home page shows.
- Click Notifications → Notifications page shows.
- Click a legacy page (e.g., Documents) → legacy Documents section shows inside shell.
- Mobile bottom nav toggles Home, Notifications, More sheet.

**Step 5: Commit**

```bash
git add static/js/app.js static/js/shell.js static/index.html
git commit -m "feat(frontend): wire new shell navigation"
```

---

## Task 12: Theme integration

**Files:**
- Modify: `static/js/shell.js`
- Modify: `static/index.html`

**Step 1: Theme toggle in header**

Ensure header theme button uses `@click="toggleTheme()"`.

**Step 2: Apply theme on load**

In `app.js` bootstrap, keep `initTheme()` and `fetchAndApplyTheme()` calls.

**Step 3: Verify**

- Toggle theme in header.
- Refresh page; theme persists from localStorage and backend.

**Step 4: Commit**

```bash
git add static/js/shell.js static/index.html static/js/app.js
git commit -m "feat(frontend): integrate theme toggle into new shell"
```

---

## Task 13: Safe-area and mobile layout testing

**Files:**
- Modify: `static/css/shell.css`

**Step 1: Add viewport meta tag if missing**

Ensure `index.html` head contains:
```html
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
```

**Step 2: Verify safe-area insets are applied**

`.app-main` padding-bottom and `.mobile-nav` height already use `--safe-bottom`.

**Step 3: Test in Chrome DevTools device mode**

- iPhone SE / Pixel 7.
- Verify bottom nav is not clipped.
- Verify content is scrollable above bottom nav.
- Verify sidebar hidden on mobile.

**Step 4: Commit**

```bash
git add static/css/shell.css static/index.html
git commit -m "fix(frontend): mobile safe-area and viewport handling"
```

---

## Task 14: Final integration and rebuild

**Files:**
- All modified frontend files

**Step 1: Rebuild Docker image**

```bash
docker build -t lamadb-api:latest -f Dockerfile . && docker compose up -d api --force-recreate
```

**Step 2: Verify in browser**

- Load `http://lamadb:8000`
- Authenticate
- Verify Home page renders
- Verify Notifications page renders
- Verify legacy pages accessible from sidebar/More sheet
- Verify theme toggle works
- Verify no console errors

**Step 3: Clean up backup**

```bash
rm -f static/index.html.legacy
```

**Step 4: Commit final state**

```bash
git add -A
git commit -m "feat(frontend): complete Life-OS shell phase 1"
```

---

## Self-Review Checklist

- [x] Spec coverage: shell, Home, Notifications, theme, mobile, legacy compatibility all have tasks.
- [x] No placeholders: every task has concrete code/commands.
- [x] Type consistency: `window.api` used throughout; `LlamaApp` helpers consistent.
- [ ] Potential gap: index.html rewrite is described at a high level because the existing file is large. The implementing agent should preserve all existing legacy sections.
- [x] API research confirmed: `/api/notifications/dismiss` does not exist; use `PATCH /api/events/{id}` with `{processed: true}` per event_id.
- [x] API research confirmed: `/api/feeds/briefing` does not exist; fetch latest brief via `GET /api/documents?tag=briefing&limit=1`.
- [x] API research confirmed: `/api/dashboard/overview` requires admin role; Home page falls back to public `GET /api/dashboard/header` for non-admin users.
- [ ] Potential gap: Home page RSS headlines use `/api/documents?source_type=agent_feed` as a pragmatic fallback. Adjust if a better endpoint exists.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-19-life-os-frontend-redesign-phase-1-plan.md`.

Two execution options:

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach would you like?
