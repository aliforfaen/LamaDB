# DB Deduplication Cron — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically deduplicate and prune old events using PostgreSQL's pg_cron extension with severity-based retention.

**Architecture:** pg_cron extension with SQL functions for pruning events, deduplicating dozzle logs, and trimming monitor_status history. Results logged to events table. Dashboard shows last maintenance run.

**Tech Stack:** PostgreSQL (pg_cron, PL/pgSQL), FastAPI, vanilla JS

---

## File Map

| Action | File | Purpose |
|--------|------|---------|
| Modify | `docker-compose.yml` | Add shared_preload_libraries for pg_cron |
| Create | `migrations/016_dedup_cron.sql` | pg_cron setup + SQL functions + scheduling |
| Modify | `app/core/dashboard.py` | Add maintenance status endpoint |
| Modify | `static/js/pages/settings.js` | Add maintenance status card |

---

### Task 1: Docker — Enable pg_cron Extension

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add shared_preload_libraries to postgres service**

In `docker-compose.yml`, add to the `postgres` service environment:

```yaml
postgres:
  image: pgvector/pgvector:pg16
  container_name: lamadb_postgres
  environment:
    POSTGRES_USER: lamadb
    POSTGRES_PASSWORD: lamadb_secret
    POSTGRES_DB: lamadb
  command: >
    postgres
    -c shared_preload_libraries='pg_cron'
    -c cron.database_name=lamadb
  # ... rest of config
```

The `command` overrides the default postgres startup to load pg_cron.

- [ ] **Step 2: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(dedup): enable pg_cron extension in postgres config"
```

---

### Task 2: Migration — pg_cron Setup + SQL Functions

**Files:**
- Create: `migrations/016_dedup_cron.sql`

- [ ] **Step 1: Write the migration**

```sql
-- 016_dedup_cron.sql
-- pg_cron extension for automated event pruning and deduplication

-- Install pg_cron extension
CREATE EXTENSION IF NOT EXISTS pg_cron;

-- Severity-based event retention
CREATE OR REPLACE FUNCTION prune_events_by_severity() RETURNS INTEGER AS $$
DECLARE
  deleted_count INTEGER;
BEGIN
  WITH deleted AS (
    DELETE FROM events
    WHERE (
      (severity = 'info' AND ts < now() - interval '14 days')
      OR (severity = 'warn' AND ts < now() - interval '30 days')
      OR (severity = 'error' AND ts < now() - interval '60 days')
      OR (severity = 'critical' AND ts < now() - interval '90 days')
    )
    AND source NOT IN ('lamadb')  -- Never prune maintenance events
    RETURNING id
  )
  SELECT count(*) INTO deleted_count FROM deleted;

  RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Deduplicate dozzle events (keep latest per dedup_key)
CREATE OR REPLACE FUNCTION dedup_dozzle_events() RETURNS INTEGER AS $$
DECLARE
  deleted_count INTEGER;
BEGIN
  WITH duplicates AS (
    SELECT e.id
    FROM events e
    INNER JOIN (
      SELECT metadata->>'dedup_key' AS dk, MAX(id) AS keep_id
      FROM events
      WHERE source = 'dozzle'
        AND metadata->>'dedup_key' IS NOT NULL
      GROUP BY metadata->>'dedup_key'
    ) latest ON e.metadata->>'dedup_key' = latest.dk
    WHERE e.source = 'dozzle'
      AND e.id < latest.keep_id
  ),
  deleted AS (
    DELETE FROM events WHERE id IN (SELECT id FROM duplicates) RETURNING id
  )
  SELECT count(*) INTO deleted_count FROM deleted;

  RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Prune monitor_status (keep last 1000 per monitor)
CREATE OR REPLACE FUNCTION prune_monitor_status() RETURNS INTEGER AS $$
DECLARE
  deleted_count INTEGER;
BEGIN
  WITH ranked AS (
    SELECT id, ROW_NUMBER() OVER (PARTITION BY monitor_id ORDER BY received_at DESC) AS rn
    FROM monitor_status
  ),
  to_delete AS (
    SELECT id FROM ranked WHERE rn > 1000
  ),
  deleted AS (
    DELETE FROM monitor_status WHERE id IN (SELECT id FROM to_delete) RETURNING id
  )
  SELECT count(*) INTO deleted_count FROM deleted;

  RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Maintenance wrapper — calls all cleanup functions and logs results
CREATE OR REPLACE FUNCTION run_maintenance() RETURNS void AS $$
DECLARE
  events_deleted INTEGER;
  dozzle_deleted INTEGER;
  monitor_deleted INTEGER;
BEGIN
  events_deleted := prune_events_by_severity();
  dozzle_deleted := dedup_dozzle_events();
  monitor_deleted := prune_monitor_status();

  INSERT INTO events (source, type, severity, title, body, metadata)
  VALUES (
    'lamadb',
    'maintenance',
    'info',
    'Daily maintenance run',
    format('Pruned %s events, %s dozzle dupes, %s monitor rows', events_deleted, dozzle_deleted, monitor_deleted),
    jsonb_build_object(
      'events_deleted', events_deleted,
      'dozzle_deleted', dozzle_deleted,
      'monitor_deleted', monitor_deleted,
      'ran_at', now()
    )
  );
END;
$$ LANGUAGE plpgsql;

