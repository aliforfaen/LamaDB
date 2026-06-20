# Life-OS Frontend Phase 1.5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Life-OS frontend feel alive and personal with terminal-inspired neon polish, tappable summary cards, smart attention notes, recent activity, animated transitions, and a selectable color theme system.

**Architecture:** Build on the existing Alpine.js shell. Convert CSS accent tokens to HSL so one hue variable recolors the entire UI. Add reusable components (SmartNote, LED, key-cap button). Enrich Home and Notifications pages with new widgets and interactions. Wire SSE refresh so pages update live. No new backend endpoints unless absolutely necessary.

**Tech Stack:** Alpine.js 3, vanilla CSS custom properties, async fetch, SSE, FastAPI backend (existing endpoints only).

---

## File Map

| File | Responsibility |
|------|----------------|
| `static/css/tokens.css` | HSL accent variables, theme presets, reduced-motion guards |
| `static/css/components.css` | SmartNote, LED pulse, key-cap button, focus rings, modal transitions |
| `static/css/shell.css` | Page transitions, nav active indicator, scroll-to-top, mobile theme tweaks |
| `static/css/pages/home.css` | Attention card, activity timeline, tappable tiles, briefing renderer, status LEDs |
| `static/css/pages/notifications.css` | Time buckets, severity borders, swipe actions, detail modal |
| `static/index.html` | Theme picker, Home additions, notification detail modal, mobile nav icons |
| `static/js/lib/utils.js` (NEW) | relativeTime, debounce, throttle, class helpers |
| `static/js/app.js` | Theme preset persistence, SSE live indicator, dead code cleanup |
| `static/js/shell.js` | Collapsible Legacy section, URL/hash sync, page transition hooks |
| `static/js/pages/home.js` | Attention logic, activity fetch, SSE refresh, tappable cards |
| `static/js/pages/notifications.js` | Time buckets, detail modal, mark-all-read, swipe handlers |

---

## Task 1: HSL Accent Token System + Theme Presets

**Files:**
- Modify: `static/css/tokens.css`
- Modify: `static/js/app.js`
- Modify: `static/index.html`
- Test: manual browser check

- [ ] **Step 1: Convert accent to HSL in tokens.css**

Replace static `--accent`, `--accent-dim`, `--accent-glow` definitions with HSL base:

```css
:root {
  --accent-h: 152;
  --accent-s: 100%;
  --accent-l: 50%;
  --accent: hsl(var(--accent-h) var(--accent-s) var(--accent-l));
  --accent-dim: hsl(var(--accent-h) var(--accent-s) var(--accent-l) / 0.12);
  --accent-glow: hsl(var(--accent-h) var(--accent-s) var(--accent-l) / 0.40);
  --accent-text: hsl(var(--accent-h) var(--accent-s) calc(var(--accent-l) + 10%));
}
```

Keep existing light/dark overrides. Add `prefers-reduced-motion` media query at the bottom:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

- [ ] **Step 2: Add theme preset helper in app.js**

Add after `applyAccent()`:

```javascript
function applyAccentHue(hue) {
  document.documentElement.style.setProperty('--accent-h', String(hue));
}
window.applyAccentHue = applyAccentHue;

var THEME_PRESETS = [
  { id: 'emerald', hue: 152, label: 'Operator' },
  { id: 'cyan',    hue: 190, label: 'Sysop' },
  { id: 'amber',   hue: 38,  label: 'Console' },
  { id: 'magenta', hue: 320, label: 'Neon' },
  { id: 'indigo',  hue: 245, label: 'Lama' }
];
window.THEME_PRESETS = THEME_PRESETS;
```

- [ ] **Step 3: Persist selected theme hue**

Add new `window.setThemePreset` and keep `toggleTheme()`:

```javascript
window.setThemePreset = function(presetId) {
  var preset = THEME_PRESETS.find(function(p) { return p.id === presetId; });
  if (!preset) return;
  applyAccentHue(preset.hue);
  localStorage.setItem('lamadb_accent_hue', String(preset.hue));
  localStorage.setItem('lamadb_accent_preset', presetId);
  var accent = localStorage.getItem('lamadb_accent') || '#6366f1';
  var scheme = _currentTheme;
  api('/api/users/me/theme', {
    method: 'PUT',
    body: JSON.stringify({ scheme: scheme, accent: accent })
  }).catch(function() {});
};
```

- [ ] **Step 4: Apply stored hue on init**

In `initTheme()`, after `applyTheme(theme)`:

```javascript
var storedHue = localStorage.getItem('lamadb_accent_hue');
if (storedHue) applyAccentHue(storedHue);
```

- [ ] **Step 5: Add theme picker to header**

In `static/index.html`, inside `.app-header .actions`, after the theme toggle button add:

