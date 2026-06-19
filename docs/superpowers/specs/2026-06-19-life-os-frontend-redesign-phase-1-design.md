# LamaDB — Life-OS Frontend Redesign: Phase 1

> Design document for the first phase of the frontend rewrite.
> Date: 2026-06-19
> Scope: new global shell + Home + smart Notifications inbox
> Approach: incremental redesign; legacy pages remain functional inside the new shell

---

## Goals

- Stop looking like a database admin panel.
- Become a personal Life-OS interface.
- Work well in the Android WebView AND on desktop.
- Surface important information first; bury noise.
- Keep the project functional during the rewrite.

---

## Out of Scope (Deferred)

The following are explicitly deferred to future phases. They are listed here so they do not get forgotten.

- Tasks / Kanban page redesign
- Things / Home Assistant page redesign
- Settings page redesign
- Feeds, Uptime, Events, Wiki, Documents, Hermes, Agent Board, Dozzle, FreshRSS, ntfy, Notflix, Secrets, Groups, Access Requests page redesigns
- Morning brief backend wiring (briefing endpoint is a future TODO)
- YouTube, Spotify, Audiobookshelf integrations
- RSS auto-publishing from events

---

## Architecture

### Tech Stack

- **Alpine.js 3** for declarative UI components.
  - Loaded via CDN with a local fallback in `static/js/lib/alpine.min.js`.
- **Vanilla CSS** with a token layer (`static/css/tokens.css`).
- **Existing `api()` wrapper** kept from `static/js/app.js`, possibly modernized.
- **No build step.** Everything is static files served by FastAPI.

### Directory Structure

```
static/
├── index.html              # new shell
├── css/
│   ├── tokens.css          # design tokens: colors, spacing, type, radius, shadows
│   ├── shell.css           # layout, sidebar, bottom nav, header
│   ├── components.css      # buttons, cards, lists, badges, sheets, empty states
│   ├── pages/
│   │   ├── home.css        # Home page specific styles
│   │   └── notifications.css
│   ├── legacy.css          # minimal shim for legacy page sections
│   ├── dashboard.css       # existing; kept for legacy page sections
│   └── kanban.css          # existing; kept for legacy kanban page
└── js/
    ├── lib/
    │   └── alpine.min.js   # local fallback
    ├── app.js              # core: auth, API, SSE, navigation, theme
    ├── shell.js            # new shell behavior (Alpine data + helpers)
    └── pages/
        ├── home.js         # Home page Alpine component
        └── notifications.js
```

### Global Shell

#### Desktop

- Collapsible left sidebar.
- Top group: **Home**, **Notifications**.
- Bottom group: legacy tools (Monitoring, Data Sources, Admin, Security).
- Top bar: page title, search button (cmd-K), theme toggle, profile.

#### Mobile

- Bottom tab bar with 3 items: **Home**, **Notifications**, **More**.
- "More" opens a bottom sheet with the full page list.
- Safe-area insets respected so the Android WebView does not clip.

#### Legacy Pages

- Existing page sections remain inside the new shell.
- They keep working as-is.
- They will visually mismatch until migrated; this is expected and documented.

---

## Design System

### Tokens (`static/css/tokens.css`)

**Colors (dark default, light via `data-theme="light"`)**

- `--fg`: primary text
- `--fg-2`: secondary text
- `--muted`: tertiary text
- `--surface`: app background
- `--surface-1`: card background
- `--surface-2`: elevated/hover background
- `--surface-3`: input background
- `--border`: divider/border
- `--accent`: user accent color
- `--accent-dim`: accent at low opacity
- `--success`, `--warning`, `--error`, `--info`

**Spacing**

- `--space-1` through `--space-12` (4px base grid)

**Typography**

- `--font-display`: Inter
- `--font-mono`: JetBrains Mono
- Sizes: xs, sm, base, lg, xl, 2xl, 3xl

**Radius & Shadows**

- `--radius-sm`, `--radius-md`, `--radius-lg`, `--radius-xl`
- `--shadow-card`, `--shadow-sheet`, `--shadow-modal`

**Safe Areas**

- `--safe-top`, `--safe-bottom`, `--safe-left`, `--safe-right`

### Components

Components are CSS classes plus Alpine behavior patterns, not custom elements.

| Component | Purpose |
|-----------|---------|
| `.ll-button` | primary, secondary, ghost, danger |
| `.ll-card` | surface, padding, shadow |
| `.ll-list` | grouped list items |
| `.ll-list-item` | row with leading icon, title, trailing action |
| `.ll-empty-state` | icon + message |
| `.ll-bottom-sheet` | mobile drawer |
| `.ll-badge` | severity/status badges |
| `.ll-skeleton` | loading placeholders |

