-- 025_dedup_mon_dd_yyyy.sql
-- Backfill dedup_keys for dozzle events whose titles contain
-- "Mon DD, YYYY HH:MM:SS" timestamps (e.g. "Jun 15, 2026 13:17:00 ...").
-- These timestamps come from Sonarr/Radarr/Syncthing/Agregarr logs and
-- were not stripped before hashing, so every minute produced a unique
-- dedup_key for the same recurring error.
--
-- The fingerprint matches the collector's _event_dedup_key() output:
--   sha256( container_id | level | normalize(title) )
-- where normalize() now strips ISO, RFC-2822, and "Mon DD, YYYY HH:MM:SS"
-- timestamps plus hex ids and collapses whitespace.
--
-- The WHERE clause restricts to rows whose old dedup_key would actually
-- change — i.e. titles that contain a "Mon DD, YYYY HH:MM:SS" timestamp.
-- Rows already collapsed to the same key as the new fingerprint are no-ops.
--
-- Safe to re-run: WHERE excludes rows that don't match the new pattern,
-- and UPDATE with the same value is a no-op for matching rows.

UPDATE events
SET metadata = jsonb_set(
    metadata,
    '{dedup_key}',
    to_jsonb(
        encode(
            sha256(
                convert_to(
                    lower(COALESCE(metadata->>'container_id', ''))
                    || '|'
                    || COALESCE(metadata->>'level', '')
                    || '|'
                    || btrim(regexp_replace(
                        regexp_replace(
                            regexp_replace(
                                regexp_replace(
                                    regexp_replace(
                                        COALESCE(title, ''),
                                        '\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?',
                                        'TS', 'g'
                                    ),
                                    '\[?\w{3},\s+\d{1,2}\s+\w{3}\s+\d{4}\s+\d{2}:\d{2}:\d{2}\s+[+-]\d{4}\]?',
                                    'TS', 'g'
                                ),
                                '\w{3}\s+\d{1,2},\s+\d{4}\s+\d{2}:\d{2}:\d{2}',
                                'TS', 'g'
                            ),
                            '\[?[0-9a-f]{8,}\]?',
                            'ID', 'gi'
                        ),
                        '\s+',
                        ' ', 'g'
                    )),
                    'UTF8'
                )
            ),
            'hex'
        )
    )
)
WHERE source = 'dozzle'
  AND metadata ? 'dedup_key'
  AND title ~ '\w{3}\s+\d{1,2},\s+\d{4}\s+\d{2}:\d{2}:\d{2}';