```html
<div class="theme-picker" x-data="{ open: false }">
  <button class="icon-btn touch-target" @click="open = !open" aria-label="Choose accent color" title="Accent">●</button>
  <div class="theme-picker-menu" x-show="open" @click.away="open = false" x-cloak>
    <template x-for="p in window.THEME_PRESETS" :key="p.id">
      <button class="theme-preset-dot" :data-preset="p.id" :title="p.label" @click="window.setThemePreset(p.id); open = false"
        :style="'background: hsl(' + p.hue + ' 100% 50%)'"></button>
    </template>
  </div>
</div>
```

- [ ] **Step 6: Add theme picker CSS**

Add to `static/css/shell.css`:

```css
.theme-picker { position: relative; }
.theme-picker-menu {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  display: flex;
  gap: 8px;
  padding: 10px;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  box-shadow: 0 10px 30px rgba(0,0,0,0.4);
  z-index: 100;
}
.theme-preset-dot {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: 2px solid var(--border);
  cursor: pointer;
  transition: transform 0.15s ease, border-color 0.15s ease;
}
.theme-preset-dot:hover { transform: scale(1.15); border-color: var(--fg); }
.theme-preset-dot.active { border-color: var(--fg); box-shadow: 0 0 0 2px var(--accent-dim); }
```

- [ ] **Step 7: Commit**

```bash
git add static/css/tokens.css static/css/shell.css static/js/app.js static/index.html
git commit -m "feat(frontend): HSL accent system and color theme picker"
```

---

## Task 2: Reusable Components (SmartNote, LED, Key-Cap Button)

**Files:**
- Modify: `static/css/components.css`
- Create: `static/js/lib/utils.js`
- Modify: `static/index.html`
- Test: manual browser check

- [ ] **Step 1: Create utils.js**

Create `static/js/lib/utils.js`:

```javascript
(function() {
  'use strict';

  window.relativeTime = function(iso) {
    var d = new Date(iso);
    var now = new Date();
    var diff = Math.floor((now - d) / 1000);
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    if (diff < 604800) return Math.floor(diff / 86400) + 'd ago';
    return d.toLocaleDateString();
  };

  window.debounce = function(fn, ms) {
    var t;
    return function() {
      var ctx = this, args = arguments;
      clearTimeout(t);
      t = setTimeout(function() { fn.apply(ctx, args); }, ms);
    };
  };

  window.throttle = function(fn, ms) {
    var last = 0;
    return function() {
      var now = Date.now();
      if (now - last >= ms) { last = now; fn.apply(this, arguments); }
    };
  };

  window.escHtml = window.escHtml || function(s) {
    var div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  };
})();
```

- [ ] **Step 2: Add SmartNote component styles**

Add to `static/css/components.css`:

```css
/* SmartNote */
.smart-note {
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
  padding: var(--space-3);
  background: var(--surface-1);
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.smart-note:hover {
  border-color: var(--accent-dim);
  box-shadow: 0 0 20px var(--accent-glow);
}
.smart-note-icon {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  font-size: 14px;
}
.smart-note-content { flex: 1; }
.smart-note-title {
  font-weight: 600;
  font-size: var(--text-sm);
  margin-bottom: 2px;
}
.smart-note-body {
  font-size: var(--text-sm);
  color: var(--fg-2);
  line-height: 1.5;
}
.smart-note.alert { border-left: 3px solid var(--danger); }
.smart-note.heads-up { border-left: 3px solid var(--accent); }
.smart-note.insight { border-left: 3px solid var(--muted); }
.smart-note.empty { border-left: 3px solid var(--border); }
```

- [ ] **Step 3: Add LED and key-cap styles**

Add to `static/css/components.css`:

```css
/* LED status indicator */
.led {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--muted);
  position: relative;
}
.led.on { background: var(--success); }
.led.warn { background: var(--warning); }
.led.error { background: var(--danger); }
.led.pulse::after {
  content: '';
  position: absolute;
  inset: -4px;
  border-radius: 50%;
  border: 1px solid currentColor;
  opacity: 0.5;
  animation: pulse-ring 2s ease-out infinite;
}
@keyframes pulse-ring {
  0% { transform: scale(1); opacity: 0.5; }
  100% { transform: scale(2.4); opacity: 0; }
}

/* Key-cap button */
.key-cap {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-3);
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
  background: var(--surface-1);
  color: var(--fg);
  cursor: pointer;
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  transition: border-color 0.15s ease, box-shadow 0.15s ease, transform 0.1s ease;
}
.key-cap:hover {
  border-color: var(--accent-dim);
  box-shadow: 0 0 16px var(--accent-glow);
}
.key-cap:active { transform: translateY(1px); }
.key-cap .key-cap-icon { font-size: 20px; color: var(--accent); }
```

- [ ] **Step 4: Add focus ring style**

Add to `static/css/components.css`:

```css
:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
```

- [ ] **Step 5: Include utils.js in index.html**

Add before app.js in `static/index.html`:

