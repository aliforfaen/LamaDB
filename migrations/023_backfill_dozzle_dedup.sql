-- 023_backfill_dozzle_dedup.sql
-- Backfill dedup_key for dozzle events that have container_id but no key.
-- These are pre-collector events inserted before dedup_key was added to the
-- collector; without a key, dedup_dozzle_events() cannot collapse them.
--
-- Safe to re-run: the WHERE clause skips rows that already have a key.

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
                                    COALESCE(title, ''),
                                    '\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?',
                                    'TS', 'g'
                                ),
                                '\[?\w{3},\s+\d{1,2}\s+\w{3}\s+\d{4}\s+\d{2}:\d{2}:\d{2}\s+[+-]\d{4}\]?',
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
  AND metadata ? 'container_id'
  AND (metadata->>'dedup_key' IS NULL OR NOT metadata ? 'dedup_key');
