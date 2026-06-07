# LamaDB

Self-hosted central data layer / Life OS. Stores documents, events, and relationships in PostgreSQL. Exposes a REST API and generates RSS feeds from summarized content.

## Quick Start

```bash
docker compose up -d
# API available at http://localhost:8000
# Swagger docs at http://localhost:8000/docs
```

## What It Does

- **Document store** — universal storage for wiki pages, agent output, summaries, notes
- **Event bus** — replaces flat-file event logging with queryable PostgreSQL
- **RSS feeds** — generates per-topic XML feeds from summarized documents
- **Uptime monitoring** — receives Uptime Kuma webhooks, tracks monitor status
- **Dashboard** — command center with status bar, scrolling ticker, and module cards
- **Ticker system** — real-time activity marquee with #breaking alerts and dashboard-icons
- **Data source modules** — ntfy notifications, Dozzle logs, FreshRSS (planned)

## Architecture

```
PostgreSQL 16 + pgvector + pg_trgm
       ↑
FastAPI (async, modular plugin architecture)
       ↑
┌──────┼──────┬──────────┐
│ Documents │ Events │ Modules  │
│ + Links   │ + Bus  │ (feeds,  │
│           │        │  uptime) │
└───────────┴────────┴──────────┘
```

## Modules

| Module | Type | Status | Description |
|--------|------|--------|-------------|
| **uptime** | Webhook | ✅ Done | Uptime Kuma webhook receiver + status tracking (4 endpoints, 10 tests) |
| **feeds** | Generator | ❌ Planned | RSS XML from summarized documents |
| **dashboard** | Static | ❌ Planned | Vue 3 CDN SPA management UI |

## Auth

API key authentication via `Authorization: Bearer *** header.

| Role | Access |
|------|--------|
| `admin` | Full read/write, all modules |
| `agent` | Scoped read/write per module |
| `read` | Read-only public endpoints |

RSS feed endpoints (`/feeds/*.xml`) are public — no auth required.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | — | PostgreSQL connection string |
| `API_KEY_SALT` | — | Salt for API key hashing |
| `CORS_ORIGINS` | `*` | Allowed CORS origins |

## Development

```bash
# Docker (recommended)
docker compose up --build -d
# API at http://localhost:8000, Swagger at http://localhost:8000/docs

# Run tests inside container
docker compose up --build -d
docker exec lamadb_api python3 -m pytest tests/ -v

# Or local (requires Python 3.12 + PostgreSQL)
pip install -r requirements.txt
DATABASE_URL=postgresql://lamadb:***@localhost:5432/lamadb uvicorn app.main:app --reload
```

## License

MIT