```html
<script src="/js/lib/utils.js"></script>
```

- [ ] **Step 6: Commit**

```bash
git add static/css/components.css static/js/lib/utils.js static/index.html
git commit -m "feat(frontend): SmartNote, LED, key-cap components and utils"
```


---

## Task 3: Home Page – Attention Notes + Recent Activity

**Files:**
- Modify: `static/index.html`
- Modify: `static/js/pages/home.js`
- Modify: `static/css/pages/home.css`
- Modify: `static/css/components.css`
- Test: manual browser check

- [ ] **Step 1: Add SmartNote HTML to Home page**

In `static/index.html`, inside `#page-home .page-content`, after the greeting header, replace the existing `status-card` placeholders with a new `.attention-grid`:

```html
<section class="attention-grid" id="attention-grid" aria-label="Attention">
  <div class="smart-note empty" id="attention-default">
    <div class="smart-note-icon">✓</div>
    <div class="smart-note-content">
      <div class="smart-note-title">All clear</div>
      <div class="smart-note-body">No open tasks, unread alerts, or stuck flows right now.</div>
    </div>
  </div>
</section>

<section class="quick-links" aria-label="Quick links">
  <button class="key-cap" onclick="window.navigateTo('kanban')">
    <span class="key-cap-icon">⊞</span>
    <span>Kanban</span>
  </button>
  <button class="key-cap" onclick="window.navigateTo('notifications')">
    <span class="key-cap-icon">☎</span>
    <span>Alerts</span>
  </button>
  <button class="key-cap" onclick="window.navigateTo('documents')">
    <span class="key-cap-icon">🗐</span>
    <span>Docs</span>
  </button>
  <button class="key-cap" onclick="window.navigateTo('wiki')">
    <span class="key-cap-icon">✎</span>
    <span>Wiki</span>
  </button>
</section>

<section class="recent-activity" aria-label="Recent activity">
  <div class="section-header">
    <h3>Recent Activity</h3>
    <span class="live-indicator">
      <span class="led on pulse" id="activity-led"></span>
      <span class="live-label" id="activity-live-label">Live</span>
    </span>
  </div>
  <div class="activity-list" id="activity-list">
    <div class="activity-empty">No recent activity.</div>
  </div>
</section>
```

- [ ] **Step 2: Add Home page styles**

Add to `static/css/pages/home.css` (create if it does not exist):

```css
#page-home .page-content {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.attention-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: var(--space-3);
}

.quick-links {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(80px, 1fr));
  gap: var(--space-3);
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-3);
}
.section-header h3 {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--fg-2);
  margin: 0;
}

.live-indicator {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-xs);
  color: var(--fg-3);
  font-family: var(--font-mono);
}

.activity-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.activity-item {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-3);
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
  background: var(--surface-1);
  cursor: pointer;
  transition: border-color 0.15s ease, transform 0.1s ease;
}
.activity-item:hover {
  border-color: var(--accent-dim);
  transform: translateX(4px);
}
.activity-item .activity-time {
  flex-shrink: 0;
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--fg-3);
  width: 70px;
}
.activity-item .activity-body {
  flex: 1;
  font-size: var(--text-sm);
  line-height: 1.5;
}
.activity-item .activity-source {
  font-size: var(--text-xs);
  color: var(--fg-3);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.activity-empty {
  color: var(--fg-3);
  font-size: var(--text-sm);
  padding: var(--space-4);
  text-align: center;
  border: 1px dashed var(--border);
  border-radius: var(--radius-md);
}
```

If `static/css/pages/home.css` does not exist, create it and add an `@import` or ensure `index.html` links to it. The existing `index.html` likely links all CSS files in `static/css/`; verify and add `<link rel="stylesheet" href="/css/pages/home.css">` if needed.

- [ ] **Step 3: Implement attention logic in home.js**

In `static/js/pages/home.js`, add:

