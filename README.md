# LamaDB

Self-hosted central data layer / Life OS. Stores documents, events, and relationships in PostgreSQL. Exposes a REST API with 11 auto-discovered modules and a management dashboard.

## Quick Start

```bash
docker compose up -d
# Dashboard at http://localhost:8000
# Swagger docs at http://localhost:8000/docs
```

## What It Does

- **Document store** — universal storage for wiki pages, agent output, summaries, notes
- **Event bus** — queryable PostgreSQL event log with severity filtering
- **RSS feeds** — per-topic XML feeds from summarized documents
- **Uptime monitoring** — Uptime Kuma webhooks + registry poller + topology host map
- **Agent Board** — task queue with claim workflow + inter-agent messaging (LISTEN/NOTIFY)
- **Dashboard** — command center with status bar, ticker, 12 tabs (Overview, Feeds, Uptime, Events, Wiki, Documents, Ntfy, Dozzle, Agent Board, Notflix, Hermes, Settings)
- **Hermes analytics** — session stats, token usage, system health from Hermes API (v0.16.0)
- **Smart notifications** — rule-based routing to Telegram/ntfy/webhook channels
- **Data collectors** — background pollers for FreshRSS, ntfy, Dozzle, Notflix, Hermes

## Architecture

```
PostgreSQL 16 + pgvector + pg_trgm
       ↑
FastAPI (async, module auto-discovery)
       ↑
┌──────┼──────┬──────────┬───────────┐
│ Documents │ Events │ Modules  │ Dashboard │
│ + Links   │ + Bus  │ (11)     │ (12 tabs) │
│ + Search  │        │          │           │
│ + Graph   │        │          │           │
└───────────┴────────┴──────────┴───────────┘
```

## Core API

| Endpoint | Description |
|----------|-------------|
| `GET /api/documents` | List/search documents |
| `POST /api/documents` | Create document |
| `GET /api/documents/{id}/graph` | Recursive graph traversal (recursive CTE, cycle detection) |
| `GET /api/search?q=term` | Full-text search (pg_trgm) |
| `GET /api/search/semantic?q=term` | Vector similarity search (pgvector `<=>`, placeholder) |
| `GET /api/events` | Event bus with severity/source filters |
| `POST /api/events` | Publish event |

## Modules

| Module | Description | Poller |
|--------|-------------|--------|
| **feeds** | RSS XML generator from documents | — |
| **uptime** | Uptime Kuma webhook + registry poller + topology | 1h |
| **agent_board** | Task queue + agent messaging | — |
| **freshrss** | FreshRSS feed aggregation | 15m |
| **ntfy** | ntfy notification history | 5m |
| **dozzle** | Docker container log viewer | 5m |
| **wiki** | Karakeep wiki reader + scratchpad | — |
| **hermes** | Hermes Agent analytics (health, sessions, tokens) | 5m |
| **notflix** | Sonarr/Radarr/Tautulli media status | 30m |
| **notifications** | Smart notification routing engine | — |
| **dashboard** | Serves static SPA | — |

## Auth

API key authentication via `Authorization: Bearer <key>` header.

| Role | Access |
|------|--------|
| `admin` | Full read/write, all modules |
| `agent` | Scoped read/write per module |
| `read` | Read-only public endpoints |

RSS feed endpoints (`/feeds/*.xml`) and uptime webhook are public.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `API_KEY_SALT` | Salt for API key bcrypt hashing |
| `CORS_ORIGINS` | Allowed CORS origins |
| `UPTIME_KUMA_URL` | Uptime Kuma API base URL (for registry poller) |
| `UPTIME_KUMA_API_KEY` | Uptime Kuma API key |

## Development

```bash
# Docker (recommended)
docker compose up -d
# Rebuild after changes
docker compose build api && docker compose up -d api

# Run specific tests
docker exec lamadb_api python3 -m pytest tests/test_feeds.py -q

# Check logs
docker logs lamadb_api --tail 20
```

## License

MIT
