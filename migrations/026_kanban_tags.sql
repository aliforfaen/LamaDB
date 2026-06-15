-- Add tags support to kanban tasks
ALTER TABLE kanban_tasks ADD COLUMN IF NOT EXISTS tags TEXT[] DEFAULT '{}';
CREATE INDEX IF NOT EXISTS idx_kanban_tasks_tags ON kanban_tasks USING GIN (tags);