```javascript
async function loadAttention() {
  var grid = document.getElementById('attention-grid');
  if (!grid) return;
  var notes = [];

  try {
    var tasks = await api('/api/kanban/me/tasks?status=in_progress&limit=5');
    if (tasks && tasks.length) {
      notes.push({
        type: 'heads-up',
        icon: '⊞',
        title: tasks.length + ' task' + (tasks.length > 1 ? 's' : '') + ' in progress',
        body: tasks.map(function(t) { return '#' + t.task_number + ' ' + t.title; }).join(' · '),
        action: function() { window.navigateTo('kanban'); }
      });
    }
  } catch (e) {}

  try {
    var notifAgg = await api('/api/notifications/unread?aggregate=true&limit=1');
    if (notifAgg && notifAgg.length) {
      var n = notifAgg[0];
      notes.push({
        type: 'alert',
        icon: '☎',
        title: (n.count || 1) + ' unread alert' + ((n.count || 1) > 1 ? 's' : ''),
        body: n.title || 'New notifications waiting.',
        action: function() { window.navigateTo('notifications'); }
      });
    }
  } catch (e) {}

  try {
    var events = await api('/api/events?severity=warning&limit=1&processed=false');
    if (events && events.length) {
      notes.push({
        type: 'alert',
        icon: '⚠',
        title: 'System warning',
        body: events[0].title,
        action: function() { window.navigateTo('events'); }
      });
    }
  } catch (e) {}

  if (!notes.length) return;

  grid.innerHTML = notes.map(function(note) {
    return '<div class="smart-note ' + note.type + '" role="button" tabindex="0">' +
      '<div class="smart-note-icon">' + window.escHtml(note.icon) + '</div>' +
      '<div class="smart-note-content">' +
        '<div class="smart-note-title">' + window.escHtml(note.title) + '</div>' +
        '<div class="smart-note-body">' + window.escHtml(note.body) + '</div>' +
      '</div>' +
    '</div>';
  }).join('');

  Array.from(grid.children).forEach(function(el, i) {
    el.addEventListener('click', notes[i].action);
    el.addEventListener('keydown', function(e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); notes[i].action(); }
    });
  });
}
```

Call `loadAttention()` inside the existing `loadHome()` or page init function.

- [ ] **Step 4: Implement recent activity feed**

In `static/js/pages/home.js`, add:

```javascript
async function loadRecentActivity() {
  var list = document.getElementById('activity-list');
  if (!list) return;
  try {
    var events = await api('/api/events?limit=20&order=desc');
    if (!events || !events.length) {
      list.innerHTML = '<div class="activity-empty">No recent activity.</div>';
      return;
    }
    list.innerHTML = events.map(function(ev) {
      return '<div class="activity-item" data-source="' + window.escHtml(ev.source || '') + '" data-type="' + window.escHtml(ev.type || '') + '">' +
        '<span class="activity-time">' + window.relativeTime(ev.ts) + '</span>' +
        '<div class="activity-body">' +
          '<div>' + window.escHtml(ev.title || '') + '</div>' +
          '<span class="activity-source">' + window.escHtml(ev.source || '') + ' · ' + window.escHtml(ev.type || '') + '</span>' +
        '</div>' +
      '</div>';
    }).join('');
  } catch (e) {
    list.innerHTML = '<div class="activity-empty">Unable to load activity.</div>';
  }
}
```

Call `loadRecentActivity()` in `loadHome()`.

- [ ] **Step 5: Mark live indicator on SSE activity**

In `static/js/app.js`, when registering SSE callbacks, add a generic activity pulse:

```javascript
window._sseCallbacks['events'] = window._sseCallbacks['events'] || [];
window._sseCallbacks['events'].push(function() {
  var led = document.getElementById('activity-led');
  if (led) {
    led.classList.add('pulse');
    setTimeout(function() { led.classList.remove('pulse'); }, 2000);
  }
  if (typeof loadRecentActivity === 'function') loadRecentActivity();
  if (typeof loadAttention === 'function') loadAttention();
});
```

- [ ] **Step 6: Commit**

```bash
git add static/index.html static/js/pages/home.js static/css/pages/home.css static/css/components.css static/js/app.js
git commit -m "feat(frontend): Home attention notes, recent activity, and live indicator"
```

---

## Task 4: Notifications Page – Time Buckets + Detail Modal

**Files:**
- Modify: `static/index.html`
- Modify: `static/js/pages/notifications.js`
- Modify: `static/css/pages/notifications.css`
- Test: manual browser check

- [ ] **Step 1: Group notifications by time bucket**

In `static/js/pages/notifications.js`, update the render function to group aggregated notifications into buckets:

```javascript
function bucketNotifications(groups) {
  var now = Date.now();
  var buckets = { today: [], yesterday: [], week: [], older: [] };
  (groups || []).forEach(function(g) {
    var t = new Date(g.last_seen || g.first_seen).getTime();
    var d = now - t;
    if (d < 86400000) buckets.today.push(g);
    else if (d < 172800000) buckets.yesterday.push(g);
    else if (d < 604800000) buckets.week.push(g);
    else buckets.older.push(g);
  });
  return buckets;
}
window.bucketNotifications = bucketNotifications;
```

- [ ] **Step 2: Render bucketed list**

Replace the existing list render with:

