-- Wiki collector sync state: tracks last CouchDB _changes sequence
CREATE TABLE IF NOT EXISTS wiki_sync_state (
    id INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    last_seq TEXT NOT NULL DEFAULT '0',
    updated_at TIMESTAMPTZ DEFAULT now()
);

INSERT INTO wiki_sync_state (id, last_seq)
VALUES (1, '0')
ON CONFLICT (id) DO NOTHING;
