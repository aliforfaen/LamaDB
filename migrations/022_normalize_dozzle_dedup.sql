-- 022_normalize_dozzle_dedup.sql
-- Backfill: re-hash dedup_keys for existing dozzle events after stripping
-- volatile tokens (timestamps, uuids). The old dedup_key used a hash over
-- the full message, which contained ISO timestamps and made every recurring
-- error unique — 500k+ agregarr 401 errors collapsed to 0 dedupes.
--
-- After this migration, all dozzle events with the same container/level/
-- normalized-message will share a dedup_key, so dedup_dozzle_events() can
-- collapse them.
--
-- This is safe to re-run: UPDATE with the same value is a no-op.

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
  AND (metadata->>'dedup_key' IS NULL OR NOT metadata ? 'dedup_key');

-- Also backfill dedup_key for dozzle events that have container_id but no key.
-- Pre-collector events were inserted without a key; dedup_dozzle_events()
-- needs the key on every row to collapse recurring errors.
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