```javascript
function renderNotifications(groups) {
  var container = document.getElementById('notifications-list');
  if (!container) return;
  if (!groups || !groups.length) {
    container.innerHTML = '<div class="notifications-empty">No unread alerts. Good job.</div>';
    return;
  }
  var buckets = bucketNotifications(groups);
  var html = '';
  function section(title, items) {
    if (!items.length) return '';
    return '<div class="notification-bucket">' +
      '<h4 class="bucket-label">' + window.escHtml(title) + '</h4>' +
      items.map(renderNotificationItem).join('') +
    '</div>';
  }
  html += section('Today', buckets.today);
  html += section('Yesterday', buckets.yesterday);
  html += section('This week', buckets.week);
  html += section('Older', buckets.older);
  container.innerHTML = html;
}

function renderNotificationItem(g) {
  var severity = g.severity || 'info';
  var count = g.count || 1;
  return '<div class="notification-item severity-' + window.escHtml(severity) + '" data-ids="' + (g.event_ids || []).join(',') + '" role="button" tabindex="0">' +
    '<div class="notification-severity"><span class="led ' + (severity === 'error' ? 'error' : severity === 'warning' ? 'warn' : 'on') + '" data-count="' + count + '"></span></div>' +
    '<div class="notification-body">' +
      '<div class="notification-title">' + window.escHtml(g.title || '') + '</div>' +
      '<div class="notification-meta">' + window.escHtml(g.source || '') + ' · ' + window.relativeTime(g.last_seen || g.first_seen) + (count > 1 ? ' · ×' + count : '') + '</div>' +
    '</div>' +
  '</div>';
}
```

- [ ] **Step 3: Add notification detail modal**

Add to `static/index.html` near the end of `body`:

```html
<div id="notification-detail-modal" class="modal" style="display:none;">
  <div class="modal-backdrop" onclick="window.closeNotificationDetail()"></div>
  <div class="modal-card">
    <div class="modal-header">
      <h3 id="notification-detail-title">Alert</h3>
      <button class="icon-btn" onclick="window.closeNotificationDetail()" aria-label="Close">×</button>
    </div>
    <div class="modal-body">
      <div class="notification-detail-meta" id="notification-detail-meta"></div>
      <pre id="notification-detail-body"></pre>
      <div class="notification-detail-ids">
        <span class="label">Event IDs:</span>
        <span id="notification-detail-ids"></span>
      </div>
    </div>
    <div class="modal-footer">
      <button class="btn primary" onclick="window.dismissSelectedNotifications()">Dismiss</button>
    </div>
  </div>
</div>
```

- [ ] **Step 4: Add notification detail JS handlers**

In `static/js/pages/notifications.js`:

```javascript
var _selectedNotificationIds = [];

window.openNotificationDetail = function(group) {
  _selectedNotificationIds = group.event_ids || [];
  document.getElementById('notification-detail-title').textContent = group.title || 'Alert';
  document.getElementById('notification-detail-meta').textContent = (group.source || '') + ' · ' + (group.type || '') + ' · ' + (group.severity || 'info');
  document.getElementById('notification-detail-body').textContent = group.body || '';
  document.getElementById('notification-detail-ids').textContent = _selectedNotificationIds.join(', ');
  document.getElementById('notification-detail-modal').style.display = 'flex';
};

window.closeNotificationDetail = function() {
  document.getElementById('notification-detail-modal').style.display = 'none';
  _selectedNotificationIds = [];
};

window.dismissSelectedNotifications = async function() {
  if (!_selectedNotificationIds.length) return;
  try {
    await api('/api/notifications/mark-read', {
      method: 'POST',
      body: JSON.stringify({ event_ids: _selectedNotificationIds })
    });
    window.closeNotificationDetail();
    window.loadNotifications && window.loadNotifications();
  } catch (e) {
    window.showError && window.showError('Failed to dismiss alerts');
  }
};
```

Wire click handlers in `renderNotifications` by selecting `.notification-item` elements after render and attaching `click` listeners that call `openNotificationDetail(group)`.

- [ ] **Step 5: Add notification CSS**

Add to `static/css/pages/notifications.css`:

```css
.notification-bucket { margin-bottom: var(--space-4); }
.bucket-label {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--fg-3);
  margin: 0 0 var(--space-2) 0;
}
.notification-item {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-3);
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
  background: var(--surface-1);
  margin-bottom: var(--space-2);
  cursor: pointer;
  transition: border-color 0.15s ease, transform 0.1s ease;
}
.notification-item:hover {
  border-color: var(--accent-dim);
  transform: translateX(4px);
}
.notification-item.severity-error { border-left: 3px solid var(--danger); }
.notification-item.severity-warning { border-left: 3px solid var(--warning); }
.notification-item.severity-info { border-left: 3px solid var(--accent); }
.notification-severity { padding-top: 2px; }
.notification-title { font-weight: 600; font-size: var(--text-sm); }
.notification-meta { font-size: var(--text-xs); color: var(--fg-3); margin-top: 2px; }

.notification-detail-meta {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--fg-3);
  margin-bottom: var(--space-3);
}
#notification-detail-body {
  background: var(--surface-0);
  padding: var(--space-3);
  border-radius: var(--radius-md);
  overflow-x: auto;
  font-size: var(--text-sm);
  white-space: pre-wrap;
}
.notification-detail-ids { margin-top: var(--space-3); font-size: var(--text-xs); color: var(--fg-3); }
.notification-detail-ids .label { font-weight: 600; margin-right: var(--space-2); }
```

