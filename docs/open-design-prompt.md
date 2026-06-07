# LamaDB Dashboard — Open Design Prompt

## Settings

- **Skill:** `dashboard`
- **Design system:** `cursor` (monospace accents, dev-tool aesthetic, dark-first)
- **Direction:** Tech Utility
- **Fallback design systems:** `warp` (terminal emulator) or `sentry` (dev monitoring)

## Prompt

Build a self-hosted management dashboard for "LamaDB" — a central data layer / Life OS that stores documents, events, and RSS feeds in PostgreSQL.

**Layout:** Dark sidebar navigation on the left, main content area on the right. Dense information layout — this is a power-user tool, not a marketing page. Monospace fonts for data, clean sans-serif for headings. Terminal/hacker aesthetic with high contrast.

**Sidebar navigation** with 5 sections:
- **Overview** (home icon)
- **Feeds** (rss icon)
- **Uptime** (heartbeat icon)
- **Events** (activity icon)
- **Documents** (database icon)

**Page 1 — Overview:**
- Top row: 4 stat cards — "Total Documents" (1,247), "Active Feeds" (3), "Monitors Up" (33/35), "Events Today" (89)
- Middle: two-column layout
  - Left: "Recent Events" — compact table with 5 rows showing timestamp, source, severity (color-coded dots: green=info, yellow=warn, red=critical), title
  - Right: "Uptime Status" — list of monitors with name, status dot (green/red), last check time
- Bottom: "Active Feeds" — horizontal cards showing feed name, slug, item count

**Page 2 — Feeds:**
- Table listing all RSS feeds: name, slug, description, filter tags, source types, max items, created date
- "Create Feed" button opens a modal/form: name, slug (auto-generated from name), description, filter tags (tag input), filter source types (dropdown), max items (number)
- Each row has edit/delete actions
- Preview panel on the right showing what the RSS XML output looks like for the selected feed

**Page 3 — Uptime:**
- Top: summary bar — "33 Up · 2 Down · 0 Unknown" with colored indicators
- Main: monitor grid — each monitor is a card showing name, URL, current status (up=green border, down=red border), last heartbeat time, response duration
- Bottom: "Status History" table — paginated, showing timestamp, monitor name, status change, message, duration

**Page 4 — Events:**
- Filter bar at top: source dropdown, severity dropdown (info/warn/critical), date range picker, search text input
- Main: full-width event table — timestamp, source, type, severity (color badge), title, body preview (truncated), processed status (checkbox)
- Pagination at bottom
- Click a row to expand and show full body + metadata JSON

**Page 5 — Documents:**
- Search bar at top with full-text search input
- Results as a card grid — each card shows title, source type badge, tags (pill badges), created date, content preview (first 200 chars)
- Click a card to open detail view: full content, metadata JSON, linked documents (graph visualization showing source → target relationships)
- "Create Document" button: form with title, source type, content (textarea), tags (tag input)

**Color palette:** Dark background (#0a0a0a or similar), accent green (#00ff88 or terminal green), secondary accent cyan (#00d4ff), warning yellow (#ffaa00), critical red (#ff3333). Monospace font (JetBrains Mono or similar) for data values, clean sans-serif for UI text.

**Branding:** "LamaDB" logo text in the sidebar header with a subtle database/circuit icon. Version number "v0.1.0" below it. Footer: "Self-hosted · PostgreSQL · FastAPI"

## After Design

Once the HTML artifact is ready, we wire it into `modules/dashboard/` + `static/` with real API calls:

| UI Element | API Endpoint | Auth |
|------------|-------------|------|
| Stat cards | `GET /api/documents`, `GET /api/feeds`, `GET /api/uptime/status`, `GET /api/events` | admin key |
| Recent Events table | `GET /api/events?limit=5&sort=ts:desc` | admin key |
| Uptime Status list | `GET /api/uptime/status` | admin key |
| Active Feeds cards | `GET /api/feeds` | admin key |
| Feeds CRUD table | `GET/POST/PUT/DELETE /api/feeds/*` | admin/agent key |
| Monitor grid | `GET /api/uptime/status` | admin key |
| Status History | `GET /api/uptime/history?limit=50` | admin key |
| Events filter table | `GET /api/events?source=X&severity=Y&limit=50` | admin key |
| Documents search | `GET /api/search?q=term` | admin key |
| Document detail | `GET /api/documents/{id}` | admin key |
| Document links | `GET /api/documents/{id}/links` | admin key |
