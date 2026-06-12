# Agent Docs + Theme Backend + DB Dedup Cron — Design Spec

> **Date:** 2026-06-12 | **Status:** Draft | **Scope:** Three independent subsystems

---

## 1. Agent Onboarding Docs (AGENTS_API.md)

### Purpose

AI agents connecting to LamaDB via MCP or REST need a single reference document that explains how to use the kanban system, task lifecycle, and identity model.

### Deliverables

**A. `AGENTS_API.md` in repo root**

Contents:
- **Quick start** — what LamaDB is, how to connect (API key header, MCP server URL)
- **MCP tools reference** — all 11 kanban tools with parameters, return shapes, example invocations
- **Task lifecycle** — create → claim → start → complete, with dependency auto-start behavior
- **Board types** — agentic (Backlog/In Progress/Review/Done) vs personal (Inbox/In Progress/Review/Done), when to use which
- **Identity** — user profiles, `user_id` from API key, agent instructions (`kanban_my_instructions`)
- **REST API fallback** — key HTTP endpoints for agents that prefer REST over MCP
- **Error handling** — common error shapes, retry patterns, `help_wanted` flag
- **SSE** — `kanban_task_updated` channel for real-time task notifications

**B. MCP tool: `lamadb_docs`**

- Handler: `app/core/mcp.py:lamadb_docs`
- Returns the content of `AGENTS_API.md` as a string
- Agents can call `lamadb_docs` to read the docs without file access
- Registered in `MODULE_MCP_TOOLS` in `app/core/__init__.py`

**C. Optional: `lamadb-kanban` skill**

- A skill file that teaches agents the task lifecycle patterns
- Covers: when to use `find_work` vs `my_tasks`, how to handle `help_wanted`, dependency chains
- Can be installed by agents that want structured guidance

### Files

| Action | File |
|--------|------|
| Create | `AGENTS_API.md` |
| Modify | `app/core/mcp.py` (add `lamadb_docs` tool) |
| Modify | `app/core/__init__.py` (register tool) |
| Create | `skills/lamadb-kanban/SKILL.md` (optional) |

---

## 2. Theme Backend Basics

### Purpose

Persist per-user theme preferences (color scheme + accent color) server-side so themes follow users across devices.

### Data Model

Add `theme` JSONB column to `users` table:

```sql
ALTER TABLE users ADD COLUMN theme JSONB DEFAULT '{"scheme": "dark", "accent": "#6366f1"}';
```

Theme shape:
```json
{
  "scheme": "dark" | "light",
  "accent": "#6366f1"  // hex color
}
```

Six preset accents:
| Name | Hex | Preview |
|------|-----|---------|
| Indigo | `#6366f1` | Default |
| Emerald | `#10b981` | Green |
| Rose | `#f43f5e` | Pink/Red |
| Amber | `#f59e0b` | Orange/Yellow |
| Cyan | `#06b6d4` | Teal |
| Violet | `#8b5cf6` | Purple |

### API Endpoints

**`GET /api/users/me/theme`**
- Returns the authenticated user's theme preferences
- Falls back to defaults if no theme set
- Auth: any role

**`PUT /api/users/me/theme`**
- Updates theme preferences
- Body: `{"scheme": "dark", "accent": "#10b981"}`
- Auth: any role (users can only update their own theme)

### Frontend Changes

**Login flow:**
1. On successful auth, fetch `GET /api/users/me/theme`
2. Apply scheme via `applyTheme(theme.scheme)` (existing function)
3. Apply accent via `applyAccent(theme.accent)` (new function)
4. Cache in localStorage as fallback

**Theme toggle:**
1. `toggleTheme()` updates localStorage + calls `PUT /api/users/me/theme`
2. Non-blocking — UI updates immediately, API call fires async

**Accent picker:**
1. New Settings section: "Appearance"
2. 6 preset color swatches
3. Clicking a swatch updates CSS custom property `--accent` + calls PUT API

**CSS changes:**
- Define `--accent` custom property in `:root` (dark) and `[data-theme="light"]`
- Replace hardcoded accent colors in `dashboard.css` with `var(--accent)`
- Add `.accent-*` utility classes for the 6 presets

### Files

| Action | File |
|--------|------|
| Create | `migrations/015_user_theme.sql` |
| Modify | `app/core/users.py` (add theme endpoints) |
| Modify | `static/js/app.js` (fetch theme on login, apply accent) |
| Modify | `static/js/pages/settings.js` (add Appearance section) |
| Modify | `static/css/dashboard.css` (replace hardcoded accents with var) |

---

## 3. DB Deduplication Cron (pg_cron)

### Purpose

Automatically deduplicate and prune old events using PostgreSQL's pg_cron extension.

### Target Tables

| Table | Strategy | Retention |
|-------|----------|-----------|
| `events` | Severity-based pruning | Critical: 90d, Error: 60d, Warn: 30d, Info: 14d |
| `events` (dozzle) | Dedup by `metadata->>'dedup_key'` | Keep latest per key, delete older |
| `monitor_status` | Count-based pruning | Keep last 1000 per monitor_id |