- [ ] **Step 6: Commit**

```bash
git add static/index.html static/js/pages/notifications.js static/css/pages/notifications.css
git commit -m "feat(frontend): notification time buckets and detail modal"
```


---

## Task 5: Page Transitions + Scroll Behavior

**Files:**
- Modify: `static/js/shell.js`
- Modify: `static/css/shell.css`
- Test: manual browser check

- [ ] **Step 1: Add page transition CSS**

Add to `static/css/shell.css`:

```css
.page {
  opacity: 0;
  transform: translateY(8px);
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.page.active {
  opacity: 1;
  transform: translateY(0);
}
```

Ensure existing `.page` rules do not override this. If `.page` has `display: none`, keep `display: block` on `.active`.

- [ ] **Step 2: Add scroll-to-top button**

Add to `static/index.html` before closing `body`:

```html
<button id="scroll-top" class="scroll-top" onclick="window.scrollToTop()" aria-label="Scroll to top">↑</button>
```

Add to `static/css/shell.css`:

```css
.scroll-top {
  position: fixed;
  bottom: 24px;
  right: 24px;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  border: 1px solid var(--border);
  background: var(--surface-1);
  color: var(--fg);
  font-size: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.2s ease, transform 0.15s ease, border-color 0.15s ease;
  z-index: 50;
}
.scroll-top.visible {
  opacity: 1;
  pointer-events: auto;
}
.scroll-top:hover { border-color: var(--accent-dim); transform: translateY(-2px); }
```

- [ ] **Step 3: Implement scroll behavior in shell.js**

In `static/js/shell.js`:

```javascript
window.scrollToTop = function() {
  document.querySelector('.app-main').scrollTo({ top: 0, behavior: 'smooth' });
};

function updateScrollTopVisibility() {
  var main = document.querySelector('.app-main');
  var btn = document.getElementById('scroll-top');
  if (!main || !btn) return;
  if (main.scrollTop > 300) btn.classList.add('visible');
  else btn.classList.remove('visible');
}

var mainEl = document.querySelector('.app-main');
if (mainEl) {
  mainEl.addEventListener('scroll', window.throttle(updateScrollTopVisibility, 150));
}
```

- [ ] **Step 4: Add transition hooks to navigateTo**

In `static/js/shell.js`, where `navigateTo` switches pages:

```javascript
window.navigateTo = function(pageId, force) {
  if (!force && window.LlamaApp && window.LlamaApp.currentPage === pageId) return;
  var pages = document.querySelectorAll('.page');
  pages.forEach(function(p) {
    p.classList.remove('active');
    if (p.id !== 'page-' + pageId) p.style.display = 'none';
  });
  var target = document.getElementById('page-' + pageId);
  if (target) {
    target.style.display = 'block';
    requestAnimationFrame(function() { target.classList.add('active'); });
    window.scrollToTop();
  }
  if (window.LlamaApp) window.LlamaApp.currentPage = pageId;
  history.pushState({ page: pageId }, '', '/#' + pageId);
  updateNavActiveState(pageId);
  window.dispatchEvent(new CustomEvent('pagechange', { detail: { page: pageId } }));
};

function updateNavActiveState(pageId) {
  document.querySelectorAll('.nav-link').forEach(function(link) {
    link.classList.toggle('active', link.dataset.page === pageId);
  });
}
```

- [ ] **Step 5: Handle popstate for back/forward**

In `static/js/shell.js`:

```javascript
window.addEventListener('popstate', function(e) {
  var pageId = (e.state && e.state.page) || location.hash.replace('#', '') || 'home';
  window.navigateTo(pageId, true);
});
```

- [ ] **Step 6: Commit**

```bash
git add static/css/shell.css static/js/shell.js static/index.html
git commit -m "feat(frontend): page transitions, scroll-to-top, and history routing"
```

---

## Task 6: SSE Live Indicator + Auto-Refresh

**Files:**
- Modify: `static/js/app.js`
- Modify: `static/index.html`
- Modify: `static/css/shell.css`
- Test: manual browser check

- [ ] **Step 1: Add connection status LED to header**

Add to `static/index.html` inside `.app-header`:

```html
<div class="connection-status" title="SSE connection status">
  <span class="led" id="sse-led"></span>
  <span class="connection-label" id="sse-label">Offline</span>
</div>
```

Add to `static/css/shell.css`:

```css
.connection-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-xs);
  color: var(--fg-3);
  font-family: var(--font-mono);
  margin-left: auto;
  margin-right: var(--space-3);
}
```

- [ ] **Step 2: Update SSE status in app.js**

Where the SSE connection is opened/closed in `static/js/app.js`, add:

