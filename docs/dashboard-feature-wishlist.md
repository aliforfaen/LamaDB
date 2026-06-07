# LamaDB Dashboard — Feature Wishlist

Extracted from Ali's brainstorm session (`open-design/lamalab-dashboard.html`).

## Global: Rolling Status Bar (Top Ticker)

A horizontally scrolling ticker bar across the top of the dashboard showing live system messages. Built-in to the dashboard shell, not a module card.

**Content sources:**
- Uptime Kuma: host status, service up/down alerts
- ntfy: pending notification count, priority alerts
- LLM Wiki: indexing progress, knowledge graph updates
- Dozzle: container errors, warnings
- Plex/Notflix: active streams, library updates
- Notebook: pending scratchpad items queued for ingestion

**Design:**
- Color-coded prefixes: ✓ green (ok), ⚠ yellow (warn), ✗ red (error)
- Duplicates content twice for infinite scroll illusion
- Status LED indicators: services count, notification count, wiki updates, dozzle errors

**Implementation:** Dashboard shell queries `/api/dashboard/overview` + events endpoint on interval, renders scrolling marquee.

---

## Module: Uptime Kuma — Host Map

A visual topology map showing hosts as positioned nodes on a grid background.

**Features:**
- SVG grid background (green lines, low opacity)
- Host nodes positioned absolutely (Valhalla, Probook, Dev-VM, Jita)
- Color-coded dots: green = healthy, yellow = degraded, red = down
- Pulsing animation on dots
- Host label + role + latency below each node
- Dashed SVG connecting lines between hosts (mesh topology)
- Summary stats row: services online, 30d uptime %, alerts today, host count
- "Last check: Xs ago" footer

**Data source:** `/api/uptime/status` grouped by host (extract host from monitor_url or name)

---

## Module: ntfy Notifications

A notification viewer panel showing ntfy messages with priority badges.

**Features:**
- Priority badges: HIGH (red), INFO (blue), LOW (gray)
- Title + body + timestamp per item
- Scrollable list (max-height 240px)
- Color-coded border (glow-red)

**Data source:** New `/api/notifications` endpoint polling ntfy server, or events table filtered by source='ntfy'

---

## Module: Notebook / Scratchpad

A quick-capture textarea for thoughts, ideas, reminders. Agents auto-ingest on interval.

**Features:**
- Monospace textarea with placeholder text
- Clear + Save buttons
- Status line: last ingested time, agents queued count, target path
- Badge: "auto-ingest 30min"
- Saves to documents table (source_type='scratchpad')
- Agent picks up new scratchpads and routes to LLM Wiki

**Data source:** `POST /api/documents` with source_type='scratchpad', `GET /api/documents?source_type=scratchpad&limit=1`

---

## Module: Dozzle Logs

A live container log stream viewer with host filtering.

**Features:**
- Host filter pills (all, valhalla, probook, dev-vm, jita ⚠)
- Color-coded log levels: INFO (green), WARN (yellow/orange), ERROR (red)
- Monospace log lines: timestamp, level, host, container, message
- Summary footer: X errors · Y warnings · Z infos (last 30m)
- Polling indicator (5s interval)

**Data source:** Dozzle API integration module (future — Poller type)

---

## Module: Plex Stack / Notflix

Media server status with active streams and library stats.

**Features:**
- Stats row: active streams, active users, recently added
- "Now Playing" list: avatar initials, title, quality, user, progress %
- Library item count badge

**Data source:** Tautulli/Sonarr/Radarr integration modules (future — Poller type)

---

## Module: LLM Wiki Log

An AI-written log feed showing wiki/knowledge graph activity.

**Features:**
- Monospace log lines with colored tags: [KG], [SYS], [AGENT]
- Highlighted entities in cyan, magenta, yellow
- Timestamp + tag + message format
- Full-width module card

**Data source:** Events table filtered by source='llm-wiki'

---

## Module: Agent Status

Cards showing each agent's status, role, and uptime.

**Features:**
- Agent name + role badge (ORCHESTRATOR, WORKER, etc.)
- Status indicator (online/offline)
- Uptime counter
- Last action summary

**Data source:** New `/api/agents` endpoint (future — Agent Board integration)

---

## Design Principles (from brainstorm)

1. **Each module owns its card** — modules define their own dashboard view
2. **Some elements are "built-in"** — rolling status bar, quick stats, nav tabs
3. **Glow aesthetics** — green/cyan/magenta/red glow effects on borders and text
4. **Full monospace** — JetBrains Mono everywhere, no sans-serif
5. **Dark canvas** — #0a0e0a background, CRT scanline overlay optional
6. **LED indicators** — colored dots for status at a glance
7. **Grid backgrounds** — SVG grid patterns on map/visualizations

---

## Implementation Priority

| Priority | Feature | Module Type | Status |
|----------|---------|-------------|--------|
| 1 | Rolling status bar | Built-in | ✅ Done |
| 2 | Ticker marquee + events | Built-in | ✅ Done |
| 3 | Uptime Kuma → ticker | Webhook | ✅ Done |
| 4 | ntfy Notifications | Poller | ✅ Module built, needs ntfy server |
| 5 | Dozzle Logs | Poller | ✅ Module built, needs Dozzle restart |
| 6 | FreshRSS | Poller | 🔄 Planned (replaces miniflux module) |
| 7 | Uptime Kuma host map | Built-in (enhanced) | 🔲 Needs brainstorm |
| 8 | Notebook/Scratchpad | New module | ✅ Done (part of wiki module) |
| 9 | LLM Wiki Log | New module | ✅ Done (wiki reader + edit log) |
| 10 | Plex/Notflix | New module (Poller) | 🔲 Large |