### Accessibility

- Visible focus rings on keyboard focus.
- `aria-label` on icon-only buttons.
- Keyboard navigation preserved (cmd-K, `/`, `g` shortcuts).
- Touch targets ≥ 44×44 on mobile.

---

## Home Page

### Purpose

"What do I need to know right now?" Scannable in 5 seconds. No raw tables.

### Sections

1. **Today card**
   - Date + greeting ("Good morning")
   - Presence status (home / away / sleeping) if Home Assistant provides it
   - One-line morning brief if the briefing feed/endpoint is available; otherwise hidden

2. **Notification summary**
   - Prominent horizontal card with actionable counts:
     - Critical issues
     - Unread grouped notifications
     - Pending tasks
   - Tapping navigates to Notifications.

3. **Quick actions grid**
   - 4-6 buttons: Log event, Toggle scene, Create task, Add note
   - Desktop: compact icon buttons
   - Mobile: larger touch targets

4. **Active automations / status**
   - Short list of what's currently happening:
     - Active HA scenes
     - Running agents
     - Recent notable events

5. **Recent RSS headlines**
   - 3-5 latest headlines from LamaDB feeds
   - Expandable

### Fallbacks

- If briefing endpoint is unavailable, hide the brief block.
- If HA presence is unavailable, hide presence.
- Empty states for all data sections.

---

## Notifications Page

### Purpose

Show what matters, grouped. Replace the raw event table.

### Default View: Grouped Inbox

- Use `/api/notifications/unread?aggregate=true`.
- Each group rendered as a card:
  - Normalized title pattern
  - Source icon/name
  - Severity badge
  - Count (e.g., `×47`)
  - First seen / last seen
- One-tap dismiss marks all event IDs in the group as processed.

### Priority Sections

1. Critical / Actionable (services down, errors)
2. Warnings
3. Info / noise (collapsed or lower)

### Filters

- Source dropdown
- Severity chips
- Date range
- "Show processed" toggle (fetches from `/api/events`)

### Empty State

- "All caught up" with an icon.

### Mobile UX

- Swipe card to dismiss.
- Pull-to-refresh.

---

## Data Flow

### Home Page

| Data | Endpoint |
|------|----------|
| Health/status | `GET /api/dashboard/overview` |
| Top notification groups | `GET /api/notifications/unread?aggregate=true&limit=5` |
| Morning brief | Future: `GET /api/feeds/briefing` or similar |
| Service status | `GET /api/uptime/status` |
| Agent status | `GET /api/hermes/health` |
| Live updates | Existing SSE channels |

### Notifications Page

| Action | Endpoint |
|--------|----------|
| Grouped inbox | `GET /api/notifications/unread?aggregate=true` |
| Dismiss group | `POST /api/notifications/dismiss` with `event_ids` |
| Filter/detail view | `GET /api/events?severity=...&source=...` |
| Mark individual processed | `POST /api/events/{id}/processed` |

### Theme

| Action | Endpoint |
|--------|----------|
| Load theme | `GET /api/users/me/theme` |
| Save theme | `PUT /api/users/me/theme` |

---

## Error Handling

- Network errors show a non-blocking toast/banner, not alert boxes.
- 401 redirects to the auth modal.
- Empty states are explicit, not blank.
- Loading states use skeletons, not spinners where possible.

---

## Testing Strategy

- Manual testing via browser DevTools and Android WebView.
- Verify desktop layout, mobile layout, and safe-area insets.
- Verify cmd-K, `/`, `g` shortcuts still work.
- Verify legacy pages still render inside the new shell.
- Unit-style checks are not required for this phase.

---

## Success Criteria

- [ ] New shell renders on desktop and mobile.
- [ ] Home page loads and displays today card, notification summary, quick actions, status, and RSS headlines.
- [ ] Notifications page shows grouped inbox with dismiss and filter behavior.
- [ ] Theme (dark/light/accent) persists per user.
- [ ] Legacy pages remain accessible and functional.
- [ ] Android WebView displays correctly without clipping.
- [ ] UI review pass scheduled after frontend subagent work.

---

## Future Roadmap (Deferred Phases)

- Phase 2: Tasks / Kanban mobile redesign
- Phase 3: Things / Home Assistant redesign
- Phase 4: Settings redesign
- Phase 5: Remaining legacy page migrations
- Phase 6: Morning brief backend wiring
- Phase 7: Media integrations (YouTube, Spotify, Audiobookshelf)

---

## Notes

- This is an incremental redesign. The old frontend is not being preserved for sentiment; it is being replaced piece by piece.
- The first implementation plan should be small enough to complete in one session.
- A UI review pass will happen after frontend subagent work to polish the result.
