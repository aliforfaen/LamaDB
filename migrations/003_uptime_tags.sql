-- Add tags array to monitor_status
ALTER TABLE monitor_status ADD COLUMN IF NOT EXISTS tags TEXT[] DEFAULT '{}';
