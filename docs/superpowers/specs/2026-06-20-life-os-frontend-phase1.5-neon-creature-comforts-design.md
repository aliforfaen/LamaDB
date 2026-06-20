# Life-OS Frontend Phase 1.5 — Creature Comforts & Terminal-Neon Style

## Goal

Make the Life-OS frontend feel alive, personal, and unmistakably "mine": a classy terminal-inspired dashboard with thin neon accents, purposeful motion, and smart surfacing of what actually needs attention today.

This phase builds on the Phase 1 shell (`feat/life-os-frontend-phase1`) without replacing legacy pages. It focuses on the **Home** and **Notifications** pages, global polish, and a selectable color theme system.

## Visual Direction

### Vibe

- **Terminal-inspired, not terminal-literal.** Monospace data, thin 1px lines, grid-aware panels, status LEDs — but clean spacing, rounded corners, and readable type.
- **Classy neon.** Restrained glow used as signal, not decoration. One dominant accent color at a time.
- **Mine.** A color theme selector lets the user pick their accent (emerald, cyan, amber, magenta, indigo). Stored per-user and in localStorage.
- **Default direction: "Calm Operator"** — single accent, subtle glow, daily-use friendly.

### Color System

Convert the static accent to HSL-driven variables so one hue change recolors everything.

```css
:root {
  --accent-h: 152; /* default emerald */
  --accent-s: 100%;
  --accent-l: 50%;
  --accent: hsl(var(--accent-h) var(--accent-s) var(--accent-l));
  --accent-dim: hsl(var(--accent-h) var(--accent-s) var(--accent-l) / 0.12);
  --accent-glow: hsl(var(--accent-h) var(--accent-s) var(--accent-l) / 0.40);
  --accent-text: hsl(var(--accent-h) var(--accent-s) calc(var(--accent-l) + 10%));
}
```

Preset themes:

| Preset | Hue | Name | Mood |
|--------|-----|------|------|
| Emerald | 152 | "Operator" | calm, default |
| Cyan | 190 | "Sysop" | cold, clinical |
| Amber | 38 | "Console" | retro warm |
| Magenta | 320 | "Neon" | bold, playful |
| Indigo | 245 | "Lama" | existing brand fallback |

Backgrounds stay deep (`#0a0a0a` / `#0f172a` dark, `#f8fafc` light). Neon is the 10% signal on top of 70% neutral surfaces.

### Typography

- Headings & body: Inter (existing)
- Data, stats, codes, timestamps: JetBrains Mono (existing)
- Apply `font-variant-numeric: tabular-nums` to all stat values and timers so numbers don't jitter when updating.

### Glow & Lines

- **Status LEDs:** 8px dot with a subtle ring pulse on live/active states.
- **Card borders:** 1px `var(--border)` by default, 1px `var(--accent-dim)` on hover, with a soft `box-shadow: 0 0 20px var(--accent-glow)` on hover for "special" cards.
- **Thin dividers:** 1px hairlines between list items and panel sections.
- **No glow on body text.** Glow is reserved for indicators, focused inputs, and active nav items.
- **Reduced motion guard:** respect `prefers-reduced-motion` by disabling pulses and transitions.

## Home Page Upgrades

### 1. Tappable Summary Cards

The existing 3 summary tiles (Critical / Notifications / Tasks) become tappable and reveal their source data.

- **Critical** — taps to Uptime page (or expands inline to show monitor names + statuses).
- **Notifications** — taps to Notifications page filtered to unread.
- **Tasks** — taps to Kanban page filtered to "my open tasks".

Visual: each tile gets a left border in the accent color, hover lift (`translateY(-2px)` + glow), and the value uses `tabular-nums`.

### 2. Smart Attention Card ("Here's what needs your attention")

Replace the empty briefing area with a dynamically generated attention card. It reads the same data Home already loads and surfaces the top 1–3 actionable items:

- If services are down: "2 monitors down: Uptime Kuma, Coolify Proxy"
- If unread critical notifications exist: "3 critical alerts need review"
- If tasks are in progress/assigned: "You have 4 open tasks, 1 due today"
- If nothing needs attention: a friendly "All clear" state with a tiny encouraging line.

This is a pure frontend aggregation — no new backend endpoint. It updates when Home re-loads or receives SSE events.

### 3. Recent Activity List

Add a "Recent Activity" panel below the summary cards. It pulls from:

- Last 5 events (`/api/events?limit=5`)
- Latest documents (`/api/documents?limit=5`)
- Recent task completions (if kanban endpoint returns recent activity)

Render as a unified timeline: icon + actor/source + one-line summary + relative timestamp. Each row is tappable where applicable.

### 4. Live Status Indicators

- Add a small "Live" pill in the header with a pulsing dot when SSE is connected.
- Service status card shows per-monitor dots (green/amber/red) with names.
- Cache hit rate and document count rendered as monospace data chips.

### 5. Briefing Renderer

The existing `brief` field loads the latest `tag=briefing` document. Replace the single-line title with a parsed brief card:

- Title as header
- Body rendered as plain text / simple markdown (paragraphs, lists)
- If no brief exists: show a "No briefing yet" placeholder with a "Publish one" action.

### 6. Quick Actions Polish

Keep the 4 quick actions but make them feel like physical keys:

- Monospace labels
- Subtle key-cap styling (thin border, slight inset shadow)
- Hover: accent border + glow
- Active: pressed-in effect

## Notifications Page Upgrades

### 1. Time-Bucketed Grouping

