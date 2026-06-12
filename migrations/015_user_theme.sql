-- 015_user_theme.sql
-- Add per-user theme preferences (color scheme + accent color)

ALTER TABLE users ADD COLUMN IF NOT EXISTS theme JSONB DEFAULT '{"scheme": "dark", "accent": "#6366f1"}';
