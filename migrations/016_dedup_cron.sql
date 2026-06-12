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
    AND source NOT IN ('lamadb')
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

-- Maintenance wrapper
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
    'lamadb', 'maintenance', 'info',
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
