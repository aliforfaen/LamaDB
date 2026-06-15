-- Migration: 027_kanban_templates.sql
-- Kanban task templates — reusable blueprints for common task types

CREATE TABLE IF NOT EXISTS kanban_task_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    priority TEXT DEFAULT 'medium',
    tags TEXT[] DEFAULT '{}',
    subtasks JSONB DEFAULT '[]',  -- [{title, position}]
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_kanban_task_templates_created_by
    ON kanban_task_templates(created_by);