```javascript
function setSseStatus(connected) {
  var led = document.getElementById('sse-led');
  var label = document.getElementById('sse-label');
  if (!led || !label) return;
  if (connected) {
    led.className = 'led on pulse';
    label.textContent = 'Live';
  } else {
    led.className = 'led';
    label.textContent = 'Offline';
  }
}
window.setSseStatus = setSseStatus;
```

Call `setSseStatus(true)` on `EventSource` `onopen` and `setSseStatus(false)` on `onerror` / `onclose`.

- [ ] **Step 3: Register refresh callbacks for each page**

In `static/js/app.js`, when SSE messages arrive, dispatch to page refresh functions:

```javascript
function dispatchSse(channel, data) {
  var cbs = window._sseCallbacks[channel] || [];
  cbs.forEach(function(fn) { try { fn(data); } catch (e) { console.error(e); } });
}
```

Ensure each page loader registers:
- `events` channel → `loadRecentActivity`, `loadAttention`, `loadNotifications`
- `kanban_task_updated` channel → `loadAttention`

- [ ] **Step 4: Commit**

```bash
git add static/js/app.js static/index.html static/css/shell.css
git commit -m "feat(frontend): SSE live indicator and auto-refresh hooks"
```

---

## Task 7: Mobile Polish + Touch Targets

**Files:**
- Modify: `static/css/shell.css`
- Modify: `static/index.html`
- Modify: `static/css/pages/home.css`
- Test: Android WebView or Chrome mobile emulation

- [ ] **Step 1: Ensure minimum touch targets**

Add to `static/css/shell.css`:

```css
.touch-target {
  min-width: 44px;
  min-height: 44px;
}
.icon-btn {
  width: 40px;
  height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.nav-link {
  min-height: 44px;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
```

- [ ] **Step 2: Add mobile bottom nav icons**

In `static/index.html`, add data-icons to nav links and render icons on narrow screens:

```html
<a class="nav-link" data-page="home" data-icon="⌂" href="#home">Home</a>
<a class="nav-link" data-page="notifications" data-icon="☎" href="#notifications">Alerts</a>
...
```

Add CSS:

```css
@media (max-width: 640px) {
  .app-nav {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    top: auto;
    flex-direction: row;
    justify-content: space-around;
    padding: var(--space-2) 0;
    border-top: 1px solid var(--border);
    border-right: none;
    z-index: 40;
  }
  .nav-link {
    flex-direction: column;
    font-size: var(--text-xs);
    gap: 2px;
  }
  .nav-link::before {
    content: attr(data-icon);
    font-size: 18px;
  }
  .app-main { padding-bottom: 64px; }
  .scroll-top { bottom: 80px; }
}
```

- [ ] **Step 3: Stack Home sections on mobile**

Add to `static/css/pages/home.css`:

```css
@media (max-width: 640px) {
  .attention-grid { grid-template-columns: 1fr; }
  .quick-links { grid-template-columns: repeat(2, 1fr); }
}
```

- [ ] **Step 4: Prevent horizontal overflow**

Add to `static/css/shell.css`:

```css
html, body { overflow-x: hidden; }
.app-main { max-width: 100vw; }
```

- [ ] **Step 5: Commit**

```bash
git add static/css/shell.css static/index.html static/css/pages/home.css
git commit -m "feat(frontend): mobile nav icons, touch targets, and responsive layout"
```


---

## Task 8: Testing + Dogfood Regression

**Files:**
- Verify: all modified files
- Run: `docker compose build api && docker compose up -d api`
- Test: desktop browser + Android WebView

- [ ] **Step 1: Build and deploy feature branch**

```bash
docker build -t lamadb-api:lifeos-phase1 -f Dockerfile . && \
docker stop lamadb-api && \
docker run -d --name lamadb-api --restart unless-stopped \
  --network lamadb_default \
  -p 8000:8000 \
  -e DATABASE_URL=postgresql://lamadb:lamadb@postgres:5432/lamadb \
  -e API_KEY_SALT=... \
  -e CORS_ORIGINS=http://localhost:3000,http://localhost:8080 \
  -e LAMADB_BASE_URL=http://jita:8000 \
  lamadb-api:lifeos-phase1
```

- [ ] **Step 2: Desktop verification checklist**

Open `http://jita:8000/` and verify:

1. Theme picker opens and each accent color changes the UI instantly.
2. Selected accent persists after refresh.
3. Home page shows SmartNote cards if there are in-progress tasks, unread notifications, or warnings; otherwise shows "All clear".
4. Quick-link key-caps navigate to Kanban, Alerts, Docs, Wiki.
5. Recent Activity loads and updates when new events arrive (use test event POST).
6. Clicking a notification opens the detail modal; Dismiss marks events processed and removes the item.
7. Page transitions are smooth and scroll position resets.
8. Scroll-to-top button appears after scrolling and works.
9. Back/forward browser buttons navigate correctly.
10. SSE LED shows "Live" when connected and "Offline" when the server stops.