Group the notification list into:

- Today
- Yesterday
- Earlier this week
- Older

Use relative timestamps within buckets.

### 2. Tappable Rows + Detail Modal

Tapping a notification group opens a detail modal showing:

- Full title
- Body / metadata
- Source, severity, first/last seen
- List of event IDs (collapsed)
- Dismiss / Mark processed buttons

### 3. Swipe Actions (Mobile)

On mobile viewports, allow horizontal swipe on a notification row to reveal:

- Dismiss
- Mark processed

Desktop keeps the visible Dismiss button.

### 4. Mark All Read

Add a "Mark all as read" button in the filter bar. Backend already supports `PATCH /api/events/{id}` per event; for now implement as parallel client-side PATCH calls. A bulk endpoint can be added later if performance matters.

### 5. Color-Coded Severity Borders

Each notification row gets a 3px left border in severity color (critical red, error orange, warn amber, info blue). Hover lifts the row slightly.

### 6. Empty State

The existing "All caught up" state gets a friendlier illustration and copy.

## Navigation Upgrades

### 1. Collapsible Legacy Section

The sidebar's "Legacy" section starts collapsed by default on first load. The user can expand it. State persisted in localStorage.

### 2. Active Page Indicator

Nav items get a thin left accent bar when active instead of just a background color change.

### 3. Mobile Bottom Nav Icons

Replace emoji text with SVG icons for Home, Notifications, and More. Keep labels small.

### 4. Breadcrumb Subtitle

Header shows a small subtitle under the page title on legacy pages: e.g. "Overview · Legacy".

## Animated Transitions

- **Page switches:** 200ms fade + 12px slide-up on `.app-page.active`.
- **Card hover:** 150ms ease on transform, border-color, box-shadow.
- **Status pulse:** 2s infinite ease-in-out on live indicators.
- **Summary tile updates:** number values flash briefly on change.
- **Modal open/close:** 150ms fade + scale from 0.98.

All animations respect `prefers-reduced-motion`.

## Smart Notes / Attention System

A reusable `SmartNote` component for surfacing insights:

| Variant | Use | Color |
|---------|-----|-------|
| `alert` | Needs action now | severity color |
| `heads-up` | Worth knowing | accent |
| `insight` | Pattern / summary | muted |
| `empty` | Nothing to see | muted |

Home's attention card is the first consumer. Future pages can use the same component.

## Color Theme Selector

Add a theme selector accessible from:

- Header: click theme icon cycles presets, long-click/click-hold opens picker
- Or a small palette button next to the theme toggle

Picker UI:

- 5 colored dots
- Selected dot has a ring
- Click sets `--accent-h` via JS and saves to `/api/users/me/theme`
- LocalStorage mirrors for instant re-load

## Module Porting (Incremental)

This phase ports the most useful legacy widgets into the new Home page instead of full-page redesigns:

- **Uptime tile** (already partially there; expand to per-monitor list)
- **Recent events strip**
- **Agent inbox count**
- **Kanban "my tasks" widget**
- **Hermes status widget**

Full page porting (Documents, Events, Settings, Kanban board) stays Phase 2+.

## Mobile Considerations

- Disable heavy glows below 640px to save battery.
- Summary cards stack vertically (existing behavior).
- Scroll-to-top button floats above bottom nav.
- Notification swipe actions only on touch.
- Theme picker as bottom sheet on mobile.

## Accessibility

- All interactive elements keyboard focusable.
- Focus rings visible (2px accent outline, offset 2px).
- Reduced motion respected.
- Color not the only indicator (icons + text accompany severity colors).

## Performance

- No new heavy dependencies.
- Animations use CSS transforms/opacity only.
- Theme switch is a single CSS custom property update.
- Home page parallel fetches remain parallel; add only lightweight calls (`/api/events?limit=5`, `/api/kanban/me`).

## Out of Scope

- Full redesign of Documents, Events, Search, Settings, Kanban board pages.
- Backend bulk-dismiss endpoint (can be added later).
- Real-time presence sensor wiring (field exists, data source TBD).
- Advanced theming (custom hue picker, background images, fonts).

## Files to Touch

- `static/css/tokens.css` — HSL accent variables, new severity-aware tokens.
- `static/css/shell.css` — animations, focus rings, nav active state, scroll-to-top mobile position.
- `static/css/components.css` — SmartNote component, LED pulse, key-cap button.
- `static/css/pages/home.css` — attention card, activity timeline, tappable tiles, briefing renderer.
- `static/css/pages/notifications.css` — time buckets, swipe actions, severity borders.
- `static/index.html` — theme picker markup, Home page additions, notification detail modal.
- `static/js/app.js` — theme preset persistence, SSE live indicator, dead `loadHome`/`loadNotificationsPage` cleanup.
- `static/js/shell.js` — collapsible legacy section state.
- `static/js/pages/home.js` — attention logic, activity fetch, SSE refresh.
- `static/js/pages/notifications.js` — time buckets, detail modal, mark-all-read, swipe handlers.
- `static/js/lib/utils.js` (new) — relative time, debounce, throttle helpers.

## Success Criteria

- Home page surfaces at least one "attention" item when data warrants it.
- Summary cards are tappable and navigate correctly.
- Theme selector changes accent color globally without reload.
- Animations feel smooth but not slow (<300ms).
- Notifications are bucketed by time and tappable for detail.
- Mobile experience is polished and battery-friendly.
- No console errors on Home → Notifications → Overview → Home loop.
