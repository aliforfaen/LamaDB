-- Migration: 014_kanban_core.sql
-- Users table (identity profiles), kanban tables, and NOTIFY triggers

-- ── Users ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL DEFAULT 'agent',
    status TEXT NOT NULL DEFAULT 'active',
    instructions TEXT,
    last_active_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Link api_keys to users
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id);

-- Seed the admin user from the existing admin API key
INSERT INTO users (name, type, status, instructions)
SELECT 'ali', 'human', 'active', 'Primary human operator'
WHERE NOT EXISTS (SELECT 1 FROM users WHERE name = 'ali');

UPDATE api_keys SET user_id = (SELECT id FROM users WHERE name = 'ali')
WHERE role = 'admin' AND user_id IS NULL;

-- ── Kanban Boards ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS kanban_boards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'agentic',
    instructions TEXT,
    owner_id UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- ── Kanban Columns ────────────────────────────────────────

CREATE TABLE IF NOT EXISTS kanban_columns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    board_id UUID NOT NULL REFERENCES kanban_boards(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    position INT NOT NULL DEFAULT 0,
    wip_limit INT
);

-- ── Kanban Tasks ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS kanban_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    board_id UUID NOT NULL REFERENCES kanban_boards(id) ON DELETE CASCADE,
    column_id UUID NOT NULL REFERENCES kanban_columns(id),
    task_number INT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    priority TEXT DEFAULT 'medium',
    due_at TIMESTAMPTZ,
    assignee_id UUID REFERENCES users(id),
    position INT DEFAULT 0,
    help_wanted BOOLEAN DEFAULT false,
    help_wanted_message TEXT,
    estimate TEXT,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_kanban_tasks_board ON kanban_tasks(board_id, column_id);
CREATE INDEX IF NOT EXISTS idx_kanban_tasks_assignee ON kanban_tasks(assignee_id);

-- ── Kanban Subtasks ───────────────────────────────────────

CREATE TABLE IF NOT EXISTS kanban_subtasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES kanban_tasks(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    completed BOOLEAN DEFAULT false,
    position INT DEFAULT 0,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- ── Kanban Task Dependencies ──────────────────────────────

CREATE TABLE IF NOT EXISTS kanban_task_dependencies (
    task_id UUID NOT NULL REFERENCES kanban_tasks(id) ON DELETE CASCADE,
    depends_on_id UUID NOT NULL REFERENCES kanban_tasks(id) ON DELETE CASCADE,
    PRIMARY KEY (task_id, depends_on_id)
);

-- ── Kanban Comments ───────────────────────────────────────

CREATE TABLE IF NOT EXISTS kanban_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES kanban_tasks(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id),
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- ── Kanban Agent Logs ─────────────────────────────────────

CREATE TABLE IF NOT EXISTS kanban_agent_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    task_id UUID REFERENCES kanban_tasks(id),
    board_id UUID REFERENCES kanban_boards(id),
    action TEXT NOT NULL,
    details TEXT,
    tool TEXT,
    session_id TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_logs_board ON kanban_agent_logs(board_id, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_logs_user ON kanban_agent_logs(user_id, created_at);

-- ── NOTIFY Trigger for real-time task updates ─────────────

CREATE OR REPLACE FUNCTION trg_kanban_task_notify()
RETURNS TRIGGER AS $$
DECLARE
    payload text;
    board uuid;
    col uuid;
    op text;
BEGIN
    op := TG_OP;
    IF op = 'DELETE' THEN
        board := OLD.board_id;
        col := OLD.column_id;
    ELSE
        board := NEW.board_id;
        col := NEW.column_id;
    END IF;
    payload := json_build_object(
        'task_id', CASE WHEN op = 'DELETE' THEN OLD.id ELSE NEW.id END,
        'board_id', board,
        'column_id', col,
        'action', op
    )::text;
    PERFORM pg_notify('kanban_task_updated', payload);
    IF op = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_kanban_task_insert ON kanban_tasks;
CREATE TRIGGER trg_kanban_task_insert AFTER INSERT ON kanban_tasks
    FOR EACH ROW EXECUTE FUNCTION trg_kanban_task_notify();

DROP TRIGGER IF EXISTS trg_kanban_task_update ON kanban_tasks;
CREATE TRIGGER trg_kanban_task_update AFTER UPDATE ON kanban_tasks
    FOR EACH ROW EXECUTE FUNCTION trg_kanban_task_notify();

DROP TRIGGER IF EXISTS trg_kanban_task_delete ON kanban_tasks;
CREATE TRIGGER trg_kanban_task_delete AFTER DELETE ON kanban_tasks
    FOR EACH ROW EXECUTE FUNCTION trg_kanban_task_notify();