### Mechanism

**pg_cron extension:**
- Already in the planned extension stack (`shared_preload_libraries`)
- Install via migration: `CREATE EXTENSION IF NOT EXISTS pg_cron;`
- Schedule jobs via `cron.schedule()`

**Migration: `016_dedup_cron.sql`**
1. Install pg_cron extension
2. Create SQL functions for each cleanup operation
3. Schedule daily jobs at 3 AM UTC

### SQL Functions

**`prune_events_by_severity()`**
```sql
CREATE OR REPLACE FUNCTION prune_events_by_severity() RETURNS void AS $$
BEGIN
  DELETE FROM events WHERE severity = 'info' AND ts < now() - interval '14 days';
  DELETE FROM events WHERE severity = 'warn' AND ts < now() - interval '30 days';
  DELETE FROM events WHERE severity = 'error' AND ts < now() - interval '60 days';
  DELETE FROM events WHERE severity = 'critical' AND ts < now() - interval '90 days';
END;
$$ LANGUAGE plpgsql;
```

**`dedup_dozzle_events()`**
```sql
CREATE OR REPLACE FUNCTION dedup_dozzle_events() RETURNS void AS $$
BEGIN
  DELETE FROM events WHERE id IN (
    SELECT e.id FROM events e
    JOIN (
      SELECT metadata->>'dedup_key' AS dk, MAX(id) AS keep_id
      FROM events WHERE source = 'dozzle' AND metadata->>'dedup_key' IS NOT NULL
      GROUP BY metadata->>'dedup_key'
    ) latest ON e.metadata->>'dedup_key' = latest.dk AND e.id < latest.keep_id
    WHERE e.source = 'dozzle'
  );
END;
$$ LANGUAGE plpgsql;
```

**`prune_monitor_status()`**
```sql
CREATE OR REPLACE FUNCTION prune_monitor_status() RETURNS void AS $$
BEGIN
  DELETE FROM monitor_status WHERE id IN (
    SELECT id FROM (
      SELECT id, ROW_NUMBER() OVER (PARTITION BY monitor_id ORDER BY received_at DESC) AS rn
      FROM monitor_status
    ) ranked WHERE rn > 1000
  );
END;
$$ LANGUAGE plpgsql;
```

**`run_maintenance()`** — wrapper that calls all three + logs results
```sql
CREATE OR REPLACE FUNCTION run_maintenance() RETURNS void AS $$
DECLARE
  events_deleted int;
  dozzle_deleted int;
  monitor_deleted int;
BEGIN
  PERFORM prune_events_by_severity();
  GET DIAGNOSTICS events_deleted = ROW_COUNT;
  PERFORM dedup_dozzle_events();
  GET DIAGNOSTICS dozzle_deleted = ROW_COUNT;
  PERFORM prune_monitor_status();
  GET DIAGNOSTICS monitor_deleted = ROW_COUNT;

  INSERT INTO events (source, type, severity, title, body, metadata)
  VALUES ('lamadb', 'maintenance', 'info', 'Daily maintenance run',
          format('Pruned %s events, %s dozzle dupes, %s monitor rows', events_deleted, dozzle_deleted, monitor_deleted),
          jsonb_build_object('events_deleted', events_deleted, 'dozzle_deleted', dozzle_deleted, 'monitor_deleted', monitor_deleted));
END;
$$ LANGUAGE plpgsql;
```

### Scheduling

```sql
-- Schedule daily at 3 AM UTC
SELECT cron.schedule('lamadb-maintenance', '0 3 * * *', 'SELECT run_maintenance()');
```

### Monitoring

- Each run logs to `events` table (source='lamadb', type='maintenance')
- Dashboard Settings page shows last maintenance run + counts
- `GET /api/dashboard/maintenance/status` endpoint returns last run info

### Files

| Action | File |
|--------|------|
| Create | `migrations/016_dedup_cron.sql` |
| Modify | `app/core/dashboard.py` (add maintenance status endpoint) |
| Modify | `static/js/pages/settings.js` (add maintenance status card) |

---

## Dependencies Between the Three

None. These are fully independent:
- Agent docs has no code dependencies on themes or dedup
- Theme backend touches users table but doesn't affect dedup
- Dedup cron touches events table but doesn't affect themes or docs

**Recommended implementation order:**
1. Agent docs (smallest, no DB changes)
2. Theme backend (migration + frontend)
3. DB dedup cron (migration + pg_cron setup)

---

## Success Criteria

| Subsystem | Criteria |
|-----------|----------|
| Agent docs | AGENTS_API.md exists, `lamadb_docs` MCP tool returns it, covers all 11 kanban tools |
| Theme backend | GET/PUT theme endpoints work, accent picker in Settings, CSS uses `var(--accent)` |
| DB dedup cron | pg_cron installed, 3 SQL functions scheduled, maintenance events logged |
