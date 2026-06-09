-- User layout persistence for drag-and-drop dashboard customization
CREATE TABLE IF NOT EXISTS user_layouts (
    user_id TEXT NOT NULL,
    page TEXT NOT NULL DEFAULT 'overview',
    layout JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (user_id, page)
);