- [ ] **Step 3: Mobile verification checklist**

Use Chrome DevTools mobile emulation or Android WebView:

1. Bottom nav renders with icons and labels.
2. All tap targets are at least 44×44px.
3. Home attention grid stacks vertically.
4. Quick links show 2 columns.
5. No horizontal overflow.
6. Theme picker fits on screen and closes on outside tap.
7. Notification detail modal is readable and dismiss button is tappable.

- [ ] **Step 4: Run automated tests (if available)**

```bash
docker exec lamadb_api python3 -m pytest tests/frontend -q
```

If no frontend tests exist, skip this step and note it in the handoff.

- [ ] **Step 5: Dogfood regression**

Use the Tester agent or manual QA to:

1. Verify the auth flow still works (log out, refresh, log in).
2. Verify legacy pages still load from the collapsible Legacy section.
3. Verify command palette still opens and navigates.
4. Verify no console errors on initial load.
5. Document any new issues in `/tmp/qa/dogfood-phase1.5/report.md`.

- [ ] **Step 6: Commit fixes**

```bash
git add -A
git commit -m "fix(frontend): Phase 1.5 QA fixes"
```

---

## Task 9: Documentation + Handoff

**Files:**
- Modify: `~/Basecamp/wiki/projects/lamadb/plans.md`
- Modify: `~/Basecamp/wiki/projects/lamadb/sessions.md`
- Create: `~/Basecamp/wiki/projects/lamadb/handoff-2026-06-20.md`
- Modify: `AGENTS.md` if new pitfalls discovered

- [ ] **Step 1: Update plans.md**

Mark Phase 1.5 as in-progress or complete, list deferred items:

```markdown
### Phase 1.5 – Terminal-Neon Creature Comforts
- [x] HSL accent system + theme presets
- [x] SmartNote, LED, key-cap components
- [x] Home attention notes + recent activity
- [x] Notification time buckets + detail modal
- [x] Page transitions, scroll-to-top, history routing
- [x] SSE live indicator + auto-refresh
- [x] Mobile nav icons + touch targets
- [ ] Full Documents/Events/Settings/Kanban page ports → Phase 2
- [ ] Notification swipe actions + bulk dismiss endpoint → Phase 2
- [ ] Pull-to-refresh → Phase 2
```

- [ ] **Step 2: Update sessions.md**

Append today's session summary:

```markdown
## 2026-06-20 – Phase 1.5 Plan
- Wrote implementation plan for terminal-neon creature comforts.
- Branch: `feat/life-os-frontend-phase1`.
- Deployed on `jita:8000` as `lamadb-api:lifeos-phase1`.
- Next: implement tasks 1-7, run dogfood regression, commit fixes.
```

- [ ] **Step 3: Create handoff doc**

Create `~/Basecamp/wiki/projects/lamadb/handoff-2026-06-20.md`:

```markdown
# Handoff – 2026-06-20

## Status
Phase 1.5 implementation plan is written and committed.
Feature branch `feat/life-os-frontend-phase1` is running on `jita:8000`.

## What’s next
Implement tasks 1-7 from `docs/superpowers/plans/2026-06-20-life-os-frontend-phase1.5-neon-creature-comforts-plan.md`.
Run desktop + mobile dogfood regression.
Commit QA fixes and push.

## Branch
`feat/life-os-frontend-phase1`

## Deployed image
`lamadb-api:lifeos-phase1`

## Known unknowns
- `/api/kanban/me` endpoint must be verified before Task 3 uses it.
- `x-collapse` Alpine plugin is missing; use `x-show` fallback.
```

- [ ] **Step 4: Update AGENTS.md if needed**

If any new pitfalls are discovered during implementation, add them to `AGENTS.md` Known Pitfalls table.

- [ ] **Step 5: Final commit and push**

```bash
git add docs/superpowers/plans/2026-06-20-life-os-frontend-phase1.5-neon-creature-comforts-plan.md
git commit -m "docs(plan): Phase 1.5 terminal-neon creature comforts implementation plan"
git push origin feat/life-os-frontend-phase1
```

---

## Definition of Done

- [ ] All checkboxes in Tasks 1-7 are implemented and committed.
- [ ] Desktop verification checklist passes.
- [ ] Mobile verification checklist passes.
- [ ] No console errors on initial load.
- [ ] Dogfood regression issues are documented and fixed.
- [ ] Wiki docs (`plans.md`, `sessions.md`, `handoff-2026-06-20.md`) are updated.
- [ ] Branch `feat/life-os-frontend-phase1` is pushed with all commits.

## Out of Scope / Deferred

- Full page ports for Documents, Events, Settings, Kanban (Phase 2)
- Notification swipe-to-dismiss and bulk dismiss backend endpoint (Phase 2)
- Pull-to-refresh gesture (Phase 2)
- Sound/notification push (Phase 3)
- Offline support / service worker (Phase 3)
