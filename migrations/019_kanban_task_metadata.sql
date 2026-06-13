-- Migration: 019_kanban_task_metadata.sql
-- Add metadata JSONB column to kanban_tasks for task types, custom fields, etc.

ALTER TABLE kanban_tasks ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';
