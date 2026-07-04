# LamaDB — Central Data Layer / Life OS

Self-hosted PostgreSQL-backed data hub that serves as the central nervous system for a homelab, agent ecosystem, and personal life management. 13 auto-discovered modules, real-time dashboard, MCP server for AI agents, and a Kanban board for task orchestration.

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/fastapi-0.100+-teal.svg)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/postgresql-16-blue.svg)](https://www.postgresql.org/)

## What It Does

LamaDB replaces scattered JSONL files, Telegram notification channels, paper notes, and manual service monitoring with a single queryable database. Everything writes to one place; everything reads from one place.

- **📄 Universal Document Store** — wiki pages, agent output, summaries, notes, all in one table with full-text, semantic (pgvector), and graph traversal search
- **📡 Event Bus** — PostgreSQL-backed event log with severity routing, NOTIFY triggers, and SSE real-time streaming
- **📊 Life Console Dashboard** — 15-tab web UI with draggable widgets, real-time updates, mobile responsive, theme toggle, command palette
- **🤖 Agent Orchestration** — Kanban boards with task state machines, agent identity with API keys, MCP server with 22+ tools, inter-agent mailboxes
- **📡 Infrastructure Monitoring** — 37 Uptime Kuma monitors with sparklines, Docker container logs via Dozzle, service health cards
- **📰 RSS Feeds** — LLM-summarized XML feeds from documents, public endpoints for feed readers
- **🔔 Smart Notifications** — rule-based routing with priority, channel selection, and batching
- **📚 Wiki Integration** — 83-page knowledge base served from filesystem with search, scratchpad, and activity log
- **🎬 Media Stack** — Sonarr/Radarr/Tautulli status, library snapshots, recent activity
- **🧠 Agent Analytics** — Hermes session tracking, token usage, cost estimates, system health

## Requirements

- **Docker** and **Docker Compose** (PostgreSQL 16 + FastAPI in containers)
- **PostgreSQL 16** with extensions: `pgvector`, `pg_trgm`
- **Python 3.12** (included in Docker image)
- **OpenAI API key** (optional — for vector embeddings, falls back to pseudo-embeddings)
- **Hermes Agent** (optional — for agent analytics, session tracking, cost monitoring)

## Deployment

LamaDB is deployed on a Proxmox LXC — **not** run locally via `docker compose up`.

- **Host**: `192.168.68.26`
- **SSH**: `ssh lamadb-dev`
- **Repo path**: `/home/messhias/projects/lamadb` (on LXC)
- **Branch**: `feat/life-os-frontend-phase1`
- **Dashboard**: `http://192.168.68.26:8000`
- **Swagger docs**: `http://192.168.68.26:8000/docs`
- **MCP endpoint**: `http://192.168.68.26:8000/mcp`
- **Admin key**: `lamadb_test_key_2026`

```bash
# Deploy/rebuild on the LXC
ssh lamadb-dev "cd /home/messhias/projects/lamadb && docker compose up -d"

# Or rebuild after code changes
ssh lamadb-dev "cd /home/messhias/projects/lamadb && docker compose build api && docker compose up -d api"
```

For a rare isolated dev instance, Docker Compose is still available — `cp .env.example .env` on the LXC, then `ssh lamadb-dev "cd /home/messhias/projects/lamadb && docker compose up -d"`.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Docker Compose                         │
│                                                          │
│  ┌──────────────────┐    ┌──────────────────────────┐   │
│  │ PostgreSQL 16    │    │  FastAPI (Python 3.12)    │   │
│  │ + pgvector       │◀──▶│  + asyncpg (async driver) │   │
│  │ + pg_trgm        │    │  + Module auto-discovery  │   │
│  │ + LISTEN/NOTIFY  │    │  + SSE / WebSocket        │   │
│  └──────────────────┘    │  + MCP server (JSON-RPC)  │   │
│                          │  + bcrypt API key auth    │   │
│                          └──────────┬────────────────┘   │
│                                     │                    │
│         ┌───────────────┬───────────┼──────────┬────────┤
│         ▼               ▼           ▼          ▼        │
│    ┌─────────┐   ┌──────────┐  ┌────────┐  ┌────────┐  │
│    │Documents│   │  Events  │  │Modules │  │Dashboard│  │
│    │+ Links  │   │  + Bus   │  │ (13)   │  │(15 tabs)│  │
│    │+ Search │   │  + SSE   │  │        │  │+ Widgets│  │
│    │+ Graph  │   │          │  │        │  │+ Kanban │  │
│    └─────────┘   └──────────┘  └────────┘  └────────┘  │
└─────────────────────────────────────────────────────────┘
```

## Core API

| Endpoint | Auth | Description |
|----------|------|-------------|
| `GET /health` | None | Health check |
| `GET /api/documents` | Bearer | List/search documents |
| `POST /api/documents` | admin/agent | Create document |
| `GET /api/documents/{id}/graph` | Bearer | Recursive graph traversal (CTE, cycle detection) |
| `GET /api/search?q=term` | Bearer | Full-text search (pg_trgm) |
| `GET /api/search/semantic?q=term` | Bearer | Vector similarity search (pgvector, OpenAI embeddings) |
| `GET /api/events` | Bearer | Event bus with severity/source filters |
| `POST /api/events` | admin/agent | Publish event |
| `POST /api/embeddings/backfill` | admin | Batch embed existing documents |
| `POST /mcp` | Bearer | MCP JSON-RPC 2.0 endpoint (22+ tools) |

## Modules

| Module | Description | Endpoints | Poller |
|--------|-------------|-----------|--------|
| **kanban** | Agent task orchestration — boards, columns, tasks, dependencies, MCP tools | 30 | — |
| **agent_board** | Task queue + agent messaging + mailboxes | 15 | — |
| **feeds** | RSS XML generator from documents | 6 | — |
| **uptime** | Uptime Kuma webhook + registry poller + topology | 7 | 1h |
| **freshrss** | FreshRSS feed aggregation | 4 | 15m |
| **ntfy** | ntfy notification history | 2 | 5m |
| **dozzle** | Docker container log viewer | 3 | 5m |
| **wiki** | Wiki reader (83 pages) + scratchpad + activity log | 10+ | — |
| **hermes** | Hermes Agent analytics (health, sessions, tokens, costs) | 8 | 5m |
| **notflix** | Sonarr/Radarr/Tautulli media status | 3 | 30m |
| **notifications** | Smart notification routing engine | 4 | — |
| **dashboard** | Management dashboard + Life Console UI | 12+ | — |
| **users** | User identity profiles + API key management | 6 | — |

## Auth

Bearer token via `Authorization: Bearer <key>`. Keys stored as bcrypt hashes with O(1) prefix lookup.

| Role | Access |
|------|--------|
| `admin` | Full read/write on all modules + core |
| `agent` | Read/write on scoped modules (kanban, documents, events) |
| `read` | Read-only on public endpoints |

Public endpoints: `GET /feeds/*.xml`, `POST /api/uptime/webhook`, `POST /api/dozzle/webhook`.

## Environment Variables

See `.env.example` for all 25+ variables. Key ones:

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `API_KEY_SALT` | Yes | Salt for API key bcrypt hashing |
| `CORS_ORIGINS` | No | Allowed CORS origins |
| `OPENAI_API_KEY` | No | For vector embeddings (skips if empty) |
| `HERMES_URL` | No | Hermes Agent API URL |
| `UPTIME_KUMA_URL` | No | Uptime Kuma API URL |
| `FRESHRSS_URL` | No | FreshRSS GReader API URL |
| `DOZZLE_URL` | No | Dozzle API URL |
| `SONARR_URL` / `RADARR_URL` / `TAUTULLI_URL` | No | Media stack URLs |

## Development

All commands run on the LXC via `ssh lamadb-dev`.

```bash
# Rebuild after code changes
ssh lamadb-dev "cd /home/messhias/projects/lamadb && docker compose build api && docker compose up -d api"

# Run a specific test
ssh lamadb-dev "cd /home/messhias/projects/lamadb && docker exec lamadb_api python3 -m pytest tests/test_feeds.py -q"

# Run benchmarks
ssh lamadb-dev "cd /home/messhias/projects/lamadb && docker exec lamadb_api python3 benchmarks/bench_all_endpoints.py"

# Check logs
ssh lamadb-dev "cd /home/messhias/projects/lamadb && docker logs lamadb_api --tail 20"

# DB access
ssh lamadb-dev "cd /home/messhias/projects/lamadb && docker exec lamadb_postgres psql -U lamadb -d lamadb"

# Swagger UI
# Open http://192.168.68.26:8000/docs
```

Static files are COPY'd into the Docker image — rebuild after any `static/`, `app/`, `modules/`, or `migrations/` changes.

## MCP Server

22 JSON-RPC tools for AI agents. Connect at `POST /mcp` with Bearer auth.

| Tool | Module | Description |
|------|--------|-------------|
| `search_documents` | Core | Full-text + semantic search |
| `get_document` | Core | Get document by ID |
| `create_document` | Core | Create document |
| `create_event` | Core | Publish event |
| `get_events` | Core | Query events |
| `kanban_my_tasks` | Kanban | Open tasks for agent |
| `kanban_find_work` | Kanban | Find unassigned tasks |
| `kanban_claim_task` | Kanban | Claim and move to In Progress |
| `kanban_complete_task` | Kanban | Complete with auto-start dependents |
| `kanban_create_task` | Kanban | Create task |
| `kanban_get_task` | Kanban | Full task detail |
| `kanban_my_instructions` | Kanban | Agent onboarding instructions |
| `get_agent_tasks` | Agent Board | Query task queue |
| `send_agent_message` | Agent Board | Send inter-agent message |
| `get_uptime_status` | Uptime | Current monitor status |
| `scratchpad_capture` | Wiki | Save quick note |

## Performance

| Metric | Value | Tool |
|--------|-------|------|
| CPU idle | 0.09% | docker stats |
| `/health` | 4ms | curl |
| `/api/dashboard/overview` | 324ms | benchmarks |
| All API endpoints p95 | < 350ms | benchmarks |
| Cache hit rate | 72% | `/api/dashboard/cache-stats` |
| Wiki pages | 83 | `/api/wiki/pages` |
| Monitors | 37 | `/api/uptime/status` |
| Hermes sessions | 193 | `/api/hermes/sessions/stats` |

See `benchmarks/bench_all_endpoints.py` for the full endpoint timing suite.

## License

MIT — see [LICENSE](LICENSE) for details.

---

**Built on:** PostgreSQL 16, FastAPI, asyncpg, SortableJS, pgvector  
**Deployed with:** Docker Compose, Coolify  
**Part of:** [LamaFiles](https://lamafiles.com) ecosystem