-- Schedule daily at 3 AM UTC
SELECT cron.schedule('lamadb-maintenance', '0 3 * * *', 'SELECT run_maintenance()');
```

- [ ] **Step 2: Commit**

```bash
git add migrations/016_dedup_cron.sql
git commit -m "feat(dedup): add pg_cron migration with severity-based pruning"
```

---

### Task 3: Maintenance Status Endpoint

**Files:**
- Modify: `app/core/dashboard.py`

- [ ] **Step 1: Add maintenance status endpoint**

Add to `app/core/dashboard.py`:

```python
@router.get("/dashboard/maintenance/status")
async def maintenance_status(
    user: Annotated[AuthUser, Depends(require_admin)],
):
    """Get the last maintenance run info."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT ts, body, metadata
               FROM events
               WHERE source = 'lamadb' AND type = 'maintenance'
               ORDER BY ts DESC LIMIT 1"""
        )

    if not row:
        return {"last_run": None, "message": "No maintenance runs yet"}

    meta = row["metadata"]
    if isinstance(meta, str):
        import json
        meta = json.loads(meta)

    return {
        "last_run": row["ts"].isoformat() if row["ts"] else None,
        "message": row["body"],
        "stats": meta,
    }


@router.post("/dashboard/maintenance/run")
async def trigger_maintenance(
    user: Annotated[AuthUser, Depends(require_admin)],
):
    """Manually trigger a maintenance run."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("SELECT run_maintenance()")

    return {"status": "ok", "message": "Maintenance run completed"}
```

- [ ] **Step 2: Commit**

```bash
git add app/core/dashboard.py
git commit -m "feat(dedup): add maintenance status and trigger endpoints"
```

---

### Task 4: Dashboard — Maintenance Status Card

**Files:**
- Modify: `static/js/pages/settings.js`

- [ ] **Step 1: Add loadMaintenance function**

```javascript
function loadMaintenance() {
  var container = document.getElementById('maintenance-section');
  if (!container) return;

  window.api('/api/dashboard/maintenance/status').then(function(data) {
    var lastRun = data.last_run ? window.relativeTime(data.last_run) : 'Never';
    var stats = data.stats || {};
    container.innerHTML =
      '<h4>Database Maintenance</h4>' +
      '<div class="health-item"><span class="label">Last Run</span><span class="value">' + lastRun + '</span></div>' +
      '<div class="health-item"><span class="label">Events Pruned</span><span class="value">' + (stats.events_deleted || 0) + '</span></div>' +
      '<div class="health-item"><span class="label">Dozzle Dupes Removed</span><span class="value">' + (stats.dozzle_deleted || 0) + '</span></div>' +
      '<div class="health-item"><span class="label">Monitor Rows Pruned</span><span class="value">' + (stats.monitor_deleted || 0) + '</span></div>' +
      '<div style="margin-top:12px;"><button class="btn btn-sm btn-ghost" onclick="triggerMaintenance()">Run Now</button></div>';
  }).catch(function(e) {
    container.innerHTML = '<h4>Database Maintenance</h4><div style="color:var(--danger);padding:10px;">Failed: ' + e.message + '</div>';
  });
}

window.triggerMaintenance = function() {
  var btn = document.querySelector('#maintenance-section .btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Running...'; }
  window.api('/api/dashboard/maintenance/run', { method: 'POST' }).then(function() {
    window.showToast('Maintenance run completed', null, null, 3000);
    loadMaintenance();
  }).catch(function(e) {
    window.showToast('Failed: ' + e.message, null, null, 5000);
    if (btn) { btn.disabled = false; btn.textContent = 'Run Now'; }
  });
};
```

- [ ] **Step 2: Call loadMaintenance from loadSettings**

Add `loadMaintenance();` to `window.loadSettings`.

- [ ] **Step 3: Add maintenance section to HTML**

In `static/index.html`, in the Settings page, add:

```html
<div id="maintenance-section" class="settings-card"></div>
```

- [ ] **Step 4: Commit**

```bash
git add static/js/pages/settings.js static/index.html
git commit -m "feat(dedup): add maintenance status card to Settings"
```

---

## Execution Order

1. Task 1 (Docker config) — must be first (pg_cron needs shared_preload_libraries)
2. Task 2 (Migration) — depends on pg_cron being available
3. Task 3 (API endpoints) — depends on migration
4. Task 4 (Dashboard) — depends on API

**Important:** After Task 1, the postgres container must be recreated:
```bash
docker compose down postgres && docker compose up -d postgres
```

## Verification

After all tasks:
```bash
docker compose down && docker compose up -d
```
1. Check pg_cron is loaded: `SELECT * FROM pg_extension WHERE extname = 'pg_cron';`
2. Check jobs scheduled: `SELECT * FROM cron.job;`
3. Manual run: `POST /api/dashboard/maintenance/run`
4. Check status: `GET /api/dashboard/maintenance/status`
5. Verify maintenance event in events table

## Retention Policy

| Severity | Retention | Rationale |
|----------|-----------|-----------|
| Critical | 90 days | Long-term incident tracking |
| Error | 60 days | Debugging and pattern analysis |
| Warn | 30 days | Short-term monitoring |
| Info | 14 days | High volume, low value |
| Dozzle | Dedup only | Keep unique entries, remove duplicates |
| Monitor | 1000 per monitor | Enough for sparklines, not too many |
