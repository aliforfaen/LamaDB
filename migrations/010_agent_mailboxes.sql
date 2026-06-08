-- Extend agent_messages with mailbox features
ALTER TABLE agent_messages ADD COLUMN IF NOT EXISTS inbox_for TEXT;
ALTER TABLE agent_messages ADD COLUMN IF NOT EXISTS reply_to BIGINT REFERENCES agent_messages(id);

-- Drop old indexes and create composite ones
DROP INDEX IF EXISTS idx_messages_to;
DROP INDEX IF EXISTS idx_messages_unread;
CREATE INDEX IF NOT EXISTS idx_messages_inbox ON agent_messages (inbox_for, read, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_from ON agent_messages (from_agent, created_at DESC);
