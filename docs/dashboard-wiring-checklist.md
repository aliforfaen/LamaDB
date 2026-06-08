# LamaDB Dashboard — Wiring Checklist

Generated from visual review of `open-design/index.html` (2026-05-29).
**Updated 2026-06-08 after Phase 8 (Dashboard Polish, SSE fixes, Test rebuild).**
## P0 — Must Fix

- [ ] **Dynamic footer status** — "All systems operational" is static. Must reflect actual uptime data (green when all up, red/warn when monitors down).
  - Affects: sidebar footer, visible on all pages

## P1 — Fix During Wiring

- [ ] **Uptime URL contrast** — URL text in monitor cards is too dark on black. Change to `--fg-2` (#b0b2b8).
- [ ] **Events: more rows** — Default 5 rows is too low for a log viewer. Default to 20-50 rows, add "rows per page" selector.
- [ ] **Truncated descriptions** — Feeds table and Document cards cut off descriptions with no way to see full text. Add `title` attribute on hover, or expandable rows.
- [x] **Loading states** — Document detail modal shows "Loading..." while fetching from API. 
- [x] **Error states** — Document detail modal shows friendly message on 404 or network failure.

## P2 — Polish Pass

- [ ] **Tag pills horizontal** — Currently stack vertically, inflating row height. Switch to `flex-wrap: wrap` with horizontal flow.
- [ ] **Documents pagination** — No pagination visible. Add page controls or infinite scroll.
- [ ] **Colorblind accessibility** — Status relies on red/green alone. Add ✓/✗ icons alongside color dots.
- [ ] **RSS syntax highlighting** — Preview panel is plain text. Color XML tags, attributes, strings differently.
- [ ] **Row hover states** — Tables and cards lack hover feedback. Add subtle `--surface-2` background on hover.
- [ ] **Keyboard focus outlines** — Add visible focus rings for keyboard navigation (accessibility).

## P3 — Nice to Have

- [ ] **Low-contrast text** — "v0.1.0", "admin", sidebar footer info are very dim. Bump to `--muted` (#6b6e76) minimum.
- [ ] **Filter bar layout** — "Apply" button is left-aligned with dead space. Move to far-right or auto-apply on change.
- [ ] **Date range picker** — Two separate date inputs. Consider a single date-range component.
- [x] **Sparklines** — Inline SVG sparklines on uptime monitor cards showing recent status history (Phase 8).
- [ ] **Uptime latency context** — Show whether 45ms is "good" or "bad" per service type.

## API Wiring Map

| UI Element | API Endpoint | Auth | Notes |
|------------|-------------|------|-------|
| Stat cards: Documents | `GET /api/documents` | admin | Count from response length or add count endpoint |
| Stat cards: Feeds | `GET /api/feeds` | admin | Count |
| Stat cards: Monitors | `GET /api/uptime/status` | admin | Count up/down from response |
| Stat cards: Events | `GET /api/events` | admin | Count today |
| Recent Events table | `GET /api/events?limit=5&sort=ts:desc` | admin | |
| Uptime Status list | `GET /api/uptime/status` | admin | |
| Active Feeds cards | `GET /api/feeds` | admin | |
| Feeds CRUD table | `GET /POST/PUT/DELETE /api/feeds/*` | admin/agent | |
| Monitor grid | `GET /api/uptime/status` | admin | |
| Status History | `GET /api/uptime/history?limit=50` | admin | Paginated |
| Events filter table | `GET /api/events?source=X&severity=Y&limit=50` | admin | |
| Documents search | `GET /api/search?q=term` | admin | |
| Document detail | `GET /api/documents/{id}` | admin | |
| Document links | `GET /api/documents/{id}/links` | admin | |
| Public RSS | `GET /feeds/{slug}.xml` | none | Already working |
| Semantic search | `GET /api/search/semantic?q=term&limit=10` | admin | pgvector cosine similarity |
| Document graph | `GET /api/documents/{id}/graph?depth=2` | admin | Recursive CTE traversal |
| Hermes health | `GET /api/hermes/health` | admin | Dashboard Hermes tab |
| Hermes system | `GET /api/hermes/system` | admin | Dashboard Hermes tab |
| Hermes sessions | `GET /api/hermes/sessions?limit=10` | admin | Dashboard Hermes tab |
| Hermes session stats | `GET /api/hermes/sessions/stats` | admin | Dashboard Hermes tab |
| FreshRSS status | `GET /api/freshrss/status` | admin | Dashboard FreshRSS tab — configured flag, article count, last sync |
| FreshRSS feeds | `GET /api/freshrss/feeds` | admin | Subscription list from GReader API |
| FreshRSS articles | `GET /api/freshrss/articles?limit=20` | admin | Stored articles (source_type=rss_article) |
| FreshRSS sync | `POST /api/freshrss/sync` | admin | Manual trigger for GReader polling |
| Embeddings backfill | `POST /api/embeddings/backfill` | admin | Batch-embed documents without embeddings (OpenAI) |
| Dashboard SSE stream | `GET /api/dashboard/stream?key=...` | any | Server-Sent Events — auth via query param, heartbeat 15s |

## Auth Pattern

Dashboard uses an admin API key stored in localStorage (set on first visit via a settings modal).
All fetch calls include `Authorization: Bearer <key>` header.
Public endpoints (`/feeds/{slug}.xml`, `/api/uptime/webhook`) skip auth.
SSE endpoint uses query-param auth (`?key=...`) since EventSource can't set headers.

```css
/* Semantic aliases for readability during wiring */
--success: var(--accent);      /* #00ff88 */
--error: var(--danger);        /* #ff3333 */
--warning: var(--warn);        /* #ffaa00 */
--info: #00bfff;
```
